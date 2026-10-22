/* Desktop assignment is presentation metadata; never replace the execution cwd. */
(() => {
  const api = {
    key(thread) { return thread.desktopProject?.key || thread.projectOverride || thread.cwd || ''; },
    cwd(key, projects) { return key === 'desktop:projectless' ? '' : (projects.find(p => p.key === key)?.cwd || key); },
    name(key, projects) {
      if (key === 'desktop:projectless') return '独立会话';
      const project = projects.find(p => p.key === key || p.cwd === key);
      if (project?.name) return project.name;
      if (!key) return '未归类项目';
      return String(key).replace(/[\\/]+$/, '').split(/[\\/]/).at(-1) || '未归类项目';
    },
    groups(groups, projects) {
      const rank = new Map(projects.map((p, i) => [p.key || p.cwd, i]));
      return [...groups].sort((a, b) => (rank.get(a[0]) ?? 100000) - (rank.get(b[0]) ?? 100000));
    }
  };
  window.projectDisplay = api;
})();
