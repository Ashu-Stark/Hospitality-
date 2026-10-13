// Officials' analytics dashboard: overview KPIs, rush heatmap, occupancy trend, market growth (SYNTHETIC),
// grievances, workforce (k-anonymous). District officers see their district only; the state admin gets a district filter.
import { html, mount, href, load, $, $$, raw, fmtDate, fmtMonth, monthName, num, pct, empty, table, bandPill, announce, fmtDateTime, titleCase, moreList, infoNote, pager } from '../ui.js';
import { api, meta, user, role } from '../api.js';
import { setQuery } from '../router.js';
import { lineChart, barChart, hbarChart, heatmap, sparkline, PALETTE, BAND_FILL, bandOf, bandLegend, bandTintLegend, bandCell } from '../charts.js';
import { roleSubnav } from './common.js';

const TABS = [['overview', 'Overview'], ['rush', 'Rush & crowd'], ['occupancy', 'Occupancy'], ['market', 'Market growth'], ['grievances', 'Grievances'], ['workforce', 'Workforce']];
const synBanner = (note) => html`<div class="synbanner" role="note"><b>SYNTHETIC DATA</b><span>Not official statistics.</span></div>`;
const shortDate = (v) => { const d = new Date(v + 'T00:00'); return `${d.getDate()} ${monthName(d.getMonth() + 1, true)}`; };

export async function analytics(ctx) {
  const el = ctx.el;
  const isAdmin = role() === 'state_admin';
  const f = { tab: TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'overview', district: isAdmin ? ctx.query.district || '' : '' };
  const m = await meta();
  mount(el, html`${roleSubnav('/officer')}
    <div class="pagehead"><div><p class="eyebrow">Officials · analytics</p><h1>Analytics dashboard</h1>
      <p>${isAdmin ? 'State view. Choose a district to focus.' : html`Scope: <strong>${user()?.district_name}</strong> district only.`} All figures below are synthetic sample data.</p></div>
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
    const fn = { overview, rush, occupancy, market, grievances, workforce }[f.tab];
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

async function overview(box, district) {
  const [k, occ, regs] = await Promise.all([
    api('/analytics/kpis', { query: { district } }),
    api('/analytics/occupancy', { query: { district, granularity: 'monthly', days: 365 } }).catch(() => null),
    api('/analytics/registrations', { query: { district, months: 12 } }).catch(() => null),
  ]);
  const spark = {
    avg_occupancy_30d: occ?.overall?.values,
    registered_businesses: regs?.series?.find((s) => s.key === 'new_registrations')?.values,
    applications_pending: regs?.series?.find((s) => s.key === 'applications_submitted')?.values,
  };
  const sparkNote = { avg_occupancy_30d: 'monthly occupancy, last 12 months', registered_businesses: 'new registrations per month, last 12 months', applications_pending: 'applications submitted per month' };
  const tone = (x) => (x.key === 'grievances_overdue' && x.value > 0 ? 'bad' : x.key === 'crowd_alerts' && x.value > 0 ? 'warn' : x.key === 'applications_pending' && x.value > 0 ? 'warn' : '');
  mount(box, html`${synBanner(k.note)}${scopeLine(k)}
    <div class="kpis section">${k.kpis.map((x) => html`<div class="kpi ${tone(x)}"><span class="k">${x.label}</span><span class="v">${x.unit === '%' ? num(x.value, 1) : num(x.value)}${x.unit ? html`<small>${x.unit}</small>` : ''}</span>
      ${spark[x.key] ? html`${raw(sparkline(spark[x.key]))}<span class="small muted">Trend: ${sparkNote[x.key]}</span>` : ''}
      ${tone(x) ? html`<span class="small"><strong>${x.key === 'grievances_overdue' ? '✕ Needs attention' : '! Review'}</strong></span>` : ''}</div>`)}</div>
    <div class="grid g2 section">
      <section class="card" aria-labelledby="ca-h"><h2 id="ca-h">Crowd-level alerts (next 14 days)</h2>
        ${k.crowd_alerts?.length ? html`<div class="list">${k.crowd_alerts.map((a) => html`<div class="item"><div class="main"><a class="t" href="${href('/destinations/' + a.destination_id)}">${a.name}</a><div class="sub">Peak ${fmtDate(a.peak_date, { weekday: true })}</div></div><div class="side">${bandPill(bandOf(a.peak_index), a.peak_index, 'Peak')}</div></div>`)}</div>`
          : html`<p class="flag green">No destination is expected to reach the very-high band (85+).</p>`}
        <p class="hint">Crowd index is an estimate.</p></section>
      <section class="card" aria-labelledby="bs-h"><h2 id="bs-h">Businesses by status</h2><div id="bs"></div>
        <div class="btnrow section"><a class="btn sm ghost" href="#/officer/applications">Applications queue</a><a class="btn sm ghost" href="#/officer/grievances">Grievance queue</a></div></section></div>`);
  const st = k.businesses_by_status || {};
  const tot = Object.values(st).reduce((a, b) => a + b, 0);
  append(box, '#bs', hbarChart({ title: `${num(st.active || 0)} of ${num(tot)} registrations are active`, items: Object.entries(st).map(([s, v]) => ({ label: titleCase(s), value: v, color: { active: '#2e8540', expired: '#b42318', suspended: '#6b6a65', pending: '#c98a00' }[s] })), valueFmt: (v) => num(v), labelHead: 'Status', valueHead: 'Businesses' }));
}

async function rush(box, district) {
  const r = await api('/analytics/rush', { query: { district, top: 10 } });
  const hm = r.heatmap;
  const vh = r.top.filter((x) => x.avg_index_14d >= 85).length;
  mount(box, html`${synBanner(r.note)}${scopeLine(r)}<div id="top" class="section"></div><div id="hm" class="section"></div>
    <section class="card section" aria-labelledby="al-h"><h2 id="al-h">${r.alerts?.length ? `${r.alerts.length} very-high crowd days ahead` : 'No very-high crowd days ahead'} <span class="pill syn">estimate</span></h2>
      ${r.alerts?.length ? html`<div id="alt"></div>`
        : html`<p class="flag green">No alerts in the outlook window.</p>`}</section>`);
  if (r.alerts?.length) pager(box.querySelector('#alt'), r.alerts, (slice) => table([{ key: 'name', label: 'Destination', render: (a) => html`<a href="${href('/destinations/' + a.destination_id + '/crowd')}">${a.name}</a>` }, { key: 'date', label: 'Date', render: (a) => fmtDate(a.date, { weekday: true }) }, { key: 'index', label: 'Index', num: true }, { key: 'events', label: 'Events', render: (a) => (a.events || []).join(', ') || '—' }], slice, 'Very high crowd outlook (estimate)'), 5);
  append(box, '#hm', heatmap({
    title: hm.rows.length ? `Week by week: ${hm.rows[0].name} peaks at ${Math.max(...hm.rows[0].values.filter((v) => v != null))}` : 'Week by week', sub: 'Average crowd index per destination and week: last 8 weeks, this week, 8-week outlook (estimate). Number in each cell; colour shows the band.',
    rows: hm.rows.map((x) => ({ label: x.name, values: x.values })), cols: hm.weeks, colKind: hm.week_kind, rowHead: 'Destination',
    colFmt: (c, j, long) => (long ? 'Week of ' + fmtDate(c) : shortDate(c)), cell: bandCell, legendItems: bandTintLegend(),
    note: 'Week columns start on Monday. Outlook weeks use the festival calendar, seasonality and synthetic occupancy patterns.',
  }));
  append(box, '#top', hbarChart({
    title: r.top.length ? `${r.top[0].name} is the busiest in the next 2 weeks${vh > 1 ? `; ${vh} places at very high` : ''}` : 'No destinations in scope', sub: 'Top destinations by average crowd index, next 14 days (estimate)', labelHead: 'Destination', valueHead: 'Avg index (14 d)',
    items: r.top.map((x) => ({ label: x.name, value: x.avg_index_14d, color: BAND_FILL[x.band] || BAND_FILL[bandOf(x.avg_index_14d)], extra: `Peak ${x.peak_index} on ${fmtDate(x.peak_date, { noYear: true })} · ${x.band.replace('_', ' ')}` })),
    max: 100, valueFmt: (v) => String(v), legendItems: bandLegend(),
  }));
}

async function occupancy(box, district, m, isAdmin) {
  const f = { granularity: 'weekly', days: '365', type: '', mode: 'overall', picks: [] };
  mount(box, html`<div id="occ-syn"></div><form class="card tight filters" id="of" aria-label="Occupancy options">
      <div class="fld"><label class="lbl" for="o-g">Granularity</label><select class="field" id="o-g" name="granularity"><option value="daily">Daily</option><option value="weekly" selected>Weekly</option><option value="monthly">Monthly</option></select></div>
      <div class="fld"><label class="lbl" for="o-d">Period</label><select class="field" id="o-d" name="days"><option value="90">Last 90 days</option><option value="365" selected>Last 12 months</option><option value="730">Last 24 months</option></select></div>
      <div class="fld"><label class="lbl" for="o-t">Business type</label><select class="field" id="o-t" name="type"><option value="">Hotels and homestays</option><option value="hotel">Hotels</option><option value="homestay">Homestays</option></select></div>
      <div class="fld"><label class="lbl" for="o-m">Compare</label><select class="field" id="o-m" name="mode"><option value="overall">${district || !isAdmin ? 'Overall' : 'State overall'}</option><option value="type">By business type</option>${isAdmin && !district ? html`<option value="district">By district (pick up to 4)</option>` : ''}</select></div>
    </form><div id="picks"></div><div id="occ" class="section"></div>`);
  const form = $('#of', box);
  const draw = () => load($('#occ', box), async () => {
    const r = await api('/analytics/occupancy', { query: { district, granularity: f.granularity, days: f.days, type: f.type || undefined } });
    mount($('#occ-syn', box), html`${synBanner(r.note)}${scopeLine(r)}`);
    let series = [{ label: r.overall.label + ' occupancy', values: r.overall.values }];
    if (f.mode === 'type') series = r.by_type.map((s) => ({ label: s.label, values: s.values }));
    if (f.mode === 'district') {
      const all = r.by_district;
      if (!f.picks.length) f.picks = all.slice().sort((a, b) => avg(b.values) - avg(a.values)).slice(0, 3).map((s) => s.key);
      mount($('#picks', box), html`<fieldset class="card tight section"><legend class="lbl">Districts to compare (max 4)</legend><div class="chips">${all.map((s) => html`<label class="check"><input type="checkbox" value="${s.key}" ${f.picks.includes(s.key) ? raw('checked') : ''}>${s.label}</label>`)}</div></fieldset>`);
      $$('#picks input', box).forEach((c) => c.addEventListener('change', () => {
        const on = $$('#picks input:checked', box).map((x) => x.value);
        if (on.length > 4) { c.checked = false; announce('Choose at most 4 districts'); return; }
        f.picks = on;
        draw();
      }));
      series = all.filter((s) => f.picks.includes(s.key)).map((s, i) => ({ label: s.label, values: s.values, color: PALETTE[all.findIndex((x) => x.key === s.key) % PALETTE.length] }));
    } else mount($('#picks', box), '');
    if (!series.length) { mount($('#occ', box), empty('Choose at least one district')); return; }
    const ov = r.overall.values.filter((v) => v != null);
    const peakI = r.overall.values.indexOf(Math.max(...ov));
    const avgAll = avg(r.overall.values);
    $('#occ', box).replaceChildren(lineChart({
      title: ov.length ? `Occupancy averaged ${num(avgAll, 0)}%, peaking ${f.granularity === 'monthly' ? 'in ' + fmtMonth(r.dates[peakI].slice(0, 7)) : 'around ' + fmtDate(r.dates[peakI], { noYear: false })}` : 'No occupancy data', sub: `${r.scope?.district_name || 'State'} · ${f.type ? titleCase(f.type) + 's' : 'hotels and homestays'} · % of available rooms`,
      x: r.dates, series, unit: '%', yMin: 0, yMax: 100, xFmt: (v, i, long) => (long ? (f.granularity === 'monthly' ? fmtMonth(v.slice(0, 7)) : (f.granularity === 'weekly' ? 'Week of ' : '') + fmtDate(v)) : f.granularity === 'monthly' ? fmtMonth(v.slice(0, 7)) : shortDate(v)),
      note: 'Gaps mean no data reported. Synthetic history plus any submitted or HOI-ingested occupancy.',
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
  mount(box, html`${synBanner(mk.note)}${scopeLine(mk)}
    <div class="section" id="arr"></div><div class="section" id="yoy"></div>
    <div class="section" id="regm"></div>
    <section class="card section" aria-labelledby="bd-h"><h2 id="bd-h">Arrivals by district (synthetic)</h2><div id="bdt"></div></section>
    <p class="hint">* ${mk.partial_year_note}</p>`);
  const full = tot.filter((x) => !x.partial_year);
  const lastFull = full[full.length - 1];
  append(box, '#arr', barChart({
    title: lastFull ? `${num(lastFull.total / 1e5, 1)} lakh arrivals in ${lastFull.year}${lastFull.yoy_pct != null ? `, ${lastFull.yoy_pct >= 0 ? 'up' : 'down'} ${Math.abs(lastFull.yoy_pct)}%` : ''} (synthetic)` : 'Tourist arrivals by year (synthetic)', sub: 'Domestic and foreign arrivals by year, stacked', x: tot.map((t) => t.year), xFmt: yrLbl, stacked: true,
    series: [{ label: 'Domestic', values: tot.map((t) => t.domestic) }, { label: 'Foreign', values: tot.map((t) => t.foreign) }],
    tipExtra: (i) => (tot[i].yoy_pct != null ? `YoY ${tot[i].yoy_pct > 0 ? '+' : ''}${tot[i].yoy_pct}%` : tot[i].partial_year ? 'Partial year' : ''),
  }));
  append(box, '#yoy', barChart({
    title: (() => { const g = tot.filter((x) => x.yoy_pct != null); const b = g.reduce((a, c) => (c.yoy_pct > a.yoy_pct ? c : a), g[0] || {}); return g.length ? `Strongest growth in ${b.year} (${b.yoy_pct > 0 ? '+' : ''}${b.yoy_pct}%)` : 'Year-on-year growth'; })(), sub: 'Year-on-year % change in arrivals (synthetic)', x: tot.map((t) => t.year), xFmt: yrLbl, unit: '%',
    series: [{ label: 'YoY growth', values: tot.map((t) => t.yoy_pct) }], valueLabels: true, valueFmt: (v) => (v > 0 ? '+' : '') + num(v, 1) + '%',
    colorFn: (i, v) => (v < 0 ? '#b42318' : '#2a78d6'), note: 'Red bars are declines. No value for the first year and the partial current year.',
  }));
  append(box, '#regm', barChart({
    title: (() => { const s = rg.series.find((x) => x.key === 'new_registrations'); const n = s ? s.values.slice(-12).reduce((a, b) => a + (b || 0), 0) : 0; return `${num(n)} new registrations in the last 12 months`; })(), sub: 'New registrations and applications submitted per month, last 24 months (synthetic)', x: rg.months, xFmt: (v) => fmtMonth(v),
    series: rg.series.map((s) => ({ label: s.label, values: s.values })), minLabelGap: 56,
  }));
  const years = mk.years;
  mount(box.querySelector('#bdt'), table([{ key: 'label', label: 'District' }, ...years.map((y, j) => ({ key: 'y' + j, label: yrLbl(y, j), num: true })), { key: 'yoy', label: 'Latest full-year YoY', num: true }],
    mk.by_district.map((d) => { const r = { label: d.label, yoy: d.latest_full_year_yoy_pct != null ? `${d.latest_full_year_yoy_pct > 0 ? '▲ +' : d.latest_full_year_yoy_pct < 0 ? '▼ ' : ''}${d.latest_full_year_yoy_pct}%` : '—' }; d.arrivals.forEach((v, j) => { r['y' + j] = num(v); }); return r; }), 'Synthetic arrivals by district and year'));
}

async function grievances(box, district, m, isAdmin) {
  const g = await api('/analytics/grievances', { query: { district } });
  mount(box, html`${synBanner(g.note)}${scopeLine(g)}
    <div class="kpis section"><div class="kpi"><span class="k">Grievances (total)</span><span class="v">${num(g.total)}</span></div>
      <div class="kpi ${g.sla_breach_rate_pct > 20 ? 'bad' : g.sla_breach_rate_pct > 0 ? 'warn' : 'ok'}"><span class="k">SLA breach rate (${g.sla_days}-day SLA, assumed)</span><span class="v">${pct(g.sla_breach_rate_pct)}</span><span class="small">${g.sla_breached} breached</span></div>
      <div class="kpi"><span class="k">Median resolution</span><span class="v">${g.median_resolution_days != null ? num(g.median_resolution_days, 1) : '—'}<small> days</small></span><span class="small">${g.resolved_count} resolved/closed</span></div></div>
    <div class="section" id="gcat"></div><div class="section" id="gst"></div>${isAdmin && !district ? html`<div class="section" id="gdist"></div>` : ''}`);
  const topCat = g.by_category.slice().sort((a, b) => b.count - a.count)[0];
  append(box, '#gcat', hbarChart({ title: topCat && topCat.count ? `Most complaints: ${topCat.label.split(' / ')[0].toLowerCase()} (${topCat.count})` : 'No complaints by category', sub: 'Grievances by category', items: g.by_category.map((c) => ({ label: c.label, value: c.count })), valueFmt: (v) => num(v), labelHead: 'Category', valueHead: 'Grievances' }));
  const STC = { received: '#2a78d6', assigned: '#6250d6', in_progress: '#c98a00', resolved: '#2e8540', closed: '#6b6a65' };
  const openN = g.by_status.filter((x) => ['received', 'assigned', 'in_progress'].includes(x.key)).reduce((a, b) => a + b.count, 0);
  append(box, '#gst', hbarChart({ title: `${openN} still open, ${g.total - openN} resolved or closed`, sub: 'Grievances by status', items: g.by_status.map((c) => ({ label: titleCase(c.key), value: c.count, color: STC[c.key] })), valueFmt: (v) => num(v), labelHead: 'Status', valueHead: 'Grievances' }));
  const topD = g.by_district.slice().sort((a, b) => b.count - a.count)[0];
  if (isAdmin && !district) append(box, '#gdist', hbarChart({ title: topD ? `${topD.label} has the most grievances (${topD.count})` : 'By district', sub: 'Grievances by district', items: g.by_district.map((c) => ({ label: c.label, value: c.count })), valueFmt: (v) => num(v), labelHead: 'District', valueHead: 'Grievances' }));
}

async function workforce(box, district) {
  let groupBy = 'district';
  const draw = async () => {
    const w = await api('/analytics/workforce', { query: { district, group_by: groupBy } });
    const ROLES = ['housekeeping', 'front_office', 'food_beverage', 'maintenance', 'other'];
    const o = w.overall;
    const shown = w.groups.filter((g) => !g.suppressed);
    const hidden = w.groups.filter((g) => g.suppressed);
    mount(box, html`${synBanner(w.note)}${scopeLine(w)}
      <p class="small muted">Month ${fmtMonth(w.month)} · groups with fewer than ${w.k_min} businesses are hidden (k-anonymity)${infoNote(`${w.source}. Never per person, never per business.`, 'About workforce privacy')}</p>
      <div class="row section"><span class="lbl">Group by</span><div class="pillnav" role="group" aria-label="Group by"><button type="button" data-g="district" aria-pressed="${String(groupBy === 'district')}" class="${groupBy === 'district' ? 'on' : ''}">District</button><button type="button" data-g="type" aria-pressed="${String(groupBy === 'type')}" class="${groupBy === 'type' ? 'on' : ''}">Business type</button></div></div>
      ${o.suppressed ? html`<div class="state wait section" role="status"><div class="ico" aria-hidden="true">🔒</div><h3>Hidden to protect privacy</h3><p>${o.reason}</p></div>` : html`<div class="kpis section">
        <div class="kpi"><span class="k">Staff (contributing stays)</span><span class="v">${num(o.staff_total)}</span><span class="small">${o.businesses} businesses</span></div>
        <div class="kpi ${o.flagged_share_pct > 10 ? 'warn' : ''}"><span class="k">Share flagged for review</span><span class="v">${pct(o.flagged_share_pct)}</span></div>
        <div class="kpi"><span class="k">Turnover, last ${w.months_in_turnover} months</span><span class="v">${pct(o.turnover_pct_12m)}</span></div></div>`}
      ${shown.length ? html`<div id="roles" class="section"></div>` : ''}
      <h2 class="section">Groups</h2>
      <div class="wf-grid section">${w.groups.map((g) => (g.suppressed ? html`<div class="wf sup"><strong>${g.label}</strong><p class="small section"><span aria-hidden="true">🔒</span> Hidden (fewer than ${w.k_min} businesses)</p></div>`
        : html`<div class="wf"><strong>${g.label}</strong><div class="small muted">${g.businesses} businesses · ${num(g.staff_total)} staff</div>
          <div class="small">Flagged ${pct(g.flagged_share_pct)} · turnover ${pct(g.turnover_pct_12m)}</div></div>`))}</div>
      ${hidden.length ? html`<p class="hint">${hidden.length} group(s) hidden: ${hidden[0].reason}</p>` : ''}`);
    if (shown.length) {
      append(box, '#roles', barChart({
        title: (() => { const tr = ROLES.map((r) => [r, shown.reduce((a, g) => a + (g.roles?.[r] || 0), 0)]).sort((a, b) => b[1] - a[1])[0]; const all = shown.reduce((a, g) => a + (g.staff_total || 0), 0); return `${titleCase(tr[0]).replace('Food beverage', 'Food & beverage')} is the largest role (${num((100 * tr[1]) / (all || 1), 0)}% of staff)`; })(), sub: 'Staff by role per group, stacked; hidden groups are left out', x: shown.map((g) => g.label), stacked: true,
        series: ROLES.map((r) => ({ label: titleCase(r).replace('Food beverage', 'Food & beverage'), values: shown.map((g) => g.roles?.[r] ?? 0) })), minLabelGap: 70,
      }));
    }
    $$('[data-g]', box).forEach((b) => b.addEventListener('click', () => { groupBy = b.dataset.g; load(box, draw, { skel: 'block' }); }));
  };
  await draw();
}
