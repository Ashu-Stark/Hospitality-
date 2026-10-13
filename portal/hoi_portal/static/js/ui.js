// UI helpers: XSS-safe HTML templating, formatting, status pills, loading/empty/error states, forms, toast, drawer.
// Every interpolated value in html`` is escaped unless it is itself the result of html`` (Safe) or raw().

export class Safe {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;', '=': '&#61;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"'`=]/g, (c) => ESC[c]);
function part(v) {
  if (v == null || v === false || v === true) return '';
  if (v instanceof Safe) return v.s;
  if (Array.isArray(v)) return v.map(part).join('');
  return esc(v);
}
export function html(strings, ...vals) {
  let out = strings[0];
  for (let i = 0; i < vals.length; i++) out += part(vals[i]) + strings[i + 1];
  return new Safe(out);
}
/** Only for markup built by this code base from constants (never API strings). */
export const raw = (s) => new Safe(String(s));
export function mount(el, content) {
  el.innerHTML = part(content);
  return el;
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ------------------------------------------------------------------ links
/** Build a hash link with a query string; values are URI-encoded, empty values dropped. */
export function href(path, query) {
  const q = query ? qs(query) : '';
  return '#' + path + (q ? '?' + q : '');
}
export function qs(query) {
  return Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false)
    .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v))
    .join('&');
}

// ------------------------------------------------------------------ formatting
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const monthName = (m, short = false) => (short ? MONTHS[m - 1]?.slice(0, 3) : MONTHS[m - 1]) || '';
export const MONTH_NAMES = MONTHS;
export function fmtDate(s, opts = {}) {
  if (!s) return '—';
  const d = new Date(s.length === 10 ? s + 'T00:00:00' : s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: opts.noYear ? undefined : 'numeric', weekday: opts.weekday ? 'short' : undefined });
}
export function fmtDateTime(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export function fmtMonth(ym) {
  if (!ym) return '—';
  const [y, m] = ym.split('-').map(Number);
  return monthName(m, true) + ' ' + y;
}
export function relTime(s) {
  if (!s) return '';
  const diff = (Date.now() - new Date(s).getTime()) / 1000;
  const abs = Math.abs(diff);
  const fut = diff < 0;
  let v;
  if (abs < 60) return 'just now';
  if (abs < 3600) v = Math.round(abs / 60) + ' min';
  else if (abs < 86400) v = Math.round(abs / 3600) + ' h';
  else { const d = Math.round(abs / 86400); v = d + (d === 1 ? ' day' : ' days'); }
  return fut ? 'in ' + v : v + ' ago';
}
export const num = (n, d = 0) => (n == null || isNaN(n) ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: 0 }));
export const pct = (n, d = 1) => (n == null ? '—' : num(n, d) + '%');
export const titleCase = (s) => String(s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

// ------------------------------------------------------------------ pills
export const BANDS = {
  low: { label: 'Quiet', cls: 'ok' },
  moderate: { label: 'Normal', cls: 'warn' },
  high: { label: 'Busy', cls: 'hot' },
  very_high: { label: 'Very busy', cls: 'bad' },
};
export function bandPill(band, index, prefix = '') {
  const b = BANDS[band] || { label: band || 'Unknown', cls: 'neutral' };
  return html`<span class="pill ${b.cls}">${prefix ? prefix + ': ' : ''}${b.label}</span>`;
}
const STATUS = {
  active: ['ok', 'Active'], expired: ['bad', 'Expired'], suspended: ['bad', 'Suspended'], pending: ['warn', 'Pending renewal'],
  submitted: ['info', 'Submitted'], changes_requested: ['warn', 'Changes requested'], approved: ['ok', 'Approved'], rejected: ['bad', 'Rejected'],
  received: ['info', 'Received'], assigned: ['violet', 'Assigned'], in_progress: ['warn', 'In progress'], resolved: ['ok', 'Resolved'], closed: ['neutral', 'Closed'],
  open: ['ok', 'Open'], caution: ['warn', 'Caution'],
};
export function statusPill(s, label) {
  const [cls, l] = STATUS[s] || ['neutral', titleCase(s)];
  return html`<span class="pill ${cls}">${label || l}</span>`;
}
// Predicted road traffic band (traffic model; never a measurement).
const TRAFFIC = { free: ['ok', 'Smooth'], moderate: ['warn', 'Slow'], heavy: ['bad', 'Very slow'], severe: ['bad', 'Very slow'] };
export function trafficPill(band, prefix = 'Traffic') {
  const [cls, l] = TRAFFIC[band] || ['neutral', band || 'Unknown'];
  return html`<span class="pill ${cls}">${prefix ? prefix + ': ' : ''}${l}</span>`;
}
export function roadPill(s) {
  const map = { open: ['ok', 'Open'], caution: ['warn', 'Caution'], closed: ['bad', 'Closed'] };
  const [cls, l] = map[s] || ['neutral', titleCase(s || 'Info')];
  return html`<span class="pill ${cls}">${l}</span>`;
}
export function impactPill(i) {
  const map = { low: ['ok', 'A little busier'], medium: ['warn', 'Busier'], high: ['bad', 'Very busy'] };
  const [cls, l] = map[i] || ['neutral', 'Busy level unknown'];
  return html`<span class="pill ${cls}">${l}</span>`;
}
export const verifiedPill = (v) => (v ? html`<span class="pill info">Verified</span>` : html`<span class="pill neutral noicon">Not verified</span>`);
export const synPill = () => '';
export const samplePill = () => '';

// ------------------------------------------------------------------ states
export function skeleton(kind = 'page', n = 3) {
  if (kind === 'cards') return html`<div class="mcgrid" aria-hidden="true">${Array.from({ length: n }, () => html`<div class="sk card"></div>`)}</div>`;
  if (kind === 'list') return html`<div class="list" aria-hidden="true">${Array.from({ length: n }, () => html`<div class="sk line sk-row"></div>`)}</div>`;
  if (kind === 'block') return html`<div class="sk block" aria-hidden="true"></div>`;
  return html`<div aria-hidden="true"><div class="sk h"></div><div class="sk line"></div><div class="sk line"></div><div class="sk block"></div></div>`;
}
export function loading(label = 'Loading…', kind = 'page', n = 3) {
  return html`<div role="status" aria-live="polite"><span class="sr-only">${label}</span>${skeleton(kind, n)}</div>`;
}
export function empty(title, text = '', action = '') {
  return html`<div class="state" role="status"><div class="ico" aria-hidden="true">○</div><h3>${title}</h3>${text ? html`<p>${text}</p>` : ''}${action}</div>`;
}
/** Friendly error state; err is an ApiError (status 0 = network). retryId gets a data-retry button. */
export function errorBox(err, { retry = true } = {}) {
  const s = err?.status;
  let title = 'Something went wrong';
  let text = err?.message || 'Please try again.';
  let cls = 'err';
  let action = retry ? html`<button type="button" class="btn ghost" data-retry>Try again</button>` : '';
  if (s === 0) { title = 'The portal service cannot be reached'; text = 'The API did not respond. Check your connection or try again in a moment.'; }
  else if (s === 401) { title = 'Please sign in again'; text = err.message || 'Your session has ended.'; action = html`<a class="btn primary" href="${href('/signin', { next: location.hash.slice(1) })}">Sign in</a>`; }
  else if (s === 403) { title = 'Not allowed'; }
  else if (s === 409) { title = 'Not possible right now'; cls = 'wait'; }
  else if (s === 404) { title = 'Not found'; action = html`<a class="btn ghost" href="#/">Go to home</a>`; }
  else if (s === 429) { title = 'Too many tries, please wait'; cls = 'wait'; }
  return html`<div class="state ${cls}" role="alert"><div class="ico" aria-hidden="true">${s === 429 ? '⏳' : '!'}</div><h3>${title}</h3><p>${text}</p>${action}</div>`;
}
/** Run a loader into a container with skeleton + error + retry wiring. */
export async function load(el, fn, { skel = 'page', n = 3, label } = {}) {
  mount(el, loading(label, skel, n));
  try {
    await fn();
  } catch (e) {
    if (!el.isConnected) return;
    console.warn(e);
    mount(el, errorBox(e));
    el.querySelector('[data-retry]')?.addEventListener('click', () => load(el, fn, { skel, n, label }));
  }
}

// ------------------------------------------------------------------ announcements, toast, copy
export function announce(msg) {
  const live = document.getElementById('live');
  if (!live) return;
  live.textContent = '';
  setTimeout(() => { live.textContent = msg; }, 50);
}
let toastTimer;
export function toast(msg, kind = '') {
  document.querySelector('.toast')?.remove();
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.setAttribute('role', kind === 'err' ? 'alert' : 'status');
  t.textContent = msg;
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 3800);
}
export const copyBtn = (text, label = 'Copy') => html`<button type="button" class="btn sm ghost" data-copy="${text}" aria-label="${label}: ${text}">${label}</button>`;
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-copy]');
  if (!b) return;
  const text = b.getAttribute('data-copy');
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to clipboard');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.className = 'sr-only';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); toast('Copied to clipboard'); } catch { toast('Copy failed; select the text manually', 'err'); }
    ta.remove();
  }
});

// ------------------------------------------------------------------ forms
export function field({ id, label, type = 'text', required = false, options, hint, value = '', placeholder = '', opt = false, attrs = '', rows }) {
  const hid = hint ? id + '-hint' : '';
  const lab = html`<label class="lbl" for="${id}">${label}${opt ? html` <span class="opt">(optional)</span>` : ''}${required ? html`<span class="sr-only"> (required)</span>` : ''}</label>`;
  let ctl;
  if (type === 'select') {
    ctl = html`<select class="field" id="${id}" name="${id}" ${required ? raw('required') : ''} ${hid ? html`aria-describedby="${hid}"` : ''}>${(options || []).map(
      (o) => html`<option value="${o.value}" ${String(o.value) === String(value) ? raw('selected') : ''}>${o.label}</option>`,
    )}</select>`;
  } else if (type === 'textarea') {
    ctl = html`<textarea class="field" id="${id}" name="${id}" rows="${rows || 5}" placeholder="${placeholder}" ${required ? raw('required') : ''} ${hid ? html`aria-describedby="${hid}"` : ''} ${raw(attrs)}>${value}</textarea>`;
  } else {
    ctl = html`<input class="field" id="${id}" name="${id}" type="${type}" value="${value}" placeholder="${placeholder}" ${required ? raw('required') : ''} ${hid ? html`aria-describedby="${hid}"` : ''} ${raw(attrs)}>`;
  }
  return html`<div class="fld">${lab}${ctl}${hint ? html`<div class="hint" id="${hid}">${hint}</div>` : ''}</div>`;
}
export function clearErrors(form) {
  $$('.ferr', form).forEach((e) => e.remove());
  $$('[aria-invalid]', form).forEach((e) => {
    e.removeAttribute('aria-invalid');
    const d = (e.getAttribute('aria-describedby') || '').split(' ').filter((x) => !x.endsWith('-err')).join(' ');
    if (d) e.setAttribute('aria-describedby', d); else e.removeAttribute('aria-describedby');
  });
  $('.formerr', form)?.remove();
}
/** errors: {fieldName: message}. Marks inputs invalid, links messages, focuses the first. */
export function showErrors(form, errors, summary) {
  clearErrors(form);
  let first = null;
  for (const [name, msg] of Object.entries(errors)) {
    const input = form.querySelector(`[name="${CSS.escape(name)}"]`);
    if (!input) continue;
    const id = (input.id || name) + '-err';
    const p = document.createElement('p');
    p.className = 'ferr';
    p.id = id;
    p.textContent = msg;
    (input.closest('.fld') || input.parentElement).appendChild(p);
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', ((input.getAttribute('aria-describedby') || '') + ' ' + id).trim());
    first = first || input;
  }
  if (summary || !first) {
    const box = document.createElement('div');
    box.className = 'flag red formerr';
    box.setAttribute('role', 'alert');
    box.textContent = summary || 'Please check the form.';
    form.prepend(box);
  }
  first?.focus();
}
/** Turn an API 422 error into field errors (field names match input names). */
export function apiFieldErrors(err) {
  const out = {};
  for (const e of err?.data?.errors || []) if (e.field) out[e.field.split('.').pop()] = e.message;
  return out;
}
export function busy(btn, on, label = 'Working…') {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.textContent; btn.textContent = label; btn.disabled = true; btn.setAttribute('aria-busy', 'true'); }
  else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; btn.removeAttribute('aria-busy'); }
}

// ------------------------------------------------------------------ table
/** cols: [{key, label, num, render(row)}] */
export function table(cols, rows, caption = '') {
  return html`<div class="tablewrap" tabindex="0" role="region" aria-label="${caption || 'Table'}"><table class="tbl">${caption ? html`<caption>${caption}</caption>` : ''}
    <thead><tr>${cols.map((c) => html`<th scope="col" class="${c.num ? 'num' : ''}">${c.label}</th>`)}</tr></thead>
    <tbody>${rows.map((r) => html`<tr>${cols.map((c, i) => {
      const v = c.render ? c.render(r) : r[c.key];
      return i === 0 ? html`<th scope="row" class="${c.num ? 'num' : ''}">${v}</th>` : html`<td class="${c.num ? 'num' : ''}">${v}</td>`;
    })}</tr>`)}</tbody></table></div>`;
}

// ------------------------------------------------------------------ drawer / dialog
export function drawer(title, { onClose } = {}) {
  const d = document.createElement('dialog');
  d.className = 'drawer';
  d.setAttribute('aria-labelledby', 'drawer-title');
  mount(d, html`<div class="drawer-h"><h2 id="drawer-title">${title}</h2><button type="button" class="btn sm ghost" data-close>Close</button></div><div class="drawer-b"></div>`);
  document.body.appendChild(d);
  const opener = document.activeElement;
  const close = () => { d.close(); };
  d.addEventListener('close', () => { d.remove(); onClose?.(); opener?.focus?.(); });
  d.querySelector('[data-close]').addEventListener('click', close);
  d.addEventListener('click', (e) => { if (e.target === d) close(); });
  d.showModal();
  return { el: d, body: d.querySelector('.drawer-b'), close, setTitle: (t) => { d.querySelector('#drawer-title').textContent = t; } };
}
export function confirmDialog(message, { ok = 'Confirm', danger = false } = {}) {
  return new Promise((resolve) => {
    const d = document.createElement('dialog');
    d.className = 'modal';
    mount(d, html`<h2>Please confirm</h2><p class="section">${message}</p><div class="btnrow section"><button type="button" class="btn ${danger ? 'danger' : 'primary'}" data-ok>${ok}</button><button type="button" class="btn ghost" data-no>Cancel</button></div>`);
    document.body.appendChild(d);
    const done = (v) => { d.close(); d.remove(); resolve(v); };
    d.querySelector('[data-ok]').addEventListener('click', () => done(true));
    d.querySelector('[data-no]').addEventListener('click', () => done(false));
    d.addEventListener('cancel', () => done(false));
    d.showModal();
  });
}

// ------------------------------------------------------------------ misc
export function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
export function store(key, val) {
  try {
    if (val === undefined) return localStorage.getItem(key);
    if (val === null) localStorage.removeItem(key); else localStorage.setItem(key, val);
  } catch { /* storage blocked */ }
  return null;
}
export function lastUpdated(iso, extra = '') {
  return html`<p class="updated">Last updated: ${iso ? fmtDateTime(iso) : fmtDate(new Date().toISOString())}${extra ? ' · ' + extra : ''}</p>`;
}
export function crumbs(items) {
  return html`<nav class="crumbs" aria-label="Breadcrumb">${items.map((c, i) => (i < items.length - 1 ? html`<a href="${c[1]}">${c[0]}</a><span aria-hidden="true">›</span>` : html`<span aria-current="page">${c[0]}</span>`))}</nav>`;
}

// Generated landscape art for destination cards (no external images; deterministic per id).
export function landscape(seed) {
  let h = 0;
  for (const c of String(seed)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const pal = [['#e0631f', '#a83b12'], ['#2c6e8f', '#123a52'], ['#5c7a5a', '#203020'], ['#7a4fb0', '#35205a'], ['#c94d16', '#5a1d06'], ['#1f6fe5', '#0d2f6b']][h % 6];
  const p1 = 40 + (h % 30), p2 = 20 + ((h >> 3) % 40), p3 = 50 + ((h >> 5) % 30);
  return raw(`<svg viewBox="0 0 300 130" preserveAspectRatio="none" aria-hidden="true" focusable="false"><defs><linearGradient id="lg${h}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${pal[0]}"/><stop offset="1" stop-color="${pal[1]}"/></linearGradient></defs><rect width="300" height="130" fill="url(#lg${h})"/><path d="M0 ${p1 + 40} L60 ${p2 + 20} L110 ${p3 + 10} L170 ${p2} L230 ${p1 + 10} L300 ${p2 + 30} V130 H0Z" fill="#fff" opacity=".18"/><path d="M0 ${p3 + 50} L80 ${p1 + 30} L150 ${p3 + 40} L220 ${p2 + 45} L300 ${p1 + 40} V130 H0Z" fill="#000" opacity=".22"/></svg>`);
}

// ------------------------------------------------------------------ progressive disclosure
let moreId = 0;
/** First n rows visible, the rest behind a "Show N more" button (keyboard + screen-reader friendly). */
export function moreList(items, render, n = 5, cls = 'list') {
  if (items.length <= n) return html`<div class="${cls}">${items.map(render)}</div>`;
  const id = 'more' + ++moreId;
  return html`<div class="${cls}">${items.slice(0, n).map(render)}</div><div class="${cls} more-rest" id="${id}" hidden>${items.slice(n).map(render)}</div>
    <button type="button" class="btn sm ghost more-btn" data-more="${id}" aria-expanded="false" aria-controls="${id}">Show ${items.length - n} more</button>`;
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-more]');
  if (!b) return;
  const rest = document.getElementById(b.dataset.more);
  if (!rest) return;
  const open = rest.hidden;
  rest.hidden = !open;
  b.setAttribute('aria-expanded', String(open));
  if (!b.classList.contains('more-btn')) return;
  if (!b.dataset.lessLabel) b.dataset.lessLabel = b.textContent;
  b.textContent = open ? 'Show less' : b.dataset.lessLabel;
  if (open) rest.querySelector('a,button,[tabindex]')?.focus();
});
/** Wrap a filter form in a <details> that is collapsed on phones (summary shows the active filter count). */
export function collapseFilters(form, label = 'Filters') {
  if (!form || form.closest('details.filterbox')) return;
  const d = document.createElement('details');
  d.className = 'filterbox';
  d.open = window.matchMedia('(min-width: 761px)').matches;
  const s = document.createElement('summary');
  d.appendChild(s);
  form.parentNode.insertBefore(d, form);
  d.appendChild(form);
  const count = () => {
    const n = Array.from(form.elements).filter((x) => x.name && x.type !== 'checkbox' && x.type !== 'radio' && x.value && x.name !== 'page' && x.value !== x.dataset.default).length;
    s.textContent = n ? `${label} (${n} active)` : label;
  };
  form.addEventListener('input', count);
  form.addEventListener('change', count);
  form.addEventListener('reset', () => setTimeout(count));
  count();
}
/** Client-side pager: renders page `p` of `items` into el via renderPage(slice), with Previous/Next. */
export function pager(el, items, renderPage, size = 12, onPage) {
  let p = 1;
  const pages = Math.max(1, Math.ceil(items.length / size));
  const draw = (focus) => {
    mount(el, html`${renderPage(items.slice((p - 1) * size, p * size))}${pages > 1 ? html`<nav class="pager" aria-label="Pages"><button type="button" class="btn sm ghost" data-p="-1" ${p <= 1 ? raw('disabled') : ''}>Previous</button>
      <span class="small">Page ${p} of ${pages} · ${items.length} items</span><button type="button" class="btn sm ghost" data-p="1" ${p >= pages ? raw('disabled') : ''}>Next</button></nav>` : ''}`);
    el.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => { p += Number(b.dataset.p); draw(true); onPage?.(p); }));
    if (focus) { el.setAttribute('tabindex', '-1'); el.focus({ preventScroll: false }); }
  };
  draw(false);
}
/** Small (i) info toggle for a section footnote. */
export function infoNote(text, label = 'About this data') {
  const id = 'inf' + ++moreId;
  return html`<span class="infowrap"><button type="button" class="infobtn" data-more="${id}" aria-expanded="false" aria-controls="${id}" aria-label="${label}">i</button><span class="infotext" id="${id}" hidden>${text}</span></span>`;
}

// ------------------------------------------------------------------ simple, image-led building blocks
// Small line icons (24x24, 1.9 px strokes). Decorative: always next to a text label.
const ic = (body) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
export const TYPE_ICON = {
  hotel: ic('<path d="M4 20V5h10v15M14 9h6v11M7 8h2M7 12h2M7 16h2M17 13h1M17 16h1M2 20h20"/>'),
  homestay: ic('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10M10 20v-5h4v5"/>'),
  guide: ic('<circle cx="12" cy="5" r="2"/><path d="M10 22l1-7-2-3 2-4h2l2 4M14 22l-1-6M9 12l-3 2M16 9l2 4"/>'),
  travel_agent: ic('<path d="M3 13l18-7-7 18-3-8z"/>'),
  tour_operator: ic('<rect x="4" y="4" width="16" height="13" rx="3"/><path d="M4 11h16M7 21v-4M17 21v-4M8 14h.01M16 14h.01"/>'),
  transport: ic('<path d="M5 16V9l2-4h10l2 4v7"/><path d="M3 16h18v2H3zM7 18v2M17 18v2M5 11h14"/>'),
  adventure_operator: ic('<path d="M3 20l6-12 4 7 2-3 6 8z"/><path d="M14 6l2-2 2 2"/>'),
  restaurant: ic('<path d="M7 3v8M5 3v5a2 2 0 004 0V3M7 11v10M17 3c-2 0-3 2-3 5s1 4 3 4v9"/>'),
  staffing_agency: ic('<circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20c0-3.3 2.7-6 6-6s6 2.7 6 6M14 15c1-.6 2-.9 3-.9 2.8 0 5 2 5 5"/>'),
  front_office: ic('<path d="M3 20h18M5 20v-7h14v7M9 13V9h6v4M12 9V6"/>'),
  housekeeping: ic('<path d="M9 3h6l-1 6h-4z"/><path d="M6 21l3-12h6l3 12z"/>'),
  food_beverage: ic('<path d="M6 3h12l-2 8a4 4 0 01-8 0zM12 15v6M8 21h8"/>'),
  kitchen: ic('<path d="M6 14a6 6 0 1112 0z"/><path d="M4 14h16v3a3 3 0 01-3 3H7a3 3 0 01-3-3z"/>'),
  maintenance: ic('<path d="M14 6a4 4 0 00-5 5L3 17l4 4 6-6a4 4 0 005-5l-3 3-3-3z"/>'),
  wellness: ic('<path d="M12 20c-5-3-8-6-8-10a4 4 0 018-1 4 4 0 018 1c0 4-3 7-8 10z"/>'),
  operations: ic('<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>'),
  admin: ic('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h3"/>'),
  security: ic('<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>'),
  village_walk: ic('<path d="M3 20l5-9 4 6 3-4 6 7z"/><path d="M6 8l2-2 2 2v2H6zM14 6h4v4h-4z"/>'),
  home_meal: ic('<path d="M3 13h18a9 9 0 01-18 0z"/><path d="M9 4c0 2 2 2 2 4M13 4c0 2 2 2 2 4"/>'),
  artisan_workshop: ic('<path d="M4 20c3-8 13-8 16 0M8 20c1-4 7-4 8 0"/><path d="M12 3v7M9 6h6"/>'),
  farm_stay: ic('<path d="M3 20h18M5 20c0-5 3-9 7-9s7 4 7 9"/><path d="M12 11V4M9 7l3-3 3 3"/>'),
  nature_walk: ic('<path d="M12 21v-6M7 15h10L12 3z"/><path d="M5 21h14"/>'),
  birding: ic('<path d="M3 12c3 0 5-4 9-4 3 0 5 2 6 4l3 1-3 1c-1 3-4 5-8 5-4 0-6-3-7-7z"/>'),
  folk_music: ic('<ellipse cx="12" cy="7" rx="7" ry="3"/><path d="M5 7v9c0 1.7 3.1 3 7 3s7-1.3 7-3V7"/>'),
  heritage_walk: ic('<path d="M12 3l4 5H8z"/><path d="M7 21V10h10v11M4 21h16M10 21v-5h4v5"/>'),
  clock: ic('<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>'),
  people: ic('<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 11a3 3 0 100-6M18 20c0-2-.8-3.8-2-5"/>'),
  rupee: ic('<path d="M7 4h10M7 8h10M7 4c5 0 7 2 7 4s-2 4-7 4l8 8"/>'),
  calendar: ic('<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
  pin: ic('<path d="M12 21s-7-6.5-7-12a7 7 0 0114 0c0 5.5-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/>'),
  star: ic('<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.3l1.1-6.2L3 9.7l6.2-.9z"/>'),
  temp: ic('<path d="M10 4a2 2 0 014 0v10a4 4 0 11-4 0z"/>'),
  stay: ic('<path d="M3 18V8M3 14h18v4M21 14v-3a3 3 0 00-3-3h-7v6"/><circle cx="7" cy="11" r="2"/>'),
  lang: ic('<path d="M4 5h9M8 3v2M6 5c0 4 3 7 6 8M11 5c-1 4-4 7-7 8M13 21l4-9 4 9M14.5 18h5"/>'),
  route: ic('<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h7a3 3 0 000-6H9a3 3 0 010-6h7"/>'),
};
export const icon = (k) => raw(TYPE_ICON[k] || '');

/**
 * Image-led card used everywhere (destinations, stays, experiences, festivals, trips, jobs, directory).
 * media: html for the cover (photos.cover()); badge: html overlaid on the photo; kicker: small line above the title
 * (icon + type); facts: [[iconKey, text]] as an icon row; chips: short tags; foot: html in the footer.
 * The title link stretches over the whole card, so each card has one clear action.
 */
export function mediaCard({ href: url, media = '', badge = '', kicker = '', kickerIcon = '', title, line = '', facts = [], chips = [], foot = '', cls = '', headingLevel = 3 }) {
  const open = headingLevel === 2 ? raw('<h2 class="mc-title">') : raw('<h3 class="mc-title">');
  const close = headingLevel === 2 ? raw('</h2>') : raw('</h3>');
  return html`<article class="mc ${cls} ${media ? '' : 'nomedia'}">
    ${media ? html`<div class="mc-media">${media}${badge ? html`<span class="mc-badge">${badge}</span>` : ''}</div>` : ''}
    <div class="mc-body">
      ${kicker ? html`<p class="mc-kicker">${kickerIcon ? icon(kickerIcon) : ''}<span>${kicker}</span></p>` : ''}
      ${open}<a href="${url}">${title}</a>${close}
      ${!media && badge ? html`<div class="mc-badge-inline">${badge}</div>` : ''}
      ${line ? html`<p class="mc-line">${line}</p>` : ''}
      ${facts.filter((f) => f && f[1]).length ? html`<ul class="mc-facts">${facts.filter((f) => f && f[1]).map(([k, v]) => html`<li>${icon(k)}<span>${v}</span></li>`)}</ul>` : ''}
      ${chips.length ? html`<div class="mc-chips">${chips.map((c) => html`<span class="mchip">${c}</span>`)}</div>` : ''}
      ${foot ? html`<div class="mc-foot">${foot}</div>` : ''}
    </div></article>`;
}

/** Month chips (best months / season): consecutive months merge into ranges. */
export function monthChips(ms, max = 3) {
  if (!ms?.length) return [];
  if (ms.length === 12) return ['All year'];
  const s = [...new Set(ms)].sort((a, b) => a - b);
  const out = [];
  let st = s[0], pr = s[0];
  for (const m of s.slice(1).concat([99])) {
    if (m === pr + 1) { pr = m; continue; }
    out.push(st === pr ? monthName(st, true) : `${monthName(st, true)}–${monthName(pr, true)}`);
    st = pr = m;
  }
  return out.slice(0, max);
}

/** Big number tile: label, value, unit, trend arrow + text, tone ('ok' | 'warn' | 'bad'). */
export function statTile({ label, value, unit = '', trend = null, note = '', tone = '' }) {
  const arrow = trend ? { up: '▲', down: '▼', flat: '▶' }[trend.dir] || '' : '';
  return html`<div class="kpi stat ${tone}"><span class="k">${label}</span><span class="v">${value}${unit ? html`<small>${unit}</small>` : ''}</span>
    ${trend ? html`<span class="trend ${trend.good === false ? 'neg' : trend.good ? 'pos' : ''}"><span aria-hidden="true">${arrow}</span> ${trend.text}</span>` : ''}
    ${note ? html`<span class="small muted">${note}</span>` : ''}</div>`;
}

/** One plain-language sentence that says what a chart or number means. */
export const takeaway = (text) => html`<p class="takeaway">${text}</p>`;

/** Secondary content behind a "Show details" disclosure (native details element). */
export function details(summary, body, cls = '') {
  return html`<details class="more ${cls}"><summary>${summary}</summary><div class="more-b">${body}</div></details>`;
}

/** Crowd strip: one coloured cell per day with weekday, date and index printed in it (no axes, no legend). */
export function dayStrip(days) {
  const B = { low: 'Quiet', moderate: 'Normal', high: 'Busy', very_high: 'Very busy' };
  const band = (v) => (v < 40 ? 'low' : v < 65 ? 'moderate' : v < 85 ? 'high' : 'very_high');
  return html`<ol class="daystrip" aria-label="Crowd estimate per day">${days.map((d) => {
    const dt = new Date(d.date + 'T00:00');
    const b = d.band || band(d.index);
    const wd = dt.toLocaleDateString('en-IN', { weekday: 'short' });
    return html`<li class="ds ${b}"><span class="sr-only">${dt.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })}: ${B[b]}</span><span class="ds-d" aria-hidden="true">${wd.slice(0, 2)} ${dt.getDate()}</span><b aria-hidden="true">${B[b]}</b></li>`;
  })}</ol>`;
}
