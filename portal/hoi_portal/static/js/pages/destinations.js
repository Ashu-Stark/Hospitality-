// Destinations list + destination detail. Detail answers "should I go this week?" first (At a glance tiles), then
// shows ONE tab panel at a time (deep-linkable: #/destinations/<id>/<tab>).
import { html, mount, href, load, bandPill, trafficPill, $, $$, empty, monthName, MONTH_NAMES, fmtDate, relTime, roadPill, impactPill, lastUpdated, crumbs, num, raw, samplePill, collapseFilters, pager, moreList, infoNote, dayStrip, takeaway, details } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';
import { barChart, BAND_FILL, bandOf, miniBars, PALETTE } from '../charts.js';
import { bizRow, advisoryRow, kv } from './common.js';
import { nearbyPanel } from './plan.js';
import { photoHead, thumbsNote } from '../photos.js';
import { destCard, localCard } from '../cards.js';

const EXP_NAMES = { spiritual: 'Spiritual & Char Dham', adventure: 'Adventure & Treks', wildlife: 'Wildlife & Nature', wellness: 'Yoga & Wellness', leisure: 'Hill towns & Leisure', culture: 'Culture & Fairs' };

// ------------------------------------------------------------------ list
export async function list(ctx) {
  const el = ctx.el;
  const f = { district: ctx.query.district || '', division: ctx.query.division || '', tag: ctx.query.tag || '', q: ctx.query.q || '' };
  mount(el, html`<div class="pagehead"><div><h1>${t('destinations')}</h1>
    <p>Pick a place to see the weather, roads, how busy it will be, registered stays and local experiences.</p></div></div>
    <form class="card tight filters" id="dfilters" aria-label="Filter destinations"></form>
    <p class="small muted" id="dcount" aria-live="polite"></p>
    <div id="dlist"></div>${thumbsNote()}`);
  await load($('#dlist', el), async () => {
    const [m, d] = await Promise.all([meta(), api('/destinations')]);
    const form = $('#dfilters', el);
    mount(form, html`
      <div class="fld"><label class="lbl" for="f-q">Name</label><input class="field" id="f-q" name="q" type="search" value="${f.q}" placeholder="e.g. Auli"></div>
      <div class="fld"><label class="lbl" for="f-division">Division</label><select class="field" id="f-division" name="division"><option value="">All divisions</option>
        ${['Garhwal', 'Kumaon'].map((x) => html`<option ${f.division === x ? raw('selected') : ''}>${x}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="f-district">District</label><select class="field" id="f-district" name="district"><option value="">All districts</option>
        ${m.districts.map((x) => html`<option value="${x.id}" ${f.district === x.id ? raw('selected') : ''}>${x.name}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="f-tag">Theme</label><select class="field" id="f-tag" name="tag"><option value="">All themes</option>
        ${d.tags.map((x) => html`<option ${f.tag === x ? raw('selected') : ''}>${x}</option>`)}</select></div>
      <div class="fld"><button type="reset" class="btn ghost">Clear</button></div>`);
    collapseFilters(form);
    const draw = () => {
      const q = f.q.toLowerCase();
      const items = d.items.filter((x) => (!f.district || x.district === f.district) && (!f.division || x.division === f.division) && (!f.tag || x.tags.includes(f.tag)) && (!q || x.name.toLowerCase().includes(q)));
      $('#dcount', el).textContent = `${items.length} places`;
      if (!items.length) { mount($('#dlist', el), empty('No destinations match', 'Try clearing a filter.')); return; }
      pager($('#dlist', el), items, (slice) => html`<div class="mcgrid g3c">${slice.map((x, i) => destCard(x, { eager: i < 3 }))}</div>`, 12);
    };
    const sync = () => {
      const fd = new FormData(form);
      Object.keys(f).forEach((k) => { f[k] = (fd.get(k) || '').toString().trim(); });
      setQuery(f);
      draw();
    };
    form.addEventListener('input', sync);
    form.addEventListener('reset', () => setTimeout(sync));
    form.addEventListener('submit', (e) => { e.preventDefault(); sync(); });
    draw();
  }, { skel: 'cards', n: 6 });
}

// ------------------------------------------------------------------ detail
const TABS = [['overview', 'Overview'], ['weather', 'Weather'], ['roads', 'Roads'], ['crowd', 'How busy'], ['stays', 'Stay & guides'], ['nearby', 'Nearby'], ['festivals', 'Festivals'], ['help', 'Help']];
let cache = null; // {id, at, d, hl}

async function getDetail(id) {
  if (cache && cache.id === id && Date.now() - cache.at < 120000) return cache;
  const [d, hl] = await Promise.all([api('/destinations/' + encodeURIComponent(id)), api('/helplines').catch(() => null)]);
  cache = { id, at: Date.now(), d, hl };
  return cache;
}
const ROAD_ORDER = { closed: 0, caution: 1, open: 2 };
const short = (iso) => fmtDate(iso, { weekday: true, noYear: true });

export async function detail(ctx) {
  const el = ctx.el;
  const id = ctx.params.id;
  const tab = TABS.some((x) => x[0] === ctx.params.tab) ? ctx.params.tab : 'overview';
  const tabSwitch = !!ctx.prev && (ctx.prev === '/destinations/' + id || ctx.prev.startsWith('/destinations/' + id + '/'));
  if (tabSwitch) ctx.keepFocus = true;
  mount(el, html`${crumbs([['Home', '#/'], ['Destinations', '#/destinations'], ['…']])}<h1 class="sr-only">Destination</h1><div id="dd"></div>`);
  await load($('#dd', el), async () => {
    const { d, hl } = await getDetail(id);
    const x = d.destination;
    const cr = d.crowd;
    const w = d.weather;
    const roadAdv = (d.roads?.advisories || []).slice().sort((a, b) => (ROAD_ORDER[a.status] ?? 3) - (ROAD_ORDER[b.status] ?? 3));
    const worst = roadAdv[0];
    const live = d.roads?.live || null; // live incidents from a provider (TomTom, HERE), alongside the posted advisories
    const tr = d.roads?.traffic || null; // predicted congestion (traffic model), always shown as a prediction
    const roadWorst = d.roads?.worst || (worst ? { status: worst.status, source: 'advisory' } : null);
    const ft = cr?.foot_traffic || null; // BestTime typical foot traffic at one well-known venue
    const outlook = cr?.outlook || [];
    const quiet = outlook.length ? outlook.reduce((a, b) => (b.index < a.index ? b : a)) : null;
    const nowM = new Date().getMonth() + 1;
    const goodNow = x.best_months?.includes(nowM);
    const wWarn = (w?.warnings || [])[0];
    const base = '/destinations/' + x.id;
    mount(el, html`${crumbs([['Home', '#/'], ['Destinations', '#/destinations'], [x.name]])}
      ${photoHead(x.id)}
      <div class="pagehead tightb"><div><p class="eyebrow">${x.district_name} · ${x.division}</p><h1>${x.name}</h1></div>
        <div class="chips">${x.tags.map((tg) => html`<span class="tag">${tg}</span>`)}</div></div>
      <section aria-label="At a glance" class="glance">
        <a class="gl ${wWarn ? 'r' : ''}" href="#${base}/weather"><span class="k">Weather now</span>
          ${w?.available ? html`<span class="v">${Math.round(w.current?.temperature_c)}°C <small>${w.current?.summary || ''}</small></span><span class="s">${wWarn ? html`<strong>⚠ ${wWarn.kind === 'snow' ? 'Snow' : 'Heavy rain'} ${short(wWarn.date)}</strong>` : 'No rain or snow warnings, 7 days'}</span>`
            : html`<span class="v">—</span><span class="s">Weather not available</span>`}</a>
        <a class="gl ${cr?.today?.band === 'very_high' ? 'r' : cr?.today?.band === 'high' ? 'w' : ''}" href="#${base}/crowd"><span class="k">How busy today</span>
          ${cr?.today ? html`<span class="v">${bandPill(cr.today.band, cr.today.index, '')}</span><span class="s">Quietest day soon: ${short(quiet.date)}</span>` : html`<span class="v">—</span><span class="s">Not known</span>`}
          ${ft?.best_window ? html`<span class="s ft">${raw(miniBars(ft.today_by_hour, bestSet(ft)))}<span>Quietest today: <strong>${ft.best_window.label}</strong></span></span>` : ''}</a>
        <a class="gl ${roadWorst?.status === 'closed' ? 'r' : roadWorst?.status === 'caution' ? 'w' : ''}" href="#${base}/roads"><span class="k">Roads</span>
          ${roadWorst && roadWorst.source !== 'advisory' && live ? html`<span class="v">${roadPill(live.status)}</span><span class="s">${live.summary}</span>`
            : worst ? html`<span class="v">${roadPill(worst.status)}</span><span class="s">Road alert: ${worst.segment || worst.title.replace(/^SAMPLE:\s*/, '')}${roadAdv.length > 1 ? ` · +${roadAdv.length - 1} more` : ''}</span>`
            : tr ? html`<span class="v">${trafficPill(tr.now.band, '')} <small>traffic now</small></span><span class="s">${tr.best_time ? `Best time to drive: ${tr.best_time.label}` : ''}</span>`
            : html`<span class="v"><span class="pill neutral noicon">No road alerts</span></span><span class="s">Ask locally before you set out</span>`}
          ${tr && (worst || (roadWorst && roadWorst.source !== 'advisory')) ? html`<span class="s">Traffic now: ${TWORD[tr.now.band] || 'not known'}</span>` : ''}</a>
        <a class="gl" href="#${base}/overview"><span class="k">Best months</span>
          <span class="v">${x.best_months?.length ? monthRanges(x.best_months) : 'Any time'}</span><span class="s">${x.best_months?.length ? (goodNow ? `✓ ${monthName(nowM)} is a good time` : `${monthName(nowM)} is outside the usual season`) : 'See seasonal notes'}</span></a>
      </section>
      <nav class="dtabs" aria-label="${x.name} sections"><div class="pillnav">${TABS.map(([k, l]) => html`<a href="#${base}/${k}" ${k === tab ? html`aria-current="page"` : ''} id="dt-${k}">${l}</a>`)}</div></nav>
      <div class="dlayout"><section class="card panel" id="panel" aria-labelledby="ph" tabindex="-1"></section>
        <aside class="card tight sos" aria-label="Emergency numbers"><h2 class="h3">Emergency numbers</h2>${sos(hl)}<a class="small" href="#${base}/help">All helplines</a></aside></div>
      ${lastUpdated(d.last_updated)}`);
    const panel = $('#panel', el);
    PANELS[tab](panel, d, hl, x);
    if (tabSwitch) {
      document.title = `${x.name}: ${TABS.find((z) => z[0] === tab)[1]} · Uttarakhand Travel Guide`;
      $('#dt-' + tab, el)?.focus({ preventScroll: true });
      $('.dtabs', el).scrollIntoView({ block: 'start' });
    }
  });
}

function monthRanges(ms) {
  const s = [...ms].sort((a, b) => a - b);
  const out = [];
  let st = s[0], pr = s[0];
  for (const m of s.slice(1).concat([99])) {
    if (m === pr + 1) { pr = m; continue; }
    out.push(st === pr ? monthName(st, true) : `${monthName(st, true)}-${monthName(pr, true)}`);
    st = pr = m;
  }
  return out.join(', ');
}
function sos(hl) {
  const items = (hl?.items || []).filter((h) => h.number).slice(0, 4);
  if (!items.length) return html`<p><strong>112</strong> all emergencies</p>`;
  return html`<ul class="plain sosl">${items.map((h) => html`<li><a class="mono" href="tel:${h.number.split(' ')[0]}">${h.number.split(' / ')[0]}</a><span>${h.name}</span></li>`)}</ul>`;
}
const ph = (title, extra = '') => html`<h2 id="ph">${title}${extra}</h2>`;

const PANELS = {
  overview(p, d, hl, x) {
    mount(p, html`${ph('Overview')}
      ${x.themes?.length ? html`<div class="chips">${x.themes.map((th) => html`<a class="chipbtn" href="${href('/experiences/' + th)}">${EXP_NAMES[th] || th}</a>`)}</div>` : ''}
      ${x.why_go ? html`<p class="takeaway section">${x.why_go}</p>` : ''}
      <h3 class="section">Good to know</h3>
      <ul class="bullets section">${[...(x.season_notes || []), ...((d.events || []).filter((e) => !e.sample).slice(0, 3).map((e) => `Usually busy during ${e.name.replace(/^SAMPLE:\s*/, '')} (${e.window}).`)), ...((x.route_facts || []).slice(0, 2))].map((s) => html`<li>${s}</li>`)}</ul>
      ${d.local_experiences?.total ? html`<div class="sechead section"><h3>Things to do with local hosts</h3><a href="${href('/experiences', { destination: x.id })}">All ${d.local_experiences.total}</a></div><div class="mcgrid g3c">${d.local_experiences.items.slice(0, 3).map(localCard)}</div>` : ''}
      ${details('Facts and best months', html`${kv([['District', x.district_name], ['Division', x.division], ['Altitude', x.altitude_m ? num(x.altitude_m) + ' m (approx.)' : 'Not in the reference set yet'], ['Coordinates', `${x.lat}, ${x.lon} (approx.)`]])}
      ${x.best_months?.length ? html`<div class="monthwin" role="list" aria-label="Best months">${MONTH_NAMES.map((n, i) => html`<span role="listitem" class="${x.best_months.includes(i + 1) ? 'on' : ''}" aria-label="${n}: ${x.best_months.includes(i + 1) ? 'good time to visit' : 'not usually recommended'}">${n.slice(0, 3)}</span>`)}</div>` : html`<p class="muted">No specific best months in the curated set.</p>`}`)}`);
  },
  weather(p, d) {
    mount(p, html`${ph('Weather')}${weather(d.weather)}`);
  },
  roads(p, d, hl, x) {
    const adv = (d.roads?.advisories || []).slice().sort((a, b) => (ROAD_ORDER[a.status] ?? 3) - (ROAD_ORDER[b.status] ?? 3));
    const other = (d.advisories || []).filter((a) => a.kind !== 'road');
    const dir = `https://www.google.com/maps/dir/?api=1&destination=${x.lat},${x.lon}`;
    mount(p, html`${ph('Getting there')}
      <p class="row"><a class="btn sm dark" href="${dir}" target="_blank" rel="noopener noreferrer">Get directions <span aria-hidden="true">↗</span><span class="sr-only"> (Google Maps, opens in a new tab)</span></a><span class="small muted">Uses approximate coordinates; check the route before you set out.</span></p>
      <div id="trf"></div>
      ${d.roads?.live ? liveTraffic(d.roads.live) : ''}
      <h3 class="section">Road alerts</h3>
      ${adv.length ? html`<div class="section">${moreList(adv, (a) => advisoryRow(a), 5)}</div>` : html`<p class="flag green section">No road alerts for ${x.name} right now. Roads in the hills change fast, so ask locally.</p>`}
      ${other.length ? html`<h3 class="section">Other alerts</h3><div class="section">${moreList(other, (a) => advisoryRow(a), 3)}</div>` : ''}
      <h3 class="section">How to get there</h3>
      <ul class="bullets section">${(d.roads?.facts || x.route_facts || []).map((r) => html`<li>${r}</li>`)}</ul>`);
    if (d.roads?.traffic) p.querySelector('#trf').appendChild(trafficBlock(d.roads.traffic));
  },
  crowd(p, d, hl, x) {
    const cr = d.crowd;
    if (!cr) { mount(p, html`${ph('How busy')}<p class="muted">Not known right now.</p>`); return; }
    const days = cr.outlook || [];
    const quiet = days.length ? days.reduce((a, b) => (b.index < a.index ? b : a)) : null;
    const um = cr.usual_by_month || [];
    const top = um.slice().sort((a, b) => b.index - a.index).slice(0, 2).map((m) => monthName(m.month)).join(' and ');
    mount(p, html`${ph('How busy')}
      ${takeaway(stripHeadline(x.name, days) + (quiet ? `. Quietest day: ${fmtDate(quiet.date, { weekday: true, noYear: true })}.` : '.'))}
      ${dayStrip(days)}
      ${um.length ? details(`Each month: usually busiest in ${top}`, html`<div id="usual"></div>`) : ''}
      ${cr.foot_traffic?.best_window ? details(`Today: usually busiest at ${ft2(cr.foot_traffic).busy}, quietest at ${cr.foot_traffic.best_window.label}`, html`<div id="ftraffic"></div>`) : ''}`);
    if (um.length) p.querySelector('#usual').appendChild(barChart({
      title: `Usually busiest in ${top}`, sub: 'Taller bar = busier',
      x: um.map((m) => m.month), series: [{ label: 'How busy (0 quiet, 100 very busy)', values: um.map((m) => m.index) }], yMax: 100, height: 180,
      xFmt: (v, i, long) => monthName(v, !long), colorFn: (i, v) => BAND_FILL[bandOf(v)], minLabelGap: 26,
    }));
    if (cr.foot_traffic?.best_window) p.querySelector('#ftraffic').appendChild(footTraffic(cr.foot_traffic));
  },
  stays(p, d, hl, x) {
    const nb = d.nearby;
    const groups = [['stays', 'Stays'], ['guides', 'Guides'], ['transport', 'Transport'], ['other', 'Agents & others']].filter(([k]) => nb?.[k]);
    if (!groups.length) { mount(p, html`${ph('Stay & guides')}<p class="muted">No registered businesses near ${x.name} yet.</p>`); return; }
    let cur = groups.find(([k]) => nb[k].items.length)?.[0] || groups[0][0];
    const draw = (focus) => {
      mount(p, html`${ph('Stay & guides')}
        <div class="tabs"><div class="pillnav" role="tablist" aria-label="Business type">${groups.map(([k, l]) => html`<button type="button" role="tab" id="tab-${k}" aria-controls="panel-nb" aria-selected="${String(k === cur)}" tabindex="${k === cur ? '0' : '-1'}" data-k="${k}">${l} (${nb[k].total})</button>`)}</div></div>
        <div id="panel-nb" role="tabpanel" aria-labelledby="tab-${cur}">${nb[cur].items.length ? moreList(nb[cur].items, bizRow, 5) : html`<p class="muted">None listed.</p>`}
        <p class="section"><a href="${href('/directory', { destination: x.id })}">All registered businesses at ${x.name}</a></p></div>`);
      const tabs = $$('[role="tab"]', p);
      if (focus) $('#tab-' + cur, p).focus();
      tabs.forEach((b, i) => {
        b.addEventListener('click', () => { cur = b.dataset.k; draw(true); });
        b.addEventListener('keydown', (e) => {
          const dd = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
          if (!dd) return;
          e.preventDefault();
          cur = tabs[(i + dd + tabs.length) % tabs.length].dataset.k;
          draw(true);
        });
      });
    };
    draw(false);
  },
  nearby(p, d, hl, x) {
    load(p, () => nearbyPanel(p, x), { skel: 'list', n: 4 });
  },
  festivals(p, d, hl, x) {
    const ev = d.events || [];
    mount(p, html`${ph(`Festivals at ${x.name}`)}
      ${ev.length ? moreList(ev, (e) => html`<div class="item"><div class="main"><strong>${e.name.replace(/^SAMPLE:\s*/, '')}</strong><div class="sub">${e.start_date ? fmtDate(e.start_date) + (e.end_date && e.end_date !== e.start_date ? ' to ' + fmtDate(e.end_date) : '') : 'Usually ' + e.window}</div></div><div class="side">${impactPill(e.crowd_impact)}${e.sample ? samplePill() : ''}</div></div>`, 5)
        : html`<p class="muted">No festivals listed for this destination.</p>`}
      <p class="hint section">Usual timing only; lunar-calendar dates are announced each year. <a href="${href('/festivals', { destination: x.id, view: 'list' })}">Open the calendar</a></p>`);
  },
  help(p, d, hl) {
    mount(p, html`${ph('Help')}
      ${hl ? html`<ul class="plain helpl">${hl.items.map((h) => html`<li><strong>${h.name}</strong>${h.number ? html`<a href="tel:${h.number.split(' ')[0]}" class="mono">${h.number}</a>` : html`<span class="muted small">to be filled by the department</span>`}</li>`)}</ul><p class="hint section">${hl.note}</p>`
        : html`<p class="muted">Helplines unavailable right now. In an emergency dial 112.</p>`}
      <div class="btnrow section"><a class="btn ghost sm" href="#/grievance">File a complaint</a><a class="btn ghost sm" href="#/verify">Verify a business</a></div>`);
  },
};

const bestSet = (ft) => new Set(ft.best_window ? [ft.best_window.start_hour, ft.best_window.start_hour + 1] : []);
const hourLabel = (h) => `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'am' : 'pm'}`;
const hourShort = (h) => (h % 12 === 0 ? (h ? '12p' : '12a') : h < 12 ? h + 'a' : (h - 12) + 'p');

// BestTime: typical foot traffic by hour today at one well-known venue (not a headcount; shown beside our estimate).
function footTraffic(ft) {
  const best = bestSet(ft);
  return barChart({
    title: `Green bars: the best two hours (${ft.best_window.label})`,
    sub: `How busy ${ft.venue_name} usually is at each hour on a ${ft.day}. Busiest day of the week: ${ft.busiest_day}.`,
    x: [...Array(24).keys()], series: [{ label: 'How busy', values: ft.today_by_hour.map((v) => (v > 0 ? v : null)) }], yMax: 100, height: 170,
    xFmt: (h, i, long) => (long ? `${hourLabel(h)}–${hourLabel((h + 1) % 24)}` : hourShort(h)),
    colorFn: (i) => (best.has(i) ? '#2e8540' : PALETTE[0]), minLabelGap: 30,
    tipExtra: (i) => (ft.peak_hours.includes(i) ? 'Peak hour' : ft.quiet_hours.includes(i) ? 'Quiet hour' : ''),
    note: ft.credit,
  });
}

// Traffic model: expected traffic for the next 24 hours, in plain words (Smooth / Slow / Very slow).
const TWORD = { free: 'smooth', moderate: 'slow', heavy: 'very slow', severe: 'very slow' };
const ft2 = (ft) => ({ busy: ft.peak_hours?.length ? hourLabel(ft.peak_hours[0]) : 'midday' });
const TFILL = { free: BAND_FILL.low, moderate: BAND_FILL.moderate, heavy: BAND_FILL.high, severe: BAND_FILL.very_high };
function trafficBlock(tr) {
  const box = document.createElement('div');
  const hrs = tr.hours || [];
  mount(box, html`<h3 class="section">Traffic ${trafficPill(tr.now.band, 'Now')}</h3>
    ${takeaway(tr.best_time ? `Best time to drive: ${tr.best_time.label}.` : `Traffic now: ${TWORD[tr.now.band] || 'not known'}.`)}
    ${tr.landslide_risk ? html`<p class="small"><strong>Heavy rain is coming. Watch for landslides.</strong></p>` : ''}
    ${details('Traffic each hour, next 24 hours', html`<div id="tchart"></div>`)}`);
  box.querySelector('#tchart').appendChild(barChart({
    title: 'Traffic each hour',
    sub: 'Green = smooth, yellow = slow, orange or red = very slow.',
    x: hrs.map((h) => h.time), series: [{ label: 'Traffic (0 smooth, 100 very slow)', values: hrs.map((h) => h.index) }], yMax: 100, height: 170,
    xFmt: (v, i, long) => { const h = new Date(v).getHours(); return long ? `${fmtDate(v, { weekday: true, noYear: true })} ${hourLabel(h)}` : hourShort(h); },
    colorFn: (i) => TFILL[hrs[i].band], minLabelGap: 30,
    tipExtra: (i) => TWORD[hrs[i].band] || '',
  }));
  return box;
}

// Live incidents near the destination from a provider (alongside officer-posted advisories).
function liveTraffic(lv) {
  const row = (i) => html`<div class="item"><div class="main"><strong>${i.description}</strong>
      <div class="sub">${[i.road, i.from && i.to ? `${i.from} → ${i.to}` : i.from || i.to].filter(Boolean).join(' · ') || 'Road not named'}${i.delay_min ? ` · delay about ${i.delay_min} min` : ''}${i.last_update ? ` · reported ${relTime(i.last_update)}` : ''}</div></div>
    <div class="side">${roadPill(i.status)}</div></div>`;
  const f = lv.flow;
  const flowText = !f ? '' : f.road_closed ? ' Nearest main road: reported closed.' : ` Nearest main road: ${f.ratio >= 0.8 ? 'moving at about its usual speed' : f.ratio >= 0.5 ? 'slower than usual' : 'much slower than usual'} .`;
  return html`<h3 class="section">Traffic right now</h3>
    <p class="small">${lv.summary} ${lv.area}.${flowText}</p>
    ${lv.incidents.length ? html`<div class="section">${moreList(lv.incidents, row, 3)}</div>` : ''}
    <p class="hint tinycredit">${lv.credit} · ${relTime(lv.fetched_at)}</p>`;
}

function stripHeadline(name, days) {
  if (!days.length) return `${name}: not known yet`;
  const busy = (z) => z.index >= 65;
  const vh = days.some((z) => z.index >= 85);
  if (busy(days[0])) {
    let i = 0;
    while (i + 1 < days.length && busy(days[i + 1])) i++;
    return i === days.length - 1 ? `${name} stays ${vh ? 'very ' : ''}busy for the next 2 weeks` : `${name} is ${vh ? 'very ' : ''}busy until ${fmtDate(days[i].date, { noYear: true })}`;
  }
  const next = days.find(busy);
  return next ? `${name} gets busy from ${fmtDate(next.date, { weekday: true, noYear: true })}` : `${name} looks quiet for the next 2 weeks`;
}

function weather(w) {
  if (!w || !w.available) {
    return html`<div class="flag amber" role="status"><strong>Weather is not available right now.</strong> Please check again later.</div>`;
  }
  const th = w.thresholds || {};
  const c = w.current || {};
  return html`<div class="wx-now"><div class="temp">${c.temperature_c != null ? Math.round(c.temperature_c) + '°C' : '—'}</div>
      <div><strong>${c.summary || ''}</strong><div class="small muted">Wind ${num(c.wind_kmh)} km/h · updated ${relTime(w.fetched_at)}</div></div></div>
    ${(w.warnings || []).map((m) => html`<p class="flag red" role="alert"><strong>Warning:</strong> ${typeof m === 'string' ? m : m.message || ''}</p>`)}
    <h3 class="section">Next 7 days</h3>
    <div class="wx-days" role="list">${(w.daily || []).slice(0, 7).map((dd) => {
      const mm = dd.precip_mm ?? 0;
      const rain = mm >= (th.heavy_rain_mm ?? 50) || ((dd.precip_probability ?? 0) >= 80 && mm >= (th.rain_likely_mm ?? 20));
      const snow = (dd.snow_cm ?? 0) >= (th.snow_cm ?? 5);
      return html`<div class="wx-day ${rain || snow ? 'alert' : ''}" role="listitem"><b>${fmtDate(dd.date, { weekday: true, noYear: true })}</b><div class="small">${dd.summary}</div>
        <div class="mx">${Math.round(dd.max_c)}° <span class="muted">/ ${Math.round(dd.min_c)}°</span></div>
        <div class="small">Rain ${dd.precip_probability ?? '—'}% · ${num(mm, 1)} mm${dd.snow_cm ? html` · ${num(dd.snow_cm, 1)} cm snow` : ''}</div>
        ${rain || snow ? html`<div class="small"><strong>${snow ? 'Snow likely' : 'Heavy rain risk'}</strong></div>` : ''}</div>`;
    })}</div>
    <p class="hint tinycredit">Weather: Open-Meteo</p>`;
}
