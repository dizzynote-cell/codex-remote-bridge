+// SPDX-License-Identifier: MIT
// Copyright (c) 2026 xiyannan
/* Shared with cloud/web/interactions.js. Human replies are not ordinary chat messages. */
(() => {
  'use strict';
  const anchor = document.querySelector('#messages');
  if (!anchor) return;
  const panel = document.createElement('section');
  panel.className = 'interaction-panel'; panel.hidden = true;
  panel.setAttribute('aria-label', '待处理请求');
  const toggle = document.createElement('button');
  toggle.type = 'button'; toggle.className = 'interaction-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  const list = document.createElement('div'); list.className = 'interaction-list'; list.hidden = true;
  panel.append(toggle, list); anchor.before(panel);
  toggle.onclick = () => { list.hidden = !list.hidden; toggle.setAttribute('aria-expanded', String(!list.hidden)); };
  const cards = new Map(), seen = new Set(), answered = new Set();
  let running = false, available = false, session = '', started = 0, revision = -1;
  const node = (tag, value, cls) => {
    const el = document.createElement(tag); if (value !== undefined) el.textContent = value;
    if (cls) el.className = cls; return el;
  };
  const option = (select, value, label) => { const el = node('option', label); el.value = value; select.append(el); };
  function nameFor(id) {
    const rows = typeof threads !== 'undefined' ? threads : [];
    return rows.find(t => t.id === id)?.name || (id ? `会话 ${id.slice(0, 8)}` : '客户端请求');
  }
  function buttonLabel(action, request) {
    return {answer:'提交回答', accept:'允许本次请求', decline:'拒绝本次请求',
      manual_done:request.category === 'pc' ? '我已在 PC 完成操作' : '我已完成授权',
      cancel:'取消此请求', dismiss:'关闭提示'}[action] || action;
  }
  function createCard(request) {
    const card = node('form', undefined, `interaction-card ${request.category === 'pc' ? 'needs-pc' : ''}`);
    card.noValidate = true;
    card.append(node('small', nameFor(request.threadId)), node('h3', request.title), node('p', request.message), node('p', request.help, 'interaction-help'));
    const readers = [];
    for (const question of request.questions || []) {
      const field = node('fieldset'); field.append(node('legend', question.question));
      if (!question.pc) {
        let select;
        if (question.options?.length) {
          select = node('select'); select.setAttribute('aria-label', question.question);
          option(select, '', '请选择，或在下方填写回答');
          for (const item of question.options) option(select, item.label, `${item.label}${item.description ? ' — ' + item.description : ''}`);
          field.append(select);
        }
        const input = node('textarea'); input.rows = 2; input.maxLength = 8000;
        input.placeholder = select ? '补充或自行填写回答（填写后优先使用文字）' : '请输入回答';
        input.setAttribute('aria-label', question.question); field.append(input);
        readers.push(() => [question.id, input.value.trim() || select?.value || '']);
      }
      card.append(field);
    }
    for (const spec of request.fields || []) {
      const field = node('label', `${spec.label}${spec.required ? ' *' : ''}`);
      let input, read;
      if (spec.enum) {
        input = node('select'); option(input, '', '请选择');
        spec.enum.forEach((value, i) => option(input, String(i), String(spec.enumNames?.[i] ?? value)));
        read = () => input.value === '' ? undefined : spec.enum[Number(input.value)];
      } else if (spec.type === 'boolean') {
        input = node('select'); option(input, '', '请选择'); option(input, 'true', '是'); option(input, 'false', '否');
        read = () => input.value === '' ? undefined : input.value === 'true';
      } else {
        input = node('input'); input.type = spec.type === 'string' ? 'text' : 'number';
        if (spec.type !== 'string') input.step = spec.type === 'integer' ? '1' : 'any';
        input.maxLength = 8000;
        read = () => input.value === '' ? undefined : spec.type === 'string' ? input.value : Number(input.value);
      }
      input.setAttribute('aria-label', spec.label); field.append(input);
      if (spec.description) field.append(node('small', spec.description));
      readers.push(() => [spec.id, read()]); card.append(field);
    }
    if (request.url) {
      // Defense in depth: never render arbitrary server text as a link or as HTML.
      try {
        const url = new URL(request.url);
        if (url.protocol === 'https:' && !url.username && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
          const link = node('a', `打开授权页面（${url.hostname}）`);
          link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
        }
      } catch {}
    }
    if (request.details) {
      const details = node('details'); details.append(node('summary', '查看本次请求的操作范围'), node('pre', request.details)); card.append(details);
    }
    const status = node('p', '', 'interaction-delivery'); status.setAttribute('role', 'status');
    const footer = node('div', undefined, 'interaction-actions');
    const state = {card, request, status, buttons:[], sending:false, error:'', transportError:false};
    for (const action of request.actions) {
      const button = node('button', buttonLabel(action, request)); button.type = 'button';
      button.onclick = () => send(state, action, readers); footer.append(button); state.buttons.push(button);
    }
    card.onsubmit = event => event.preventDefault();
    card.append(status, footer); return state;
  }
  function refreshCard(state) {
    const queued = state.request.delivery === 'queued';
    state.buttons.forEach(b => { b.disabled = state.sending || queued || !available; });
    state.status.textContent = state.sending ? '正在提交…' : queued ? '回答已提交，等待主力 PC 确认；无需重复发送。'
      : !available ? '主力 PC 暂时未连接，恢复连接后才能回答。'
      : state.error || state.request.deliveryError || '';
  }
  async function send(state, action, readers) {
    if (state.sending || !available || state.request.delivery === 'queued') return;
    const r = state.request;
    const payload = {id:r.id, session:r.session, threadId:r.threadId, turnId:r.turnId, action};
    if (action === 'answer' || (action === 'manual_done' && r.kind === 'questions')) {
      const values = Object.fromEntries(readers.map(read => read()).filter(([, value]) => value !== undefined));
      if (r.kind === 'questions') {
        if (Object.values(values).some(v => !v)) { state.error = '请回答所有问题'; refreshCard(state); return; }
        payload.answers = values;
      } else payload.content = values;
    }
    state.sending = true; state.error = ''; refreshCard(state);
    try {
      const response = await fetch('/api/interactions/respond', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '回答未被接受');
      if (data.status === 'queued') state.request.delivery = 'queued';
      else { answered.add(r.id); state.card.remove(); cards.delete(r.id); }
    } catch (error) { state.error = error.message || '提交暂时失败，请稍后重试'; }
    finally { state.sending = false; refreshCard(state); poll(); }
  }
  async function poll() {
    if (running) return;
    running = true;
    try {
      const response = await fetch('/api/interactions', {cache:'no-store'});
      if (response.status === 401 || response.status === 404) { panel.hidden = true; return; }
      if (!response.ok) throw new Error('sync');
      const data = await response.json();
      if (data.startedAt < started || (data.session === session && data.revision < revision)) return;
      if (session !== data.session) {
        for (const state of cards.values()) state.card.remove();
        cards.clear(); answered.clear(); session = data.session; started = data.startedAt; revision = -1;
      }
      revision = data.revision; available = data.available === true;
      const pending = (data.requests || []).filter(r => r.status === 'pending' && !answered.has(r.id));
      const ids = new Set(pending.map(r => r.id));
      for (const [id, state] of cards) if (!ids.has(id)) { state.card.remove(); cards.delete(id); }
      for (const request of pending) {
        let state = cards.get(request.id);
        if (!state) { state = createCard(request); cards.set(request.id, state); list.append(state.card); }
        state.request = request; refreshCard(state);
        if (!seen.has(request.id)) { seen.add(request.id); list.hidden = false; }
      }
      toggle.textContent = `待处理 ${pending.length} 项${pending.some(r => r.category === 'pc') ? ' · 有操作需要在主力 PC 完成' : ' · 可在网页回答'}`;
      toggle.setAttribute('aria-expanded', String(!list.hidden)); panel.hidden = pending.length === 0;
    } catch {
      available = false; for (const state of cards.values()) refreshCard(state);
    } finally { running = false; }
  }
  window.bridgeInteractions = {poll};
  setInterval(poll, 2000); poll();
})();

