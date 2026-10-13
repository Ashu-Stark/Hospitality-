// Hash router: #/path/:param?query. Deep-linkable; filters update the URL with replaceState (no re-render).
import { role } from './api.js';
import { announce, href, mount, html, errorBox } from './ui.js';

const routes = [];
let renderId = 0;
let first = true;
let prevPath = null;
let cleanup = null;
let onNav = () => {};

export function route(pattern, view, opts = {}) {
  const keys = [];
  const re = new RegExp('^' + pattern.replace(/\/:([a-z_]+)/gi, (_, k) => { keys.push(k); return '/([^/]+)'; }) + '/?$');
  routes.push({ pattern, re, keys, view, ...opts });
}
export function parseHash() {
  const h = location.hash.slice(1) || '/';
  const [path, q = ''] = h.split('?');
  const query = Object.fromEntries(new URLSearchParams(q));
  return { path: path || '/', query };
}
export function go(path, query) { location.hash = href(path, query).slice(1); }
/** Update the query string of the current route without re-rendering (filters, tabs). */
export function setQuery(query) {
  const { path } = parseHash();
  history.replaceState(null, '', href(path, query));
}
export function onNavigate(fn) { onNav = fn; }

export async function render() {
  const id = ++renderId;
  const { path, query } = parseHash();
  let r = null;
  let params = {};
  for (const x of routes) {
    const m = x.re.exec(path);
    if (m) { r = x; x.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); }); break; }
  }
  const main = document.getElementById('main');
  if (typeof cleanup === 'function') { try { cleanup(); } catch { /* ignore */ } }
  cleanup = null;
  if (r?.roles && !r.roles.includes(role())) {
    go('/signin', { next: path + (Object.keys(query).length ? '?' + new URLSearchParams(query) : ''), need: r.roles.includes('business') ? 'business' : r.roles.includes('job_seeker') ? 'seeker' : 'official' });
    return;
  }
  onNav(path, r);
  const page = document.createElement('div');
  page.className = 'wrap page anim';
  main.replaceChildren(page);
  window.scrollTo(0, 0);
  const ctx = { params, query, el: page, alive: () => id === renderId, path, prev: prevPath };
  prevPath = path;
  if (!r) {
    mount(page, html`<h1>Page not found</h1><div class="section">${errorBox({ status: 404, message: 'There is no page at this address. Try the sitemap or search.' }, { retry: false })}</div>`);
    document.title = 'Not found · UTHP (concept)';
    return;
  }
  try {
    const res = await r.view(ctx);
    if (id !== renderId) return;
    if (typeof res === 'function') cleanup = res;
  } catch (e) {
    console.error(e);
    if (id === renderId) mount(page, errorBox(e, { retry: false }));
  }
  if (id !== renderId) return;
  const h1 = page.querySelector('h1');
  const title = (h1?.textContent || 'Portal').trim();
  document.title = title + ' · UTHP (concept)';
  const wasFirst = first;
  first = false;
  if (!ctx.keepFocus && !wasFirst) {
    if (h1) { h1.setAttribute('tabindex', '-1'); h1.focus({ preventScroll: true }); }
    announce(title);
  }
}
export function start() {
  window.addEventListener('hashchange', render);
  render();
}
