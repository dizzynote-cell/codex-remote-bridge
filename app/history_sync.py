"""Prioritize requested/live threads; transfer six turns by default."""
import json
import hashlib
import subprocess
import time
import threading

TERMINAL = {'completed', 'failed', 'interrupted', 'cancelled'}

def status(turn):
    value = turn.get('status')
    return value.get('type') if isinstance(value, dict) else value

def run(api):
    env = api['os'].environ
    url, token = env.get('CODEX_HISTORY_URL','').strip(), env.get('CODEX_HISTORY_SYNC_TOKEN','').strip()
    if not url or not token:
        return
    summaries, interests, seen, last_read = {}, [], {}, {}
    retry_after = {}
    digests = {}
    next_list, https_retry_at = 0, 0
    runtime = api['cloud_runtime_state']
    quota = {}
    def quota_worker():
        while True:
            try:
                value = api['account_quota']()
                if value.get('available'):
                    quota.update(value)
            except Exception as error:
                api['log'](f'额度读取暂时失败，继续使用缓存：{error}')
            time.sleep(300)
    threading.Thread(target=quota_worker,daemon=True).start()
    cursor = None

    def send(payload):
        nonlocal https_retry_at
        ssh_host, ssh_key = env.get('CODEX_HISTORY_SSH_HOST'), env.get('CODEX_HISTORY_SSH_KEY')
        if time.monotonic() >= https_retry_at or not (ssh_host and ssh_key):
            try:
                response = api['http'].post(url, headers={'Authorization':f'Bearer {token}'}, json=payload, timeout=(4,12))
                response.raise_for_status()
                return response.json()
            except Exception:
                if not (ssh_host and ssh_key):
                    raise
                https_retry_at = time.monotonic()+60
        result = subprocess.run(['ssh','-i',ssh_key,'-o','BatchMode=yes','-o','ConnectTimeout=5',ssh_host,
                                 'python3 /opt/codex-history/import_sync.py'], input=json.dumps(payload,ensure_ascii=False),
                                text=True,capture_output=True,encoding='utf-8',errors='replace',timeout=25,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(result.stderr[:300])
        return json.loads(result.stdout)

    while True:
        try:
            now = time.time()
            payload = {'threads':[]}
            if now >= next_list:
                page = api['list_threads_page'](100, None)
                for item in page.get('data', []):
                    summaries[item['id']] = {key:item.get(key) for key in ('id','name','cwd','status','preview','updatedAt')}
                payload['summaries'] = list(summaries.values())
                cursor = cursor or page.get('nextCursor')
                if cursor:
                    older = api['list_threads_page'](100,cursor)
                    for item in older.get('data',[]):
                        summary = {key:item.get(key) for key in ('id','name','cwd','status','preview','updatedAt')}
                        summaries[item['id']] = summary
                        payload['summaries'].append(summary)
                    cursor = older.get('nextCursor')
                if quota:
                    payload['quota'] = dict(quota)
                next_list = now+10
            active = set(api['active_turns'])
            viewed = {r['threadId']:r for r in interests}
            candidates = []
            for tid in set(summaries) | active | set(viewed):
                if retry_after.get(tid,0)>now:
                    continue
                stamp = float(summaries.get(tid,{}).get('updatedAt') or 0)
                request = viewed.get(tid,{})
                pending = request.get('requestId') != request.get('completedId') and now-float(request.get('requestedAt') or 0)<120
                running = tid in active or tid in runtime.get('detected_thread_ids',[])
                viewing = now-float(request.get('viewedAt') or 0)<30
                if pending:
                    priority = 0
                elif running and now-last_read.get(tid,0)>=2:
                    priority = 1
                elif viewing and now-last_read.get(tid,0)>=3:
                    priority = 2
                elif (stamp>now-7*86400 or now-float(request.get('viewedAt') or 0)<1800) and seen.get(tid)!=stamp:
                    priority = 3
                else:
                    continue
                candidates.append((priority,-float(request.get('viewedAt') or 0) if pending else last_read.get(tid,0),tid,request if pending else None))
            if candidates:
                _, _, tid, request = min(candidates)
                try:
                    thread = api['read_thread'](tid)
                    turns = thread.get('turns') or []
                    total = len(turns)
                    limit = request.get('turnLimit','6') if request else '6'
                    limit = total if limit=='all' else max(6,int(limit))
                    thread['turns'] = turns[-limit:] if limit else []
                    thread['bridgeTotalTurns'] = total
                    thread['updatedAt'] = summaries.get(tid,{}).get('updatedAt') or thread.get('recencyAt') or thread.get('updatedAt')
                    if request:
                        thread['bridgeRequestId'] = request['requestId']
                    snapshot = api['enrich_thread_attachments'](thread,True)
                    digest = hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                    if request or digests.get(tid)!=digest:
                        payload['threads'] = [snapshot]
                    payload['checkedThreads'] = [tid]
                    detected = set(runtime.get('detected_thread_ids',[]))
                    if turns and status(turns[-1]) not in TERMINAL:
                        detected.add(tid)
                    else:
                        detected.discard(tid)
                    runtime.update(detected_thread_ids=list(detected),detected_working=bool(detected),detected_at=now)
                except Exception as error:
                    retry_after[tid]=time.time()+15
                    api['log'](f'对话历史读取暂时失败，将稍后重试：{tid} {error}')
                    if request:
                        payload['historyErrors']=[{'threadId':tid,'requestId':request['requestId'],'message':str(error)[:200]}]
            response = send(payload)
            interests = response.get('historyRequests',[])
            if candidates:
                last_read[tid] = time.time()
                if payload.get('checkedThreads'):
                    seen[tid] = float(summaries.get(tid,{}).get('updatedAt') or 0)
                    digests[tid] = digest
            runtime.update(last_history_sync=time.time(),last_error='')
        except Exception as error:
            runtime['last_error'] = str(error)[:300]
            api['log'](f'云端历史同步暂时失败：{error}')
            time.sleep(2)
        time.sleep(1)
