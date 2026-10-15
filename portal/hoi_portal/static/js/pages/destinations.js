// Destinations list + destination detail. Detail answers "should I go this week?" first (At a glance tiles), then
// shows ONE tab panel at a time (deep-linkable: #/destinations/<id>/<tab>).
import { html, mount, href, load, bandPill, trafficPill, $, $$, empty, monthName, MONTH_NAMES, fmtDate, relTime, roadPill, impactPill, lastUpdated, crumbs, num, raw, samplePill, pager, moreList, infoNote, dayStrip, crowdAlertText, CONF_WORD, takeaway, details, icon, BANDS, monthChips, debounce, announce, errorBox } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';
import { barChart, BAND_FILL, bandOf, miniBars, PALETTE } from '../charts.js';
import { bizRow, advisoryRow, kv } from './common.js';
import { nearbyPanel } from './plan.js';
import { photoHead, thumbsNote, photo, img } from '../photos.js';
import { localCards } from '../cards.js';

const EXP_NAMES = { spiritual: 'Spiritual & Char Dham', adventure: 'Adventure & Treks', wildlife: 'Wildlife & Nature', wellness: 'Yoga & Wellness', leisure: 'Hill towns & Leisure', culture: 'Culture & Fairs' };

// ------------------------------------------------------------------ list
// Results layout: filter panel on the left (a slide-up sheet on phones), a 12-month strip with the usual busy level,
// then one row card per place (photo; name, district, weather, how busy, road; tags).
const CHIPS = [
  ['quiet', 'quiet', 'Quiet now'],
  ['chardham', 'temple', 'Char Dham'],
  ['treks', 'trek', 'Treks'],
  ['lakes', 'lake', 'Lakes'],
  ['family', 'people', 'Family'],
];
const BAND_ORDER = ['low', 'moderate', 'high', 'very_high'];
const ROAD_WORD = { closed: 'Closed', caution: 'Slow, take care', open: 'Open' };
const csv = (v) => (v ? String(v).split(',').filter(Boolean) : []);

export async function list(ctx) {
  const el = ctx.el;
  const nowM = new Date().getMonth() + 1;
  const f = {
    q: ctx.query.q || '', district: ctx.query.district || '', division: ctx.query.division || '', tag: ctx.query.tag || '',
    chip: csv(ctx.query.chip), month: Number(ctx.query.month) || 0, busy: csv(ctx.query.busy),
  };
  let d = null;
  let roads = new Map();
  const bandAt = (x) => (f.month ? x.usual_busy?.[f.month - 1] : x.crowd_today?.band) || null;
  const chipOk = (x, c) => {
    if (c === 'quiet') return bandAt(x) === 'low';
    if (c === 'chardham') return x.tags.includes('Char Dham');
    if (c === 'treks') return x.tags.includes('trek');
    if (c === 'lakes') return x.tags.includes('lake');
    if (c === 'family') return (x.themes || []).some((t) => t === 'leisure' || t === 'wildlife') && !x.tags.includes('trek');
    return true;
  };
  // Everything except the month and how-busy filters (the month strip summarises this set).
  const baseOk = (x) => (!f.district || x.district === f.district) && (!f.division || x.division === f.division) && (!f.tag || x.tags.includes(f.tag))
    && (!f.q || x.name.toLowerCase().includes(f.q.toLowerCase())) && f.chip.filter((c) => c !== 'quiet').every((c) => chipOk(x, c));
  const fullOk = (x) => baseOk(x) && (!f.chip.includes('quiet') || chipOk(x, 'quiet'))
    && (!f.month || !x.best_months?.length || x.best_months.includes(f.month)) && (!f.busy.length || f.busy.includes(bandAt(x)));
  const active = () => [f.district, f.division, f.tag, f.month, ...f.chip, ...f.busy].filter(Boolean).length;

  mount(el, html`<div class="pagehead"><div><h1>${t('destinations')}</h1>
    <p>Pick a place to see the weather, roads, how busy it will be, registered stays and local experiences.</p></div></div>
    <div class="dres">
      <div class="dres-shade" id="dshade" hidden></div>
      <aside class="dres-side" id="fpanel" aria-labelledby="fp-h">
        <div class="fp-head"><h2 id="fp-h">Filter results</h2><button type="button" class="btn sm ghost fp-close" id="fp-close">Close</button></div>
        <form id="dfilters" class="fp" aria-label="Filter destinations">
          <div class="fp-chips" role="group" aria-label="Quick filters">${CHIPS.map(([k, ic, l]) => html`<button type="button" class="fp-chip" data-chip="${k}" aria-pressed="${String(f.chip.includes(k))}">${icon(ic)}<span>${l}</span></button>`)}</div>
          <details class="fp-g" ${f.district || f.division ? raw('open') : ''}><summary>District ${icon('chevron')}</summary>
            <div class="fp-in"><div class="fp-seg" role="group" aria-label="Division">${[['', 'All'], ['Garhwal', 'Garhwal'], ['Kumaon', 'Kumaon']].map(([v, l]) => html`<label><input type="radio" name="division" value="${v}" ${f.division === v ? raw('checked') : ''}><span>${l}</span></label>`)}</div>
              <label class="lbl" for="f-district">District</label><select class="field" id="f-district" name="district"><option value="">All districts</option></select></div></details>
          <details class="fp-g" ${f.month ? raw('open') : ''}><summary>Best month ${icon('chevron')}</summary>
            <div class="fp-in"><label class="lbl" for="f-month">Going in</label><select class="field" id="f-month" name="month"><option value="">Any month</option>${MONTH_NAMES.map((n, i) => html`<option value="${i + 1}" ${f.month === i + 1 ? raw('selected') : ''}>${n}</option>`)}</select></div></details>
          <details class="fp-g" ${f.busy.length ? raw('open') : ''}><summary>How busy ${icon('chevron')}</summary>
            <div class="fp-in fp-checks">${BAND_ORDER.map((b) => html`<label class="check"><input type="checkbox" name="busy" value="${b}" ${f.busy.includes(b) ? raw('checked') : ''}><span class="hv-dot b-${b}" aria-hidden="true"></span>${BANDS[b].label}</label>`)}
              <p class="small muted">Today, or the usual level in the month you pick. Estimate from sample data.</p></div></details>
          <details class="fp-g" ${f.tag ? raw('open') : ''}><summary>Type of place ${icon('chevron')}</summary>
            <div class="fp-in"><label class="lbl" for="f-tag">Type</label><select class="field" id="f-tag" name="tag"><option value="">All types</option></select></div></details>
          <div class="fp-foot"><button type="button" class="btn ghost" id="fp-clear">Clear all</button><button type="button" class="btn primary fp-show" id="fp-show">Show places</button></div>
        </form>
      </aside>
      <div class="dres-main">
        <div class="dres-bar">
          <label class="dres-q"><span class="sr-only">Search by name</span>${icon('search')}<input id="f-q" type="search" placeholder="Search by name" value="${f.q}" maxlength="60" autocomplete="off"></label>
          <button type="button" class="btn ghost dres-fbtn" id="fp-open" aria-controls="fpanel" aria-expanded="false">${icon('filter')}<span id="fp-n">Filters</span></button>
        </div>
        <div class="mstrip-card">
          <div class="mstrip" id="mstrip" role="group" aria-label="Pick a month">${MONTH_NAMES.map((n, i) => html`<button type="button" data-m="${i + 1}" class="${i + 1 === nowM ? 'now' : ''}" aria-pressed="${String(f.month === i + 1)}"><b>${n.slice(0, 3)}</b><span class="mb">&nbsp;</span></button>`)}</div>
          <p class="mstrip-note small muted">Usual busy level for the places shown. Estimate from sample data.${raw('&nbsp;')}<span class="mnow">Ring = this month.</span></p>
        </div>
        <p class="dres-count" id="dcount" aria-live="polite">&nbsp;</p>
        <div id="dlist"><div class="rclist" aria-hidden="true">${[0, 1, 2, 3].map(() => html`<div class="rc sk"></div>`)}</div></div>
      </div>
    </div>`);

  // Phones: the strip scrolls; start with this month in view (before any data, so nothing shifts later).
  const ms = $('#mstrip', el);
  const nowB = $('#mstrip .now', el);
  if (nowB && ms.scrollWidth > ms.clientWidth) ms.scrollLeft = nowB.getBoundingClientRect().left - ms.getBoundingClientRect().left - 8;
  const form = $('#dfilters', el);
  const side = $('#fpanel', el);
  const shade = $('#dshade', el);
  const openBtn = $('#fp-open', el);
  const sheet = (open) => {
    side.classList.toggle('open', open);
    shade.hidden = !open;
    openBtn.setAttribute('aria-expanded', String(open));
    document.documentElement.classList.toggle('sheet-open', open);
    if (open) $('#fp-close', el).focus(); else openBtn.focus();
  };
  openBtn.addEventListener('click', () => sheet(true));
  $('#fp-close', el).addEventListener('click', () => sheet(false));
  $('#fp-show', el).addEventListener('click', () => sheet(false));
  shade.addEventListener('click', () => sheet(false));
  const onKey = (e) => { if (e.key === 'Escape' && side.classList.contains('open')) sheet(false); };
  document.addEventListener('keydown', onKey);

  const strip = () => {
    if (!d) return;
    const base = d.items.filter(baseOk);
    $$('#mstrip button', el).forEach((b) => {
      const m = Number(b.dataset.m);
      const bands = base.map((x) => x.usual_busy?.[m - 1]).filter(Boolean).map((x) => BAND_ORDER.indexOf(x)).sort((a, c) => a - c);
      const mid = bands.length ? BAND_ORDER[bands[Math.floor((bands.length - 1) / 2)]] : null;
      const word = mid ? BANDS[mid].label : '–';
      b.querySelector('.mb').textContent = word;
      b.querySelector('.mb').className = 'mb ' + (mid ? 'b-' + mid : '');
      b.setAttribute('aria-pressed', String(f.month === m));
      b.setAttribute('aria-label', `${MONTH_NAMES[m - 1]}${m === nowM ? ' (this month)' : ''}: usually ${word.toLowerCase()}`);
    });
  };
  const card = (x, i) => {
    const p = photo(x.id);
    const w = x.weather_now;
    const band = bandAt(x);
    const road = roads.get(x.id);
    const best = x.best_months?.length ? monthChips(x.best_months, 2).join(', ') : 'All year';
    const url = href('/destinations/' + x.id);
    return html`<article class="rc">
      <a class="rc-ph" href="${url}" tabindex="-1" aria-hidden="true">${p ? img(p, { alt: '', eager: i < 2 }) : ''}</a>
      <div class="rc-body">
        <h2 class="rc-t"><a href="${url}">${x.name}</a></h2>
        <p class="rc-d">${icon('pin')}${x.district_name} · ${x.division}</p>
        ${x.why_go ? html`<p class="rc-why">${x.why_go}</p>` : ''}
        <dl class="rc-facts">
          <div><dt>${icon('weather')}Weather</dt><dd>${w?.available && w.temperature_c != null ? `${Math.round(w.temperature_c)}°C${w.summary ? ' · ' + w.summary : ''}` : html`<span class="muted">See forecast</span>`}</dd></div>
          <div><dt>${icon('people')}${f.month ? 'Busy in ' + MONTH_NAMES[f.month - 1].slice(0, 3) : 'How busy'}</dt><dd>${band ? html`<span class="hv-dot b-${band}" aria-hidden="true"></span>${BANDS[band].label}` : 'No estimate'}</dd></div>
          <div><dt>${icon('road')}Road</dt><dd>${road ? html`<span class="rd rd-${road.status}">${ROAD_WORD[road.status] || road.status}</span>${road.segment ? html`<span class="muted"> · ${road.segment}</span>` : ''}` : html`<span class="muted">No alerts posted</span>`}</dd></div>
          <div><dt>${icon('calendar')}Best</dt><dd>${best}</dd></div>
        </dl>
      </div>
      <div class="rc-side">
        <ul class="rc-tags">${x.tags.slice(0, 3).map((tg) => html`<li>${tg}</li>`)}</ul>
        <span class="rc-go" aria-hidden="true">View ${icon('arrow')}</span>
      </div></article>`;
  };
  const draw = () => {
    if (!d) return;
    const items = d.items.filter(fullOk);
    if (f.chip.includes('quiet') || f.busy.length || f.month) items.sort((a, b) => BAND_ORDER.indexOf(bandAt(a)) - BAND_ORDER.indexOf(bandAt(b)));
    const n = active();
    $('#fp-n', el).textContent = n ? `Filters (${n})` : 'Filters';
    $('#fp-show', el).textContent = `Show ${items.length} place${items.length === 1 ? '' : 's'}`;
    $('#dcount', el).textContent = `${items.length} place${items.length === 1 ? '' : 's'}${f.month ? ' good in ' + MONTH_NAMES[f.month - 1] : ''}`;
    strip();
    $$('[data-chip]', el).forEach((b) => b.setAttribute('aria-pressed', String(f.chip.includes(b.dataset.chip))));
    if (!items.length) { mount($('#dlist', el), empty('No destinations match', 'Try clearing a filter.', html`<button type="button" class="btn ghost" data-clear>Clear all filters</button>`)); return; }
    pager($('#dlist', el), items, (slice) => html`<div class="rclist">${slice.map(card)}</div>`, 12);
  };
  const sync = () => {
    const fd = new FormData(form);
    f.district = (fd.get('district') || '').toString();
    f.division = (fd.get('division') || '').toString();
    f.tag = (fd.get('tag') || '').toString();
    f.month = Number(fd.get('month')) || 0;
    f.busy = fd.getAll('busy').map(String);
    setQuery({ q: f.q, district: f.district, division: f.division, tag: f.tag, chip: f.chip.join(','), month: f.month || '', busy: f.busy.join(',') });
    draw();
  };
  const clearAll = () => {
    Object.assign(f, { q: '', district: '', division: '', tag: '', chip: [], month: 0, busy: [] });
    form.reset();
    $('#f-q', el).value = '';
    $$('input[name="division"]', form).forEach((r) => { r.checked = r.value === ''; });
    $('#f-month', el).value = '';
    sync();
    announce('Filters cleared');
  };
  form.addEventListener('change', sync);
  form.addEventListener('submit', (e) => { e.preventDefault(); sync(); });
  $('#f-q', el).addEventListener('input', debounce(() => { f.q = $('#f-q', el).value.trim(); sync(); }, 200));
  $$('[data-chip]', el).forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.chip;
    f.chip = f.chip.includes(k) ? f.chip.filter((c) => c !== k) : [...f.chip, k];
    sync();
  }));
  $('#mstrip', el).addEventListener('click', (e) => {
    const b = e.target.closest('button[data-m]');
    if (!b) return;
    const m = Number(b.dataset.m);
    $('#f-month', el).value = f.month === m ? '' : String(m);
    sync();
    announce(f.month ? `Showing places good in ${MONTH_NAMES[f.month - 1]}` : 'Any month');
  });
  $('#fp-clear', el).addEventListener('click', clearAll);
  el.addEventListener('click', (e) => { if (e.target.closest('[data-clear]')) clearAll(); });

  try {
    const [m, dd, adv] = await Promise.all([meta(), api('/destinations'), api('/advisories').catch(() => ({ items: [] }))]);
    d = dd;
    const order = { closed: 0, caution: 1, open: 2 };
    roads = new Map();
    for (const a of adv.items) {
      if (a.kind !== 'road' || !a.destination_id) continue;
      const cur = roads.get(a.destination_id);
      if (!cur || (order[a.status] ?? 3) < (order[cur.status] ?? 3)) roads.set(a.destination_id, a);
    }
    mount($('#f-district', el), html`<option value="">All districts</option>${m.districts.map((x) => html`<option value="${x.id}" ${f.district === x.id ? raw('selected') : ''}>${x.name}</option>`)}`);
    mount($('#f-tag', el), html`<option value="">All types</option>${d.tags.map((x) => html`<option value="${x}" ${f.tag === x ? raw('selected') : ''}>${x}</option>`)}`);
    draw();
  } catch (e) {
    mount($('#dlist', el), errorBox(e, { retry: false }));
  }
  return () => { document.removeEventListener('keydown', onKey); document.documentElement.classList.remove('sheet-open'); };
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
    const openDays = outlook.filter((z) => !z.closed);
    const quiet = openDays.length ? openDays.reduce((a, b) => (b.index < a.index ? b : a)) : null;
    const nowM = new Date().getMonth() + 1;
    const goodNow = x.best_months?.includes(nowM);
    const wWarn = (w?.warnings || [])[0];
    const base = '/destinations/' + x.id;
    mount(el, html`${crumbs([['Home', '#/'], ['Destinations', '#/destinations'], [x.name]])}
      ${photoHead(x.id)}
      <div class="pagehead tightb"><div><p class="eyebrow">${x.district_name} · ${x.division}</p><h1>${x.name}</h1></div></div>
      <section aria-label="At a glance" class="glance">
        <a class="gl ${wWarn ? 'r' : ''}" href="#${base}/weather"><span class="k">Weather now</span>
          ${w?.available ? html`<span class="v">${Math.round(w.current?.temperature_c)}°C <small>${w.current?.summary || ''}</small></span><span class="s">${wWarn ? html`<strong>⚠ ${wWarn.kind === 'snow' ? 'Snow' : 'Heavy rain'} ${short(wWarn.date)}</strong>` : 'No rain or snow warnings, 7 days'}</span>`
            : html`<span class="v">—</span><span class="s">Weather not available</span>`}</a>
        <a class="gl ${cr?.today?.band === 'very_high' ? 'r' : cr?.today?.band === 'high' ? 'w' : ''}" href="#${base}/crowd"><span class="k">How busy today</span>
          ${cr?.today ? html`<span class="v">${cr.today.closed ? html`<span class="pill neutral noicon">Closed for the season</span>` : bandPill(cr.today.band, cr.today.index, '')}</span><span class="s">${cr.alerts?.length ? html`<strong>${crowdAlertText(cr.alerts[0])}</strong>` : quiet ? `Quietest day soon: ${short(quiet.date)}` : 'Open again next season'}</span>` : html`<span class="v">—</span><span class="s">Not known</span>`}
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
        <aside class="dside">${planCard(x, w, cr, goodNow, nowM, base)}
          <section class="card tight sos" aria-labelledby="sos-h"><h2 class="h3" id="sos-h">Emergency numbers</h2>${sos(hl)}<a class="small" href="#${base}/help">All helplines</a></section></aside></div>
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
/** Right-column card: best months, how to reach, today's weather and crowd, and the next step. */
function planCard(x, w, cr, goodNow, nowM, base) {
  const reach = (x.route_facts || [])[0];
  return html`<section class="card tight plancard" aria-labelledby="pv-h"><h2 class="h3" id="pv-h">Plan your visit</h2>
    <dl class="pv">
      <div><dt>Best months</dt><dd><strong>${x.best_months?.length ? monthRanges(x.best_months) : 'Any time'}</strong>${x.best_months?.length ? html`<span class="small muted">${goodNow ? `${monthName(nowM)} is a good time` : `${monthName(nowM)} is outside the usual season`}</span>` : ''}</dd></div>
      ${reach ? html`<div><dt>How to reach</dt><dd><span>${reach}</span><a class="small" href="#${base}/roads">Route and road alerts</a></dd></div>` : ''}
      <div><dt>Today</dt><dd class="pv-today">${w?.available ? html`<span>${Math.round(w.current?.temperature_c)}°C ${w.current?.summary || ''}</span>` : html`<span class="muted">Weather not known</span>`}
        ${cr?.today ? bandPill(cr.today.band, null, '') : ''}</dd></div>
    </dl>
    <a class="btn primary block" href="${href('/plan', { theme: x.themes?.[0] || '' })}">Make a trip plan</a></section>`;
}
const BUSY_WORD = { low: 'Quiet', moderate: 'Normal', high: 'Busy', very_high: 'Busy' };
const BUSY_CLS = { low: 'q', moderate: 'n', high: 'b', very_high: 'b' };
/** 12-month strip: colour plus a word in every cell (never colour alone). */
function busyStrip(um) {
  if (!um?.length) return '';
  const nowM = new Date().getMonth() + 1;
  return html`<ol class="busystrip" aria-label="How busy each month usually is">${um.map((m) => html`<li class="${BUSY_CLS[m.band] || 'n'} ${m.month === nowM ? 'now' : ''}"><b>${monthName(m.month, true)}</b><span>${BUSY_WORD[m.band] || 'Normal'}</span></li>`)}</ol>`;
}
const ph = (title, extra = '') => html`<h2 id="ph">${title}${extra}</h2>`;

const PANELS = {
  overview(p, d, hl, x) {
    const busy = (d.events || []).filter((e) => !e.sample && e.crowd_impact !== 'low').slice(0, 4);
    mount(p, html`${ph('Overview')}
      ${x.themes?.length ? html`<div class="chips">${x.themes.map((th) => html`<a class="chipbtn" href="${href('/experiences/' + th)}">${EXP_NAMES[th] || th}</a>`)}</div>` : ''}
      ${x.why_go ? html`<p class="takeaway section">${x.why_go}</p>` : ''}
      <h3 class="section">Good to know</h3>
      <ul class="bullets section">${[...(x.season_notes || []), ...((x.route_facts || []).slice(1, 2))].map((s) => html`<li>${s}</li>`)}</ul>
      ${busy.length || d.crowd?.usual_by_month?.length ? html`<div class="busyline section"><p><strong>Busy seasons:</strong> ${busy.length ? busy.map((e) => `${e.name.replace(/^SAMPLE:\s*/, '')} (${e.window})`).join(', ') : 'none listed'}.</p>${busyStrip(d.crowd?.usual_by_month)}</div>` : ''}
      ${d.local_experiences?.total ? html`<div class="sechead section"><h3>Things to do with local hosts</h3><a href="${href('/experiences', { destination: x.id })}">All ${d.local_experiences.total}</a></div><div class="mcgrid g3c">${d.local_experiences.items.slice(0, 3).map(localCards())}</div>` : ''}
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
    const open = days.filter((z) => !z.closed);
    const quiet = open.length ? open.reduce((a, b) => (b.index < a.index ? b : a)) : null;
    const um = cr.usual_by_month || [];
    const top = um.slice().sort((a, b) => b.index - a.index).slice(0, 2).map((m) => monthName(m.month)).join(' and ');
    const t = cr.today || {};
    const al = cr.alerts || [];
    mount(p, html`${ph('How busy')}
      ${takeaway(stripHeadline(x.name, days) + (quiet ? `. Quietest day: ${fmtDate(quiet.date, { weekday: true, noYear: true })}.` : '.'))}
      ${al.length ? html`<p class="flag amber" role="status"><strong>${crowdAlertText(al[0])}</strong>${al.length > 1 ? ` · ${al.length - 1} more very busy day${al.length > 2 ? 's' : ''} in the next 2 weeks` : ''}</p>` : ''}
      <p class="crowdconf small muted"><span>${CONF_WORD[t.confidence] || CONF_WORD.low}</span><span>${cr.source === 'real_model' ? 'Based on official pilgrim counts (real data)' : 'Estimate from sample data'}</span>${t.pilgrims != null && !t.closed ? html`<span>About ${num(t.pilgrims)} pilgrims today (likely ${num(t.range[0])}–${num(t.range[1])})</span>` : ''}</p>
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
  if (days.every((z) => z.closed)) return `${name} is closed for the season`;
  const shut = days.findIndex((z) => z.closed);
  if (shut > 0) return `${openHeadline(name, days.slice(0, shut))}; closed for the season from ${fmtDate(days[shut].date, { weekday: true, noYear: true })}`;
  return openHeadline(name, days.filter((z) => !z.closed));
}

function openHeadline(name, days) {
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
