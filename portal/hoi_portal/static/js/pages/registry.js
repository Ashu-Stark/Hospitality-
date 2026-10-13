// Registry / directory (A-Z, filters, paging), business detail, and "Verify a business" by registration number.
import { html, mount, href, load, $, $$, empty, raw, statusPill, verifiedPill, fmtDate, crumbs, lastUpdated, num, announce, busy, errorBox, showErrors, clearErrors, synPill, collapseFilters } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';
import { bizRow, kv } from './common.js';
import { bizCard } from '../cards.js';

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

export async function directory(ctx) {
  const el = ctx.el;
  const f = { q: '', type: '', district: '', destination: '', status: '', verified: '', letter: '', page: '1', ...ctx.query };
  mount(el, html`<div class="pagehead"><div><h1>Business directory A-Z</h1>
      <p>Stays, guides, travel agents, taxis and adventure companies.</p></div></div>
    <form class="card tight filters" id="rf" aria-label="Filter businesses"><div class="sk line"></div></form>
    <nav class="letters" id="letters" aria-label="Filter by first letter"></nav>
    <p class="small muted" id="rcount" aria-live="polite"></p>
    <div id="rlist" class="section"></div>`);
  const m = await meta();
  const form = $('#rf', el);
  const sel = (name, label, opts) => html`<div class="fld"><label class="lbl" for="r-${name}">${label}</label><select class="field" id="r-${name}" name="${name}">${opts.map(([v, l]) => html`<option value="${v}" ${String(f[name]) === String(v) ? raw('selected') : ''}>${l}</option>`)}</select></div>`;
  mount(form, html`<div class="fld"><label class="lbl" for="r-q">Name or reg. no.</label><input class="field" id="r-q" name="q" type="search" value="${f.q}" placeholder="e.g. Homestay, UK-HMS-…"></div>
    ${sel('type', 'Type', [['', 'All types'], ...m.business_types.map((x) => [x.key, x.label])])}
    ${sel('district', 'District', [['', 'All districts'], ...m.districts.map((x) => [x.id, x.name])])}
    ${sel('destination', 'Destination', [['', 'All destinations'], ...m.destinations.map((x) => [x.id, x.name])])}
    ${sel('status', 'Status', [['', 'Any status'], ...m.business_statuses.map((s) => [s, s[0].toUpperCase() + s.slice(1)])])}
    ${sel('verified', 'Verified', [['', 'Any'], ['true', 'Verified only'], ['false', 'Not verified']])}
    <div class="fld"><button type="reset" class="btn ghost">Clear</button></div>`);
  collapseFilters(form);
  const listEl = $('#rlist', el);
  const drawLetters = (avail) => {
    mount($('#letters', el), html`<a href="#/directory" data-letter="" aria-current="${String(!f.letter)}">All</a>${LETTERS.map((L) => (avail.includes(L) || f.letter === L
      ? html`<a href="#/directory" data-letter="${L}" aria-current="${String(f.letter === L)}" aria-label="Names starting with ${L}">${L}</a>`
      : html`<span aria-hidden="true">${L}</span>`))}`);
    $$('[data-letter]', el).forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); f.letter = a.dataset.letter; f.page = '1'; refresh(); }));
  };
  let avail = [];
  const refresh = () => {
    setQuery(f);
    drawLetters(avail);
    return load(listEl, async () => {
      const q = { ...f, page_size: 12 };
      Object.keys(q).forEach((k) => { if (q[k] === '') delete q[k]; });
      const r = await api('/registry', { query: q });
      if (!f.letter) avail = r.letters || avail;
      if (!avail.length) avail = r.letters || [];
      drawLetters(avail);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      $('#rcount', el).textContent = `${num(r.total)} businesses${f.letter ? ' starting with ' + f.letter : ''} · page ${r.page} of ${pages}`;
      mount(listEl, r.items.length ? html`<div class="mcgrid g4c">${r.items.map(bizCard)}</div>
        <nav class="pager" aria-label="Pages"><button type="button" class="btn ghost sm" data-pg="${r.page - 1}" ${r.page <= 1 ? raw('disabled') : ''}>Previous</button>
        <span class="small">Page ${r.page} of ${pages}</span><button type="button" class="btn ghost sm" data-pg="${r.page + 1}" ${r.page >= pages ? raw('disabled') : ''}>Next</button></nav>`
        : empty('No businesses match these filters', 'Clear a filter or try another letter. Unregistered operators can be reported through a grievance.', html`<a class="btn ghost" href="#/grievance">Report an unregistered business</a>`));
      $$('[data-pg]', listEl).forEach((b) => b.addEventListener('click', () => { f.page = b.dataset.pg; refresh().then(() => $('#rcount', el).scrollIntoView()); }));
      announce($('#rcount', el).textContent);
    }, { skel: 'list', n: 6 });
  };
  const sync = () => {
    const fd = new FormData(form);
    ['q', 'type', 'district', 'destination', 'status', 'verified'].forEach((k) => { f[k] = (fd.get(k) || '').toString().trim(); });
    f.page = '1';
    refresh();
  };
  let tmr;
  form.addEventListener('input', (e) => { clearTimeout(tmr); tmr = setTimeout(sync, e.target.name === 'q' ? 350 : 0); });
  form.addEventListener('reset', () => setTimeout(() => { f.letter = ''; sync(); }));
  form.addEventListener('submit', (e) => { e.preventDefault(); sync(); });
  await refresh();
}

export async function business(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Directory', '#/directory'], ['…']])}<h1 class="sr-only">Business</h1><div id="bd"></div>`);
  await load($('#bd', el), async () => {
    const b = await api('/registry/' + encodeURIComponent(ctx.params.id));
    mount(el, html`${crumbs([['Home', '#/'], ['Directory', '#/directory'], [b.name]])}
      <div class="pagehead"><div><p class="eyebrow">${b.type_label} · ${b.district_name}</p><h1>${b.name}</h1>
        <div class="chips section">${statusPill(b.status)}${verifiedPill(b.verified)}${b.hoi_connected ? html`<span class="pill neutral noicon">Reports via HOI</span>` : ''}</div></div>
        <div class="btnrow"><a class="btn ghost" href="${href('/verify', { reg: b.reg_no })}">Check registration</a><a class="btn ghost" href="${href('/grievance', { reg: b.reg_no, district: b.district })}">Report a problem</a></div></div>
      <div class="split"><section class="card" aria-labelledby="reg-h"><h2 id="reg-h">Registration</h2>
        ${kv([['Registration no.', html`<span class="mono">${b.reg_no}</span>`], ['Status', statusPill(b.status)], ['Registered on', fmtDate(b.registered_on)], ['Valid until', fmtDate(b.valid_until)],
          ['Type', b.type_label], ['Capacity', b.capacity != null ? `${num(b.capacity)} ${b.capacity_unit}` : '—'], ...(b.beds != null ? [['Beds', num(b.beds)]] : []),
          ['Rating', b.rating != null ? `★ ${b.rating} / 5` : '—'], ['Languages', (b.languages || []).join(', ') || '—']])}
        ${b.status !== 'active' ? html`<p class="flag red section"><strong>This registration is ${b.status}.</strong> Ask the operator for a current registration before paying.</p>` : ''}</section>
        <section class="card" aria-labelledby="loc-h"><h2 id="loc-h">Location & contact</h2>
          ${kv([['District', b.district_name], ['Destination', b.destination_id ? html`<a href="${href('/destinations/' + b.destination_id)}">${b.destination_name}</a>` : '—']])}
          <p class="flag blue section">${b.contact}</p></section></div>
      ${lastUpdated(null)}`);
  });
}

export async function verify(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><h1>${t('verify')}</h1>
      <p>Check before you pay: enter the registration number from the certificate, bill or signboard.</p></div></div>
    <form class="card form" id="vf" novalidate>
      <div class="fld"><label class="lbl" for="reg_no">Registration number</label>
        <div class="searchbox"><input class="field mono" id="reg_no" name="reg_no" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="40" required value="${ctx.query.reg || ''}" placeholder="UK-HMS-RUD-00001" aria-describedby="reg-hint">
        <button class="btn primary" type="submit">Verify</button></div>
        <p class="hint" id="reg-hint">Format <span class="mono">UK-TYPE-DISTRICT-00000</span>, e.g. <span class="mono">UK-HMS-RUD-00001</span>. Prototype codes, not official. Or <a href="#/directory">browse the directory</a>.</p></div>
    </form>
    <div id="vres" class="section" aria-live="polite"></div>`);
  const form = $('#vf', el);
  const out = $('#vres', el);
  const run = async () => {
    clearErrors(form);
    const v = $('#reg_no', el).value.trim().toUpperCase();
    if (!v) { showErrors(form, { reg_no: 'Enter a registration number.' }); return; }
    setQuery({ reg: v });
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Checking…');
    try {
      const r = await api('/registry/verify', { query: { reg_no: v } });
      const b = r.business;
      let cls = 'bad', ico = '✕', head = 'Not found';
      if (r.found && r.valid) { cls = 'ok'; ico = '✓'; head = 'Verified: registration is active'; }
      else if (r.found) { cls = b?.status === 'pending' ? 'warn' : 'bad'; ico = '!'; head = `Found, but ${b?.status === 'expired' ? 'expired' : b?.status === 'suspended' ? 'suspended' : b?.status === 'pending' ? 'renewal pending' : 'not valid'}`; }
      mount(out, html`<div class="vres ${cls}" role="status"><div class="ico" aria-hidden="true">${ico}</div><div class="stack"><h2>${head}</h2><p>${r.message}</p>
        ${b ? html`${kv([['Business', html`<a href="${href('/directory/' + b.id)}">${b.name}</a>`], ['Registration no.', html`<span class="mono">${b.reg_no}</span>`], ['Type', b.type_label], ['District', b.district_name], ['Status', statusPill(b.status)], ['Valid until', fmtDate(b.valid_until)]])}` : ''}
        ${!r.found ? html`<p>If someone is operating without registration, you can <a href="${href('/grievance', { category: 'unregistered', reg: v })}">report an unregistered business</a>.</p>` : ''}</div></div>`);
      announce(head);
    } catch (e) {
      mount(out, errorBox(e, { retry: false }));
    } finally {
      busy(btn, false);
    }
  };
  form.addEventListener('submit', (e) => { e.preventDefault(); run(); });
  if (ctx.query.reg) await run();
}
