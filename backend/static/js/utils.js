/* Utility helpers */
const U = {
  $(sel, parent) { return (parent || document).querySelector(sel); },
  $$(sel, parent) { return [...(parent || document).querySelectorAll(sel)]; },
  el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'html') e.innerHTML = v;
      else e.setAttribute(k, v);
    });
    children.flat(9).forEach(c => {
      if (c == null) return;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  },
  formatTime(s) {
    const m = Math.floor(s / 60);
    return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
  },
  formatSize(bytes) {
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  },
  svg(html, w, h) {
    const d = U.el('div', { html });
    const s = d.firstElementChild;
    if (s) { s.setAttribute('width', w); s.setAttribute('height', h); }
    return s || d;
  }
};
