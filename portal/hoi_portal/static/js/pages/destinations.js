// Destinations list + destination detail. Detail answers "should I go this week?" first (At a glance tiles), then
// shows ONE tab panel at a time (deep-linkable: #/destinations/<id>/<tab>).
import { html, mount, href, load, bandPill, $, $$, empty, monthName, MONTH_NAMES, fmtDate, relTime, roadPill, impactPill, lastUpdated, crumbs, landscape, num, raw, samplePill, collapseFilters, pager, moreList, infoNote } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';
import { barChart, BAND_FILL, bandLegend, bandOf } from '../charts.js';
import { bizRow, advisoryRow, kv } from './common.js';
import { nearbyPanel } from './plan.js';
import { photo, img, photoHead, thumbsNote } from '../photos.js';

const EXP_NAMES = { spiritual: 'Spiritual & Char Dham', adventure: 'Adventure & Treks', wildlife: 'Wildlife & Nature', wellness: 'Yoga & Wellness', leisure: 'Hill towns & Leisure', culture: 'Culture & Fairs' };

// ------------------------------------------------------------------ list
export async function list(ctx) {
  const el = ctx.el;
  const f = { district: ctx.query.district || '', division: ctx.query.division || '', tag: ctx.query.tag || '', q: ctx.query.q || '' };
  mount(el, html`<div class="pagehead"><div><h1>${t('destinations')}</h1>
    <p>Pick a place to see weather, road alerts and how crowded it will be.</p></div></div>
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
      $('#dcount', el).textContent = `${items.length} of ${d.items.length} destinations · crowd level is an estimate`;
      if (!items.length) { mount($('#dlist', el), empty('No destinations match', 'Try clearing a filter.')); return; }
      pager($('#dlist', el), items, (slice) => html`<div class="cards">${slice.map(card)}</div>`, 12);
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

function card(x) {
  const c = x.crowd_today;
  const p = photo(x.id);
  return html`<a class="dcard" href="${href('/destinations/' + x.id)}">
    <div class="art ${p ? 'photo' : ''}">${p ? img(p, { cls: 'cover', alt: '' }) : landscape(x.id)}<b>${x.name}</b><small>${x.district_name} · ${x.division}</small></div>
    <div class="body"><div class="meta">${c ? bandPill(c.band, c.index) : html`<span class="pill neutral">Crowd: no estimate</span>`}</div>
      <div class="meta">${x.tags.slice(0, 3).map((tg) => html`<span class="tag">${tg}</span>`)}</div></div></a>`;
}

// ------------------------------------------------------------------ detail
const TABS = [['overview', 'Overview'], ['weather', 'Weather'], ['roads', 'Getting there'], ['crowd', 'Crowd'], ['stays', 'Stay & guides'], ['nearby', 'Nearby'], ['festivals', 'Festivals'], ['help', 'Help']];
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
            : html`<span class="v">—</span><span class="s">Live weather unavailable</span>`}</a>
        <a class="gl ${cr?.today?.band === 'very_high' ? 'r' : cr?.today?.band === 'high' ? 'w' : ''}" href="#${base}/crowd"><span class="k">Crowd today <span class="tag">estimate</span></span>
          ${cr?.today ? html`<span class="v">${bandPill(cr.today.band, cr.today.index, '')}</span><span class="s">Quietest in 14 days: ${short(quiet.date)} (${quiet.index})</span>` : html`<span class="v">—</span><span class="s">No estimate</span>`}</a>
        <a class="gl ${worst?.status === 'closed' ? 'r' : worst?.status === 'caution' ? 'w' : ''}" href="#${base}/roads"><span class="k">Roads</span>
          ${worst ? html`<span class="v">${roadPill(worst.status)}</span><span class="s">${worst.segment || worst.title.replace(/^SAMPLE:\s*/, '')}${roadAdv.length > 1 ? ` · +${roadAdv.length - 1} more` : ''}</span>`
            : html`<span class="v"><span class="pill neutral noicon">No alerts posted</span></span><span class="s">Check locally before setting out</span>`}</a>
        <a class="gl" href="#${base}/overview"><span class="k">Best months</span>
          <span class="v">${x.best_months?.length ? monthRanges(x.best_months) : 'Any time'}</span><span class="s">${x.best_months?.length ? (goodNow ? `✓ ${monthName(nowM)} is a good time` : `${monthName(nowM)} is outside the usual season`) : 'See seasonal notes'}</span></a>
      </section>
      <nav class="dtabs" aria-label="${x.name} sections"><div class="pillnav">${TABS.map(([k, l]) => html`<a href="#${base}/${k}" ${k === tab ? html`aria-current="page"` : ''} id="dt-${k}">${l}</a>`)}</div></nav>
      <div class="dlayout"><section class="card panel" id="panel" aria-labelledby="ph" tabindex="-1"></section>
        <aside class="card tight sos" aria-label="Emergency numbers"><h2 class="h3">Emergency numbers</h2>${sos(hl)}<a class="small" href="#${base}/help">All helplines</a></aside></div>
      ${lastUpdated(d.last_updated, 'Businesses and occupancy are synthetic sample data')}`);
    const panel = $('#panel', el);
    PANELS[tab](panel, d, hl, x);
    if (tabSwitch) {
      document.title = `${x.name}: ${TABS.find((z) => z[0] === tab)[1]} · UTHP (concept)`;
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
    mount(p, html`${ph('Overview', html` <span class="pill warn">Verify</span>${infoNote(x.facts_note)}`)}
      ${x.themes?.length ? html`<div class="chips">${x.themes.map((th) => html`<a class="chipbtn" href="${href('/experiences/' + th)}">${EXP_NAMES[th] || th}</a>`)}</div>` : ''}
      <h3 class="section">At a glance</h3>
      ${kv([['District', x.district_name], ['Division', x.division], ['Altitude', x.altitude_m ? num(x.altitude_m) + ' m (approx.)' : 'Not in the reference set yet'], ['Coordinates', `${x.lat}, ${x.lon} (approx.)`]])}
      <h3 class="section">Best months</h3>
      ${x.best_months?.length ? html`<div class="monthwin" role="list" aria-label="Best months">${MONTH_NAMES.map((n, i) => html`<span role="listitem" class="${x.best_months.includes(i + 1) ? 'on' : ''}" aria-label="${n}: ${x.best_months.includes(i + 1) ? 'good time to visit' : 'not usually recommended'}">${n.slice(0, 3)}</span>`)}</div>` : html`<p class="muted">No specific best months in the curated set.</p>`}
      ${x.season_notes?.length ? html`<h3 class="section">What to know</h3><ul class="bullets section">${x.season_notes.map((s) => html`<li>${s}</li>`)}</ul>` : ''}`);
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
      <h3 class="section">Live road alerts</h3>
      ${adv.length ? html`<div class="section">${moreList(adv, (a) => advisoryRow(a), 5)}</div>` : html`<p class="flag green section">No live road alerts posted for ${x.name}. Conditions change quickly in the hills; check locally.</p>`}
      ${other.length ? html`<h3 class="section">Other alerts</h3><div class="section">${moreList(other, (a) => advisoryRow(a), 3)}</div>` : ''}
      ${[...adv, ...other].some((a) => a.sample) ? html`<p class="hint">Alerts marked Sample are illustrative, not real road status.</p>` : ''}
      <h3 class="section">Route facts <span class="pill warn">Verify</span>${infoNote(d.roads?.facts_note || x.facts_note)}</h3>
      <ul class="bullets section">${(d.roads?.facts || x.route_facts || []).map((r) => html`<li>${r}</li>`)}</ul>`);
  },
  crowd(p, d, hl, x) {
    const cr = d.crowd;
    if (!cr) { mount(p, html`${ph('Crowd')}<p class="muted">No crowd estimate available.</p>`); return; }
    const days = cr.outlook || [];
    mount(p, html`${ph('Crowd', html` <span class="pill syn">estimate</span>${infoNote(`${cr.note} Method: ${cr.method}.`)}`)}<div id="strip"></div><div id="usual" class="section"></div>`);
    p.querySelector('#strip').appendChild(barChart({
      title: stripHeadline(x.name, days), sub: 'Crowd index per day (0-100). Dashed line: very-high threshold (85).',
      x: days.map((z) => z.date), series: [{ label: 'Crowd index', values: days.map((z) => z.index) }], yMax: 100, height: 220,
      xFmt: (v, i, long) => (long ? fmtDate(v, { weekday: true }) : String(new Date(v + 'T00:00').getDate())),
      xSub: (i) => new Date(days[i].date + 'T00:00').toLocaleDateString('en-IN', { weekday: 'short' }).slice(0, 2),
      colorFn: (i, v) => BAND_FILL[bandOf(v)], legendItems: bandLegend(), valueLabels: true, minLabelGap: 22,
      refLines: [{ y: 85, label: 'very high (85)' }],
      tipExtra: (i) => [days[i].events?.length ? 'Events: ' + days[i].events.join(', ') : '', days[i].weekend ? 'Weekend' : '', 'Basis: ' + days[i].basis].filter(Boolean).join(' · '),
    }));
    const um = cr.usual_by_month || [];
    const top = um.slice().sort((a, b) => b.index - a.index).slice(0, 2).map((m) => monthName(m.month)).join(' and ');
    p.querySelector('#usual').appendChild(barChart({
      title: `Usually busiest in ${top}`, sub: 'Typical crowd index by month (estimate)',
      x: um.map((m) => m.month), series: [{ label: 'Usual crowd index', values: um.map((m) => m.index) }], yMax: 100, height: 200,
      xFmt: (v, i, long) => monthName(v, !long), colorFn: (i, v) => BAND_FILL[bandOf(v)], legendItems: bandLegend(), valueLabels: true, minLabelGap: 26,
    }));
  },
  stays(p, d, hl, x) {
    const nb = d.nearby;
    const groups = [['stays', 'Stays'], ['guides', 'Guides'], ['transport', 'Transport'], ['other', 'Agents & others']].filter(([k]) => nb?.[k]);
    if (!groups.length) { mount(p, html`${ph('Stay & guides')}<p class="muted">No registered businesses near ${x.name} yet.</p>`); return; }
    let cur = groups.find(([k]) => nb[k].items.length)?.[0] || groups[0][0];
    const draw = (focus) => {
      mount(p, html`${ph('Stay & guides', html` <span class="pill syn">synthetic names</span>`)}
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

function stripHeadline(name, days) {
  if (!days.length) return `${name}: no outlook`;
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
    return html`<div class="flag amber" role="status"><strong>Live weather unavailable.</strong> ${w?.reason || 'The forecast service did not respond.'} Check local sources before travel.</div>`;
  }
  const th = w.thresholds || {};
  const c = w.current || {};
  return html`<div class="wx-now"><div class="temp">${c.temperature_c != null ? Math.round(c.temperature_c) + '°C' : '—'}</div>
      <div><strong>${c.summary || ''}</strong><div class="small muted">Wind ${num(c.wind_kmh)} km/h · updated ${relTime(w.fetched_at)}${w.stale ? ' (stale cache)' : ''}</div></div></div>
    ${(w.warnings || []).map((m) => html`<p class="flag red" role="alert"><strong>Warning:</strong> ${typeof m === 'string' ? m : m.message || ''}</p>`)}
    <h3 class="section">Next 7 days</h3>
    <div class="wx-days" role="list">${(w.daily || []).slice(0, 7).map((dd) => {
      const mm = dd.precip_mm ?? 0;
      const rain = mm >= (th.heavy_rain_mm ?? 50) || ((dd.precip_probability ?? 0) >= 80 && mm >= (th.rain_likely_mm ?? 20));
      const snow = (dd.snow_cm ?? 0) >= (th.snow_cm ?? 5);
      return html`<div class="wx-day ${rain || snow ? 'alert' : ''}" role="listitem"><b>${fmtDate(dd.date, { weekday: true, noYear: true })}</b><div class="small">${dd.summary}</div>
        <div class="mx">${Math.round(dd.max_c)}° <span class="muted">/ ${Math.round(dd.min_c)}°</span></div>
        <div class="small">${dd.precip_probability ?? '—'}% · ${num(mm, 1)} mm${dd.snow_cm ? html` · ${num(dd.snow_cm, 1)} cm snow` : ''}</div>
        ${rain || snow ? html`<div class="small"><strong>${snow ? 'Snow likely' : 'Heavy rain risk'}</strong></div>` : ''}</div>`;
    })}</div>
    <p class="hint">Rain chance · rainfall. ${w.source}.${infoNote(`Highlighted days meet the heavy-rain (${th.heavy_rain_mm ?? 50} mm, or ${th.rain_likely_mm ?? 20} mm at 80%+ chance) or snow (${th.snow_cm ?? 5} cm) thresholds. ${th.note || ''}`, 'About the warning thresholds')}</p>`;
}
