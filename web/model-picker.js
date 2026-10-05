/* Shared model, reasoning, and speed picker. Settings are saved only after a task is accepted. */
(() => {
  const composer = document.querySelector('#composer');
  const newForm = document.querySelector('#new-thread-form');
  const row = document.createElement('section');
  row.className = 'model-bar';
  row.innerHTML = '<label>模型 <select id="bridge-model" aria-label="模型"></select></label>' +
    '<label>强度 <select id="bridge-effort" aria-label="推理强度"></select></label>' +
    '<label class="fast-choice" title="快速模式的订阅额度消耗为标准模式的 2.5 倍；运行中的补充引导沿用当前回合速度"><input id="bridge-fast" type="checkbox"> <span id="bridge-fast-label">快速模式</span></label>' +
    '<span id="model-running" role="status"></span>';
  composer.before(row);

  const newRow = document.createElement('div');
  newRow.className = 'new-model-settings';
  newRow.innerHTML = '<label>模型 <select id="new-thread-model"></select></label>' +
    '<label>推理强度 <select id="new-thread-effort"></select></label>' +
    '<label class="fast-choice" title="快速模式的订阅额度消耗为标准模式的 2.5 倍"><input id="new-thread-fast" type="checkbox"> <span id="new-thread-fast-label">快速模式</span></label>';
  newForm.querySelector('footer').before(newRow);

  const model = row.querySelector('#bridge-model');
  const effort = row.querySelector('#bridge-effort');
  const fast = row.querySelector('#bridge-fast');
  const fastLabel = row.querySelector('#bridge-fast-label');
  const status = row.querySelector('#model-running');
  const newModel = newRow.querySelector('#new-thread-model');
  const newEffort = newRow.querySelector('#new-thread-effort');
  const newFast = newRow.querySelector('#new-thread-fast');
  const newFastLabel = newRow.querySelector('#new-thread-fast-label');
  const names = {none:'不推理',minimal:'最低',low:'轻度',medium:'中',high:'高',xhigh:'极高',max:'最大',ultra:'Ultra'};
  let models = [], choices = {}, drafts = {}, defaults = {}, current = null, currentId = null;
  let pending = 0, loading = false, error = '', newManual = false, speedAvailable = false;

  const entry = id => models.find(item => item.model === id);
  const defaultEffort = id => id === defaults.model ? defaults.effort || entry(id)?.defaultReasoningEffort : entry(id)?.defaultReasoningEffort;
  const fastOption = id => (entry(id)?.serviceTiers || []).find(item => item.id === 'fast' || item.id === 'priority' || /fast/i.test(item.name || ''));
  const fastTier = id => speedAvailable
    ? fastOption(id)?.id || (entry(id)?.additionalSpeedTiers || []).find(id => id === 'fast' || id === 'priority') || null
    : null;
  const tierFrom = (choice, id) => choice && Object.hasOwn(choice, 'serviceTier') && choice.serviceTier != null
    ? choice.serviceTier : id === defaults.model ? defaults.serviceTier || 'default' : 'default';

  function label(turn) {
    const record = turn?.bridgeModel;
    const name = turn?.model || record?.actual || record?.requested;
    if (!name) return '模型未记录';
    const tier = record?.serviceTier || turn?.serviceTier;
    return `${name} · ${names[record?.effort] || record?.effort || '强度未记录'}${tier && tier !== 'default' ? ' · 快速' : ''}`;
  }
  function merge(incoming) {
    for (const [id, value] of Object.entries(incoming || {})) {
      if (value && value.updated > (choices[id]?.updated || 0)) choices[id] = value;
    }
  }
  function fill(target, items, value) {
    const signature = JSON.stringify(items);
    if (target.dataset.catalog !== signature) {
      target.replaceChildren(...items.map(([id, name]) => new Option(name, id)));
      target.dataset.catalog = signature;
    }
    target.value = value || '';
  }
  function fillPair(m, e, modelId, effortId) {
    fill(m, models.map(item => [item.model, item.displayName || item.model]), modelId);
    fill(e, (entry(modelId)?.supportedReasoningEfforts || []).map(item => [item.reasoningEffort, names[item.reasoningEffort] || item.reasoningEffort]), effortId);
  }
  function paint() {
    const choice = drafts[currentId] || choices[currentId];
    const manual = Boolean(choice?.model);
    const selectedModel = manual ? choice.model : defaults.model;
    fillPair(model, effort, selectedModel, manual ? choice.effort || defaultEffort(selectedModel) : defaultEffort(selectedModel));
    const tier = tierFrom(manual ? choice : null, selectedModel);
    fast.checked = Boolean(fastTier(selectedModel) && tier !== 'default');
    fast.disabled = !current || !fastTier(selectedModel) || pending > 0;
    fastLabel.textContent = '快速模式';
    row.querySelector('.fast-choice').hidden = !fastTier(selectedModel);

    const newModelId = newManual ? newModel.value : defaults.model;
    const newEffortId = newManual ? newEffort.value : defaultEffort(newModelId);
    fillPair(newModel, newEffort, newModelId, newEffortId);
    if (!newManual) newFast.checked = Boolean(fastTier(newModelId) && tierFrom(null, newModelId) !== 'default');
    newFast.disabled = !models.length || !fastTier(newModelId);
    newFastLabel.textContent = '快速模式';
    newRow.querySelector('.fast-choice').hidden = !fastTier(newModelId);

    model.disabled = effort.disabled = !models.length || !current || pending > 0;
    newModel.disabled = newEffort.disabled = !models.length;
    status.textContent = error;
    row.classList.toggle('model-error', Boolean(error));
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch('/api/models', {cache:'no-store'});
      if (!response.ok) throw Error('模型设置暂不可用，请稍后刷新');
      const data = await response.json();
      models = data.models || [];
      defaults = data.defaults || {};
      speedAvailable = data.speedModeSupported === true;
      merge(data.choices);
      if (!pending) error = '';
    } catch (reason) { error = reason.message; }
    finally { loading = false; paint(); }
  }
  function draft(m, e, tier) {
    drafts[currentId] = {model:m, effort:e, serviceTier:tier};
    error = '';
    paint();
  }
  model.onchange = () => draft(model.value, defaultEffort(model.value), fast.checked && fastTier(model.value) ? fastTier(model.value) : 'default');
  effort.onchange = () => draft(model.value, effort.value, fast.checked && fastTier(model.value) ? fastTier(model.value) : 'default');
  fast.onchange = () => draft(model.value, effort.value, fast.checked ? fastTier(model.value) : 'default');
  newModel.onchange = () => {
    newManual = true;
    if (!fastTier(newModel.value)) newFast.checked = false;
    fillPair(newModel, newEffort, newModel.value, defaultEffort(newModel.value));
    paint();
  };
  newEffort.onchange = () => { newManual = true; };
  newFast.onchange = () => { newManual = true; };

  window.modelPicker = {
    begin(id) { if (currentId !== id) { currentId = id; current = null; error = ''; paint(); } },
    thread(thread) { if (thread.id !== currentId) return; current = thread; if (thread.bridgeModelChoice) merge({[thread.id]:thread.bridgeModelChoice}); paint(); },
    capture(id, isNew = false) {
      if (pending) throw Error('设置仍在保存，请稍后发送');
      if (!isNew && (id !== currentId || !current)) throw Error('正在读取此对话，请稍后发送');
      const m = isNew ? newModel.value : model.value;
      const e = isNew ? newEffort.value : effort.value;
      const selectedFast = isNew ? newFast.checked : fast.checked;
      if (!entry(m) || (entry(m).supportedReasoningEfforts || []).every(item => item.reasoningEffort !== e))
        throw Error('请等待模型与强度加载，或重新选择');
      if (selectedFast && !fastTier(m)) throw Error('该模型不支持快速模式');
      return {model:m, effort:e, serviceTier:selectedFast ? fastTier(m) : 'default',
        followDefaults:isNew ? !newManual : !(drafts[id] || choices[id])?.model};
    },
    accepted(id, settings) {
      if (id && !settings.followDefaults) {
        choices[id] = {model:settings.model, effort:settings.effort, serviceTier:settings.serviceTier, updated:Date.now()/1000};
        const draftValue = drafts[id];
        if (draftValue?.model === settings.model && draftValue?.effort === settings.effort && draftValue?.serviceTier === settings.serviceTier)
          delete drafts[id];
      }
      if (!id) newManual = false;
      paint();
    },
    label, refresh,
  };
  paint();
  refresh();
  setInterval(refresh, 10000);
})();
