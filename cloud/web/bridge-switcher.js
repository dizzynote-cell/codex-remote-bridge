/* SPDX-License-Identifier: MIT -- shared provider navigation and isolated drafts. */
(() => {
  'use strict';
  const script = document.currentScript;
  const current = script?.dataset.provider || 'codex';
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  const logo = document.querySelector('#provider-toggle') || document.querySelector('.brand .logo');
  if (!logo) return;
  const storage = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch {} }
  };
  const previousProvider = storage.get('bridge:last-provider');
  storage.set('bridge:last-provider', current);
  const prefix = 'bridge:' + current + ':';
  const prompt = document.querySelector('#prompt');
  const files = document.querySelector('#files');
  const id = () => typeof selected === 'string' ? selected : '';
  const keyFor = thread => prefix + (thread || 'new');
  let dbPromise, signature = '', restoring = false, editVersion = 0, pendingDraft = null;
  for (const control of [prompt, files]) control?.addEventListener(control === files ? 'change' : 'input', () => {
    if (!restoring) editVersion++;
  });
  function database() {
    if (!dbPromise) dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open('bridge-provider-drafts-v1', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('drafts');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return dbPromise;
  }
  async function writeDraft(key, value) {
    const db = await database();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite');
      tx.objectStore('drafts').put(value, key);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }
  async function saveDraft(thread = id()) {
    if (!prompt || restoring) return true;
    if (pendingDraft?.thread === thread && pendingDraft.revision === editVersion) return true;
    const value = {text: prompt.value, files: [...(files?.files || [])], at: Date.now()};
    storage.set(keyFor(thread) + ':text', value.text);
    if (thread) storage.set(prefix + 'thread', thread);
    try { await writeDraft(keyFor(thread), value); return true; }
    catch { return value.files.length === 0; }
  }
  async function restoreDraft(thread, revision = editVersion) {
    restoring = true;
    try {
      let value;
      try {
        const db = await database();
        value = await new Promise((resolve, reject) => {
          const req = db.transaction('drafts').objectStore('drafts').get(keyFor(thread));
          req.onsuccess = () => resolve(req.result); req.onerror = reject;
        });
      } catch {}
      if (id() !== thread || editVersion !== revision) return;
      prompt.value = value?.text ?? storage.get(keyFor(thread) + ':text') ?? '';
      prompt.dispatchEvent(new Event('input', {bubbles: true}));
      if (files) {
        const transfer = new DataTransfer();
        for (const file of value?.files || []) transfer.items.add(file);
        files.files = transfer.files;
        files.dispatchEvent(new Event('change', {bubbles: true}));
      }
    } finally {
      restoring = false; signature = '';
      if (pendingDraft?.thread === thread) pendingDraft = null;
    }
  }
  if (typeof loadThread === 'function') {
    const original = loadThread;
    loadThread = async function(thread, ...args) {
      const changing = thread !== id();
      let saving;
      if (changing) {
        saving = saveDraft();
        if (prompt) prompt.value = '';
        if (files) { files.value = ''; files.dispatchEvent(new Event('change', {bubbles: true})); }
        pendingDraft = {thread, revision: editVersion};
      }
      const result = await original(thread, ...args);
      if (changing && id() === thread) {
        await saving;
        if (pendingDraft?.thread === thread) await restoreDraft(thread, pendingDraft.revision);
      }
      return result;
    };
  }
  setInterval(() => {
    if (restoring || !prompt) return;
    const next = JSON.stringify([id(), prompt.value, [...(files?.files || [])].map(f => [f.name, f.size, f.lastModified])]);
    if (next !== signature) { signature = next; saveDraft().catch(() => {}); }
  }, 1000);
  addEventListener('pagehide', () => {
    if (prompt && !(pendingDraft?.thread === id() && pendingDraft.revision === editVersion))
      storage.set(keyFor(id()) + ':text', prompt.value);
    if (id()) storage.set(prefix + 'thread', id());
  });
  // Entering or refreshing the page never selects or reads a conversation.
  const style = document.createElement('style');
  style.textContent = '.brand{position:relative}.brand .logo[role=button]{cursor:pointer;border:0}.bridge-provider-menu{position:absolute;z-index:150;top:72px;left:16px;width:280px;padding:8px;background:#181c24;border:1px solid #414957;border-radius:12px;box-shadow:0 12px 36px #0008}.bridge-provider-menu[hidden]{display:none}.bridge-provider-menu button{display:flex;justify-content:space-between;align-items:center;width:100%;gap:8px;padding:12px;border:0;border-radius:7px;text-align:left;background:transparent;color:#eef2f7;font:inherit;cursor:pointer}.bridge-provider-menu button:hover{background:#28303b}.bridge-provider-menu button:disabled{opacity:.55;cursor:default}.bridge-provider-menu small{font-size:11px;color:#aeb8c8}';
  document.head.append(style);
  const menu = document.createElement('div');
  menu.className = 'bridge-provider-menu'; menu.id = 'bridge-provider-menu';
  menu.hidden = true; menu.setAttribute('role', 'menu');
  logo.closest('.brand')?.append(menu);
  logo.setAttribute('role', 'button'); logo.setAttribute('tabindex', '0');
  logo.setAttribute('aria-haspopup', 'menu'); logo.setAttribute('aria-controls', menu.id);
  logo.setAttribute('aria-label', '切换 Codex / DeepSeek Harness');
  let providers = [
    {id: 'codex', name: 'Codex', url: local ? 'http://127.0.0.1:8765/' : '/', online: true},
    {id: 'deepseek-harness', name: 'DeepSeek Harness', url: local ? 'http://127.0.0.1:8766/dsh/' : '/dsh/', online: false}
  ];
  const targetUrl = target => {
    const url = new URL(target.url, location.href);
    url.searchParams.set('provider', target.id);
    return url.href;
  };
  async function navigate(target) {
    if (!target.online && !target.cached) return;
    const saved = await saveDraft();
    if (!saved && !confirm('浏览器未能保存待发送附件，切换后需要重新选择。是否继续切换？')) return;
    storage.set('bridge:last-provider', target.id);
    location.assign(targetUrl(target));
  }
  function paint() {
    menu.replaceChildren();
    for (const target of providers) {
      const button = document.createElement('button'); button.type = 'button';
      button.setAttribute('role', 'menuitem');
      const name = document.createElement('span'); name.textContent = target.name;
      const state = document.createElement('small');
      state.textContent = target.id === current ? '当前' : target.online ? '切换' : target.cached ? '离线 · 可看快照' : '主机离线';
      if (target.id === current) button.setAttribute('aria-current', 'true');
      button.disabled = target.id !== current && !target.online && !target.cached;
      button.append(name, state); button.onclick = () => target.id === current ? close() : navigate(target);
      menu.append(button);
    }
  }
  function close() { menu.hidden = true; logo.setAttribute('aria-expanded', 'false'); }
  logo.addEventListener('click', event => {
    event.stopImmediatePropagation();
    const native = document.querySelector('#provider-menu'); if (native) native.hidden = true;
    menu.hidden = !menu.hidden; logo.setAttribute('aria-expanded', String(!menu.hidden));
  }, true);
  logo.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); logo.click(); }
  });
  menu.addEventListener('click', event => event.stopPropagation());
  document.addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  window.bridgeSaveDraft = () => saveDraft();
  let authRedirecting = false;
  let mayRestoreProvider = !local && location.pathname === '/' && !new URLSearchParams(location.search).has('provider');
  async function refresh() {
    if(window.bridgeLoading&&!window.bridgeLoading.allowed())return;
    if (authRedirecting || document.querySelector("#auth-gate")?.hidden === false) return;
    try {
      if (local) {
        const other = providers.find(p => p.id !== current);
        const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 2500);
        try { await fetch(other.url, {mode: 'no-cors', cache: 'no-store', signal: controller.signal}); other.online = true; }
        catch { other.online = false; }
        finally { clearTimeout(timer); }
      } else {
        const response = await fetch('/api/providers', {cache: 'no-store'});
        if (response.status === 401) {
          authRedirecting = true;
          await saveDraft();
          location.assign('/signed-out.html');
          return;
        }
        if (!response.ok) return;
        const value = await response.json();
        providers = value.providers || providers;
        if (mayRestoreProvider) {
          mayRestoreProvider = false;
          const target = providers.find(p => p.id === previousProvider && p.id !== current && p.online);
          if (target) { await navigate(target); return; }
        }
      }
      paint();
    } catch {}
  }
  paint(); refresh(); setInterval(refresh, 10000);
})();
