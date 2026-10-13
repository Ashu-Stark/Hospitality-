// Experiences (themes) and the Plan section: sample itineraries (stop-by-stop live status + best start), circuits,
// schematic dot map, how to reach, official services. Built only from curated destinations; no invented facts.
import { html, mount, href, load, $, $$, raw, empty, bandPill, roadPill, fmtDate, crumbs, lastUpdated, monthName, moreList, infoNote, collapseFilters, announce, num } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { BAND_FILL, bandLegend } from '../charts.js';
import { EXP_ART, paintTones } from '../art.js';
import { photo, img, photoHead, thumbsNote } from '../photos.js';

const short = (iso) => fmtDate(iso, { weekday: true, noYear: true });
const ext = (url, label) => html`<a class="btn sm dark" href="${url}" target="_blank" rel="noopener noreferrer">${label} <span aria-hidden="true">↗</span><span class="sr-only"> (official site, opens in a new tab)</span></a>`;
const wxText = (w) => (!w ? 'Weather not loaded yet' : !w.available ? 'Weather unavailable' : `${Math.round(w.temperature_c)}°C ${w.summary || ''}`);

// ------------------------------------------------------------------ experiences
export function expTile(e, cls = 'exptile') {
  const p = cls === 'exptile big' ? photo('exp-' + e.id) : null;
  return html`<a class="${cls}${p ? ' hasphoto' : ''}" data-tone="${e.id}" href="${href('/experiences/' + e.id)}">${p ? img(p, { cls: 'cover', alt: '' }) : html`<span class="art">${raw(EXP_ART[e.icon] || '')}</span>`}<span class="nm">${e.name}</span>${e.short && cls === 'exptile big' ? html`<span class="sh">${e.short}</span>` : ''}</a>`;
}

export async function experiences(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><h1>Experiences</h1><p>Start from what you want to do; each experience lists places with today's crowd estimate.</p></div></div><div id="ex"></div>`);
  await load($('#ex', el), async () => {
    const r = await api('/experiences');
    mount($('#ex', el), html`<div class="expgrid">${r.items.map((e) => html`${expTile(e, 'exptile big')}`)}</div>${thumbsNote()}`);
    $$('.exptile', el).forEach((a, i) => { const c = r.items[i].destination_count; a.insertAdjacentHTML('beforeend', `<span class="ct">${c} place${c === 1 ? '' : 's'}</span>`); });
    paintTones(el);
  }, { skel: 'cards', n: 6 });
}

export async function experience(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Experiences', '#/experiences'], ['…']])}<h1 class="sr-only">Experience</h1><div id="e1"></div>`);
  await load($('#e1', el), async () => {
    const e = await api('/experiences/' + encodeURIComponent(ctx.params.id));
    mount(el, html`${crumbs([['Home', '#/'], ['Experiences', '#/experiences'], [e.name]])}
      ${photoHead('exp-' + e.id)}
      <section class="exphero" data-tone="${e.id}">${photo('exp-' + e.id) ? '' : html`<span class="art">${raw(EXP_ART[e.icon] || '')}</span>`}<div><h1>${e.name}</h1><p>${e.intro}</p></div></section>
      <section class="section" aria-labelledby="pl-h"><div class="sechead"><h2 id="pl-h">Places <span class="pill syn">crowd: estimate</span>${infoNote(e.crowd_note)}</h2><a href="${href('/plan/map', { theme: e.id })}">See on map</a></div>
        ${moreList(e.destinations, placeCard, 6, 'cards placecards')}${thumbsNote()}</section>
      ${e.itineraries.length ? html`<section class="section" aria-labelledby="it-h"><div class="sechead"><h2 id="it-h">Sample trips <span class="pill syn">sample</span></h2></div><div class="cards">${e.itineraries.map(itinCard)}</div></section>` : ''}
      <div class="grid g2 section">
        <section class="card tight" aria-labelledby="fe-h"><h2 id="fe-h">Festivals</h2>${e.festivals.length ? html`<ul class="lines">${e.festivals.slice(0, 4).map((f) => html`<li><a href="${href('/festivals', { view: 'list', q: f.name })}">${f.name}</a><span class="muted small">${f.window || ''}</span></li>`)}</ul><p class="hint">Usual timing; lunar dates are announced each year.</p>` : html`<p class="muted">None listed.</p>`}</section>
        <section class="card tight" aria-labelledby="tm-h"><h2 id="tm-h">Words to know</h2><div class="chips">${e.terms.map((t) => html`<a class="chipbtn" href="${href('/dictionary/' + t.id)}" title="${t.definition}">${t.term}${t.hindi ? html` <span lang="hi" class="muted">${t.hindi}</span>` : ''}</a>`)}</div></section>
      </div>
      ${lastUpdated(null, 'Intro text is a short orientation in our own words; verify details before travel')}`);
    paintTones(el);
  });
}

function placeCard(d) {
  const w = d.weather_now;
  const p = photo(d.id);
  return html`<a class="card tight placecard" href="${href('/destinations/' + d.id)}">${p ? img(p, { cls: 'pthumb', alt: '' }) : ''}<strong>${d.name}</strong><span class="muted small">${d.district_name} · ${d.division}</span>
    <span class="row">${bandPill(d.crowd_today.band, d.crowd_today.index, 'Crowd')}</span>
    <span class="small">${wxText(w)}${w?.warning ? html` · <strong class="warnx">⚠ ${w.warning.kind === 'snow' ? 'snow' : 'heavy rain'} ${short(w.warning.date)}</strong>` : ''}</span></a>`;
}
function itinCard(i) {
  return html`<a class="card tight itincard" href="${href('/plan/itineraries/' + i.id)}"><strong>${i.name}</strong>
    <span class="chain">${i.stops.map((s, n) => html`${n ? html`<span aria-hidden="true">→</span>` : ''}<span>${s.name}</span>`)}</span>
    <span class="row"><span class="pill neutral noicon">${i.suggested_days_total} days suggested</span><span class="pill syn">sample</span></span></a>`;
}

// ------------------------------------------------------------------ itineraries
export async function itineraries(ctx) {
  const el = ctx.el;
  const f = { theme: ctx.query.theme || '' };
  mount(el, html`<div class="pagehead"><div><h1>Sample itineraries</h1><p>Ready-made trips through curated places. Open one to see today's crowd, weather and road status at every stop and the best day to start.</p></div></div>
    <div class="chips" id="tf" role="group" aria-label="Filter by experience"></div><div id="il" class="section"></div>`);
  const m = await meta();
  const exps = m.experiences || [];
  const drawF = () => mount($('#tf', el), html`<button type="button" class="chipbtn" data-t="" aria-pressed="${String(!f.theme)}">All</button>${exps.map((x) => html`<button type="button" class="chipbtn" data-t="${x.id}" aria-pressed="${String(f.theme === x.id)}">${x.name}</button>`)}`);
  const refresh = () => load($('#il', el), async () => {
    setQuery(f);
    drawF();
    $$('[data-t]', el).forEach((b) => b.addEventListener('click', () => { f.theme = b.dataset.t; refresh(); }));
    const r = await api('/itineraries', { query: { theme: f.theme || undefined } });
    mount($('#il', el), r.items.length ? html`<div class="cards">${r.items.map(itinCard)}</div><p class="hint section">${r.note}</p>` : empty('No sample trips for this experience yet'));
    announce(`${r.items.length} itineraries`);
  }, { skel: 'cards', n: 4 });
  await refresh();
}

export async function itinerary(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Itineraries', '#/plan'], ['…']])}<h1 class="sr-only">Itinerary</h1><div id="it"></div>`);
  await load($('#it', el), async () => {
    const i = await api('/itineraries/' + encodeURIComponent(ctx.params.id));
    const b = i.best_start;
    const better = b.offset_days > 0 && b.avg_index < b.if_start_today.avg_index;
    mount(el, html`${crumbs([['Home', '#/'], ['Itineraries', '#/plan'], [i.name]])}
      <div class="pagehead tightb"><div><p class="eyebrow">${i.theme_name} · ${i.suggested_days_total} days suggested</p><h1>${i.name}</h1><p>${i.summary}</p></div><span class="pill syn">sample plan</span></div>
      <section class="beststart ${b.band === 'very_high' ? 'r' : b.band === 'high' ? 'w' : 'g'}" aria-labelledby="bs-h">
        <div><p class="k" id="bs-h">Best start in the next 14 days <span class="tag">estimate</span>${infoNote(b.method)}</p>
        <p class="v">${short(b.date)}${b.offset_days === 0 ? ' (today)' : ''}</p></div>
        <div class="bsx">${bandPill(b.band, b.avg_index, 'Avg crowd')}<span class="small">${better ? html`vs ${b.if_start_today.avg_index} (${b.if_start_today.band.replace('_', ' ')}) if you start today` : 'Starting today is as good as any day in the next two weeks'}</span></div>
      </section>
      <h2 class="section">Stop by stop, today</h2>
      <ol class="stops section">${i.stops.map((s) => html`<li><span class="n" aria-hidden="true">${s.order}</span><div class="stopc ${photo(s.destination_id) ? 'hasimg' : ''}">
          ${photo(s.destination_id) ? img(photo(s.destination_id), { cls: 'sthumb', alt: '' }) : ''}<div class="stopb">
          <div class="sh"><a class="t" href="${href('/destinations/' + s.destination_id)}">${s.name}</a><span class="muted small">${s.district_name} · ${s.suggested_days} day${s.suggested_days > 1 ? 's' : ''} suggested</span></div>
          <div class="st">${bandPill(s.crowd_today.band, s.crowd_today.index, 'Crowd')}
            <span class="pill ${s.weather?.warning ? 'bad' : 'neutral'} noicon">${s.weather?.warning ? `⚠ ${s.weather.warning.kind === 'snow' ? 'Snow' : 'Heavy rain'} ${short(s.weather.warning.date)}` : wxText(s.weather)}</span>
            ${s.road ? html`<span class="roadx">Road: ${roadPill(s.road.status)}${s.road.sample ? html`<span class="pill syn">sample</span>` : ''}</span>` : html`<span class="pill neutral noicon">No road alerts</span>`}</div>
          ${s.best_months?.length ? html`<div class="small muted">Usually best: ${s.best_months.map((m) => monthName(m, true)).join(', ')}</div>` : ''}
        </div></div></li>`)}</ol>
      <p class="hint">${i.note}</p>${thumbsNote()}
      ${lastUpdated(i.generated_at, 'Crowd levels are estimates; road alerts marked sample are illustrative')}`);
  });
}

// ------------------------------------------------------------------ circuits
export async function circuits(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><h1>Circuits</h1><p>Groups of places that are often visited together. The order is a suggestion.</p></div></div><div id="cl"></div>`);
  await load($('#cl', el), async () => {
    const [r, its] = await Promise.all([api('/circuits'), api('/itineraries')]);
    mount($('#cl', el), html`<div class="grid g2">${r.items.map((c) => html`<section class="card tight circ" aria-labelledby="c-${c.id}"><h2 id="c-${c.id}" class="h3">${c.name}</h2><p class="small muted">${c.description}</p>
        <ol class="chainlist">${c.destinations.map((d) => html`<li><a href="${href('/destinations/' + d.id)}">${d.name}</a></li>`)}</ol>
        <div class="btnrow"><a class="btn sm ghost" href="${href('/plan/map', { circuit: c.id })}">On the map</a>${its.items.filter((i) => i.circuit_id === c.id).slice(0, 2).map((i) => html`<a class="btn sm ghost" href="${href('/plan/itineraries/' + i.id)}">${i.name}</a>`)}</div></section>`)}</div>
      <p class="hint section">${r.note}</p>`);
  }, { skel: 'cards', n: 4 });
}

// ------------------------------------------------------------------ schematic map
export async function map(ctx) {
  const el = ctx.el;
  const f = { circuit: ctx.query.circuit || '', district: ctx.query.district || '', theme: ctx.query.theme || '' };
  mount(el, html`<div class="pagehead"><div><h1>Map view</h1><p>Where the places are, coloured by today's crowd estimate.</p></div></div>
    <form class="card tight filters" id="mf" aria-label="Filter the map"></form>
    <div class="maplayout"><figure class="card mapfig"><div id="mapbox" class="mapbox"></div>
      <figcaption class="hint">Schematic, not to scale; no boundaries shown. Dots use approximate coordinates. North is up.</figcaption>
      <div class="heat-legend" id="mleg"></div></figure>
    <section class="card tight maplist" aria-labelledby="ml-h"><h2 id="ml-h" class="h3">Places shown</h2><div id="mlist" aria-live="polite"></div></section></div>`);
  await load($('#mapbox', el), async () => {
    const m = await api('/map');
    const form = $('#mf', el);
    const sel = (name, label, all, opts) => html`<div class="fld"><label class="lbl" for="m-${name}">${label}</label><select class="field" id="m-${name}" name="${name}"><option value="">${all}</option>${opts.map(([v, l]) => html`<option value="${v}" ${f[name] === v ? raw('selected') : ''}>${l}</option>`)}</select></div>`;
    mount(form, html`${sel('circuit', 'Circuit', 'All circuits', m.circuits.map((c) => [c.id, c.name]))}${sel('theme', 'Experience', 'All experiences', m.experiences.map((x) => [x.id, x.name]))}${sel('district', 'District', 'All districts', m.districts.map((x) => [x.id, x.name]))}<div class="fld"><button type="reset" class="btn ghost">Clear</button></div>`);
    collapseFilters(form);
    mount($('#mleg', el), html`${bandLegend().map((l) => html`<span><i data-c="${l.color}"></i>${l.label}</span>`)}<span><i class="faded"></i>Not in the current filter</span>`);
    $$('#mleg i[data-c]', el).forEach((i) => { i.style.background = i.dataset.c; });
    const box = $('#mapbox', el);
    const match = (p) => (!f.circuit || p.circuits.includes(f.circuit)) && (!f.district || p.district === f.district) && (!f.theme || p.themes.includes(f.theme));
    let lastW = 0;
    const draw = (force) => {
      const W = Math.max(280, Math.floor(box.clientWidth));
      if (!force && W === lastW) return;
      lastW = W;
      mount(box, raw(drawMap(m, W, match, f.circuit ? m.circuits.find((c) => c.id === f.circuit) : null)));
      const shown = m.items.filter(match);
      mount($('#mlist', el), shown.length ? moreList(shown, (p) => html`<li>${bandPill(p.crowd_today.band, p.crowd_today.index, '')}<a href="${href('/destinations/' + p.id)}">${p.name}</a><span class="muted small">${p.district_name}</span></li>`, window.matchMedia('(max-width: 1000px)').matches ? 6 : 24, 'lines') : empty('No places match these filters'));
    };
    const sync = () => { const fd = new FormData(form); Object.keys(f).forEach((k) => { f[k] = (fd.get(k) || '').toString(); }); setQuery(f); draw(true); announce(`${m.items.filter(match).length} places shown`); };
    form.addEventListener('change', sync);
    form.addEventListener('reset', () => setTimeout(sync));
    const ro = new ResizeObserver(() => requestAnimationFrame(() => { if (box.isConnected) draw(false); }));
    ro.observe(box);
    draw(true);
  }, { skel: 'block' });
}

function drawMap(m, W, match, circuit) {
  const [la0, la1] = m.bounds.lat;
  const [lo0, lo1] = m.bounds.lon;
  const k = Math.cos((((la0 + la1) / 2) * Math.PI) / 180);
  const pad = W < 500 ? 22 : 40;
  const MAXH = 620; // keep the map within one screen; shrink the drawing width if needed
  const fit = Math.min(W - 2 * pad, ((MAXH - 2 * pad) * (lo1 - lo0) * k) / (la1 - la0));
  const sx = fit / ((lo1 - lo0) * k);
  const H = Math.round((la1 - la0) * sx + 2 * pad);
  const ox = (W - fit - 2 * pad) / 2;
  const X = (lon) => ox + pad + (lon - lo0) * k * sx;
  const Y = (lat) => pad + (la1 - lat) * sx;
  const fs = W < 500 ? 10 : 12;
  const r = W < 500 ? 5.5 : 7;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let s = `<svg class="mapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="group" aria-label="Schematic map of destinations">`;
  s += `<g class="compass" aria-hidden="true"><path d="M${W - 24} ${30} l6 -14 l6 14 l-6 -4z" fill="#52514e"/><text x="${W - 18}" y="44" text-anchor="middle" font-size="10" fill="#52514e">N</text></g>`;
  if (circuit) {
    const pts = circuit.destinations.map((d) => `${X(d.lon).toFixed(1)},${Y(d.lat).toFixed(1)}`).join(' ');
    s += `<polyline points="${pts}" fill="none" stroke="#0b0b0b" stroke-width="2" stroke-dasharray="6 5" opacity=".55"/>`;
  }
  const on = m.items.filter(match);
  const off = m.items.filter((p) => !match(p));
  off.forEach((p) => { s += `<circle cx="${X(p.lon).toFixed(1)}" cy="${Y(p.lat).toFixed(1)}" r="${r - 2}" fill="#c9c8c2" aria-hidden="true"/>`; });
  // Greedy label placement: try right, left, above, below; skip if it would overlap an earlier label.
  const boxes = [];
  const overlaps = (b) => boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
  const labels = [];
  on.forEach((p) => {
    const cx = X(p.lon), cy = Y(p.lat);
    boxes.push({ x: cx - r, y: cy - r, w: 2 * r, h: 2 * r });
  });
  on.forEach((p) => {
    const cx = X(p.lon), cy = Y(p.lat);
    const w = p.name.length * fs * 0.55 + 4, h = fs + 2;
    const cands = [[cx + r + 3, cy - h / 2, 'start'], [cx - r - 3 - w, cy - h / 2, 'end'], [cx - w / 2, cy - r - h - 2, 'middle'], [cx - w / 2, cy + r + 2, 'middle']];
    for (const [x, y, anchor] of cands) {
      const b = { x, y, w, h };
      if (x < 2 || x + w > W - 2 || y < 2 || y + h > H - 2 || overlaps(b)) continue;
      boxes.push(b);
      const tx = anchor === 'start' ? x : anchor === 'end' ? x + w : x + w / 2;
      labels.push(`<text x="${tx.toFixed(1)}" y="${(y + h - 3).toFixed(1)}" text-anchor="${anchor}" font-size="${fs}" fill="#0b0b0b" aria-hidden="true">${esc(p.name)}</text>`);
      break;
    }
  });
  on.forEach((p) => {
    const lbl = `${p.name}, ${p.district_name}: crowd ${p.crowd_today.band.replace('_', ' ')} (estimate)`;
    s += `<a href="#/destinations/${esc(p.id)}" aria-label="${esc(lbl)}"><title>${esc(lbl)}</title><circle cx="${X(p.lon).toFixed(1)}" cy="${Y(p.lat).toFixed(1)}" r="${r}" fill="${BAND_FILL[p.crowd_today.band]}" stroke="#fff" stroke-width="2"/></a>`;
  });
  s += labels.join('') + '</svg>';
  return s;
}

// ------------------------------------------------------------------ how to reach + official services
export async function reach(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><h1>How to reach</h1><p>Airports, railheads and access notes from the curated reference set. <span class="pill warn">Verify</span></p></div></div><div id="rc"></div>`);
  await load($('#rc', el), async () => {
    const d = await api('/destinations');
    const general = (div) => [...new Set(d.items.filter((x) => x.division === div).flatMap((x) => x.route_facts).filter((t) => /airport|railhead/i.test(t)))];
    const specific = d.items.map((x) => ({ x, facts: x.route_facts.filter((t) => !/airport|railhead/i.test(t)) })).filter((s) => s.facts.length);
    mount($('#rc', el), html`<div class="grid g2">${['Garhwal', 'Kumaon'].map((div) => html`<section class="card tight"><h2 class="h3">${div} division</h2><ul class="bullets section">${general(div).map((t) => html`<li>${t}</li>`)}</ul></section>`)}</div>
      <section class="card tight section" aria-labelledby="ac-h"><h2 id="ac-h" class="h3">Access notes for specific places</h2>
        <ul class="lines">${specific.map((s) => html`<li><a href="${href('/destinations/' + s.x.id + '/roads')}">${s.x.name}</a><span class="small">${s.facts.join(' ')}</span></li>`)}</ul></section>
      <p class="hint section">Approximate; verify with official sources before travel. No distances or travel times are given on purpose. Each destination's Getting there tab has live road alerts and a directions link.</p>`);
  });
}

export async function services(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><h1>Official services</h1><p>Links to official sites for things this concept portal does not do itself.</p></div></div><div id="sv"></div>`);
  await load($('#sv', el), async () => {
    const [o, m] = await Promise.all([api('/official-services'), meta()]);
    mount($('#sv', el), html`<div class="grid g2">${o.items.map((s) => html`<section class="card tight svc"><h2 class="h3">${s.name}</h2><p class="small">${s.description}</p><p class="mono small muted">${s.url.replace(/^https:\/\//, '').replace(/\/$/, '')}</p>${ext(s.url, 'Open official site')}</section>`)}</div>
      <p class="flag amber section">${o.note}</p>
      <section class="card section onewin" aria-labelledby="ow-h"><h2 id="ow-h">One window for tourism businesses</h2>
        <p>Instead of a separate site for each registration, businesses use one account here to apply, renew, report occupancy and connect HOI: ${m.business_types.map((b) => b.label.toLowerCase()).join(', ')}.</p>
        <div class="btnrow section"><a class="btn primary" href="#/register">Create a business account</a><a class="btn ghost" href="#/signin?need=business">Business sign in</a></div></section>`);
  });
}

// Shared by the destination page (Nearby tab).
export async function nearbyPanel(box, dest) {
  const r = await api(`/destinations/${encodeURIComponent(dest.id)}/nearby`, { query: { limit: 8 } });
  mount(box, html`<h2 id="ph">Nearby places</h2>
    ${moreList(r.items, (p) => html`<a class="item nearby" href="${href('/destinations/' + p.id)}">${photo(p.id) ? img(photo(p.id), { cls: 'nthumb', alt: '' }) : html`<span class="nthumb ph" aria-hidden="true"></span>`}<div class="main"><strong>${p.name}</strong><div class="sub">${p.district_name} · about ${num(p.distance_km)} km straight-line</div></div><div class="side">${bandPill(p.crowd_today.band, p.crowd_today.index, '')}</div></a>`, 5)}
    <p class="hint section">${r.distance_note}</p>${thumbsNote()}`);
}
