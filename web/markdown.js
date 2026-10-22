/* Local Markdown parser. Raw HTML is always text; no remote scripts or images. */
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const parser = window.markdownit?.({html: false, breaks: true, linkify: false, typographer: false});
  if (parser) {
    const valid = parser.validateLink.bind(parser);
    parser.validateLink = href => {
      try { return valid(href) && ['http:', 'https:', 'mailto:'].includes(new URL(href, 'https://bridge.invalid/').protocol); }
      catch { return false; }
    };
    parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
      tokens[index].attrSet('target', '_blank');
      tokens[index].attrSet('rel', 'noopener noreferrer');
      return renderer.renderToken(tokens, index, options);
    };
    parser.renderer.rules.image = (tokens, index) => {
      const token = tokens[index], href = token.attrGet('src') || '';
      const label = parser.renderer.renderInlineAsText(token.children || [], {}, {});
      return parser.validateLink(href) ? `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">图片：${escape(label || '查看图片')}</a>` : escape(label);
    };
    parser.renderer.rules.table_open = () => '<div class="markdown-table" tabindex="0" role="region" aria-label="表格，可横向滚动"><table>\n';
    parser.renderer.rules.table_close = () => '</table></div>\n';
  }
  const cache = new Map();
  window.renderMarkdown = value => {
    const text = String(value ?? '');
    if (cache.has(text)) return cache.get(text);
    let html;
    try { html = parser ? parser.render(text) : `<div class="markdown-fallback">${escape(text)}</div>`; }
    catch { html = `<div class="markdown-fallback">${escape(text)}</div>`; }
    if (text.length < 200000) {
      if (cache.size >= 32) cache.delete(cache.keys().next().value);
      cache.set(text, html);
    }
    return html;
  };
})();
