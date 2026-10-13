// Home (photo hero + search, five pillars, in-season destinations, local experiences, coming up + alerts) and Search results.
import { html, mount, raw, href, load, debounce, $, $$, announce, empty, icon } from '../ui.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { setQuery, go } from '../router.js';
import { resultLink, resultTitle, resultSub, TYPE_LABEL, advisoryLine } from './common.js';
import { photo, credit, thumbsNote } from '../photos.js';
import { destCard, localCard, festCard } from '../cards.js';

const ORDER = ['destinations', 'businesses', 'events', 'dictionary', 'rules', 'advisories'];

export async function home(ctx) {
  const el = ctx.el;
  el.classList.remove('page');
  el.classList.add('homepage');
  const hp = photo('hero');
  const pill = (to, ic, title, sub, cls = '') => html`<a class="pillar ${cls}" href="${to}"><span class="ic">${icon(ic)}</span><span class="pt"><b>${title}</b><span class="s">${sub}</span></span></a>`;
  mount(el, html`
  <section class="hero ${hp ? 'photo' : ''}" aria-labelledby="hero-h">
    <div class="hero-in">
      <p class="eyebrow">Uttarakhand travel &amp; hospitality</p>
      <h1 id="hero-h">${t('hero_title')}</h1>
      <p class="lead">Where to go, where to stay, and what to do. Plus today's weather, roads and how busy it is.</p>
      <div class="hsearch" id="hsearch">
        <form class="panel" role="search" id="hform" aria-label="Search the portal">
          <label for="hq" class="sr-only">${t('search')}</label>
          <input class="field" id="hq" name="q" type="search" autocomplete="off" placeholder="${t('search_ph')}" role="combobox" aria-expanded="false" aria-controls="ta" aria-autocomplete="list" maxlength="200">
          <button class="btn primary" type="submit">${raw('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>')}${t('search')}</button>
        </form>
        <div class="typeahead" id="ta" role="listbox" aria-label="Search suggestions" hidden></div>
      </div>
    </div>
    ${hp ? credit(hp, 'pcredit herocredit') : ''}
  </section>
  <nav class="pillars" aria-label="Start here">
    ${pill('#/stays', 'homestay', 'Stays', 'Homestays and hotels')}
    ${pill('#/experiences', 'village_walk', 'Things to do', 'With local families and guides')}
    ${pill('#/plan', 'route', 'Trip plans', 'Ready-made routes')}
    ${pill('#/jobs', 'people', 'Jobs', 'Work in hotels and travel')}
    ${pill('#/host', 'staffing_agency', 'List your property', 'Join for free', 'cta')}
  </nav>
  <div id="adv" class="alertline" aria-live="polite"></div>
  <section class="sec2" aria-labelledby="dst-h">
    <div class="sechead"><h2 id="dst-h">Good to go now <span class="pill neutral noicon">quiet places first</span></h2><a href="#/destinations">All 24 places</a></div>
    <div id="dst"></div>
  </section>
  <section class="sec2" aria-labelledby="lx-h">
    <div class="sechead"><h2 id="lx-h">Things to do <span class="pill neutral noicon">with local hosts</span></h2><a href="#/experiences">See all</a></div>
    <div id="lx"></div>
  </section>
  <section class="sec2" aria-labelledby="fest-h">
    <div class="sechead"><h2 id="fest-h">${t('coming_up')} <span class="pill neutral noicon">festivals</span></h2><a href="#/festivals">Calendar</a></div>
    <div id="fest" class="fest2"></div>
  </section>
  ${thumbsNote()}`);

  wireTypeahead($('#hform', el), $('#hq', el), $('#ta', el));
  const m = new Date().getMonth() + 1;
  await Promise.all([
    load($('#dst', el), async () => {
      const d = await api('/destinations');
      const inSeason = d.items.filter((x) => x.crowd_today && (!x.best_months?.length || x.best_months.includes(m)));
      const pick = (inSeason.length >= 4 ? inSeason : d.items).slice().sort((a, b) => (a.crowd_today?.index ?? 99) - (b.crowd_today?.index ?? 99)).slice(0, 4);
      mount($('#dst', el), html`<div class="mcgrid g4c">${pick.map((x, i) => destCard(x, { eager: i < 2 }))}</div>`);
    }, { skel: 'cards', n: 4 }),
    load($('#lx', el), async () => {
      const r = await api('/local-experiences', { query: { month: m, page_size: 40 } });
      const seenT = new Set();
      const seenD = new Set();
      const pick = r.items.filter((e) => !seenT.has(e.type) && !seenD.has(e.destination_id) && seenT.add(e.type) && seenD.add(e.destination_id)).slice(0, 4);
      mount($('#lx', el), pick.length ? html`<div class="mcgrid g4c">${pick.map(localCard)}</div>` : empty('No local experiences this month'));
    }, { skel: 'cards', n: 4 }),
    load($('#adv', el), async () => {
      const a = await api('/advisories');
      const order = { closed: 0, caution: 1, open: 2 };
      const items = a.items.slice().sort((x, y) => (order[x.status] ?? 3) - (order[y.status] ?? 3));
      mount($('#adv', el), items.length ? html`<ul class="lines">${advisoryLine(items[0])}</ul><a href="#/helplines">${items.length} road alert${items.length > 1 ? 's' : ''} · help</a>` : html`<span class="muted">No road alerts right now.</span><a href="#/helplines">Help</a>`);
    }, { skel: 'list', n: 3 }),
    load($('#fest', el), async () => {
      const next = (m % 12) + 1;
      const [a, b] = await Promise.all([api('/events', { query: { month: m } }), api('/events', { query: { month: next } })]);
      const seen = new Set();
      const items = [...a.items, ...b.items].filter((e) => !e.sample && !seen.has(e.id) && seen.add(e.id)).slice(0, 3);
      mount($('#fest', el), items.length ? html`<div class="mcgrid">${items.map((e) => festCard(e, { hz: true }))}</div>` : html`<p class="muted">Nothing listed for the next two months.</p>`);
    }, { skel: 'block' }),
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
