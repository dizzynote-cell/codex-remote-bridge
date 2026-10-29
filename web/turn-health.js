/* Per-conversation execution status, separate from transient submission notices. */
(() => {
  window.formatSyncAge = seconds => {
    if (!Number.isFinite(seconds)) return '未知';
    const total = Math.max(0, Math.floor(seconds)), days = Math.floor(total/86400),
      hours = Math.floor(total%86400/3600), minutes = Math.floor(total%3600/60), rest = total%60;
    const pad = value => String(value).padStart(2, '0');
    if (days) return `${days}天 ${pad(hours)}小时 ${pad(minutes)}分 ${pad(rest)}秒`;
    if (hours) return `${hours}小时 ${pad(minutes)}分 ${pad(rest)}秒`;
    if (minutes) return `${minutes}分 ${pad(rest)}秒`;
    return `${rest}秒`;
  };
  // Interpret only the turn-level failure, never a recoverable tool error.
  window.turnStatusMessage = turn => {
    const status = typeof turn?.status === 'object' ? turn.status?.type : turn?.status;
    const final = (turn?.items || []).some(i => i.type === 'agentMessage' && ['final_answer','final'].includes(i.phase));
    if (status !== 'failed') return ({completed:'任务已完成', cancelled:'任务已取消',
      interrupted:final ? '本轮已中断 · 已有回复，请确认结果是否完整' : '本轮已中断，未生成最终答案'})[status] || 'Codex 正在处理';
    const error = turn?.error;
    const code = typeof error?.codexErrorInfo === 'string' ? error.codexErrorInfo : JSON.stringify(error?.codexErrorInfo || '');
    const detail = `${code} ${typeof error === 'string' ? error : error?.message || ''}`;
    if (/serverOverloaded|at capacity|server overloaded|model.*overloaded/i.test(detail))
      return '模型服务繁忙，本轮未完成。可稍后重试，或切换模型后继续。';
    if (/usageLimitExceeded|rateLimit|rate.limit|quota.*exceeded|insufficient.*quota/i.test(detail))
      return '模型额度或请求频率受限，本轮未完成。请查看额度和错误信息，恢复后再继续。';
    if (/contextWindowExceeded|context.*(?:window|length).*exceed|maximum context length/i.test(detail))
      return '对话上下文超出模型限制，本轮未完成。请压缩上下文或交接到新对话后继续。';
    if (/unauthorized|authentication|invalid.*api.key|token.*expired/i.test(detail))
      return '模型身份验证失败，本轮未完成。请检查 Codex 登录状态。';
    if (/httpConnectionFailed|responseStream|stream.*(?:disconnect|closed)|connection.*(?:reset|closed|failed)|network|timed? ?out/i.test(detail))
      return '模型连接中断或超时，本轮未完成。请先确认已有输出和进度，再决定是否继续。';
    const safeCode = /^[a-zA-Z][a-zA-Z0-9_]{0,70}$/.test(code) ? `（${code}）` : '';
    return `本轮执行失败${safeCode}。请检查已有输出和进度；具体原因暂未识别。`;
  };
  const box = document.querySelector('#turn-health');
  if (!box) return;
  const cache = new Map(), terminal = new Set(['completed', 'failed', 'interrupted', 'cancelled']);
  const running = new Set(['inProgress', 'in_progress', 'running']);
  const toolTypes = new Set(['commandExecution', 'fileChange', 'mcpToolCall', 'dynamicToolCall', 'imageGeneration', 'webSearch', 'contextCompaction']);
  const state = item => typeof item?.status === 'object' ? item.status?.type : item?.status;
  // Never show raw commands, tool arguments, environment variables or output here.
  function label(item) {
    if (item?.type === 'commandExecution') {
      const command = String(item.command || '');
      const script = command.match(/(?:python(?:3)?|node)\s+["']?(?:[\w.:/\\-]+[/\\])?([\w.-]+\.(?:py|mjs|cjs|js))\b/i);
      if (script) return `运行脚本 ${script[1]}`;
      if (/\b(?:npm|pnpm|yarn)\s+(?:run\s+)?build\b/i.test(command)) return '构建项目';
      if (/\b(?:npm|pnpm|yarn)\s+(?:install|add|ci)\b/i.test(command)) return '安装依赖';
      if (/\b(?:pytest|npm\s+(?:run\s+)?test)\b/i.test(command)) return '运行测试';
      const action = item.commandActions?.at(-1)?.type;
      return ({read:'读取文件', listFiles:'查看文件列表', search:'搜索文件'})[action] || '执行命令';
    }
    return ({fileChange:'修改文件', mcpToolCall:'调用外部工具', dynamicToolCall:'调用工具',
      imageGeneration:'生成图片', webSearch:'检索网页', contextCompaction:'压缩上下文',
      reasoning:'推理摘要', agentMessage:'回复内容'})[item?.type] || '处理任务';
  }
  function activity(thread) {
    const turn = thread?.turns?.at(-1);
    if (!turn) return null;
    const status = state(turn);
    if (terminal.has(status)) return {kind: status === 'failed' ? 'failed' : 'activity', message:
      status === 'failed' ? window.turnStatusMessage(turn) : ({completed:'本轮已完成', interrupted:'本轮已中断，请确认回复是否完整', cancelled:'本轮已取消'})[status]};
    if (!running.has(status)) return null;
    const flags = typeof thread.status === 'object' ? thread.status.activeFlags || [] : [];
    if (flags.some(flag => /waitingFor(?:Approval|UserInput)/i.test(typeof flag === 'object' ? flag.type : flag)))
      return {kind:'activity', message:'等待你处理授权或回答请求'};
    const items = turn.items || [], tools = items.filter(i => toolTypes.has(i.type) && running.has(state(i)));
    if (tools.length) return {kind:'activity', message:`正在执行：${label(tools.at(-1))}${tools.length > 1 ? `（另有 ${tools.length-1} 项并行操作）` : ''}`};
    const last = [...items].reverse().find(i => toolTypes.has(i.type) || ['reasoning','agentMessage'].includes(i.type));
    let recent = '';
    if (last && toolTypes.has(last.type)) {
      const outcome = state(last);
      recent = `最近操作${outcome === 'completed' ? '已完成' : ['failed','declined'].includes(outcome) ? '未成功' : '有记录'}：${label(last)}`;
    } else if (last) recent = `最近收到${label(last)}`;
    return {kind:'activity', message:`本轮尚未结束，等待模型继续输出${recent ? ` · ${recent}` : ''}`};
  }
  let current = null;
  function render(view, prefix = '') {
    const message = view ? prefix + String(view.message || '').slice(0, 500) : '';
    if (box.textContent !== message) box.textContent = message;
    box.dataset.kind = view?.kind || '';
    box.hidden = !message;
  }
  function remember(id, view) {
    cache.delete(id); cache.set(id, view);
    if (cache.size > 128) cache.delete(cache.keys().next().value);
  }
  window.turnHealthUI = {
    begin(id) {
      if (current === id) return;
      current = id;
      render(cache.get(id), '上次读取：');
    },
    unavailable(id) {
      if (id !== current) return;
      render(cache.get(id) || {kind:'no_progress', message:'暂时无法读取当前对话状态，正在重试'}, '状态更新暂时断开 · ');
    },
    show(id, health, syncedAt, thread) {
      if (id !== current) return; // A late reply from another conversation cannot overwrite this one.
      const last = thread?.turns?.at(-1), finished = last && terminal.has(state(last));
      const validHealth = !finished && health && ['retrying', 'no_progress'].includes(health.kind) &&
        (!health.turnId || !last || health.turnId === last.id);
      const view = validHealth ? health : activity(thread);
      remember(id, view);
      const stamp = Number(syncedAt), age = Number.isFinite(stamp) && stamp > 0 ? Date.now()/1000-stamp : 0;
      const prefix = age > 30 ? `上次同步时（${window.formatSyncAge(age)}前）：` : '';
      render(view, prefix);
    }
  };
})();
