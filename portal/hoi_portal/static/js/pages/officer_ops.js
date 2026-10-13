// Officials' work queues and managers: applications (decide), grievances (assign / status / notes, SLA),
// advisories (create / edit / withdraw), events, businesses (suspend / reactivate), officers + audit (state admin).
import { html, mount, href, load, $, $$, raw, field, showErrors, clearErrors, apiFieldErrors, busy, fmtDate, fmtDateTime, relTime, statusPill, roadPill, impactPill, announce, errorBox, toast, num, empty, drawer, confirmDialog, table, titleCase, samplePill, collapseFilters, pager, moreList } from '../ui.js';
import { api, meta, user, role } from '../api.js';
import { setQuery } from '../router.js';
import { roleSubnav, advisoryRow, kv, bizRow } from './common.js';
import { timelineCard } from './grievance.js';

const isAdmin = () => role() === 'state_admin';
const head = (path, title, sub, extra = '') => html`${roleSubnav(path)}<div class="pagehead"><div><p class="eyebrow">Officials${isAdmin() ? ' · all districts' : ' · ' + (user()?.district_name || '')}</p><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ''}</div>${extra}</div>`;
const districtSel = (m, cur, name = 'district', label = 'District', all = 'All districts') => (isAdmin()
  ? html`<div class="fld"><label class="lbl" for="f-${name}">${label}</label><select class="field" id="f-${name}" name="${name}"><option value="">${all}</option>${m.districts.map((d) => html`<option value="${d.id}" ${cur === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></div>` : '');
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v != null));
const daysBetween = (a, b) => Math.round((new Date(a) - new Date(b)) / 86400000);

function slaPill(g) {
  if (g.resolved_at || ['resolved', 'closed'].includes(g.status)) return html`<span class="pill neutral sla">Done</span>`;
  const d = daysBetween(g.sla_due_at, Date.now());
  if (g.overdue || d < 0) return html`<span class="pill bad sla">Overdue ${Math.abs(d)} d</span>`;
  return html`<span class="pill ${d <= 2 ? 'warn' : 'info'} sla">Due in ${d} d</span>`;
}

// ------------------------------------------------------------------ applications
export async function applications(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { status: 'submitted', kind: '', district: '', ...ctx.query };
  mount(el, html`${head('/officer/applications', 'Applications queue', 'New registrations and renewals waiting for a decision. Approving issues a registration number.')}
    <form class="card tight filters" id="af">
      <div class="fld"><label class="lbl" for="f-status">Status</label><select class="field" id="f-status" name="status"><option value="">Any status</option>${m.application_statuses.map((s) => html`<option value="${s}" ${f.status === s ? raw('selected') : ''}>${titleCase(s)}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="f-kind">Kind</label><select class="field" id="f-kind" name="kind"><option value="">New and renewal</option><option value="new" ${f.kind === 'new' ? raw('selected') : ''}>New</option><option value="renewal" ${f.kind === 'renewal' ? raw('selected') : ''}>Renewal</option></select></div>
      ${districtSel(m, f.district)}</form>
    <div class="chips section" id="acount" aria-live="polite"></div><div id="al" class="section"></div>`);
  const form = $('#af', el);
  collapseFilters(form);
  const refresh = () => load($('#al', el), async () => {
    setQuery(f);
    const r = await api('/officer/applications', { query: clean({ ...f, page_size: 100 }) });
    const c = r.counts || {};
    mount($('#acount', el), html`${Object.entries(c).map(([k, v]) => html`${statusPill(k, `${titleCase(k)}: ${v}`)}`)}<span class="small muted">${r.total} in this view</span>`);
    if (!r.items.length) { mount($('#al', el), empty('Queue is empty', 'No applications match these filters.')); return; }
    const wire = () => $$('[data-open]', el).forEach((b) => b.addEventListener('click', () => openApp(b.dataset.open, m, refresh)));
    pager($('#al', el), r.items, (slice) => table([
      { key: 'id', label: 'Application', render: (a) => html`<button type="button" class="linkbtn" data-open="${a.id}">${a.id}</button>` },
      { key: 'business_name', label: 'Business' },
      { key: 'kind', label: 'Kind', render: (a) => (a.kind === 'renewal' ? html`Renewal <span class="mono small">${a.reg_no || ''}</span>` : 'New') },
      { key: 'type_label', label: 'Type' }, { key: 'district_name', label: 'District' },
      { key: 'submitted_at', label: 'Submitted', render: (a) => html`${fmtDate(a.submitted_at)} <span class="muted small">(${relTime(a.submitted_at)})</span>` },
      { key: 'docs', label: 'Documents', render: (a) => (a.missing_documents?.length ? html`<span class="pill warn">${a.missing_documents.length} missing</span>` : html`<span class="pill ok">Complete</span>`) },
      { key: 'status', label: 'Status', render: (a) => statusPill(a.status) },
    ], slice, 'Applications'), 12, wire);
    wire();
  }, { skel: 'list', n: 5 });
  form.addEventListener('change', () => { const fd = new FormData(form); ['status', 'kind', 'district'].forEach((k) => { f[k] = (fd.get(k) || '').toString(); }); refresh(); });
  await refresh();
}

function openApp(id, m, refresh) {
  const d = drawer('Application ' + id);
  load(d.body, async () => {
    const a = await api('/officer/applications/' + encodeURIComponent(id));
    const lbl = (k) => m.documents_checklist.find((x) => x.key === k)?.label || k;
    const open = ['submitted'].includes(a.status);
    mount(d.body, html`<h3>${a.business_name}</h3><div class="chips section">${statusPill(a.status)}<span class="pill neutral noicon">${a.kind === 'renewal' ? 'Renewal' : 'New'}</span>${a.synthetic ? html`<span class="pill syn">Synthetic</span>` : ''}</div>
      <div class="section">${kv([['Type', a.type_label], ['District', a.district_name], ['Destination', a.destination_name || '—'], ['Capacity', `${a.capacity} ${a.capacity_unit}`], ...(a.beds != null ? [['Beds', a.beds]] : []), ['Languages', (a.languages || []).join(', ')], ['Registration no.', a.reg_no || 'issued on approval'], ['Submitted', fmtDateTime(a.submitted_at)], ['Applicant notes', a.notes || '—']])}</div>
      <h3 class="section">Required documents (ticked by applicant)</h3>
      <ul class="plain stack section">${(a.required_documents || []).map((k) => html`<li>${a.documents?.[k] ? html`<span class="pill ok">Ticked</span>` : html`<span class="pill bad">Missing</span>`} ${lbl(k)}</li>`)}</ul>
      <h3 class="section">History</h3><ol class="timeline section">${(a.history || []).map((h) => html`<li class="done"><strong>${titleCase(h.action)}</strong><div class="when">${fmtDateTime(h.at)}${h.by ? ' · ' + h.by : ''}</div>${h.reason ? html`<div>${h.reason}</div>` : ''}</li>`)}</ol>
      ${open ? html`<form class="card form section" id="decf" novalidate><h3>Decision</h3>
        <fieldset class="fld"><legend class="lbl">Action</legend><div class="stack">
          <label class="check"><input type="radio" name="action" value="approve"><span><strong>Approve</strong> and issue a registration number</span></label>
          <label class="check"><input type="radio" name="action" value="request_changes" ${a.missing_documents?.length ? raw('checked') : ''}><span><strong>Request changes</strong> (applicant can update and resubmit)</span></label>
          <label class="check"><input type="radio" name="action" value="reject"><span><strong>Reject</strong></span></label></div></fieldset>
        ${field({ id: 'reason', label: 'Reason / remark for the applicant', type: 'textarea', rows: 3, value: a.missing_documents?.length ? `Please tick and keep ready: ${a.missing_documents.map(lbl).join(', ')}.` : '', hint: 'Required for request changes and reject. Shown to the applicant.', attrs: 'maxlength="1000"' })}
        <button class="btn primary" type="submit">Record decision</button></form>` : html`<p class="flag blue section">This application is ${titleCase(a.status).toLowerCase()}; no decision is pending.${a.reason ? ' Remark: ' + a.reason : ''}</p>`}
      <div id="decres" aria-live="polite"></div>`);
    const form = $('#decf', d.body);
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const action = fd.get('action');
      const reason = (fd.get('reason') || '').toString().trim();
      const errs = {};
      if (!action) errs.action = 'Choose an action.';
      if (action && action !== 'approve' && reason.length < 3) errs.reason = 'Give a reason so the applicant knows what to do.';
      if (Object.keys(errs).length) { showErrors(form, errs, errs.action); return; }
      clearErrors(form);
      if (action === 'reject' && !(await confirmDialog(`Reject application ${a.id}?`, { ok: 'Reject', danger: true }))) return;
      const btn = form.querySelector('button[type=submit]');
      busy(btn, true, 'Saving…');
      try {
        const r = await api(`/officer/applications/${encodeURIComponent(a.id)}/decision`, { method: 'POST', body: { action, reason: reason || null } });
        mount($('#decres', d.body), html`<p class="flag green" role="status"><strong>${titleCase(r.status)}.</strong>${r.reg_no ? html` Registration number <span class="mono">${r.reg_no}</span> issued.` : ''}</p>`);
        form.remove();
        toast(`Application ${a.id}: ${titleCase(r.status).toLowerCase()}`);
        refresh();
      } catch (err) {
        busy(btn, false);
        mount($('#decres', d.body), errorBox(err, { retry: false }));
      }
    });
  });
}

// ------------------------------------------------------------------ grievances
const TRANS = { received: ['assigned', 'in_progress', 'resolved', 'closed'], assigned: ['in_progress', 'resolved', 'closed'], in_progress: ['resolved', 'closed'], resolved: ['closed', 'in_progress'], closed: [] };

export async function grievances(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { status: '', overdue: '', category: '', district: '', ...ctx.query };
  mount(el, html`${head('/officer/grievances', 'Grievance queue', `Service level: ${m.grievance_sla_days} days from filing (assumed). Overdue items first.`)}
    <form class="card tight filters" id="gf">
      <div class="fld"><label class="lbl" for="f-status">Status</label><select class="field" id="f-status" name="status"><option value="">Any status</option>${m.grievance_statuses.map((s) => html`<option value="${s}" ${f.status === s ? raw('selected') : ''}>${titleCase(s)}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="f-overdue">SLA</label><select class="field" id="f-overdue" name="overdue"><option value="">All</option><option value="true" ${f.overdue === 'true' ? raw('selected') : ''}>Overdue only</option></select></div>
      <div class="fld"><label class="lbl" for="f-category">Category</label><select class="field" id="f-category" name="category"><option value="">All categories</option>${m.grievance_categories.map((c) => html`<option value="${c.key}" ${f.category === c.key ? raw('selected') : ''}>${c.label}</option>`)}</select></div>
      ${districtSel(m, f.district)}</form>
    <div class="chips section" id="gcount" aria-live="polite"></div><div id="gl" class="section"></div>`);
  const form = $('#gf', el);
  collapseFilters(form);
  const refresh = () => load($('#gl', el), async () => {
    setQuery(f);
    const r = await api('/officer/grievances', { query: clean({ ...f, page_size: 100 }) });
    mount($('#gcount', el), html`<span class="pill info">${r.open ?? '—'} open</span><span class="pill ${r.overdue ? 'bad' : 'ok'}">${r.overdue ?? 0} overdue</span><span class="small muted">${r.total} in this view</span>`);
    const items = r.items.slice().sort((a, b) => (b.overdue - a.overdue) || (a.sla_due_at || '').localeCompare(b.sla_due_at || ''));
    if (!items.length) { mount($('#gl', el), empty('No grievances match', 'Nothing in the queue for these filters.')); return; }
    const wire = () => $$('[data-open]', el).forEach((b) => b.addEventListener('click', () => openGrievance(b.dataset.open, refresh)));
    pager($('#gl', el), items, (slice) => table([
      { key: 'ticket_id', label: 'Ticket', render: (g) => html`<button type="button" class="linkbtn" data-open="${g.ticket_id}">${g.ticket_id}</button>` },
      { key: 'category_label', label: 'Category' }, { key: 'district_name', label: 'District' },
      { key: 'created_at', label: 'Filed', render: (g) => fmtDate(g.created_at) },
      { key: 'assigned_to', label: 'Assigned to', render: (g) => g.assigned_to || '—' },
      { key: 'status', label: 'Status', render: (g) => statusPill(g.status) }, { key: 'sla', label: 'SLA', render: slaPill },
    ], slice, 'Grievances'), 12, wire);
    wire();
  }, { skel: 'list', n: 5 });
  form.addEventListener('change', () => { const fd = new FormData(form); ['status', 'overdue', 'category', 'district'].forEach((k) => { f[k] = (fd.get(k) || '').toString(); }); refresh(); });
  await refresh();
}

function openGrievance(id, refresh) {
  const d = drawer('Grievance ' + id);
  const draw = () => load(d.body, async () => {
    const g = await api('/officer/grievances/' + encodeURIComponent(id));
    const next = TRANS[g.status] || [];
    mount(d.body, html`<div class="chips">${statusPill(g.status)}${slaPill(g)}</div>
      <section class="card section"><h3>Complaint</h3><p>${g.description || '—'}</p>
        ${kv([['Business reg. no.', g.business_reg_no ? html`<a href="${href('/verify', { reg: g.business_reg_no })}" class="mono">${g.business_reg_no}</a>` : '—'], ['Contact (private)', g.contact || 'not given'], ['Assigned to', g.assigned_to || '—'], ['SLA due', fmtDateTime(g.sla_due_at)]])}</section>
      ${next.length ? html`<form class="card form section" id="guf" novalidate><h3>Update</h3>
        <div class="grid g2">${field({ id: 'status', label: 'New status', type: 'select', options: [{ value: '', label: 'Keep ' + titleCase(g.status) }, ...next.map((s) => ({ value: s, label: titleCase(s) }))] })}
        ${field({ id: 'assign_to', label: 'Assign to', opt: true, value: g.assigned_to || '', placeholder: user()?.username || '', attrs: 'maxlength="60"' })}</div>
        ${field({ id: 'note', label: 'Note', type: 'textarea', rows: 3, opt: true, hint: 'Public notes are visible on the tracking page; keep them factual and polite.', attrs: 'maxlength="1000"' })}
        <label class="check"><input type="checkbox" name="public" checked> Visible to the person who filed (public note)</label>
        <div class="btnrow section"><button class="btn primary" type="submit">Save update</button>${next.includes('resolved') ? html`<button type="button" class="btn ok" id="quickres">Mark resolved</button>` : ''}</div>
        <div id="gures" aria-live="polite"></div></form>` : html`<p class="flag blue section">This grievance is closed.</p>`}
      <div class="section">${timelineCard(g, { officer: true })}</div>`);
    const form = $('#guf', d.body);
    const send = async (body, btn) => {
      busy(btn, true, 'Saving…');
      try {
        await api('/officer/grievances/' + encodeURIComponent(id), { method: 'POST', body });
        toast('Grievance updated');
        refresh();
        draw();
      } catch (err) {
        busy(btn, false);
        if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message);
        else mount($('#gures', d.body), errorBox(err, { retry: false }));
      }
    };
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const body = { status: fd.get('status') || null, note: (fd.get('note') || '').toString().trim() || null, public: fd.get('public') === 'on', assign_to: (fd.get('assign_to') || '').toString().trim() || null };
      if (body.assign_to === (g.assigned_to || null)) body.assign_to = null;
      if (!body.status && !body.note && !body.assign_to) { showErrors(form, { note: 'Change the status, assign, or add a note.' }); return; }
      send(clean(body), form.querySelector('button[type=submit]'));
    });
    $('#quickres', d.body)?.addEventListener('click', (e) => {
      const note = $('#note', d.body).value.trim() || 'Resolved by the district tourism office.';
      send({ status: 'resolved', note, public: true }, e.currentTarget);
    });
  });
  draw();
}

// ------------------------------------------------------------------ advisories
function toLocalInput(iso) {
  if (!iso) return '';
  const dt = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}T${p(dt.getHours())}:${p(dt.getMinutes())}`;
}
function advForm(m, a = {}, isNew = true) {
  const dist = a.district || (isAdmin() ? '' : user()?.district);
  const in3 = new Date(Date.now() + 3 * 86400000).toISOString();
  return html`<form class="form" id="advf" novalidate>
    <div class="grid g2">${field({ id: 'kind', label: 'Kind', type: 'select', value: a.kind || 'road', options: m.advisory_kinds.map((k) => ({ value: k, label: titleCase(k) })) })}
    ${field({ id: 'status', label: 'Road status', type: 'select', value: a.status || 'caution', options: [{ value: '', label: 'Not applicable' }, ...m.road_statuses.map((k) => ({ value: k, label: titleCase(k) }))], hint: 'Shown as Open / Caution / Closed with text, not colour only.' })}</div>
    ${field({ id: 'title', label: 'Title', required: true, value: a.title || '', placeholder: 'e.g. Single-lane traffic near Sonprayag', attrs: 'maxlength="140"' })}
    ${field({ id: 'segment', label: 'Road segment / area', opt: true, value: a.segment || '', attrs: 'maxlength="140"' })}
    ${field({ id: 'reason', label: 'Reason and advice', type: 'textarea', rows: 3, opt: true, value: a.reason || '', attrs: 'maxlength="500"' })}
    <div class="grid g2">${isNew && isAdmin() ? field({ id: 'district', label: 'District', type: 'select', required: true, value: dist, options: [{ value: '', label: 'Choose a district' }, ...m.districts.map((d) => ({ value: d.id, label: d.name }))] }) : ''}
    ${field({ id: 'destination_id', label: 'Destination', type: 'select', opt: true, value: a.destination_id || '', options: [{ value: '', label: 'Whole district' }, ...m.destinations.filter((d) => !dist || d.district === dist).map((d) => ({ value: d.id, label: d.name }))] })}
    ${field({ id: 'expires_at', label: 'Expires at', type: 'datetime-local', value: toLocalInput(a.expires_at || in3), hint: 'Local time. Expired advisories disappear from public pages.' })}</div>
    <div class="btnrow"><button class="btn primary" type="submit">${isNew ? 'Publish advisory' : 'Save changes'}</button></div><div id="advres" aria-live="polite"></div></form>`;
}
function readAdv(form, isNew) {
  const fd = new FormData(form);
  const s = (k) => (fd.get(k) || '').toString().trim();
  const body = { kind: s('kind'), status: s('status') || null, title: s('title'), segment: s('segment') || null, reason: s('reason') || null, destination_id: s('destination_id') || null, expires_at: s('expires_at') ? new Date(s('expires_at')).toISOString() : null };
  if (isNew && isAdmin()) body.district = s('district') || null;
  const errs = {};
  if (body.title.length < 3) errs.title = 'Give a short title (at least 3 characters).';
  if (isNew && isAdmin() && !body.district) errs.district = 'Choose the district.';
  if (body.expires_at && new Date(body.expires_at) < new Date()) errs.expires_at = 'Choose a time in the future.';
  return { body, errs };
}

export async function advisories(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { district: '', ...ctx.query };
  mount(el, html`${head('/officer/advisories', 'Advisories manager', 'Publish road, weather and general advisories. They appear on destination pages, the helplines page and the home page until they expire.')}
    <div class="split"><section class="card" aria-labelledby="al-h"><div class="sechead"><h2 id="al-h">Advisories</h2>${isAdmin() ? html`<form id="adf">${districtSel(m, f.district)}</form>` : ''}</div><div id="advl"></div></section>
      <section class="card" aria-labelledby="an-h"><h2 id="an-h">New advisory</h2><div id="newadv"></div></section></div>`);
  const refresh = () => load($('#advl', el), async () => {
    setQuery(f);
    const r = await api('/officer/advisories', { query: clean(f) });
    const items = r.items.slice().sort((a, b) => (b.active !== false) - (a.active !== false) || (b.posted_at || '').localeCompare(a.posted_at || ''));
    mount($('#advl', el), items.length ? moreList(items, (a) => advisoryRow(a, { manage: true }), 6) : empty('No advisories', 'Nothing posted for this scope.'));
    $$('[data-edit]', el).forEach((b) => b.addEventListener('click', () => editAdv(items.find((x) => x.id === b.dataset.edit), m, refresh)));
    $$('[data-expire]', el).forEach((b) => b.addEventListener('click', async () => {
      if (!(await confirmDialog('Withdraw this advisory now? It will stop showing on public pages.', { ok: 'Withdraw', danger: true }))) return;
      try { await api('/officer/advisories/' + encodeURIComponent(b.dataset.expire), { method: 'DELETE' }); toast('Advisory withdrawn'); refresh(); } catch (e) { toast(e.message, 'err'); }
    }));
  }, { skel: 'list', n: 3 });
  const drawNew = () => {
    mount($('#newadv', el), advForm(m));
    const form = $('#advf', el);
    form.querySelector('#district')?.addEventListener('change', (e) => {
      const sel = form.querySelector('#destination_id');
      mount(sel, html`<option value="">Whole district</option>${m.destinations.filter((d) => d.district === e.target.value).map((d) => html`<option value="${d.id}">${d.name}</option>`)}`);
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const { body, errs } = readAdv(form, true);
      if (Object.keys(errs).length) { showErrors(form, errs); return; }
      clearErrors(form);
      const btn = form.querySelector('button[type=submit]');
      busy(btn, true, 'Publishing…');
      try {
        await api('/officer/advisories', { method: 'POST', body: clean(body) });
        toast('Advisory published');
        drawNew();
        refresh();
      } catch (err) {
        busy(btn, false);
        if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message); else mount($('#advres', el), errorBox(err, { retry: false }));
      }
    });
  };
  $('#adf', el)?.addEventListener('change', (e) => { f.district = e.target.value; refresh(); });
  drawNew();
  await refresh();
}
function editAdv(a, m, refresh) {
  const d = drawer('Edit advisory');
  mount(d.body, html`<p class="small muted">${a.district_name} · posted ${fmtDateTime(a.posted_at)}</p>${advForm(m, a, false)}`);
  const form = $('#advf', d.body);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const { body, errs } = readAdv(form, false);
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Saving…');
    try {
      await api('/officer/advisories/' + encodeURIComponent(a.id), { method: 'PATCH', body });
      toast('Advisory updated');
      d.close();
      refresh();
    } catch (err) {
      busy(btn, false);
      if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message); else mount($('#advres', d.body), errorBox(err, { retry: false }));
    }
  });
}

// ------------------------------------------------------------------ events
function evForm(m, ev = {}, isNew = true) {
  const dist = (ev.districts && ev.districts[0]) || (isAdmin() ? '' : user()?.district);
  return html`<form class="form" id="evf" novalidate>
    ${field({ id: 'name', label: 'Event name', required: true, value: ev.name || '', attrs: 'maxlength="140"' })}
    ${field({ id: 'description', label: 'Description', type: 'textarea', rows: 3, opt: true, value: ev.description || '', attrs: 'maxlength="1000"' })}
    <div class="grid g2">${field({ id: 'start_date', label: 'Start date', type: 'date', required: true, value: ev.start_date || '' })}${field({ id: 'end_date', label: 'End date', type: 'date', opt: true, value: ev.end_date || '' })}</div>
    <div class="grid g2">${field({ id: 'crowd_impact', label: 'Expected crowd impact', type: 'select', value: ev.crowd_impact || 'low', options: ['low', 'medium', 'high'].map((x) => ({ value: x, label: titleCase(x) })) })}
    ${isNew && isAdmin() ? field({ id: 'district', label: 'District', type: 'select', required: true, value: dist, options: [{ value: '', label: 'Choose a district' }, ...m.districts.map((d) => ({ value: d.id, label: d.name }))] }) : ''}</div>
    <fieldset class="fld"><legend class="lbl">Destinations <span class="opt">(optional)</span></legend><div class="chips" id="evdest">${destChecks(m, dist, ev.destination_ids || [])}</div></fieldset>
    <button class="btn primary" type="submit">${isNew ? 'Add event' : 'Save changes'}</button><div id="evres" aria-live="polite"></div></form>`;
}
const destChecks = (m, dist, sel) => {
  const list = m.destinations.filter((d) => !dist || d.district === dist);
  return list.length && dist ? html`${list.map((d) => html`<label class="check"><input type="checkbox" name="destination_ids" value="${d.id}" ${sel.includes(d.id) ? raw('checked') : ''}>${d.name}</label>`)}` : html`<span class="muted small">Choose a district first.</span>`;
};
function readEv(form, isNew) {
  const fd = new FormData(form);
  const s = (k) => (fd.get(k) || '').toString().trim();
  const body = { name: s('name'), description: s('description') || null, start_date: s('start_date'), end_date: s('end_date') || null, crowd_impact: s('crowd_impact'), destination_ids: fd.getAll('destination_ids').map(String) };
  if (isNew && isAdmin()) body.district = s('district') || null;
  const errs = {};
  if (body.name.length < 3) errs.name = 'Enter the event name.';
  if (!body.start_date) errs.start_date = 'Choose the start date.';
  if (body.end_date && body.end_date < body.start_date) errs.end_date = 'The end date must be on or after the start date.';
  if (isNew && isAdmin() && !body.district) errs.district = 'Choose the district.';
  return { body, errs };
}
export async function events(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { district: '', ...ctx.query };
  mount(el, html`${head('/officer/events', 'Events manager', 'District events appear in the public festival calendar with their crowd impact.')}
    <div class="split"><section class="card"><div class="sechead"><h2>Posted events</h2>${isAdmin() ? html`<form id="edf">${districtSel(m, f.district)}</form>` : ''}</div><div id="evl"></div></section>
      <section class="card"><h2>New event</h2><div id="newev"></div></section></div>`);
  const refresh = () => load($('#evl', el), async () => {
    setQuery(f);
    const r = await api('/officer/events', { query: clean(f) });
    mount($('#evl', el), r.items.length ? html`<div class="list">${r.items.map((e) => html`<div class="item"><div class="main"><strong>${e.name}</strong><div class="sub">${e.start_date ? fmtDate(e.start_date) + (e.end_date && e.end_date !== e.start_date ? ' to ' + fmtDate(e.end_date) : '') : e.window} · ${(e.destination_names || []).join(', ') || (e.district_names || []).join(', ')}</div></div>
      <div class="side">${impactPill(e.crowd_impact)}${e.sample ? samplePill() : ''}<button type="button" class="btn sm ghost" data-edit="${e.id}">Edit</button><button type="button" class="btn sm danger" data-del="${e.id}">Delete</button></div></div>`)}</div>` : empty('No district events', 'Curated festivals are listed in the public calendar; add local events here.'));
    $$('[data-edit]', el).forEach((b) => b.addEventListener('click', () => {
      const ev = r.items.find((x) => x.id === b.dataset.edit);
      const d = drawer('Edit event');
      mount(d.body, evForm(m, ev, false));
      const form = $('#evf', d.body);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const { body, errs } = readEv(form, false);
        if (Object.keys(errs).length) { showErrors(form, errs); return; }
        try { await api('/officer/events/' + encodeURIComponent(ev.id), { method: 'PATCH', body }); toast('Event updated'); d.close(); refresh(); } catch (err) { mount($('#evres', d.body), errorBox(err, { retry: false })); }
      });
    }));
    $$('[data-del]', el).forEach((b) => b.addEventListener('click', async () => {
      if (!(await confirmDialog('Delete this event?', { ok: 'Delete', danger: true }))) return;
      try { await api('/officer/events/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' }); toast('Event deleted'); refresh(); } catch (e) { toast(e.message, 'err'); }
    }));
  }, { skel: 'list', n: 3 });
  const drawNew = () => {
    mount($('#newev', el), evForm(m));
    const form = $('#evf', el);
    form.querySelector('#district')?.addEventListener('change', (e) => mount($('#evdest', el), destChecks(m, e.target.value, [])));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const { body, errs } = readEv(form, true);
      if (Object.keys(errs).length) { showErrors(form, errs); return; }
      clearErrors(form);
      const btn = form.querySelector('button[type=submit]');
      busy(btn, true, 'Saving…');
      try { await api('/officer/events', { method: 'POST', body: clean(body) }); toast('Event added'); drawNew(); refresh(); } catch (err) {
        busy(btn, false);
        if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message); else mount($('#evres', el), errorBox(err, { retry: false }));
      }
    });
  };
  $('#edf', el)?.addEventListener('change', (e) => { f.district = e.target.value; refresh(); });
  drawNew();
  await refresh();
}

// ------------------------------------------------------------------ businesses
export async function businesses(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { q: '', status: '', type: '', district: '', page: '1', ...ctx.query };
  mount(el, html`${head('/officer/businesses', 'Business registry', 'Suspend a registration after an inspection or reactivate it. Every change is written to the audit log.')}
    <form class="card tight filters" id="bf"><div class="fld"><label class="lbl" for="f-q">Name or reg. no.</label><input class="field" id="f-q" name="q" type="search" value="${f.q}"></div>
      <div class="fld"><label class="lbl" for="f-st">Status</label><select class="field" id="f-st" name="status"><option value="">Any</option>${m.business_statuses.map((s) => html`<option value="${s}" ${f.status === s ? raw('selected') : ''}>${titleCase(s)}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="f-ty">Type</label><select class="field" id="f-ty" name="type"><option value="">Any</option>${m.business_types.map((t) => html`<option value="${t.key}" ${f.type === t.key ? raw('selected') : ''}>${t.label}</option>`)}</select></div>
      ${districtSel(m, f.district)}</form>
    <p class="small muted section" id="bcount" aria-live="polite"></p><div id="bl"></div>`);
  const form = $('#bf', el);
  collapseFilters(form);
  const refresh = () => load($('#bl', el), async () => {
    setQuery(f);
    const r = await api('/officer/businesses', { query: clean({ ...f, page_size: 12 }) });
    const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    $('#bcount', el).textContent = `${r.total} businesses · page ${r.page} of ${pages}`;
    mount($('#bl', el), r.items.length ? html`<div class="list">${r.items.map((b) => html`<div class="item"><div class="main"><a class="t" href="${href('/directory/' + b.id)}">${b.name}</a><div class="sub">${b.type_label} · ${b.district_name} · <span class="mono">${b.reg_no}</span> · valid until ${fmtDate(b.valid_until)}</div></div>
      <div class="side">${statusPill(b.status)}${b.status === 'suspended' ? html`<button type="button" class="btn sm ok" data-st="active" data-id="${b.id}">Reactivate</button>` : b.status === 'active' ? html`<button type="button" class="btn sm danger" data-st="suspended" data-id="${b.id}">Suspend</button>` : ''}</div></div>`)}</div>
      <nav class="pager" aria-label="Pages"><button type="button" class="btn sm ghost" data-pg="${r.page - 1}" ${r.page <= 1 ? raw('disabled') : ''}>Previous</button><span class="small">Page ${r.page} of ${pages}</span><button type="button" class="btn sm ghost" data-pg="${r.page + 1}" ${r.page >= pages ? raw('disabled') : ''}>Next</button></nav>` : empty('No businesses match'));
    $$('[data-pg]', el).forEach((b) => b.addEventListener('click', () => { f.page = b.dataset.pg; refresh(); }));
    $$('[data-st]', el).forEach((b) => b.addEventListener('click', () => {
      const dlg = drawer(b.dataset.st === 'suspended' ? 'Suspend registration' : 'Reactivate registration');
      mount(dlg.body, html`<form class="form" id="stf" novalidate>${field({ id: 'reason', label: 'Reason (recorded in the audit log)', type: 'textarea', rows: 3, required: true, attrs: 'maxlength="500"' })}<button class="btn ${b.dataset.st === 'suspended' ? 'danger' : 'primary'}" type="submit">${b.dataset.st === 'suspended' ? 'Suspend' : 'Reactivate'}</button><div id="stres"></div></form>`);
      const sf = $('#stf', dlg.body);
      sf.addEventListener('submit', async (e) => {
        e.preventDefault();
        const reason = $('#reason', dlg.body).value.trim();
        if (reason.length < 3) { showErrors(sf, { reason: 'Give a reason (at least 3 characters).' }); return; }
        try { await api(`/officer/businesses/${encodeURIComponent(b.dataset.id)}/status`, { method: 'POST', body: { status: b.dataset.st, reason } }); toast('Status updated'); dlg.close(); refresh(); } catch (err) { mount($('#stres', dlg.body), errorBox(err, { retry: false })); }
      });
    }));
  }, { skel: 'list', n: 5 });
  let tmr;
  form.addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(() => { const fd = new FormData(form); ['q', 'status', 'type', 'district'].forEach((k) => { f[k] = (fd.get(k) || '').toString().trim(); }); f.page = '1'; refresh(); }, 300); });
  form.addEventListener('submit', (e) => e.preventDefault());
  await refresh();
}

// ------------------------------------------------------------------ state admin: officers + audit
export async function officers(ctx) {
  const el = ctx.el;
  const m = await meta();
  mount(el, html`${head('/officer/officers', 'Officer management', 'Create district officer accounts and disable accounts that should no longer have access.')}
    <div class="split"><section class="card"><h2>Accounts</h2><div id="ul"></div></section>
      <section class="card"><h2>New district officer</h2><form class="form" id="of" novalidate>
        ${field({ id: 'username', label: 'Username', required: true, attrs: 'maxlength="40" autocomplete="off" autocapitalize="off" spellcheck="false"' })}
        ${field({ id: 'label', label: 'Display name', opt: true, placeholder: 'District tourism officer, Chamoli', attrs: 'maxlength="80"' })}
        ${field({ id: 'district', label: 'District', type: 'select', required: true, options: [{ value: '', label: 'Choose a district' }, ...m.districts.map((d) => ({ value: d.id, label: d.name }))] })}
        ${field({ id: 'password', label: 'Initial password', type: 'password', required: true, hint: 'At least 10 characters. Share it securely, never by chat or email in plain text.', attrs: 'autocomplete="new-password" maxlength="200"' })}
        <button class="btn primary" type="submit">Create officer</button><div id="ores" aria-live="polite"></div></form></section></div>`);
  const refresh = () => load($('#ul', el), async () => {
    const r = await api('/admin/users');
    mount($('#ul', el), table([
      { key: 'username', label: 'Username' }, { key: 'role_label', label: 'Role' }, { key: 'district_name', label: 'District', render: (u) => u.district_name || 'All' },
      { key: 'last_login', label: 'Last sign-in', render: (u) => (u.last_login ? relTime(u.last_login) : 'never') },
      { key: 'active', label: 'Status', render: (u) => (u.active ? html`<span class="pill ok">Active</span>` : html`<span class="pill bad">Disabled</span>`) },
      { key: 'act', label: 'Action', render: (u) => (u.id === user()?.id ? html`<span class="muted small">You</span>` : html`<button type="button" class="btn sm ${u.active ? 'danger' : 'ok'}" data-uid="${u.id}" data-on="${String(!u.active)}">${u.active ? 'Disable' : 'Enable'}</button>`) },
    ], r.items, 'Accounts'));
    $$('[data-uid]', el).forEach((b) => b.addEventListener('click', async () => {
      const on = b.dataset.on === 'true';
      if (!on && !(await confirmDialog('Disable this account? Its sessions stop working immediately.', { ok: 'Disable', danger: true }))) return;
      try { await api('/admin/users/' + encodeURIComponent(b.dataset.uid), { method: 'PATCH', body: { active: on } }); toast(on ? 'Account enabled' : 'Account disabled'); refresh(); } catch (e) { toast(e.message, 'err'); }
    }));
  }, { skel: 'list', n: 4 });
  const form = $('#of', el);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = { username: (fd.get('username') || '').toString().trim(), label: (fd.get('label') || '').toString().trim() || null, district: fd.get('district'), password: (fd.get('password') || '').toString() };
    const errs = {};
    if (!/^[A-Za-z0-9._-]{3,40}$/.test(body.username)) errs.username = 'Use 3-40 letters, digits, dot, dash or underscore.';
    if (!body.district) errs.district = 'Choose the district.';
    if (body.password.length < 10) errs.password = 'At least 10 characters.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Creating…');
    try { const u = await api('/admin/officers', { method: 'POST', body }); toast(`Officer ${u.username} created`); form.reset(); refresh(); } catch (err) {
      if (err.status === 409) showErrors(form, { username: err.message }); else if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message); else mount($('#ores', el), errorBox(err, { retry: false }));
    } finally { busy(btn, false); }
  });
  await refresh();
}

export async function audit(ctx) {
  const el = ctx.el;
  const m = await meta();
  const f = { district: '', ...ctx.query };
  mount(el, html`${head('/officer/audit', 'Audit log', 'Every sign-in, decision and change, newest first.')}<form class="card tight filters" id="auf">${districtSel(m, f.district)}</form><div id="aul" class="section"></div>`);
  const refresh = () => load($('#aul', el), async () => {
    setQuery(f);
    const r = await api('/admin/audit', { query: clean({ ...f, limit: 200 }) });
    mount($('#aul', el), r.items.length ? table([{ key: 'ts', label: 'When', render: (a) => fmtDateTime(a.ts) }, { key: 'actor', label: 'Who' }, { key: 'action', label: 'Action' }, { key: 'target', label: 'Target' }, { key: 'detail', label: 'Detail' }, { key: 'district', label: 'District', render: (a) => m.districts.find((d) => d.id === a.district)?.name || '—' }], r.items, `Latest ${r.items.length} entries`) : empty('No entries'));
  }, { skel: 'list', n: 5 });
  $('#auf', el).addEventListener('change', (e) => { f.district = e.target.value; refresh(); });
  await refresh();
}
