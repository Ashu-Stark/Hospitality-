// Home: photo hero with tabbed search, quick actions, popular destinations, Char Dham banner, things to do with local
// hosts, a "list your property" band; plus the Search results page and the shared typeahead.
import { html, mount, raw, href, load, debounce, $, $$, announce, empty, icon, BANDS, monthChips, MONTH_NAMES } from '../ui.js';
import { api, meta } from '../api.js';
import { t } from '../i18n.js';
import { setQuery, go } from '../router.js';
import { resultLink, resultTitle, resultSub, TYPE_LABEL } from './common.js';
import { photo, img } from '../photos.js';
import { rupees, LX_SHORT, lxPhotoIds } from '../cards.js';

const ORDER = ['destinations', 'businesses', 'events', 'dictionary', 'rules', 'advisories'];

// The destination list request starts as soon as the app loads on the home page (prefetchHome in app.js); the last
// answer is kept in sessionStorage so a return visit draws the popular cards at once, then refreshes.
const DST_KEY = 'uthp.home.dst2';
let dstP = null;
export function prefetchHome() {
  if (!dstP) dstP = api('/destinations').catch(() => null);
}
function readDst() {
  try { const v = JSON.parse(sessionStorage.getItem(DST_KEY) || 'null'); return Array.isArray(v) && v.length ? v : null; } catch { return null; }
}
function saveDst(items) {
  try { sessionStorage.setItem(DST_KEY, JSON.stringify(items)); } catch { /* storage blocked or full: no cache */ }
}

// ------------------------------------------------------------------ hero search (one form, five kinds of search)
const TABS = [
  ['places', 'pin', 'places'],
  ['stays', 'homestay', 'stays'],
  ['experiences', 'village_walk', 'experiences'],
  ['trips', 'route', 'trips'],
  ['jobs', 'briefcase', 'jobs'],
];
// "Who?" maps to a real filter on the destinations page (never a decorative field).
const WHO = [['', 'Anyone'], ['family', 'Family or older parents'], ['treks', 'Trekkers'], ['chardham', 'Pilgrims'], ['quiet', 'Want it quiet']];
const MONTH_OPTS = (sel = '') => html`<option value="">Any month</option>${MONTH_NAMES.map((n, i) => html`<option value="${i + 1}" ${String(i + 1) === String(sel) ? raw('selected') : ''}>${n}</option>`)}`;

function field(id, ic, label, control, cls = '') {
  return html`<div class="hv-f ${cls}"><span class="hv-f-ic" aria-hidden="true">${icon(ic)}</span><span class="hv-f-in"><label for="${id}">${label}</label>${control}</span></div>`;
}
function fieldsFor(tab, m, keep) {
  const where = (ph = 'Anywhere in Uttarakhand') => field('hv-where', 'pin', tab === 'jobs' ? 'Where?' : 'Where to?',
    html`<input id="hv-where" name="where" type="text" list="hv-places" autocomplete="off" maxlength="80" placeholder="${ph}" value="${keep.where || ''}">`, 'grow');
  const when = () => field('hv-when', 'calendar', 'When?', html`<select id="hv-when" name="when">${MONTH_OPTS(keep.when)}</select>`);
  if (tab === 'places') return html`${where()}${when()}${field('hv-who', 'people', 'Who?', html`<select id="hv-who" name="who">${WHO.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select>`)}`;
  if (tab === 'stays') return html`${where()}${field('hv-kind', 'homestay', 'Type of stay', html`<select id="hv-kind" name="kind"><option value="">Homestays and hotels</option><option value="homestay">Homestays</option><option value="hotel">Hotels</option></select>`)}`;
  if (tab === 'experiences') return html`${where()}${when()}${field('hv-kind', 'village_walk', 'What?', html`<select id="hv-kind" name="kind"><option value="">Anything</option>${(m?.local_experience_types || []).map((x) => html`<option value="${x.key}">${x.label}</option>`)}</select>`)}`;
  if (tab === 'trips') return field('hv-kind', 'route', 'What kind of trip?', html`<select id="hv-kind" name="kind"><option value="">Any kind of trip</option>${(m?.experiences || []).map((x) => html`<option value="${x.id}">${x.name}</option>`)}</select>`, 'grow');
  return html`${where('Any district')}${field('hv-work', 'briefcase', 'What work?', html`<input id="hv-work" name="work" type="text" maxlength="80" autocomplete="off" placeholder="e.g. cook, front desk">`, 'grow')}`;
}
/** Free text -> a destination (exact name, then starts-with, then contains), else null. */
function findPlace(m, text) {
  const q = text.trim().toLowerCase();
  if (!q || !m) return null;
  const ds = m.destinations || [];
  return ds.find((d) => d.name.toLowerCase() === q) || ds.find((d) => d.name.toLowerCase().startsWith(q)) || ds.find((d) => d.name.toLowerCase().includes(q)) || null;
}
function submitSearch(tab, fd, m) {
  const where = (fd.get('where') || '').toString().trim();
  const when = (fd.get('when') || '').toString();
  const kind = (fd.get('kind') || '').toString();
  const place = findPlace(m, where);
  const unknown = where && !place ? where : '';
  if (tab === 'places') {
    if (place && !when && !fd.get('who')) return go('/destinations/' + place.id);
    if (unknown) return go('/search', { q: unknown });
    return go('/destinations', { q: place?.name, month: when, chip: fd.get('who') || '' });
  }
  if (tab === 'stays') return unknown ? go('/search', { q: unknown }) : go('/stays', { destination: place?.id, type: kind });
  if (tab === 'experiences') return go('/experiences', { destination: place?.id, month: when, type: kind, q: unknown });
  if (tab === 'trips') return go('/plan', { theme: kind });
  const work = (fd.get('work') || '').toString().trim();
  return go('/jobs', { district: place?.district, q: [work, unknown].filter(Boolean).join(' ') });
}

function heroSearch(el) {
  let tab = 'places';
  let m = null;
  const form = $('#hv-form', el);
  const tabs = $('#hv-tabs', el);
  const draw = () => {
    const fd = form.querySelector('#hv-where') ? new FormData(form) : null;
    const keep = { where: fd?.get('where') || '', when: fd?.get('when') || '' };
    mount($('#hv-fields', el), fieldsFor(tab, m, keep));
    $$('button', tabs).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tab === tab)));
  };
  tabs.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tab]');
    if (!b || b.dataset.tab === tab) return;
    tab = b.dataset.tab;
    draw();
    announce(`Search ${b.textContent.trim()}`);
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); submitSearch(tab, new FormData(form), m); });
  draw();
  meta().then((x) => {
    m = x;
    mount($('#hv-places', el), html`${(x.destinations || []).map((d) => html`<option value="${d.name}"></option>`)}`);
    if (tab === 'experiences' || tab === 'trips') draw();
  }).catch(() => { /* the form still works with free text (goes to search) */ });
}

// ------------------------------------------------------------------ sections
const QUICK = [
  ['weather', 'Weather', '#/destinations'],
  ['alert', 'Road alerts', '#/helplines', 'qa-roads'],
  ['people', 'How busy', '#/destinations?chip=quiet'],
  ['temple', 'Char Dham', '#/destinations?chip=chardham'],
  ['route', 'Trip plans', '#/plan'],
  ['homestay', 'Find a stay', '#/stays'],
  ['briefcase', 'Jobs', '#/jobs'],
  ['help', 'Help & complaints', '#/helplines'],
];
const POPULAR = ['kedarnath', 'rishikesh', 'nainital', 'mussoorie', 'auli'];

function popCard(x) {
  const p = photo(x.id);
  const band = x.crowd_today?.band;
  const best = x.best_months?.length ? 'best ' + monthChips(x.best_months, 1)[0] : 'good all year';
  return html`<li><a class="hv-dest" href="${href('/destinations/' + x.id)}">
    <span class="hv-dest-ph">${p ? img(p, { size: 'lg', alt: '' }) : ''}
      <span class="hv-dest-txt"><b class="hv-serif">${x.name}</b><small>${x.district_name}</small></span></span>
    <span class="hv-dest-fact"><span>${band ? html`<span class="hv-dot b-${band}" aria-hidden="true"></span>${BANDS[band].label}<span class="sr-only"> today</span>` : 'Open for details'} · ${best}</span>${icon('arrow')}</span></a></li>`;
}
const popSkeleton = () => html`${POPULAR.map(() => html`<li aria-hidden="true"><span class="hv-dest sk-dest"><span class="hv-dest-ph sk"></span><span class="hv-dest-fact"></span></span></li>`)}`;
async function popular(box) {
  const draw = (items) => mount(box, html`${items.map(popCard)}`);
  const pick = (d) => POPULAR.map((id) => d.items.find((x) => x.id === id)).filter(Boolean);
  const kept = readDst();
  if (kept) draw(kept);
  try {
    const pending = dstP;
    dstP = null;
    const d = (await pending) || (await api('/destinations'));
    const items = pick(d);
    saveDst(items);
    if (!kept || JSON.stringify(items) !== JSON.stringify(kept)) draw(items);
  } catch {
    if (!kept) mount(box, html`<li class="hv-pop-err"><p class="muted">Places could not load. <a href="#/destinations">Open all destinations</a>.</p></li>`);
  }
}

const LX_TINT = ['t-sky', 't-sand', 't-lilac', 't-mint'];
function lxCard(e, i, used) {
  const ids = lxPhotoIds(e, used);
  const p = ids.map((id) => photo(id)).find(Boolean);
  const place = e.destination_name || e.district_name;
  return html`<li><a class="hv-lx ${LX_TINT[i % 4]}" href="${href('/experiences/local/' + e.id)}">
    <span class="hv-lx-txt"><span class="hv-lx-kind">${icon(e.type)}${place}</span>
      <b>${LX_SHORT[e.type] || e.type_label}</b>
      <span class="hv-lx-sub">${e.title}</span>
      <span class="hv-lx-price">${rupees(e.price_min, e.price_max)}<small> per person</small></span>
      <span class="hv-lx-go">Ask to join ${icon('arrow')}</span></span>
    <span class="hv-lx-ph">${p ? img(p, { alt: '' }) : ''}</span></a></li>`;
}

export async function home(ctx) {
  const el = ctx.el;
  el.classList.remove('page', 'wrap');
  el.classList.add('homepage', 'hv');
  const hp = photo('hero');
  const banner = photo('itin-char-dham-yatra');
  const band = photo('lx-farm_stay');
  mount(el, html`
  <section class="hv-hero" aria-labelledby="hero-h">
    ${hp ? html`<img class="hv-hero-img" src="img/photos/${hp.file}" alt="" width="${hp.width}" height="${hp.height}" fetchpriority="high" decoding="async">` : ''}
    <div class="hv-hero-in">
      <h1 id="hero-h"><span>${t('hero_l1')}</span> <span>${t('hero_l2')}</span></h1>
      <p class="hv-sub">${t('hero_sub')}</p>
      <div class="hv-tabs" id="hv-tabs" role="group" aria-label="What are you looking for?">
        ${TABS.map(([k, ic, lk]) => html`<button type="button" data-tab="${k}" aria-pressed="${String(k === 'places')}">${icon(ic)}<span>${t(lk)}</span></button>`)}
      </div>
      <form class="hv-search" id="hv-form" role="search" aria-label="Search Uttarakhand">
        <div class="hv-fields" id="hv-fields"></div>
        <datalist id="hv-places"></datalist>
        <button class="hv-go" type="submit">${icon('search')}<span>${t('search')}</span></button>
      </form>
      <ul class="hv-trust" aria-label="What you get">
        <li>${icon('shield')}Verified stays</li><li>${icon('road')}Live road alerts</li><li>${icon('people')}Crowd forecast</li><li>${icon('lang')}Hindi &amp; English</li>
      </ul>
    </div>
  </section>

  <div class="wrap">
    <nav class="hv-quick" aria-label="Quick links">
      <ul>${QUICK.map(([ic, l, to, id]) => html`<li><a href="${to}" ${id ? html`id="${id}"` : ''}><span class="hv-qa-ic">${icon(ic)}</span><span class="hv-qa-l">${l}</span></a></li>`)}</ul>
    </nav>

    <section class="hv-sec" aria-labelledby="pop-h">
      <div class="hv-head"><div><p class="hv-eyebrow">${t('where_go')}</p><h2 id="pop-h">${t('popular')}</h2></div><a class="hv-pill" href="#/destinations">${t('view_all')}</a></div>
      <ul class="hv-pop" id="hv-pop">${popSkeleton()}</ul>
    </section>
  </div>

  <section class="hv-banner" aria-labelledby="bn-h">
    ${banner ? img(banner, { size: 'lg', cls: 'hv-banner-img', alt: '' }) : ''}
    <div class="hv-banner-in">
      <p class="hv-eyebrow light">Pilgrim season</p>
      <h2 id="bn-h">Char Dham 2026: plan around the crowds</h2>
      <p>See the quieter weeks, slow roads and ready-made routes before you book. Shrine dates change each year, so check them first.</p>
      <a class="hv-btn-white" href="#/plan/itineraries/char-dham-yatra">See the trip plan ${icon('arrow')}</a>
    </div>
  </section>

  <div class="wrap">
    <section class="hv-sec" aria-labelledby="lx-h">
      <div class="hv-head"><div><p class="hv-eyebrow">Local experiences</p><h2 id="lx-h">${t('things_local')}</h2></div><a class="hv-pill" href="#/experiences">${t('view_all')}</a></div>
      <ul class="hv-lxrow" id="hv-lx">${[0, 1, 2, 3].map(() => html`<li aria-hidden="true"><span class="hv-lx sk"></span></li>`)}</ul>
    </section>
  </div>

  <section class="hv-band" aria-labelledby="band-h">
    <div class="hv-band-in">
      <p class="hv-eyebrow light">For homestay and hotel owners</p>
      <h2 id="band-h"><span>List your property,</span> <span>free</span></h2>
      <p>Get a registration guests can check, show your rooms to travellers and host village walks or home meals. No fee in this demo.</p>
      <div class="hv-band-btns"><a class="hv-btn-white" href="#/host">List your property ${icon('arrow')}</a><a class="hv-btn-line" href="#/jobs/hire">Hire staff</a></div>
    </div>
    <div class="hv-phones" aria-hidden="true">
      <div class="hv-phone p1"><div class="hv-scr">
        <div class="hv-scr-top">Your listing</div>
        <div class="hv-scr-ph">${band ? img(band, { alt: '' }) : ''}</div>
        <div class="hv-scr-b"><b>Sample Homestay</b><span>Munsiyari · 4 rooms</span><span class="hv-scr-pill">Verified</span>
          <span class="hv-scr-row"><i></i><i></i></span><span class="hv-scr-row s"><i></i></span></div></div></div>
      <div class="hv-phone p2"><div class="hv-scr">
        <div class="hv-scr-top">Requests</div>
        <div class="hv-scr-b"><span class="hv-scr-card"><b>Village walk</b><span>2 people · Sat</span></span>
          <span class="hv-scr-card"><b>Home meal</b><span>4 people · Sun</span></span><span class="hv-scr-card dim"><b>Stay, 2 nights</b><span>Ask about rooms</span></span></div></div></div>
      <p class="hv-phones-cap">Example screens</p>
    </div>
  </section>`);

  heroSearch(el);
  const m = new Date().getMonth() + 1;
  await Promise.all([
    popular($('#hv-pop', el)),
    (async () => {
      const box = $('#hv-lx', el);
      try {
        const r = await api('/local-experiences', { query: { month: m, page_size: 40 } });
        const seenT = new Set();
        const seenD = new Set();
        const pick = r.items.filter((e) => !seenT.has(e.type) && !seenD.has(e.destination_id) && seenT.add(e.type) && seenD.add(e.destination_id)).slice(0, 4);
        const used = new Set();
        mount(box, pick.length ? html`${pick.map((e, i) => lxCard(e, i, used))}` : html`<li class="hv-wide">${empty('No local experiences this month')}</li>`);
      } catch {
        mount(box, html`<li class="hv-wide"><p class="muted">Experiences could not load. <a href="#/experiences">Open things to do</a>.</p></li>`);
      }
    })(),
    (async () => {
      try {
        const a = await api('/advisories');
        const n = a.items.filter((x) => x.kind === 'road' && x.status !== 'open').length;
        const tile = $('#qa-roads', el);
        if (n && tile) tile.insertAdjacentHTML('beforeend', `<span class="hv-qa-n">${n}<span class="sr-only"> alerts</span></span>`);
      } catch { /* the tile still links to help and road alerts */ }
    })(),
  ]);
}

/** Grouped typeahead on a search input (combobox + listbox, keyboard operable, debounced). */
export function wireTypeahead(form, input, box) {
  let active = -1;
  let opts = [];
  let reqId = 0;
  const close = () => { box.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; };
  const setActive = (i) => {
    opts.forEach((o) => o.classList.remove('act'));
    active = i;
    if (i >= 0 && opts[i]) { opts[i].classList.add('act'); input.setAttribute('aria-activedescendant', opts[i].id); opts[i].scrollIntoView({ block: 'nearest' }); }
    else input.removeAttribute('aria-activedescendant');
  };
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    const id = ++reqId;
    try {
      const r = await api('/search', { query: { q, limit: 4 } });
      if (id !== reqId) return;
      let n = 0;
      const groups = ORDER.filter((k) => r.groups[k]?.length);
      mount(box, groups.length ? html`${groups.map((k) => html`<div role="group" aria-label="${TYPE_LABEL[k]}"><div class="ta-h" aria-hidden="true"><span>${TYPE_LABEL[k]}</span><span>${r.counts[k]}</span></div>
        ${r.groups[k].map((it) => html`<a role="option" id="ta-${n++}" href="${resultLink(k, it)}"><span>${resultTitle(k, it)}</span><small>${resultSub(k, it)}</small></a>`)}</div>`)}
        <a role="option" id="ta-${n++}" class="ta-all" href="${href('/search', { q })}">${t('all_results')} (${r.total})</a>`
        : html`<div class="ta-h">No matches for “${q}”</div><a role="option" id="ta-0" class="ta-all" href="${href('/search', { q })}">Open the search page</a>`);
      opts = $$('[role="option"]', box);
      box.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      setActive(-1);
      announce(`${r.total} results. Use the down arrow to browse.`);
    } catch (e) {
      if (id !== reqId) return;
      mount(box, html`<div class="ta-h">${e.status === 429 ? 'Too many searches, please wait a moment.' : 'Search is unavailable right now.'}</div>`);
      opts = [];
      box.hidden = false;
    }
  }, 320);
  input.addEventListener('input', run);
  input.addEventListener('keydown', (e) => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(Math.min(opts.length - 1, active + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(-1, active - 1)); }
    else if (e.key === 'Escape') { close(); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); location.hash = opts[active].getAttribute('href').slice(1); close(); }
  });
  box.addEventListener('click', (e) => { if (e.target.closest('a')) close(); });
  document.addEventListener('click', (e) => { if (!form.parentElement.contains(e.target)) close(); });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (q.length < 2) { input.setAttribute('aria-invalid', 'true'); announce('Type at least 2 characters.'); return; }
    close();
    go('/search', { q });
  });
}

export async function search(ctx) {
  const el = ctx.el;
  const q = (ctx.query.q || '').trim();
  let type = ctx.query.type || '';
  mount(el, html`<div class="pagehead"><div><p class="eyebrow">Unified search</p><h1>${q ? html`Results for “${q}”` : 'Search the portal'}</h1>
    <p>Places, businesses, festivals, words, rules and road alerts.</p></div></div>
    <form class="card tight searchbox" role="search" id="sform"><label for="sq" class="sr-only">Search</label>
      <input class="field" id="sq" name="q" type="search" value="${q}" placeholder="${t('search_ph')}" minlength="2" maxlength="200" required>
      <button class="btn primary" type="submit">${t('search')}</button></form>
    <div id="sres" class="section" aria-live="polite"></div>`);
  $('#sform', el).addEventListener('submit', (e) => {
    e.preventDefault();
    const v = $('#sq', el).value.trim();
    if (v.length < 2) { $('#sq', el).setAttribute('aria-invalid', 'true'); announce('Type at least 2 characters.'); return; }
    go('/search', { q: v });
  });
  const res = $('#sres', el);
  if (q.length < 2) { mount(res, empty('Type at least 2 characters', 'Try “Kedarnath”, “homestay”, “RevPAR”, “Form C” or a registration number.')); return; }
  await load(res, async () => {
    const r = await api('/search', { query: { q, limit: 25 } });
    const draw = () => {
      const groups = ORDER.filter((k) => r.groups[k]?.length && (!type || type === k));
      mount(res, html`<div class="chips" role="group" aria-label="Filter by type">
          <button type="button" class="chipbtn" data-type="" aria-pressed="${String(!type)}">All (${r.total})</button>
          ${ORDER.map((k) => html`<button type="button" class="chipbtn" data-type="${k}" aria-pressed="${String(type === k)}" ${r.counts[k] ? '' : raw('disabled')}>${TYPE_LABEL[k]} (${r.counts[k] || 0})</button>`)}</div>
        ${groups.length ? groups.map((k) => html`<section class="section" aria-labelledby="g-${k}"><h2 id="g-${k}" class="sechead">${TYPE_LABEL[k]} <span class="muted small">${r.counts[k]} found${r.counts[k] > r.groups[k].length ? `, showing ${r.groups[k].length}` : ''}</span></h2>
          <div class="list">${r.groups[k].map((it) => html`<div class="item"><div class="main"><a class="t" href="${resultLink(k, it)}">${resultTitle(k, it)}</a><div class="sub">${resultSub(k, it)}</div></div>
          ${k === 'businesses' ? html`<div class="side"><span class="pill ${it.status === 'active' ? 'ok' : 'bad'}">${it.status}</span></div>` : ''}</div>`)}</div>
          ${k === 'businesses' && r.counts[k] > r.groups[k].length ? html`<p class="section"><a class="btn ghost" href="${href('/directory', { q })}">See all ${r.counts[k]} in the directory</a></p>` : ''}</section>`)
          : empty(`Nothing found for “${q}”`, 'Check the spelling, try a shorter word, or browse the directory and destinations.', html`<div class="btnrow"><a class="btn ghost" href="#/directory">Directory</a><a class="btn ghost" href="#/destinations">Destinations</a></div>`)}`);
      $$('[data-type]', res).forEach((b) => b.addEventListener('click', () => { type = b.dataset.type; setQuery({ q, type }); draw(); announce(`Showing ${type ? TYPE_LABEL[type] : 'all results'}`); }));
    };
    draw();
  }, { skel: 'list', n: 5, label: 'Searching…' });
}
