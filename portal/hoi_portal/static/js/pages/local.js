// Local (community-hosted) experiences: public list + detail with "Request to join" (no payment), the host's
// dashboard (list / edit / pause / remove experiences, accept or decline join requests) and the staffing-agency
// dashboard (block offers, HOI staffing requests with responses, notifications).
import { html, mount, href, load, $, $$, raw, empty, announce, crumbs, field, showErrors, clearErrors, apiFieldErrors, busy, toast, drawer, confirmDialog,
  fmtDate, fmtDateTime, num, monthName, MONTH_NAMES, icon, mediaCard, statTile, takeaway, details, lastUpdated, collapseFilters, statusPill } from '../ui.js';
import { api, meta, jobsMeta } from '../api.js';
import { setQuery } from '../router.js';
import { localCards, stayCard, bizCard, rupees, offerCard } from '../cards.js';
import { cover, photo, credit, thumbsNote } from '../photos.js';
import { roleSubnav } from './common.js';
import { serverPager } from './jobs.js';

const THEMES = [['spiritual', 'Spiritual & Char Dham'], ['adventure', 'Adventure & Treks'], ['wildlife', 'Wildlife & Nature'], ['wellness', 'Yoga & Wellness'], ['leisure', 'Hill towns & Leisure'], ['culture', 'Culture & Fairs']];
const hours = (h) => (h >= 6 ? 'Full day' : `${num(h, 1)} hours`);

// ------------------------------------------------------------------ public list
export async function list(ctx) {
  const el = ctx.el;
  const f = { type: ctx.query.type || '', destination: ctx.query.destination || '', month: ctx.query.month || '', q: ctx.query.q || '', page: Number(ctx.query.page) || 1 };
  const m = await meta();
  const types = m.local_experience_types || [];
  mount(el, html`<div class="pagehead"><div><h1>Things to do with local hosts</h1>
      <p class="lead2">Village walks, home-cooked meals and craft classes with local families and guides. Ask to join and the host will reply. Your money stays in the village.</p></div></div>
    <div class="chiprow" role="group" aria-label="Kind of experience" id="lt"></div>
    <form class="card tight filters" id="lf" aria-label="Filter local experiences">
      <div class="fld"><label class="lbl" for="l-d">Destination</label><select class="field" id="l-d" name="destination"><option value="">Anywhere</option>${m.destinations.map((d) => html`<option value="${d.id}" ${f.destination === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="l-m">Month</label><select class="field" id="l-m" name="month"><option value="">Any month</option>${MONTH_NAMES.map((n, i) => html`<option value="${i + 1}" ${String(i + 1) === f.month ? raw('selected') : ''}>${n}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="l-q">Search</label><input class="field" id="l-q" name="q" type="search" value="${f.q}" maxlength="80" placeholder="e.g. meal, Almora"></div>
    </form>
    <p class="small muted" id="lcount" aria-live="polite"></p>
    <div id="ll"></div>
    <section class="sec2" aria-labelledby="th-h"><div class="sechead"><div><h2 id="th-h">Or explore by theme</h2><p class="sub">Curated places for each kind of trip.</p></div><a href="#/experiences/themes">All themes</a></div>
      <div class="chiprow">${THEMES.map(([k, n]) => html`<a class="chipbtn" href="#/experiences/${k}">${n}</a>`)}</div></section>
    ${thumbsNote()}`);
  const form = $('#lf', el);
  collapseFilters(form);
  const chips = () => {
    mount($('#lt', el), html`<button type="button" class="chipbtn" data-t="" aria-pressed="${String(!f.type)}">All</button>${types.map((t) => html`<button type="button" class="chipbtn" data-t="${t.key}" aria-pressed="${String(f.type === t.key)}">${icon(t.key)}${t.label}</button>`)}`);
    $$('[data-t]', el).forEach((b) => b.addEventListener('click', () => { f.type = b.dataset.t; f.page = 1; chips(); draw(); }));
  };
  const box = $('#ll', el);
  const draw = () => load(box, async () => {
    setQuery({ ...f, page: f.page > 1 ? f.page : '' });
    const r = await api('/local-experiences', { query: { type: f.type || undefined, destination: f.destination || undefined, month: f.month || undefined, q: f.q || undefined, page: f.page } });
    $('#lcount', el).textContent = `${r.total} local experience${r.total === 1 ? '' : 's'}${f.month ? ' in ' + monthName(Number(f.month)) : ''}`;
    mount(box, r.items.length ? html`<div class="mcgrid g4c">${r.items.map(localCards())}</div>` : empty('Nothing matches', 'Try another month or clear a filter.'));
    serverPager(box, r, (pg) => { f.page = pg; draw().then(() => $('#lcount', el).scrollIntoView({ block: 'start' })); });
    announce($('#lcount', el).textContent);
  }, { skel: 'cards', n: 8 });
  let tmr;
  form.addEventListener('change', (e) => { if (e.target.name === 'q') return; const fd = new FormData(form); f.destination = fd.get('destination') || ''; f.month = fd.get('month') || ''; f.page = 1; draw(); });
  form.addEventListener('input', (e) => { if (e.target.name !== 'q') return; clearTimeout(tmr); tmr = setTimeout(() => { f.q = e.target.value.trim(); f.page = 1; draw(); }, 350); });
  form.addEventListener('submit', (e) => e.preventDefault());
  chips();
  await draw();
}

// ------------------------------------------------------------------ public detail + request to join
export async function detail(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Local experiences', '#/experiences'], ['…']])}<h1 class="sr-only">Local experience</h1><div id="lx1"></div>`);
  await load($('#lx1', el), async () => {
    const e = await api('/local-experiences/' + encodeURIComponent(ctx.params.id));
    const p = photo('lx-' + e.type) || photo(e.destination_id);
    const nowM = new Date().getMonth() + 1;
    mount(el, html`${crumbs([['Home', '#/'], ['Local experiences', '#/experiences'], [e.title]])}
      <section class="photohero" aria-labelledby="xh">${cover(['lx-' + e.type, e.destination_id], { eager: true, seed: e.id })}
        <div class="ph-in"><p class="eyebrow">${e.type_label} · ${e.destination_name}${e.district_name !== e.destination_name ? ", " + e.district_name : ""}</p><h1 id="xh">${e.title}</h1>
          </div></section>
      <div class="xlayout">
        <div>
          <div class="factgrid">
            <div><span class="k">${icon('clock')}Duration</span><span class="v">${hours(e.duration_hours)}</span></div>
            <div><span class="k">${icon('people')}Group</span><span class="v">${e.group_min}-${e.group_max} people</span></div>
            <div><span class="k">${icon('rupee')}Price</span><span class="v">${rupees(e.price_min, e.price_max) || 'Ask the host'}</span></div>
            <div><span class="k">${icon('calendar')}Season</span><span class="v">${e.months.includes(nowM) ? 'Runs this month' : 'Not this month'}</span></div>
          </div>
          <p class="section">${e.description.replace(/^SAMPLE \(synthetic\):\s*/, '')}</p>
          ${e.community_share ? html`<p class="notice section"><strong>Where your money goes:</strong> ${e.community_share.replace(/^Sample:\s*/, '')} </p>` : ''}
          <ul class="mc-facts section"><li>${icon('lang')}<span>${e.languages.join(', ')}</span></li><li>${icon('calendar')}<span>${e.months.map((m) => monthName(m, true)).join(', ')}</span></li></ul>
          ${e.what_to_bring?.length ? html`<h2 class="h3 sec2">Bring</h2><ul class="bullets section">${e.what_to_bring.map((b) => html`<li>${b}</li>`)}</ul>` : ''}
          <h2 class="h3 sec2">Your host</h2><div class="mcgrid section">${bizCard(e.host)}</div>
          ${e.stays_nearby?.length ? html`<h2 class="h3 sec2">Stay nearby</h2><p class="small muted">Registered homestays linked by the host.</p><div class="mcgrid g3c section">${e.stays_nearby.map(stayCard)}</div>` : ''}
          ${e.more_here?.length ? html`<p class="sec2">More here: ${e.more_here.map((m, i) => html`${i ? ' · ' : ''}<a href="${href('/experiences/local/' + m.id)}">${m.title}</a>`)} · <a href="${href('/destinations/' + e.destination_id)}">About ${e.destination_name}</a></p>` : ''}
        </div>
        <aside class="card sticky" aria-labelledby="jh"><h2 id="jh" class="h3">Ask to join</h2><p class="small muted">No payment here. The host replies with the plan and how to pay. Only this host sees your phone or email.</p><div id="jbox"></div></aside>
      </div>
      ${lastUpdated(null)}`);
    joinForm($('#jbox', el), e);
  });
}

function nextDateIn(months) {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  for (let i = 0; i < 400; i++) { if (months.includes(d.getMonth() + 1)) break; d.setDate(d.getDate() + 1); }
  return d.toISOString().slice(0, 10);
}
function joinForm(box, e) {
  mount(box, html`<form id="jf" class="form" novalidate>
    ${field({ id: 'name', label: 'Your first name', required: true, attrs: 'maxlength="60" autocomplete="given-name"' })}
    <div class="grid g2">${field({ id: 'group_size', label: 'People', type: 'number', required: true, value: e.group_min, attrs: `min="${e.group_min}" max="${e.group_max}" inputmode="numeric"` })}
    ${field({ id: 'date', label: 'Date', type: 'date', required: true, value: nextDateIn(e.months) })}</div>
    ${field({ id: 'contact', label: 'Phone or email', required: true, hint: 'Shared with this host only.', attrs: 'maxlength="120" autocomplete="tel"' })}
    ${field({ id: 'note', label: 'Note for the host', type: 'textarea', rows: 2, opt: true, attrs: 'maxlength="500"' })}
    <button class="btn primary" type="submit">Ask to join</button></form>`);
  const form = $('#jf', box);
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    clearErrors(form);
    const fd = new FormData(form);
    const body = { name: fd.get('name').trim(), group_size: Number(fd.get('group_size')), date: fd.get('date'), contact: fd.get('contact').trim(), note: fd.get('note').trim() || null };
    const errs = {};
    if (body.name.length < 2) errs.name = 'Enter your first name.';
    if (body.contact.length < 5) errs.contact = 'Enter a phone number or email.';
    if (!body.date) errs.date = 'Choose a date.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Sending…');
    try {
      const r = await api(`/local-experiences/${encodeURIComponent(e.id)}/join`, { method: 'POST', body });
      mount(box, html`<div class="flag green" role="status"><strong>Request sent (${r.request_id}).</strong> ${r.message}</div>`);
      announce('Request sent');
    } catch (err) {
      busy(btn, false);
      showErrors(form, apiFieldErrors(err), err.message);
    }
  });
}

// ------------------------------------------------------------------ host dashboard (business)
const head = (path, title, sub, extra = '') => html`${roleSubnav(path)}<div class="pagehead"><div><p class="eyebrow">Business</p><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ''}</div>${extra}</div>`;

export async function hostDashboard(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business/experiences', 'Local experiences you host', 'List what you offer, link nearby homestays and answer join requests.', html`<button type="button" class="btn primary" id="newx" hidden>List an experience</button>`)}<div id="hx"></div>`);
  const box = $('#hx', el);
  const draw = () => load(box, async () => {
    const [mine, reqs, m] = await Promise.all([api('/business/experiences'), api('/business/experience-requests'), meta()]);
    const nb = $('#newx', el);
    nb.hidden = !mine.can_host;
    nb.onclick = () => expForm(null, mine, m, draw);
    if (!mine.host_businesses.length) {
      mount(box, empty('Hosting is for guides, homestays and adventure operators', 'Register one of these business types to list local experiences.', html`<a class="btn primary" href="#/host">How to join</a>`));
      return;
    }
    const pending = reqs.items.filter((r) => r.status === 'pending');
    mount(box, html`<div class="kpis k4">${statTile({ label: 'Listed experiences', value: mine.items.filter((x) => x.status === 'listed').length })}
        ${statTile({ label: 'Requests waiting', value: pending.length, tone: pending.length ? 'warn' : '' })}
        ${statTile({ label: 'Accepted requests', value: reqs.items.filter((r) => r.status === 'accepted').length })}
        ${statTile({ label: 'Paused', value: mine.items.filter((x) => x.status === 'paused').length })}</div>
      <section class="sec2" aria-labelledby="rq-h"><h2 id="rq-h">Join requests</h2>
        ${pending.length ? html`<div class="list section">${pending.map(reqRow)}</div>` : html`<p class="muted section">No requests waiting.</p>`}
        ${reqs.items.length > pending.length ? details(`Answered requests (${reqs.items.length - pending.length})`, html`<div class="list">${reqs.items.filter((r) => r.status !== 'pending').map(reqRow)}</div>`) : ''}</section>
      <section class="sec2" aria-labelledby="mx-h"><h2 id="mx-h">Your experiences</h2>
        ${mine.items.length ? html`<div class="mcgrid g3c section">${mine.items.map((x) => mediaCard({
          href: href('/experiences/local/' + x.id), media: cover(['lx-' + x.type, x.destination_id], { seed: x.id }),
          badge: x.status === 'listed' ? html`<span class="pill ok">Listed</span>` : html`<span class="pill warn">Paused</span>`,
          kicker: `${x.type_label} · ${x.destination_name}`, kickerIcon: x.type, title: x.title,
          facts: [['people', `${x.group_min}-${x.group_max} people`], ['rupee', rupees(x.price_min, x.price_max, ' pp')], ['calendar', `${x.requests.pending} waiting · ${x.requests.total} request${x.requests.total === 1 ? '' : 's'}`]],
          foot: html`<button type="button" class="btn sm ghost" data-edit="${x.id}">Edit</button><button type="button" class="btn sm ghost" data-toggle="${x.id}" data-st="${x.status === 'listed' ? 'paused' : 'listed'}">${x.status === 'listed' ? 'Pause' : 'List again'}</button><button type="button" class="btn sm danger" data-del="${x.id}">Remove</button>`,
        }))}</div>` : empty('Nothing listed yet', 'List your first experience: a village walk, a home-cooked meal or a craft workshop.')}</section>`);
    $$('[data-act]', box).forEach((b) => b.addEventListener('click', async () => {
      busy(b, true, '…');
      try { await api('/business/experience-requests/' + encodeURIComponent(b.dataset.id), { method: 'POST', body: { action: b.dataset.act } }); toast(b.dataset.act === 'accept' ? 'Accepted. Contact the visitor to confirm.' : 'Declined'); draw(); } catch (e) { busy(b, false); toast(e.message, 'err'); }
    }));
    $$('[data-edit]', box).forEach((b) => b.addEventListener('click', () => expForm(mine.items.find((x) => x.id === b.dataset.edit), mine, m, draw)));
    $$('[data-toggle]', box).forEach((b) => b.addEventListener('click', async () => {
      try { await api('/business/experiences/' + encodeURIComponent(b.dataset.toggle), { method: 'PATCH', body: { status: b.dataset.st } }); draw(); } catch (e) { toast(e.message, 'err'); }
    }));
    $$('[data-del]', box).forEach((b) => b.addEventListener('click', async () => {
      if (!(await confirmDialog('Remove this experience from the portal? Waiting requests are declined.', { ok: 'Remove', danger: true }))) return;
      try { await api('/business/experiences/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' }); toast('Removed'); draw(); } catch (e) { toast(e.message, 'err'); }
    }));
  }, { skel: 'cards', n: 3 });
  await draw();
}

function reqRow(r) {
  return html`<div class="item"><div class="main"><strong>${r.name}</strong> · ${r.group_size} people · ${fmtDate(r.date, { weekday: true })}
    <div class="sub">${r.experience_title} · <span class="mono">${r.contact}</span>${r.note ? html` · ${r.note.replace(/^SAMPLE \(synthetic\):\s*/, '')}` : ''}</div></div>
    <div class="side">${r.status === 'pending' ? html`<button type="button" class="btn sm ok" data-act="accept" data-id="${r.id}">Accept</button><button type="button" class="btn sm ghost" data-act="decline" data-id="${r.id}">Decline</button>`
      : html`<span class="pill ${r.status === 'accepted' ? 'ok' : 'neutral'}">${r.status}</span>`}</div></div>`;
}

async function expForm(x, mine, m, done) {
  const dw = drawer(x ? 'Edit experience' : 'List an experience');
  const hosts = mine.host_businesses.filter((b) => b.status === 'active');
  const bid = x?.host_business_id || hosts[0]?.id;
  const biz = () => mine.host_businesses.find((b) => b.id === ($('#business_id', dw.body)?.value || bid));
  const stays = async (district) => (await api('/registry', { query: { type: 'homestay', district, status: 'active', page_size: 100 } })).items;
  let stayList = await stays(biz()?.district);
  const v = x || { type: 'village_walk', group_min: 2, group_max: 8, duration_hours: 2, months: [3, 4, 5, 9, 10, 11], languages: ['Hindi'], stay_business_ids: [] };
  mount(dw.body, html`<form id="xf" class="form" novalidate>
    ${x ? '' : field({ id: 'business_id', label: 'Hosting business', type: 'select', value: bid, options: hosts.map((b) => ({ value: b.id, label: b.name })) })}
    ${field({ id: 'title', label: 'Title', required: true, value: v.title || '', attrs: 'maxlength="90"' })}
    ${field({ id: 'type', label: 'Kind', type: 'select', value: v.type, options: mine.types.map((t) => ({ value: t.key, label: t.label })) })}
    ${field({ id: 'description', label: 'What visitors do', type: 'textarea', rows: 4, required: true, value: (v.description || '').replace(/^SAMPLE \(synthetic\):\s*/, ''), attrs: 'maxlength="1200"' })}
    <div class="grid g3">${field({ id: 'duration_hours', label: 'Hours', type: 'number', value: v.duration_hours, attrs: 'min="0.5" max="12" step="0.5"' })}
      ${field({ id: 'group_min', label: 'Min people', type: 'number', value: v.group_min, attrs: 'min="1" max="50"' })}${field({ id: 'group_max', label: 'Max people', type: 'number', value: v.group_max, attrs: 'min="1" max="50"' })}</div>
    <div class="grid g2">${field({ id: 'price_min', label: 'Price from (₹ per person)', type: 'number', opt: true, value: v.price_min ?? '', attrs: 'min="0" max="50000"' })}${field({ id: 'price_max', label: 'Price up to', type: 'number', opt: true, value: v.price_max ?? '', attrs: 'min="0" max="50000"' })}</div>
    <fieldset class="fld"><legend class="lbl">Months it runs</legend><div class="chips">${MONTH_NAMES.map((n, i) => html`<label class="check"><input type="checkbox" name="months" value="${i + 1}" ${v.months.includes(i + 1) ? raw('checked') : ''}>${n.slice(0, 3)}</label>`)}</div></fieldset>
    <fieldset class="fld"><legend class="lbl">Languages</legend><div class="chips">${m.languages.map((l) => html`<label class="check"><input type="checkbox" name="languages" value="${l}" ${v.languages.includes(l) ? raw('checked') : ''}>${l}</label>`)}</div></fieldset>
    <fieldset class="fld"><legend class="lbl">Stay nearby (up to 3 registered homestays)</legend><div class="chips" id="xstays">${stayList.slice(0, 30).map((s) => html`<label class="check"><input type="checkbox" name="stay_business_ids" value="${s.id}" ${v.stay_business_ids.includes(s.id) ? raw('checked') : ''}>${s.name.replace(/ Sample /, ' ')}</label>`)}</div></fieldset>
    ${field({ id: 'community_share', label: 'How the fee is shared locally', opt: true, value: (v.community_share || '').replace(/^Sample:\s*/, ''), attrs: 'maxlength="200"' })}
    <button class="btn primary" type="submit">${x ? 'Save changes' : 'List experience'}</button></form>`);
  const form = $('#xf', dw.body);
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    clearErrors(form);
    const fd = new FormData(form);
    const n = (k) => (fd.get(k) === '' || fd.get(k) == null ? null : Number(fd.get(k)));
    const body = {
      title: fd.get('title').trim(), type: fd.get('type'), description: fd.get('description').trim(), duration_hours: n('duration_hours'), group_min: n('group_min'), group_max: n('group_max'),
      price_min: n('price_min'), price_max: n('price_max'), months: fd.getAll('months').map(Number), languages: fd.getAll('languages'), stay_business_ids: fd.getAll('stay_business_ids').slice(0, 3),
      community_share: fd.get('community_share').trim() || null,
    };
    if (!x) body.business_id = fd.get('business_id');
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Saving…');
    try {
      await api(x ? '/business/experiences/' + encodeURIComponent(x.id) : '/business/experiences', { method: x ? 'PATCH' : 'POST', body });
      dw.close();
      toast(x ? 'Saved' : 'Listed. It is now public.');
      done();
    } catch (err) {
      busy(btn, false);
      showErrors(form, apiFieldErrors(err), err.message);
    }
  });
}

// ------------------------------------------------------------------ staffing agency dashboard (business)
export async function agencyDashboard(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business/staffing', 'Staffing agency', 'Offer your workers to hotels and answer hotels that are short of staff.', html`<button type="button" class="btn primary" id="newo" hidden>Post a block offer</button>`)}<div id="ag"></div>`);
  const box = $('#ag', el);
  const draw = () => load(box, async () => {
    const [d, jm, m] = await Promise.all([api('/staffing/mine'), jobsMeta(), meta()]);
    const active = d.agencies.filter((a) => a.status === 'active');
    $('#newo', el).hidden = !active.length;
    $('#newo', el).onclick = () => offerForm(active, jm, m, draw);
    if (!d.agencies.length) {
      mount(box, empty('No staffing agency on this account', 'Register a staffing agency to publish block offers and receive HOI staffing requests.', html`<a class="btn primary" href="${href('/business/apply', { type: 'staffing_agency' })}">Register an agency</a>`));
      return;
    }
    const s = d.summary;
    const ag = active[0] || d.agencies[0];
    mount(box, html`<div class="kpis k4">${statTile({ label: 'Hotels needing staff', value: s.open_requests, tone: s.open_requests > s.responded ? 'warn' : '', note: `${s.responded} answered` })}
        ${statTile({ label: 'Unread notifications', value: d.unread, tone: d.unread ? 'warn' : '' })}
        ${statTile({ label: 'Open block offers', value: s.open_offers })}${statTile({ label: 'Workers offered', value: s.workers_offered })}</div>
      <section class="sec2" aria-labelledby="rq-h"><h2 id="rq-h">Hotels that need staff now</h2>
        ${takeaway(d.open_requests.length ? `${d.open_requests.length} hotel${d.open_requests.length > 1 ? 's are' : ' is'} short of staff for skills and districts you cover.` : 'No open requests match your skills and districts right now.')}
        <div class="list">${d.open_requests.map((j) => html`<div class="item"><div class="main"><a class="t" href="${href('/jobs/' + j.id)}">${j.title}</a>
          <div class="sub">${j.business_name} · ${j.district_name} · ${fmtDate(j.season_from, { noYear: true })} – ${fmtDate(j.season_to)}${j.staffing_request?.shift_note ? ' · ' + j.staffing_request.shift_note : ''}</div></div>
          <div class="side">${j.my_response ? html`<span class="pill ok">You offered ${j.my_response.workers}</span>` : ''}
            <form class="row respond" data-job="${j.id}"><label class="sr-only" for="w-${j.id}">Workers you can send</label><input class="field num" id="w-${j.id}" name="workers" type="number" min="1" max="200" value="${j.my_response?.workers || Math.min(j.openings, ag.pool_size || j.openings)}" required>
            <button class="btn sm primary" type="submit">${j.my_response ? 'Update' : 'Respond'}</button></form></div></div>`)}</div></section>
      <section class="sec2" aria-labelledby="of-h"><h2 id="of-h">Your block offers</h2>
        ${d.offers.length ? html`<div class="mcgrid g3c section">${d.offers.map((o) => html`<div>${offerCard(o)}${o.status === 'open' ? html`<button type="button" class="btn sm ghost section" data-wd="${o.id}">Withdraw</button>` : html`<span class="pill neutral section">${o.status}</span>`}</div>`)}</div>` : html`<p class="muted section">No offers yet.</p>`}</section>
      ${details(`Notifications (${d.notifications.length})`, d.notifications.length ? html`<ul class="lines">${d.notifications.map((n) => html`<li>${n.read ? '' : html`<span class="pill warn">New</span>`}<a href="${href('/jobs/' + n.job_id)}">${n.title}</a><span class="muted small">${fmtDateTime(n.created_at)}</span></li>`)}</ul>` : html`<p class="muted">None.</p>`)}
      ${details('Your agency: skills and districts', html`<p class="small">${ag.name} · <span class="mono">${ag.reg_no}</span> · pool of ${ag.pool_size}</p>
        <p class="section"><strong>Skills:</strong> ${ag.skills.map((x) => x.label).join(', ') || '—'}</p><p><strong>Districts:</strong> ${ag.districts_served.map((x) => x.name).join(', ') || '—'}</p>
        <p class="hint">You get a message when a hotel in these districts needs these skills.</p>`)}
`);
    $$('form.respond', box).forEach((f) => f.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const btn = f.querySelector('button');
      busy(btn, true, '…');
      try {
        await api(`/staffing/requests/${encodeURIComponent(f.dataset.job)}/respond`, { method: 'POST', body: { business_id: ag.id, workers: Number(new FormData(f).get('workers')) } });
        toast('Sent to the hotel');
        draw();
      } catch (e) { busy(btn, false); toast(e.message, 'err'); }
    }));
    $$('[data-wd]', box).forEach((b) => b.addEventListener('click', async () => {
      try { await api('/staffing/offers/' + encodeURIComponent(b.dataset.wd), { method: 'PATCH', body: { status: 'withdrawn' } }); draw(); } catch (e) { toast(e.message, 'err'); }
    }));
  }, { skel: 'block' });
  await draw();
}

function offerForm(agencies, jm, m, done) {
  const dw = drawer('Post a block offer');
  const a = agencies[0];
  const iso = (d) => d.toISOString().slice(0, 10);
  const t = new Date();
  mount(dw.body, html`<form id="of" class="form" novalidate>
    ${field({ id: 'business_id', label: 'Agency', type: 'select', value: a.id, options: agencies.map((x) => ({ value: x.id, label: x.name })) })}
    ${field({ id: 'skill', label: 'Skill', type: 'select', value: a.skills[0]?.key, options: jm.skills.map((s) => ({ value: s.key, label: s.label })) })}
    <div class="grid g2">${field({ id: 'workers', label: 'Workers available', type: 'number', required: true, value: 10, attrs: 'min="1" max="200"' })}
      ${field({ id: 'district', label: 'District', type: 'select', value: a.district, options: m.districts.map((d) => ({ value: d.id, label: d.name })) })}</div>
    <div class="grid g2">${field({ id: 'available_from', label: 'From', type: 'date', required: true, value: iso(new Date(t.getFullYear(), t.getMonth() + 1, 1)) })}
      ${field({ id: 'available_to', label: 'To', type: 'date', required: true, value: iso(new Date(t.getFullYear(), t.getMonth() + 3, 0)) })}</div>
    ${field({ id: 'note', label: 'Note', opt: true, attrs: 'maxlength="300"', hint: 'Counts only; never name individual workers.' })}
    <button class="btn primary" type="submit">Post offer</button></form>`);
  const form = $('#of', dw.body);
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    clearErrors(form);
    const fd = new FormData(form);
    const body = { business_id: fd.get('business_id'), skill: fd.get('skill'), workers: Number(fd.get('workers')), district: fd.get('district'), available_from: fd.get('available_from'), available_to: fd.get('available_to'), note: fd.get('note').trim() || null };
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Posting…');
    try { await api('/staffing/offers', { method: 'POST', body, auth: true }); dw.close(); toast('Offer posted'); done(); } catch (err) { busy(btn, false); showErrors(form, apiFieldErrors(err), err.message); }
  });
}

export { statusPill };
