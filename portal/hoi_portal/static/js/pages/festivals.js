// Festivals & events: month calendar grid + list view, filters, crowd impact.
import { html, mount, href, load, $, $$, empty, raw, monthName, MONTH_NAMES, impactPill, fmtDate, crumbs, lastUpdated, announce, samplePill, collapseFilters, pager, infoNote } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';

export async function festivals(ctx) {
  const el = ctx.el;
  const now = new Date();
  const f = { view: 'calendar', month: '', year: String(now.getFullYear()), district: '', destination: '', q: '', ...ctx.query };
  if (f.view === 'calendar' && !f.month) f.month = String(now.getMonth() + 1);
  mount(el, html`<div class="pagehead"><div><h1>Festivals & events</h1>
      <p>Fairs, yatras and seasonal rushes, with their crowd impact. <span class="pill warn">Verify dates</span>${infoNote('Usual timing only. Lunar-calendar dates are announced each year; check the official notice. District events marked Sample are illustrative.')}</p></div>
      <div class="tabs"><div class="pillnav" role="group" aria-label="View"><button type="button" data-view="calendar" aria-pressed="false">Month calendar</button><button type="button" data-view="list" aria-pressed="false">List</button></div></div></div>
    <form class="card tight filters" id="ff" aria-label="Filter events"></form>
    <div id="fres" class="section" aria-live="polite"></div>`);
  const m = await meta();
  const form = $('#ff', el);
  const drawForm = () => mount(form, html`
    <div class="fld"><label class="lbl" for="e-q">Search</label><input class="field" id="e-q" name="q" type="search" value="${f.q}" placeholder="e.g. Nanda Devi"></div>
    <div class="fld"><label class="lbl" for="e-month">Month</label><select class="field" id="e-month" name="month">${f.view === 'list' ? html`<option value="">All months</option>` : ''}
      ${MONTH_NAMES.map((n, i) => html`<option value="${i + 1}" ${String(i + 1) === String(f.month) ? raw('selected') : ''}>${n}</option>`)}</select></div>
    <div class="fld"><label class="lbl" for="e-district">District</label><select class="field" id="e-district" name="district"><option value="">All districts</option>
      ${m.districts.map((x) => html`<option value="${x.id}" ${f.district === x.id ? raw('selected') : ''}>${x.name}</option>`)}</select></div>
    <div class="fld"><label class="lbl" for="e-destination">Destination</label><select class="field" id="e-destination" name="destination"><option value="">All destinations</option>
      ${m.destinations.map((x) => html`<option value="${x.id}" ${f.destination === x.id ? raw('selected') : ''}>${x.name}</option>`)}</select></div>
    <div class="fld"><button type="reset" class="btn ghost">Clear</button></div>`);
  const res = $('#fres', el);
  const setViewBtns = () => $$('[data-view]', el).forEach((b) => { b.setAttribute('aria-pressed', String(b.dataset.view === f.view)); b.classList.toggle('on', b.dataset.view === f.view); });
  const refresh = () => {
    setQuery(f);
    setViewBtns();
    return load(res, async () => {
      const q = { month: f.month || undefined, district: f.district || undefined, destination: f.destination || undefined, q: f.q || undefined };
      const r = await api('/events', { query: q });
      if (f.view === 'calendar') calendar(res, r, f, refresh); else listView(res, r, f);
      announce(`${r.total} events`);
    }, { skel: 'block' });
  };
  drawForm();
  collapseFilters(form);
  form.addEventListener('change', () => { const fd = new FormData(form); ['month', 'district', 'destination', 'q'].forEach((k) => { f[k] = (fd.get(k) || '').toString().trim(); }); refresh(); });
  let tmr;
  form.addEventListener('input', (e) => { if (e.target.name !== 'q') return; clearTimeout(tmr); tmr = setTimeout(() => { f.q = e.target.value.trim(); refresh(); }, 350); });
  form.addEventListener('reset', () => setTimeout(() => { Object.assign(f, { district: '', destination: '', q: '', month: f.view === 'calendar' ? String(now.getMonth() + 1) : '' }); drawForm(); refresh(); }));
  form.addEventListener('submit', (e) => e.preventDefault());
  $$('[data-view]', el).forEach((b) => b.addEventListener('click', () => {
    f.view = b.dataset.view;
    if (f.view === 'calendar' && !f.month) f.month = String(now.getMonth() + 1);
    drawForm();
    refresh();
  }));
  await refresh();
}

function where(e) {
  return (e.destination_names || []).join(', ') || (e.district_names || []).join(', ') || (e.statewide ? 'Statewide' : '—');
}

function calendar(box, r, f, refresh) {
  const month = Number(f.month);
  const year = Number(f.year);
  const first = new Date(year, month - 1, 1);
  const days = new Date(year, month, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Monday first
  const dated = r.items.filter((e) => e.start_date);
  const usual = r.items.filter((e) => !e.start_date);
  const iso = (d) => `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  const today = new Date();
  const isToday = (d) => today.getFullYear() === year && today.getMonth() + 1 === month && today.getDate() === d;
  const on = (d) => dated.filter((e) => e.start_date <= iso(d) && (e.end_date || e.start_date) >= iso(d));
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(html`<div class="day out" aria-hidden="true"></div>`);
  for (let d = 1; d <= days; d++) {
    const evs = on(d);
    cells.push(html`<div class="day ${isToday(d) ? 'today' : ''}"><span class="dn">${d}<span class="sr-only"> ${monthName(month)}${isToday(d) ? ' (today)' : ''}${evs.length ? '' : ', no events'}</span></span>
      ${evs.map((e) => html`<a class="ev ${e.crowd_impact}" href="${href('/festivals', { view: 'list', q: e.name })}" title="${e.name} (${e.crowd_impact} crowd impact)">${e.name}</a>`)}</div>`);
  }
  const prev = month === 1 ? [12, year - 1] : [month - 1, year];
  const next = month === 12 ? [1, year + 1] : [month + 1, year];
  mount(box, html`<div class="card">
    <div class="sechead"><h2 id="calh">${monthName(month)} ${year}</h2><div class="btnrow"><button type="button" class="btn sm ghost" data-m="${prev[0]}" data-y="${prev[1]}" aria-label="Previous month: ${monthName(prev[0])}">‹ ${monthName(prev[0], true)}</button>
      <button type="button" class="btn sm ghost" data-m="${next[0]}" data-y="${next[1]}" aria-label="Next month: ${monthName(next[0])}">${monthName(next[0], true)} ›</button></div></div>
    <h3>Usually in ${monthName(month)} <span class="muted small">(dates announced annually)</span></h3>
    ${usual.length ? html`<div class="list section">${usual.map((e) => html`<div class="item"><div class="main"><strong>${e.name}</strong><div class="sub">${e.window} · ${where(e)}</div></div><div class="side">${impactPill(e.crowd_impact)}</div></div>`)}</div>` : html`<p class="muted section">No usual festivals this month for these filters.</p>`}
    <h3 class="section">Dated events</h3>
    <div class="cal section" aria-labelledby="calh">${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => html`<div class="dow" aria-hidden="true">${d}</div>`)}${cells}</div>
    <div class="heat-legend section" aria-label="Legend"><span><i class="lg-high"></i>High crowd impact</span><span><i class="lg-medium"></i>Medium</span><span><i class="lg-low"></i>Low</span></div>
    ${!dated.length ? html`<p class="muted section">No dated events posted for ${monthName(month)} ${year}.</p>` : ''}
  </div>`);
  $$('[data-m]', box).forEach((b) => b.addEventListener('click', () => { f.month = b.dataset.m; f.year = b.dataset.y; const s = document.getElementById('e-month'); if (s) s.value = f.month; refresh(); }));
}

function listView(box, r, f) {
  const items = [...r.items].sort((a, b) => (a.start_date || '').localeCompare(b.start_date || '') || (a.months?.[0] || 0) - (b.months?.[0] || 0));
  if (!items.length) { mount(box, empty('No events match', 'Try another month or clear the filters.')); return; }
  pager(box, items, (slice) => html`<div class="list">${slice.map((e) => html`<article class="item"><div class="main">
      <h2 class="t">${e.name}</h2>
      <div class="sub">${e.start_date ? `${fmtDate(e.start_date)}${e.end_date && e.end_date !== e.start_date ? ' to ' + fmtDate(e.end_date) : ''}` : e.window} · ${where(e)}</div>
      ${e.description ? html`<p class="small">${e.description}</p>` : ''}
      <div class="monthwin" aria-label="Usual months: ${(e.months || []).map((m) => monthName(m)).join(', ')}">${MONTH_NAMES.map((n, i) => html`<span class="${(e.months || []).includes(i + 1) ? 'on' : ''}" aria-hidden="true">${n.slice(0, 1)}</span>`)}</div>
      </div>
      <div class="side">${impactPill(e.crowd_impact)}${e.sample ? samplePill() : ''}${e.kind === 'event' ? html`<span class="pill neutral noicon">District event</span>` : ''}</div></article>`)}</div>`, 10);
}
