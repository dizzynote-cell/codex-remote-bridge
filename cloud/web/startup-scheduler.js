/* First paint and the conversation list precede background reads. */
(() => {
  let primary = false, foreground = 0, scheduled = false;
  const queue = new Map(), running = new Map();
  const allowed = () => primary && foreground === 0;
  function drain() {
    if (scheduled || !allowed() || !queue.size) return;
    scheduled = true;
    const later = window.requestAnimationFrame || (fn => setTimeout(fn, 0));
    later(() => later(() => {
      scheduled = false;
      if (!allowed()) return;
      const jobs = [...queue]; queue.clear();
      // Independent low-priority jobs begin together after the list can paint.
      for (const [key, job] of jobs) {
        if (!allowed()) { queue.set(key, job); continue; }
        const work = Promise.resolve().then(job.fn);
        running.set(key, work);
        work.then(job.resolve, job.reject).finally(() => { running.delete(key); drain(); });
      }
    }));
  }
  window.bridgeLoading = {
    allowed,
    background(key, fn) {
      if (running.has(key)) return running.get(key);
      if (queue.has(key)) return queue.get(key).promise;
      let resolve, reject;
      const promise = new Promise((a,b) => { resolve=a; reject=b; });
      queue.set(key, {fn, resolve, reject, promise}); drain();
      return promise;
    },
    release() { primary = true; drain(); },
    begin() { foreground++; },
    end() { foreground = Math.max(0, foreground-1); drain(); }
  };
})();
