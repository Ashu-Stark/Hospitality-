// Officials' analytics dashboard: overview KPIs, rush heatmap, occupancy trend, market growth (SYNTHETIC),
// grievances, workforce (k-anonymous). District officers see their district only; the state admin gets a district filter.
import { html, mount, href, load, $, $$, raw, fmtDate, fmtMonth, monthName, num, pct, empty, table, bandPill, announce, fmtDateTime, titleCase, infoNote, pager, statTile, details } from '../ui.js';
import { api, meta, user, role } from '../api.js';
import { setQuery } from '../router.js';
import { lineChart, barChart, hbarChart, heatmap, PALETTE, BAND_FILL, bandOf, bandCell } from '../charts.js';
import { roleSubnav } from './common.js';

const TABS = [['overview', 'Overview'], ['rush', 'How busy'], ['occupancy', 'How full'], ['market', 'Visitors'], ['grievances', 'Complaints'], ['workforce', 'Hotel staff'], ['jobs', 'Jobs and workers']];
const synBanner = (note) => html`<div class="synbanner" role="note"><b>Demo numbers</b><span>Not official figures.</span></div>`;
const shortDate = (v) => { const d = new Date(v + 'T00:00'); return `${d.getDate()} ${monthName(d.getMonth() + 1, true)}`; };

export async function analytics(ctx) {
  const el = ctx.el;
  const isAdmin = role() === 'state_admin';
  const f = { tab: TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'overview', district: isAdmin ? ctx.query.district || '' : '' };
  const m = await meta();
  mount(el, html`${roleSubnav('/officer')}
    <div class="pagehead"><div><p class="eyebrow">Officials · analytics</p><h1>Analytics dashboard</h1>
      <p>${isAdmin ? 'State view. Choose a district to focus.' : html`Scope: <strong>${user()?.district_name}</strong> district only.`} All numbers here are demo numbers.</p></div>
      ${isAdmin ? html`<form class="fld" id="scope"><label class="lbl" for="sc-d">District</label><select class="field" id="sc-d" name="district"><option value="">All districts (state)</option>${m.districts.map((d) => html`<option value="${d.id}" ${f.district === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></form>` : ''}</div>
    <div class="tabs"><div class="pillnav" role="tablist" aria-label="Analytics sections">${TABS.map(([k, l]) => html`<button type="button" role="tab" id="t-${k}" aria-controls="tabpanel" data-tab="${k}">${l}</button>`)}</div></div>
    <div id="tabpanel" role="tabpanel" tabindex="-1"></div>`);
  const panel = $('#tabpanel', el);
  const tabs = $$('[role="tab"]', el);
  const show = (focusTab) => {
    tabs.forEach((b) => { const on = b.dataset.tab === f.tab; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
    panel.setAttribute('aria-labelledby', 't-' + f.tab);
    setQuery({ tab: f.tab === 'overview' ? '' : f.tab, district: f.district });
    if (focusTab) $('#t-' + f.tab, el).focus();
    const d = f.district || undefined;
    const fn = { overview, rush, occupancy, market, grievances, workforce, jobs: jobsMarket }[f.tab];
    return load(panel, () => fn(panel, d, m, isAdmin), { skel: 'block', label: 'Loading analytics…' });
  };
  tabs.forEach((b, i) => {
    b.addEventListener('click', () => { f.tab = b.dataset.tab; show(false); });
    b.addEventListener('keydown', (e) => {
      const dir = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); f.tab = tabs[e.key === 'Home' ? 0 : tabs.length - 1].dataset.tab; show(true); return; }
      if (!dir) return;
      e.preventDefault();
      f.tab = tabs[(i + dir + tabs.length) % tabs.length].dataset.tab;
      show(true);
    });
  });
  $('#sc-d', el)?.addEventListener('change', (e) => { f.district = e.target.value; show(false); announce('Scope: ' + (e.target.selectedOptions[0]?.textContent || 'state')); });
  await show(false);
}

function scopeLine(r) {
  return html`<p class="small muted">Scope: <strong>${r.scope?.district_name || 'State'}</strong> · generated ${fmtDateTime(r.generated_at)}</p>`;
}
const append = (box, sel, node) => { box.querySelector(sel).appendChild(node); };

// Every tab: a short row of big-number tiles, then ONE chart whose title is a plain-language takeaway; everything
// secondary (more charts, heatmaps, tables, options) sits behind "Show details". Charts keep their table toggle.
const tiles = (arr) => html`<div class="kpis k4 section">${arr}</div>`;
const pctTrend = (a, b) => {
  if (a == null || b == null) return null;
  const d = Math.round((a - b) * 10) / 10;
  return { dir: d > 0.5 ? 'up' : d < -0.5 ? 'down' : 'flat', text: `${d > 0 ? '+' : ''}${num(d, 1)} pts vs previous month` };
};

async function overview(box, district) {
  const [k, occ] = await Promise.all([
    api('/analytics/kpis', { query: { district } }),
    api('/analytics/occupancy', { query: { district, granularity: 'monthly', days: 365 } }).catch(() => null),
  ]);
  const by = Object.fromEntries(k.kpis.map((x) => [x.key, x]));
  const ov = (occ?.overall?.values || []).filter((v) => v != null);
  const v = (key) => by[key]?.value ?? 0;
  mount(box, html`${synBanner(k.note)}${scopeLine(k)}
    ${tiles(html`${statTile({ label: 'Active registrations', value: num(v('registered_businesses')), note: `${num(v('active_rooms'))} rooms, ${num(v('active_beds'))} beds` })}
      ${statTile({ label: 'Rooms full, last 30 days', value: num(v('avg_occupancy_30d'), 1), unit: '%', trend: pctTrend(ov[ov.length - 1], ov[ov.length - 2]) })}
      ${statTile({ label: 'Applications waiting', value: v('applications_pending'), tone: v('applications_pending') ? 'warn' : 'ok', note: html`<a href="#/officer/applications">Open queue</a>` })}
      ${statTile({ label: 'Complaints that are late', value: v('grievances_overdue'), tone: v('grievances_overdue') ? 'bad' : 'ok', note: html`${v('grievances_open')} open · <a href="#/officer/grievances">Open queue</a>` })}`)}
    <div class="grid g2 section"><div id="bs"></div>
      <section class="card" aria-labelledby="ca-h"><h2 id="ca-h" class="h3">${k.crowd_alerts?.length ? `${k.crowd_alerts.length} place${k.crowd_alerts.length > 1 ? 's' : ''} will be very crowded in the next 14 days` : 'No place is expected to be very crowded in the next 14 days'}</h2>
        ${k.crowd_alerts?.length ? html`<ul class="lines section">${k.crowd_alerts.slice(0, 5).map((a) => html`<li>${bandPill(bandOf(a.peak_index), a.peak_index, '')}<a href="${href('/destinations/' + a.destination_id + '/crowd')}">${a.name}</a><span class="muted small">peak ${fmtDate(a.peak_date, { weekday: true, noYear: true })}</span></li>`)}</ul>` : ''}
        </section></div>`);
  const st = k.businesses_by_status || {};
  const tot = Object.values(st).reduce((a, b) => a + b, 0);
  append(box, '#bs', hbarChart({ title: `${num(st.active || 0)} of ${num(tot)} registrations are active`, items: Object.entries(st).map(([s, x]) => ({ label: titleCase(s), value: x, color: { active: '#2e8540', expired: '#b42318', suspended: '#6b6a65', pending: '#c98a00' }[s] })), valueFmt: (x) => num(x), labelHead: 'Status', valueHead: 'Businesses' }));
}

async function rush(box, district) {
  const r = await api('/analytics/rush', { query: { district, top: 10 } });
  const hm = r.heatmap;
  const vh = r.top.filter((x) => x.avg_index_14d >= 85).length;
  const busiest = r.top[0];
  mount(box, html`${synBanner(r.note)}${scopeLine(r)}
    ${tiles(html`${statTile({ label: 'Busiest place, next 2 weeks', value: busiest ? busiest.name : '—', note: '' })}
      ${statTile({ label: 'Very busy places', value: vh, tone: vh ? 'bad' : 'ok' })}
      ${statTile({ label: 'Very busy days ahead', value: r.alerts?.length || 0, tone: r.alerts?.length ? 'warn' : 'ok' })}`)}
    <div id="top" class="section"></div>
    ${details('Week by week, every place', html`<div id="hm"></div>`)}
    ${r.alerts?.length ? details(`All ${r.alerts.length} very busy days`, html`<div id="alt"></div>`) : ''}`);
  append(box, '#top', hbarChart({
    title: busiest ? `${busiest.name} will be the busiest place in the next two weeks` : 'No destinations in scope', sub: 'Longer bar = busier (0 quiet, 100 very busy)', labelHead: 'Place', valueHead: 'How busy (0-100)',
    items: r.top.map((x) => ({ label: x.name, value: x.avg_index_14d, color: BAND_FILL[x.band] || BAND_FILL[bandOf(x.avg_index_14d)], extra: `Peak ${x.peak_index} on ${fmtDate(x.peak_date, { noYear: true })} · ${x.band.replace('_', ' ')}` })),
    max: 100, valueFmt: (x) => String(x),
  }));
  append(box, '#hm', heatmap({
    title: 'How busy each week', sub: 'Green quiet, yellow normal, orange busy, red very busy.',
    rows: hm.rows.map((x) => ({ label: x.name, values: x.values })), cols: hm.weeks, colKind: hm.week_kind, rowHead: 'Destination',
    colFmt: (c, j, long) => (long ? 'Week of ' + fmtDate(c) : shortDate(c)), cell: bandCell,
    note: 'Weeks start on Monday.',
  }));
  if (r.alerts?.length) pager(box.querySelector('#alt'), r.alerts, (slice) => table([{ key: 'name', label: 'Destination', render: (a) => html`<a href="${href('/destinations/' + a.destination_id + '/crowd')}">${a.name}</a>` }, { key: 'date', label: 'Date', render: (a) => fmtDate(a.date, { weekday: true }) }, { key: 'index', label: 'How busy (0-100)', num: true }, { key: 'events', label: 'Events', render: (a) => (a.events || []).join(', ') || '—' }], slice, 'Very busy days'), 8);
}

async function occupancy(box, district, m, isAdmin) {
  const f = { granularity: 'monthly', days: '365', type: '', mode: 'overall', picks: [] };
  mount(box, html`<div id="occ-syn">${synBanner()}<p class="small muted">Scope: loading…</p></div><div id="occ-k"></div><div id="occ" class="section"></div>
    ${details('Change the view', html`<form class="filters" id="of" aria-label="Occupancy options">
      <div class="fld"><label class="lbl" for="o-g">Granularity</label><select class="field" id="o-g" name="granularity"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly" selected>Monthly</option></select></div>
      <div class="fld"><label class="lbl" for="o-d">Period</label><select class="field" id="o-d" name="days"><option value="90">Last 90 days</option><option value="365" selected>Last 12 months</option><option value="730">Last 24 months</option></select></div>
      <div class="fld"><label class="lbl" for="o-t">Business type</label><select class="field" id="o-t" name="type"><option value="">Hotels and homestays</option><option value="hotel">Hotels</option><option value="homestay">Homestays</option></select></div>
      <div class="fld"><label class="lbl" for="o-m">Compare</label><select class="field" id="o-m" name="mode"><option value="overall">${district || !isAdmin ? 'Overall' : 'State overall'}</option><option value="type">By business type</option>${isAdmin && !district ? html`<option value="district">By district (pick up to 4)</option>` : ''}</select></div>
    </form><div id="picks"></div>`)}`);
  const form = $('#of', box);
  const draw = () => load($('#occ', box), async () => {
    const r = await api('/analytics/occupancy', { query: { district, granularity: f.granularity, days: f.days, type: f.type || undefined } });
    mount($('#occ-syn', box), html`${synBanner(r.note)}${scopeLine(r)}`);
    let series = [{ label: r.overall.label + ' occupancy', values: r.overall.values }];
    if (f.mode === 'type') series = r.by_type.map((s) => ({ label: s.label, values: s.values }));
    if (f.mode === 'district') {
      const all = r.by_district;
      if (!f.picks.length) f.picks = all.slice().sort((a, b) => avg(b.values) - avg(a.values)).slice(0, 3).map((s) => s.key);
      mount($('#picks', box), html`<fieldset class="section"><legend class="lbl">Districts to compare (max 4)</legend><div class="chips">${all.map((s) => html`<label class="check"><input type="checkbox" value="${s.key}" ${f.picks.includes(s.key) ? raw('checked') : ''}>${s.label}</label>`)}</div></fieldset>`);
      $$('#picks input', box).forEach((c) => c.addEventListener('change', () => {
        const on = $$('#picks input:checked', box).map((x) => x.value);
        if (on.length > 4) { c.checked = false; announce('Choose at most 4 districts'); return; }
        f.picks = on;
        draw();
      }));
      series = all.filter((s) => f.picks.includes(s.key)).map((s) => ({ label: s.label, values: s.values, color: PALETTE[all.findIndex((x) => x.key === s.key) % PALETTE.length] }));
    } else mount($('#picks', box), '');
    if (!series.length) { mount($('#occ', box), empty('Choose at least one district')); return; }
    const ov = r.overall.values.filter((v) => v != null);
    const peakI = r.overall.values.indexOf(Math.max(...ov));
    const avgAll = avg(r.overall.values);
    const when = (i) => (f.granularity === 'monthly' ? fmtMonth(r.dates[i].slice(0, 7)) : fmtDate(r.dates[i]));
    mount($('#occ-k', box), tiles(html`${statTile({ label: 'Rooms full on average', value: num(avgAll, 0), unit: '%', note: `${r.scope?.district_name || 'State'}, ${f.days === '365' ? 'last 12 months' : `last ${f.days} days`}` })}
      ${statTile({ label: 'Peak', value: ov.length ? num(Math.max(...ov), 0) : '—', unit: '%', note: ov.length ? when(peakI) : '' })}
      ${statTile({ label: 'Latest', value: ov.length ? num(ov[ov.length - 1], 0) : '—', unit: '%', trend: f.granularity === 'monthly' ? pctTrend(ov[ov.length - 1], ov[ov.length - 2]) : null })}`));
    $('#occ', box).replaceChildren(lineChart({
      title: ov.length ? `Rooms were ${num(avgAll, 0)}% full on average, most full ${f.granularity === 'monthly' ? 'in ' : 'around '}${when(peakI)}` : 'No occupancy data', sub: `${f.type ? titleCase(f.type) + 's' : 'Hotels and homestays'} · % of rooms full`,
      x: r.dates, series, unit: '%', yMin: 0, yMax: 100, height: 240, xFmt: (v, i, long) => (long ? (f.granularity === 'monthly' ? fmtMonth(v.slice(0, 7)) : (f.granularity === 'weekly' ? 'Week of ' : '') + fmtDate(v)) : f.granularity === 'monthly' ? fmtMonth(v.slice(0, 7)) : shortDate(v)),
      note: 'A gap means no figures were sent.',
    }));
  }, { skel: 'block' });
  form.addEventListener('change', () => { const fd = new FormData(form); f.granularity = fd.get('granularity'); f.days = fd.get('days'); f.type = fd.get('type'); f.mode = fd.get('mode'); draw(); });
  await draw();
}
const avg = (v) => { const x = v.filter((n) => n != null); return x.reduce((a, b) => a + b, 0) / (x.length || 1); };

async function market(box, district) {
  const [mk, rg] = await Promise.all([api('/analytics/market', { query: { district } }), api('/analytics/registrations', { query: { district, months: 24 } })]);
  const tot = mk.totals;
  const yrLbl = (y, i) => String(y) + (tot[i]?.partial_year ? '*' : '');
  const full = tot.filter((x) => !x.partial_year);
  const lastFull = full[full.length - 1];
  const g = tot.filter((x) => x.yoy_pct != null);
  const best = g.reduce((a, c) => (c.yoy_pct > a.yoy_pct ? c : a), g[0] || {});
  const newRegs = (() => { const s = rg.series.find((x) => x.key === 'new_registrations'); return s ? s.values.slice(-12).reduce((a, b) => a + (b || 0), 0) : 0; })();
  mount(box, html`${synBanner(mk.note)}${scopeLine(mk)}
    ${tiles(html`${statTile({ label: `Visitors in ${lastFull?.year ?? '—'}`, value: lastFull ? num(lastFull.total / 1e5, 1) : '—', unit: ' lakh', trend: lastFull?.yoy_pct != null ? { dir: lastFull.yoy_pct >= 0 ? 'up' : 'down', good: lastFull.yoy_pct >= 0, text: `${lastFull.yoy_pct >= 0 ? '+' : ''}${lastFull.yoy_pct}% compared with last year` } : null })}
      ${statTile({ label: 'Best year for growth', value: best.year ?? '—', note: best.yoy_pct != null ? `${best.yoy_pct > 0 ? '+' : ''}${best.yoy_pct}%` : '' })}
      ${statTile({ label: 'New registrations, last 12 months', value: num(newRegs) })}`)}
    <div class="section" id="arr"></div>
    ${details('Visitors compared with last year, new businesses, visitors by district', html`<div id="yoy"></div><div class="section" id="regm"></div><h3 class="section">Visitors by district</h3><div id="bdt"></div>`)}
    <p class="hint">* This year is not over yet.</p>`);
  append(box, '#arr', barChart({
    title: lastFull ? `${num(lastFull.total / 1e5, 1)} lakh visitors came in ${lastFull.year}` : 'Visitors each year', sub: 'Visitors each year, from India and abroad', x: tot.map((t) => t.year), xFmt: yrLbl,
    series: [{ label: 'Visitors', values: tot.map((t) => t.total) }], valueLabels: true, valueFmt: (v) => num(v / 1e5, 1) + 'L', colorFn: (i) => (tot[i].partial_year ? '#9db8e8' : '#2a78d6'), height: 230,
    tipExtra: (i) => `From India ${num(tot[i].domestic)} · from abroad ${num(tot[i].foreign)}${tot[i].yoy_pct != null ? ` · ${tot[i].yoy_pct > 0 ? '+' : ''}${tot[i].yoy_pct}% vs last year` : ''}`,
  }));
  append(box, '#yoy', barChart({
    title: g.length ? `Biggest rise in ${best.year} (${best.yoy_pct > 0 ? '+' : ''}${best.yoy_pct}%)` : 'Visitors compared with last year', sub: 'Change in visitors compared with the year before; red = fewer', x: tot.map((t) => t.year), xFmt: yrLbl, unit: '%',
    series: [{ label: 'Change vs last year', values: tot.map((t) => t.yoy_pct) }], valueLabels: true, valueFmt: (v) => (v > 0 ? '+' : '') + num(v, 1) + '%',
    colorFn: (i, v) => (v < 0 ? '#b42318' : '#2a78d6'),
  }));
  const ns = rg.series.find((x) => x.key === 'new_registrations') || rg.series[0];
  append(box, '#regm', barChart({
    title: `${num(newRegs)} new registrations in the last 12 months`, sub: 'New businesses each month, last 2 years', x: rg.months, xFmt: (v) => fmtMonth(v),
    series: [{ label: ns.label, values: ns.values }], minLabelGap: 56,
  }));
  const years = mk.years;
  mount(box.querySelector('#bdt'), table([{ key: 'label', label: 'District' }, ...years.map((y, j) => ({ key: 'y' + j, label: yrLbl(y, j), num: true })), { key: 'yoy', label: 'Compared with last year', num: true }],
    mk.by_district.map((d) => { const r = { label: d.label, yoy: d.latest_full_year_yoy_pct != null ? `${d.latest_full_year_yoy_pct > 0 ? '▲ +' : d.latest_full_year_yoy_pct < 0 ? '▼ ' : ''}${d.latest_full_year_yoy_pct}%` : '—' }; d.arrivals.forEach((v, j) => { r['y' + j] = num(v); }); return r; }), 'Visitors by district and year'));
}

async function grievances(box, district, m, isAdmin) {
  const g = await api('/analytics/grievances', { query: { district } });
  const openN = g.by_status.filter((x) => ['received', 'assigned', 'in_progress'].includes(x.key)).reduce((a, b) => a + b.count, 0);
  mount(box, html`${synBanner(g.note)}${scopeLine(g)}
    ${tiles(html`${statTile({ label: 'Open complaints', value: openN, note: `${num(g.total)} in total`, tone: openN ? 'warn' : 'ok' })}
      ${statTile({ label: `Not answered within ${g.sla_days} days`, value: pct(g.sla_breach_rate_pct), tone: g.sla_breach_rate_pct > 20 ? 'bad' : g.sla_breach_rate_pct > 0 ? 'warn' : 'ok', note: `${g.sla_breached} complaints` })}
      ${statTile({ label: 'Median time to resolve', value: g.median_resolution_days != null ? num(g.median_resolution_days, 1) : '—', unit: ' days', note: `${g.resolved_count} resolved or closed` })}`)}
    <div class="section" id="gcat"></div>
    ${details(isAdmin && !district ? 'By status and by district' : 'By status', html`<div id="gst"></div>${isAdmin && !district ? html`<div class="section" id="gdist"></div>` : ''}`)}`);
  const topCat = g.by_category.slice().sort((a, b) => b.count - a.count)[0];
  append(box, '#gcat', hbarChart({ title: topCat && topCat.count ? `Most complaints are about ${topCat.label.split(' / ')[0].toLowerCase()} (${topCat.count})` : 'No complaints by category', sub: 'Complaints by category', items: g.by_category.map((c) => ({ label: c.label, value: c.count })), valueFmt: (v) => num(v), labelHead: 'Category', valueHead: 'Complaints' }));
  const STC = { received: '#2a78d6', assigned: '#6250d6', in_progress: '#c98a00', resolved: '#2e8540', closed: '#6b6a65' };
  append(box, '#gst', hbarChart({ title: `${openN} still open, ${g.total - openN} resolved or closed`, sub: 'Complaints by status', items: g.by_status.map((c) => ({ label: titleCase(c.key), value: c.count, color: STC[c.key] })), valueFmt: (v) => num(v), labelHead: 'Status', valueHead: 'Complaints' }));
  const topD = g.by_district.slice().sort((a, b) => b.count - a.count)[0];
  if (isAdmin && !district) append(box, '#gdist', hbarChart({ title: topD ? `${topD.label} has the most complaints (${topD.count})` : 'By district', sub: 'Complaints by district', items: g.by_district.map((c) => ({ label: c.label, value: c.count })), valueFmt: (v) => num(v), labelHead: 'District', valueHead: 'Complaints' }));
}

async function workforce(box, district) {
  let groupBy = 'district';
  const draw = async () => {
    const w = await api('/analytics/workforce', { query: { district, group_by: groupBy } });
    const ROLES = ['housekeeping', 'front_office', 'food_beverage', 'maintenance', 'other'];
    const roleName = (r) => titleCase(r).replace('Food beverage', 'Food & beverage');
    const o = w.overall;
    const shown = w.groups.filter((g) => !g.suppressed);
    const hidden = w.groups.filter((g) => g.suppressed);
    const totals = ROLES.map((r) => ({ r, v: shown.reduce((a, g) => a + (g.roles?.[r] || 0), 0) })).sort((a, b) => b.v - a.v);
    const all = totals.reduce((a, b) => a + b.v, 0) || 1;
    mount(box, html`${synBanner(w.note)}${scopeLine(w)}
      <p class="small muted">Month ${fmtMonth(w.month)} · groups with fewer than ${w.k_min} hotels are not shown, to keep them private${infoNote(`${w.source}. Never per person, never per business.`, 'About privacy')}</p>
      ${o.suppressed ? html`<div class="state wait section" role="status"><div class="ico" aria-hidden="true">🔒</div><h3>Not shown: too few hotels to keep it private</h3><p>${o.reason}</p></div>` : tiles(html`
        ${statTile({ label: 'Staff in contributing stays', value: num(o.staff_total), note: `${o.businesses} businesses` })}
        ${statTile({ label: 'Staff who may leave soon', value: pct(o.flagged_share_pct), tone: o.flagged_share_pct > 10 ? 'warn' : '' })}
        ${statTile({ label: `Staff who left, last ${w.months_in_turnover} months`, value: pct(o.turnover_pct_12m) })}`)}
      ${shown.length ? html`<div id="roles" class="section"></div>` : ''}
      ${details(`Groups by ${groupBy === 'district' ? 'district' : 'business type'} (${w.groups.length})`, html`<div class="row section"><span class="lbl">Group by</span><div class="pillnav" role="group" aria-label="Group by"><button type="button" data-g="district" aria-pressed="${String(groupBy === 'district')}" class="${groupBy === 'district' ? 'on' : ''}">District</button><button type="button" data-g="type" aria-pressed="${String(groupBy === 'type')}" class="${groupBy === 'type' ? 'on' : ''}">Business type</button></div></div>
        <div class="wf-grid section">${w.groups.map((g) => (g.suppressed ? html`<div class="wf sup"><strong>${g.label}</strong><p class="small section"><span aria-hidden="true">🔒</span> Not shown: too few hotels to keep it private</p></div>`
          : html`<div class="wf"><strong>${g.label}</strong><div class="small muted">${g.businesses} businesses · ${num(g.staff_total)} staff</div><div class="small">May leave ${pct(g.flagged_share_pct)} · left ${pct(g.turnover_pct_12m)}</div></div>`))}</div>
        ${hidden.length ? html`<p class="hint">${hidden.length} group(s) hidden: ${hidden[0].reason}</p>` : ''}`, groupBy === 'type' ? 'open' : '')}`);
    if (groupBy === 'type') box.querySelector('details.more')?.setAttribute('open', '');
    if (shown.length) {
      append(box, '#roles', hbarChart({
        title: `${roleName(totals[0].r)} is the largest role: ${num((100 * totals[0].v) / all, 0)}% of staff`, sub: 'Share of staff by role, all visible groups',
        items: totals.map((t) => ({ label: roleName(t.r), value: Math.round((1000 * t.v) / all) / 10 })), unit: '%', max: 100, labelHead: 'Role', valueHead: 'Share of staff',
      }));
    }
    $$('[data-g]', box).forEach((b) => b.addEventListener('click', () => { groupBy = b.dataset.g; load(box, draw, { skel: 'block' }); }));
  };
  await draw();
}

// Hiring board aggregates: open jobs vs visible candidates (k-anonymous), seasonal demand, time to fill.
async function jobsMarket(box, district, m, isAdmin) {
  const w = await api('/analytics/workforce-market', { query: { district } });
  const t = w.totals;
  const hid = (v) => (v == null ? html`<span class="muted" title="${w.suppress_reason}">not shown</span>` : num(v));
  const gapCell = (r) => (r.gap == null ? html`<span class="muted">—</span>` : r.gap > 0 ? html`<strong class="txt-bad">${r.gap} short</strong>` : r.gap < 0 ? html`${-r.gap} spare` : 'balanced');
  const ttf = w.time_to_fill;
  const short = w.by_skill.filter((r) => r.gap > 0).sort((a, b) => b.gap - a.gap);
  mount(box, html`${synBanner(w.note)}${scopeLine(w)}
    ${tiles(html`${statTile({ label: 'Open job posts', value: num(t.open_posts), note: `${num(t.openings)} openings` })}
      ${statTile({ label: 'Workers looking', value: hid(t.candidates) })}
      ${statTile({ label: 'Hardest job to fill', value: short[0]?.label || 'None', tone: short.length ? 'warn' : 'ok', note: short[0] ? `${short[0].gap} more jobs than workers` : '' })}
      ${statTile({ label: 'Usual time to fill a job', value: ttf.median_days != null ? num(ttf.median_days, 0) : '—', unit: ttf.median_days != null ? ' days' : '', note: ttf.suppressed ? ttf.reason : `${ttf.filled_posts} filled posts` })}`)}
    <div class="section" id="wm-season"></div>
    ${details('Jobs and workers by skill' + (isAdmin && !district ? ' and by district' : ''), html`<p class="small muted">Jobs open and workers with each skill. “Short” = more jobs than workers. Small groups are not shown, to keep people private.${infoNote(`${w.source} A candidate counts once per listed skill and per preferred district; "any district" counts everywhere.`, 'About this data')}</p><div id="wm-skt"></div>${isAdmin && !district ? html`<h3 class="section">By district</h3><div id="wm-dt"></div>` : ''}`)}`);
  const sea = w.seasonal;
  const peak = sea.openings.indexOf(Math.max(...sea.openings));
  append(box, '#wm-season', barChart({
    title: `Most staff are needed in ${monthName(peak + 1)} (${num(sea.openings[peak])} jobs)`, sub: 'Jobs open each month; workers per month are in the table',
    x: sea.months, xFmt: (v) => monthName(v, true), series: [{ label: 'Openings', values: sea.openings }], valueLabels: true, height: 220,
    colorFn: (i) => (i === peak ? '#c94d16' : '#2a78d6'),
    tableHtml: table([{ key: 'm', label: 'Month' }, { key: 'o', label: 'Openings', num: true }, { key: 'c', label: 'Candidates available', num: true }], sea.months.map((mm, i) => ({ m: monthName(mm), o: num(sea.openings[i]), c: sea.candidates[i] == null ? 'hidden' : num(sea.candidates[i]) })), 'Openings and candidates by month'),
    note: sea.note,
  }));
  const cols = [{ key: 'label', label: 'Skill' }, { key: 'openings', label: 'Openings', num: true }, { key: 'open_posts', label: 'Posts', num: true },
    { key: 'candidates', label: 'Candidates', num: true, render: (r) => hid(r.candidates) }, { key: 'gap', label: 'Gap', num: true, render: gapCell }];
  pager(box.querySelector('#wm-skt'), w.by_skill, (slice) => table(cols, slice, 'Jobs and workers by skill'), 10);
  if (isAdmin && !district) {
    pager(box.querySelector('#wm-dt'), w.by_district, (slice) => table([{ ...cols[0], label: 'District' }, ...cols.slice(1)], slice, 'Jobs and workers by district'), 13);
  }
}
