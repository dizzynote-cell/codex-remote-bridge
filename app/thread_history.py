"""Read native turn pages without resuming a thread or hydrating all history."""


def _unsupported(error):
    text = str(error).lower()
    return '-32601' in text or 'method not found' in text or (
        'thread/turns/list' in text and ('not supported' in text or 'unsupported' in text))


def _recorded_times(turn):
    result = dict(turn)
    result['items'] = [dict(item) for item in turn.get('items') or []]
    for item in result['items']:
        keys = ('completedAtMs','startedAtMs') if item.get('type') == 'agentMessage' else ('startedAtMs','completedAtMs')
        for key in keys:
            stamp = item.get(key)
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0:
                item.setdefault('bridgeTimestamp', stamp)
                break
    return result


def read_history(call, thread_id, turn_limit=6):
    limit = None if turn_limit == 'all' else max(6, min(int(turn_limit), 100000))
    metadata = call('thread/read', {'threadId': thread_id, 'includeTurns': False})
    thread = dict(metadata.get('thread') or {})
    newest, ids, cursors = [], set(), set()
    cursor = None
    try:
        for _ in range(2000):
            count = min(50, limit - len(newest)) if limit is not None else 50
            params = {'threadId': thread_id, 'limit': count, 'sortDirection': 'desc', 'itemsView': 'full'}
            if cursor is not None:
                params['cursor'] = cursor
            page = call('thread/turns/list', params)
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise ValueError('Invalid native turn page')
            for turn in page['data']:
                if not isinstance(turn, dict) or not turn.get('id'):
                    raise ValueError('Invalid native turn')
                if turn.get('itemsView') not in (None, 'full'):
                    raise ValueError('Native turn page did not provide complete items')
                if turn['id'] not in ids:
                    newest.append(_recorded_times(turn))
                    ids.add(turn['id'])
            cursor = page.get('nextCursor')
            if cursor is not None and (not isinstance(cursor, str) or not cursor or cursor in cursors):
                raise ValueError('Native turn pagination did not advance')
            if cursor is None or (limit is not None and len(newest) >= limit):
                break
            cursors.add(cursor)
        else:
            raise ValueError('Native turn pagination exceeded its page bound')
    except RuntimeError as error:
        # Old runtimes only. Timeouts, ownership errors and network failures must
        # never silently fall back to an expensive full-history request.
        if newest or not _unsupported(error):
            raise
        legacy = call('thread/read', {'threadId': thread_id, 'includeTurns': True})
        thread = dict(legacy.get('thread') or {})
        turns = thread.get('turns') or []
        total = len(turns)
        thread.update(turns=turns[-limit:] if limit is not None else turns,
                      bridgeTotalTurns=total, bridgeHasMoreTurns=limit is not None and total > limit,
                      bridgeNativeHistory=False)
        thread['bridgeVisibleTurns'] = len(thread['turns'])
        return thread
    # The server emits newest-first pages; the UI renders chronological turns.
    has_more = cursor is not None or (limit is not None and len(newest) > limit)
    if limit is not None:
        newest = newest[:limit]
    thread.update(turns=list(reversed(newest)), bridgeVisibleTurns=len(newest),
                  bridgeTotalTurns=None if has_more else len(newest),
                  bridgeHasMoreTurns=has_more, bridgeNativeHistory=True)
    return thread
