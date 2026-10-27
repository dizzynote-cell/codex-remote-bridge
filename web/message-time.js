/* Recorded message times, shared by local and cloud pages. */
(function () {
  function dateOf(value) {
    if (value == null || value === '' || typeof value === 'boolean') return null;
    let n = value;
    if (typeof n === 'string' && /^\d+(?:\.\d+)?$/.test(n)) n = Number(n);
    if (typeof n === 'number') {
      if (!Number.isFinite(n) || n <= 0) return null;
      if (n < 1e11) n *= 1000;
    } else if (typeof n !== 'string' || !/\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(n)) return null;
    const date = new Date(n);
    return Number.isFinite(date.getTime()) ? date : null;
  }
  function render(item, turn, role) {
    const values = [item?.bridgeTimestamp, item?.createdAt, item?.created_at, item?.timestamp];
    // A turn start is a fallback only for its first user message, never steering inputs.
    if (role === 'user' && (!item || (turn?.items || []).find(i => i.type === 'userMessage') === item))
      values.push(turn?.bridgeStartedAt, turn?.startedAt);
    let date = null;
    for (const value of values) { date = dateOf(value); if (date) break; }
    if (!date) return '<span class="message-time unknown">时间未记录</span>';
    const text = new Intl.DateTimeFormat('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date);
    return `<time class="message-time" datetime="${date.toISOString()}" title="浏览器本地时间">${text}</time>`;
  }
  window.messageTime = {render, dateOf};
})();
