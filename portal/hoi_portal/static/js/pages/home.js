// Home (hero + unified search typeahead + quick tiles + crowd strip + advisories + festivals + role entries) and Search results.
import { html, mount, raw, href, load, bandPill, num, debounce, $, $$, announce, empty, errorBox, loading, monthName, impactPill, lastUpdated, infoNote, fmtDate } from '../ui.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { setQuery, go } from '../router.js';
import { ICONS, resultLink, resultTitle, resultSub, TYPE_LABEL, advisoryLine } from './common.js';
import { expTile } from './plan.js';
import { paintTones } from '../art.js';
import { photo, img, credit } from '../photos.js';

const ORDER = ['destinations', 'businesses', 'events', 'dictionary', 'rules', 'advisories'];

export async function home(ctx) {
  const el = ctx.el;
  el.classList.remove('page');
  el.classList.add('homepage');
  const hp = photo('hero');
  mount(el, html`
  <section class="hero ${hp ? 'photo' : ''}" aria-labelledby="hero-h">
    <div class="hero-in">
      <p class="eyebrow">Uttarakhand · concept portal</p>
      <h1 id="hero-h">${t('hero_title')}</h1>
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
  <section class="tasks" aria-label="What do you want to do?">
    <div class="task"><span class="ic">${raw(ICONS.plan)}</span><h2>${t('task_plan')}</h2><p>Weather, roads and how crowded it will be.</p>
      <div class="btnrow"><a class="btn dark sm" href="#/destinations">Destinations</a><a class="btn ghost sm" href="#/festivals">Festivals</a></div></div>
    <div class="task"><span class="ic">${raw(ICONS.verify)}</span><h2>${t('task_check')}</h2><p>Is this stay, guide or taxi registered?</p>
      <form class="minisearch" id="vform" novalidate><label for="vreg" class="sr-only">Registration number</label><input class="field mono" id="vreg" name="reg" placeholder="UK-HMS-RUD-00001" autocapitalize="characters" spellcheck="false" maxlength="40"><button class="btn dark sm" type="submit">Verify</button></form></div>
    <div class="task"><span class="ic">${raw(ICONS.complaint)}</span><h2>${t('task_help')}</h2><p>Emergency <strong>112</strong> · helplines · complaints.</p>
      <div class="btnrow"><a class="btn dark sm" href="#/grievance">${t('file')}</a><a class="btn ghost sm" href="#/helplines">Helplines</a></div></div>
  </section>
  <section class="section" aria-labelledby="exp-h">
    <div class="sechead"><h2 id="exp-h">Explore by experience</h2><a href="#/experiences">${t('see_all')}</a></div>
    <div id="exps"></div>
  </section>
  <section class="section" aria-labelledby="crowd-h">
    <div class="sechead"><h2 id="crowd-h">${t('crowd_now')} <span class="pill syn">estimate</span>${infoNote('Crowd index 0-100 from reported and synthetic occupancy, festivals, weekends and season. Not a headcount.')}</h2>
      <a href="#/destinations">${t('see_all')}</a></div>
    <div id="crowd"></div>
  </section>
  <div class="grid g2 section">
    <section class="card tight" aria-labelledby="adv-h"><div class="sechead"><h2 id="adv-h">${t('alerts')}</h2><a href="#/helplines">${t('see_all')}</a></div><div id="adv"></div></section>
    <section class="card tight" aria-labelledby="fest-h"><div class="sechead"><h2 id="fest-h">${t('coming_up')}</h2><a href="#/festivals">Calendar</a></div><div id="fest"></div></section>
  </div>
  <p class="partner section"><span>Run a tourism business? <a href="#/signin?need=business">Register or renew</a></span><span>District or state official? <a href="#/signin?need=official">Officials sign in</a></span></p>`);

  wireTypeahead($('#hform', el), $('#hq', el), $('#ta', el));
  $('#vform', el).addEventListener('submit', (e) => { e.preventDefault(); const v = $('#vreg', el).value.trim(); go('/verify', v ? { reg: v.toUpperCase() } : {}); });

  await Promise.all([
    load($('#exps', el), async () => {
      const r = await api('/experiences');
      mount($('#exps', el), html`<div class="exprow">${r.items.map((e) => expTile(e))}</div>`);
      paintTones($('#exps', el));
    }, { skel: 'block' }),
    load($('#crowd', el), async () => {
      const d = await api('/destinations');
      const top = d.items.filter((x) => x.crowd_today).sort((a, b) => b.crowd_today.index - a.crowd_today.index).slice(0, 6);
      mount($('#crowd', el), top.length ? html`<div class="crowdstrip" role="list">${top.map((x) => html`<a role="listitem" class="crowdcard" href="${href('/destinations/' + x.id)}">
        ${photo(x.id) ? img(photo(x.id), { cls: 'cthumb', alt: '' }) : ''}<b>${x.name}</b><span class="muted small">${x.district_name}</span>
        <div class="idxrow"><span class="idx">${x.crowd_today.index}<small> / 100</small></span>${bandPill(x.crowd_today.band, null, '')}</div></a>`)}</div><p class="hint photonote">Photos: Wikimedia Commons contributors, illustrative only. <a href="#/credits">Photo credits</a></p>` : empty('No crowd estimates yet'));
    }, { skel: 'block' }),
    load($('#adv', el), async () => {
      const a = await api('/advisories');
      const order = { closed: 0, caution: 1, open: 2 };
      const items = a.items.slice().sort((x, y) => (order[x.status] ?? 3) - (order[y.status] ?? 3)).slice(0, 3);
      mount($('#adv', el), items.length ? html`<ul class="lines">${items.map(advisoryLine)}</ul>${a.items.some((x) => x.sample) ? html`<p class="hint">Items marked Sample are illustrative, not real road status.</p>` : ''}` : html`<p class="muted">No active alerts. Always check locally before travel.</p>`);
    }, { skel: 'list', n: 3 }),
    load($('#fest', el), async () => {
      const m = new Date().getMonth() + 1;
      const next = (m % 12) + 1;
      const [a, b] = await Promise.all([api('/events', { query: { month: m } }), api('/events', { query: { month: next } })]);
      const seen = new Set();
      const items = [...a.items, ...b.items].filter((e) => !seen.has(e.id) && seen.add(e.id)).slice(0, 3);
      mount($('#fest', el), items.length ? html`<ul class="lines">${items.map((e) => html`<li>${impactPill(e.crowd_impact)}<a href="${href('/festivals', { view: 'list', q: e.name })}">${e.name.replace(/^SAMPLE:\s*/, '').replace(/^./, (c) => c.toUpperCase())}</a><span class="muted small">${e.start_date ? fmtDate(e.start_date, { noYear: true }) : e.window}</span>${e.sample ? html`<span class="pill syn">Sample</span>` : ''}</li>`)}</ul>
        <p class="hint">Usual timing; lunar dates are announced annually.</p>` : html`<p class="muted">Nothing listed for the next two months.</p>`);
    }, { skel: 'list', n: 3 }),
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
    <p>Destinations, businesses, festivals, dictionary terms, rules and advisories in one place.</p></div></div>
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
