/* One creation at a time; an unknown result must never trigger another POST. */
(() => {
  window.createThreadGuard = ({form, dialog, opener}) => {
    const submit = form.querySelector('[type="submit"]');
    const originalLabel = submit.textContent;
    const note = document.createElement('p');
    note.className = 'new-thread-location';
    note.setAttribute('role', 'status');
    note.setAttribute('aria-live', 'polite');
    note.hidden = true;
    form.querySelector('footer').before(note);
    let busy = false, uncertain = false, disabled = [];
    const tell = text => { note.textContent = text; note.hidden = !text; };
    const restore = () => {
      for (const [control, wasDisabled] of disabled) control.disabled = wasDisabled;
      disabled = [];
      submit.textContent = originalLabel;
      form.removeAttribute('aria-busy');
    };
    dialog.addEventListener('cancel', event => { if (busy && !uncertain) event.preventDefault(); });
    const unknown = text => {
      uncertain = true;
      tell(text || '创建结果暂未确认，请先检查对话列表，不要重复创建。确认结果后再刷新页面操作。');
      // Let the user inspect the list while retaining the submission lock.
      for (const id of ['close-new-thread', 'cancel-new-thread']) {
        const button = form.querySelector('#' + id);
        if (button) button.disabled = false;
      }
      submit.textContent = '等待确认结果';
    };
    const pause = () => new Promise(resolve => setTimeout(resolve, 1000));
    const read = async (fetcher, path) => {
      const response = await fetcher(path, {cache:'no-store'});
      if (!response.ok) throw new Error('创建状态暂时无法读取');
      return response.json();
    };
    const rejected = text => Object.assign(new Error(text || '创建失败，请检查参数后重试'), {creationConfirmed:true});
    return {
      get busy() { return busy; },
      start() {
        if (busy) return false;
        busy = true; uncertain = false;
        disabled = [...new Set([...form.elements, opener])].map(control => [control, control.disabled]);
        for (const [control] of disabled) control.disabled = true;
        form.setAttribute('aria-busy', 'true');
        submit.textContent = '正在创建…';
        tell('正在创建对话，请稍候。结果确认前请勿重复提交。');
        return true;
      },
      succeed() {
        busy = false; uncertain = false;
        restore(); tell(''); dialog.close();
      },
      fail(error) {
        if (!busy) return;
        if (!error.creationConfirmed) { unknown(); return; }
        busy = false; uncertain = false;
        restore(); tell(error.message);
      },
      async local(data, fetcher) {
        if (data.threadId) return data;
        if (!data.taskId) throw new Error('创建结果未确认');
        while (busy) {
          let task;
          try { task = await read(fetcher, `/api/local-task/${encodeURIComponent(data.taskId)}`); }
          catch { unknown('创建状态暂时无法读取，正在继续查询；不会重复提交。'); await pause(); continue; }
          if (task.threadId) return task;
          if (['failed','cancelled','interrupted','expired'].includes(task.status)) throw rejected(task.message || task.error);
          await pause();
        }
      },
      async cloud(data, fetcher) {
        if (!data.taskId) throw new Error('创建结果未确认');
        const after = Math.floor(Date.now() / 1000) - 60;
        while (busy) {
          let events, tasks;
          try {
            events = (await read(fetcher, `/api/task/${encodeURIComponent(data.taskId)}/events?after=0`)).events || [];
            const created = events.find(event => event.kind === 'created' && event.payload?.threadId);
            if (created) return created.payload;
            const error = events.find(event => event.kind === 'error');
            if (error) throw rejected(error.payload?.message);
            tasks = (await read(fetcher, `/api/tasks?after=${after}`)).tasks || [];
          } catch (error) {
            if (error.creationConfirmed) throw error;
            unknown('创建状态暂时无法读取，正在继续查询；不会重复提交。'); await pause(); continue;
          }
          const task = tasks.find(task => task.id === data.taskId);
          if (task && ['failed','cancelled','expired'].includes(task.status)) throw rejected(task.error || (task.status === 'expired' ? '本机未及时接收，创建请求已过期。请确认主机在线后重试。' : '创建失败'));
          await pause();
        }
      }
    };
  };
})();
