// Business owner area: dashboard, apply/resubmit (stepper + document checklist), application detail with timeline,
// registration certificate + renew, monthly occupancy submission, API keys for HOI automated reporting.
import { html, mount, href, load, $, $$, raw, field, showErrors, clearErrors, apiFieldErrors, busy, copyBtn, crumbs, fmtDate, fmtDateTime, fmtMonth, statusPill, verifiedPill, announce, errorBox, toast, num, empty, confirmDialog, table, relTime } from '../ui.js';
import { api, meta } from '../api.js';
import { go, setQuery } from '../router.js';
import { lineChart } from '../charts.js';
import { roleSubnav, kv } from './common.js';

const head = (path, title, sub, extra = '') => html`${roleSubnav(path)}<div class="pagehead"><div><p class="eyebrow">Business</p><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ''}</div>${extra}</div>`;

function appTimeline(a) {
  const LBL = { submitted: 'Submitted', resubmitted: 'Resubmitted', changes_requested: 'Changes requested', approve: 'Approved', approved: 'Approved', reject: 'Rejected', rejected: 'Rejected', request_changes: 'Changes requested' };
  return html`<ol class="timeline">${(a.history || []).map((h) => html`<li class="done"><strong>${LBL[h.action] || h.action}</strong><div class="when">${fmtDateTime(h.at)}</div>${h.reason ? html`<div>Officer remark: ${h.reason}</div>` : ''}</li>`)}
    ${['submitted', 'changes_requested'].includes(a.status) ? html`<li class="todo"><strong>Officer decision</strong><div class="when">pending</div></li>` : ''}</ol>`;
}

export async function dashboard(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business', 'Business dashboard', 'Your registrations, applications and reporting.', html`<a class="btn primary" href="#/business/apply">Apply for a new registration</a>`)}<div id="bd"></div>`);
  await load($('#bd', el), async () => {
    const [d, lx, ag, nt] = await Promise.all([api('/business/dashboard'), api('/business/experiences').catch(() => null), api('/staffing/mine').catch(() => null), api('/business/notifications').catch(() => null)]);
    const s = d.summary || {};
    mount($('#bd', el), html`<div class="kpis">
        <div class="kpi"><span class="k">Registered businesses</span><span class="v">${s.businesses ?? d.businesses.length}</span></div>
        <div class="kpi ok"><span class="k">Active</span><span class="v">${s.active ?? '—'}</span></div>
        <div class="kpi ${s.renewals_due ? 'warn' : ''}"><span class="k">Renewals due (60-day window)</span><span class="v">${s.renewals_due ?? 0}</span></div>
        <div class="kpi"><span class="k">Applications open</span><span class="v">${s.applications_open ?? 0}</span></div>
        <div class="kpi ${s.changes_requested ? 'warn' : ''}"><span class="k">Changes requested</span><span class="v">${s.changes_requested ?? 0}</span></div></div>
      ${(lx?.host_businesses?.length || ag?.agencies?.length || nt?.unread) ? html`<section class="section" aria-labelledby="cm-h"><h2 id="cm-h" class="sr-only">Community and staffing</h2><div class="grid g3">
        ${lx?.host_businesses?.length ? html`<a class="scard ${lx.requests_pending ? 'w' : ''}" href="#/business/experiences"><div class="rowx"><span>Local experiences</span></div><div class="big">${lx.requests_pending} join request${lx.requests_pending === 1 ? '' : 's'} waiting</div><div class="small">${lx.total} experience${lx.total === 1 ? '' : 's'} listed · manage</div></a>` : ''}
        ${ag?.agencies?.length ? html`<a class="scard ${ag.summary.open_requests > ag.summary.responded ? 'w' : ''}" href="#/business/staffing"><div class="rowx"><span>Staffing agency</span></div><div class="big">${ag.summary.open_requests} HOI staffing request${ag.summary.open_requests === 1 ? '' : 's'}</div><div class="small">${ag.summary.open_offers} block offers · ${ag.summary.workers_offered} workers offered</div></a>` : ''}
        ${nt?.unread ? html`<div class="scard w"><div class="rowx"><span>Notifications</span></div><div class="big">${nt.unread} new</div><ul class="small plain">${nt.items.filter((n) => !n.read).slice(0, 3).map((n) => html`<li><a href="${href('/jobs/' + n.job_id)}">${n.title}</a></li>`)}</ul></div>` : ''}
      </div></section>` : ''}
      <section class="section" aria-labelledby="regs-h"><div class="sechead"><h2 id="regs-h">My registrations</h2></div>
        ${d.businesses.length ? html`<div class="grid g2">${d.businesses.map(bizCard)}</div>` : empty('No registrations yet', 'Apply for registration; once an officer approves it, it appears here with its registration number.', html`<a class="btn primary" href="#/business/apply">Apply now</a>`)}</section>
      <section class="section" aria-labelledby="apps-h"><div class="sechead"><h2 id="apps-h">My applications</h2></div>
        ${d.applications.length ? html`<div class="list">${d.applications.map((a) => html`<div class="item"><div class="main"><a class="t" href="${href('/business/applications/' + a.id)}">${a.business_name}</a>
          <div class="sub">${a.id} · ${a.kind === 'renewal' ? 'Renewal' : 'New registration'} · ${a.type_label} · ${a.district_name} · submitted ${fmtDate(a.submitted_at)}</div>
          ${a.reason ? html`<div class="sub"><strong>Officer remark:</strong> ${a.reason}</div>` : ''}</div>
          <div class="side">${statusPill(a.status)}${a.status === 'changes_requested' ? html`<a class="btn sm primary" href="${href('/business/apply', { edit: a.id })}">Update and resubmit</a>` : ''}</div></div>`)}</div>` : empty('No applications')}</section>`);
    $$('[data-renew]', el).forEach((b) => b.addEventListener('click', () => renew(b, b.dataset.renew)));
  });
}

function bizCard(b) {
  const tone = b.status === 'active' ? (b.renewal_due ? 'w' : '') : b.status === 'pending' ? 'w' : 'r';
  return html`<article class="scard ${tone}"><div class="rowx"><span>${b.type_label} · ${b.district_name}</span>${statusPill(b.status)}</div>
    <div class="big">${b.name}</div>
    <div class="small mono">${b.reg_no}</div>
    <div class="small">Valid until ${fmtDate(b.valid_until)}${b.days_to_expiry != null ? ` · ${b.days_to_expiry >= 0 ? b.days_to_expiry + ' days left' : 'expired ' + -b.days_to_expiry + ' days ago'}` : ''}</div>
    <div class="small">${b.reports_occupancy ? (b.hoi_connected ? 'Occupancy: reported automatically by HOI' : 'Occupancy: submit monthly') : 'No occupancy reporting needed'}${b.api_keys_active ? ` · ${b.api_keys_active} active API key(s)` : ''}</div>
    <div class="btnrow section"><a class="btn sm ghost" href="${href('/business/certificate/' + b.id)}">Certificate</a>
      ${b.open_renewal_id ? html`<a class="btn sm ghost" href="${href('/business/applications/' + b.open_renewal_id)}">Renewal under review</a>` : b.renewal_due || b.status === 'expired' ? html`<button type="button" class="btn sm primary" data-renew="${b.id}">Renew now</button>` : ''}
      ${b.reports_occupancy ? html`<a class="btn sm ghost" href="${href('/business/occupancy', { b: b.id })}">Occupancy</a>` : ''}</div></article>`;
}

async function renew(btn, id) {
  if (!(await confirmDialog('Submit a renewal application for this registration? An officer will review it.', { ok: 'Submit renewal' }))) return;
  busy(btn, true, 'Submitting…');
  try {
    const a = await api(`/business/businesses/${encodeURIComponent(id)}/renew`, { method: 'POST' });
    toast(`Renewal ${a.id} submitted`);
    go('/business/applications/' + a.id);
  } catch (e) {
    busy(btn, false);
    toast(e.message, 'err');
  }
}

export async function apply(ctx) {
  const el = ctx.el;
  const editId = ctx.query.edit;
  mount(el, html`${head('/business/apply', editId ? 'Update your application' : 'Apply for registration', 'Three short steps. No file upload in this prototype: tick the documents you have ready; the officer may ask to see them.')}<div id="ap"></div>`);
  await load($('#ap', el), async () => {
    const m = await meta();
    let existing = null;
    if (editId) existing = await api('/business/applications/' + encodeURIComponent(editId));
    const st = {
      business_name: existing?.business_name || '', type: existing?.type || ctx.query.type || '', district: existing?.district || '', destination_id: existing?.destination_id || '',
      capacity: existing?.capacity ?? '', beds: existing?.beds ?? '', languages: existing?.languages || ['Hindi'], documents: { ...(existing?.documents || {}) }, notes: existing?.notes || '',
    };
    let step = 0;
    const box = $('#ap', el);
    const STEPS = ['Business details', 'Documents checklist', 'Review & submit'];
    const unit = () => m.business_types.find((b) => b.key === st.type)?.capacity_unit || 'capacity';
    const isStay = () => ['hotel', 'homestay'].includes(st.type);
    const draw = () => {
      const req = m.required_documents[st.type] || [];
      mount(box, html`${existing ? html`<div class="flag amber"><strong>Officer remark:</strong> ${existing.reason || 'Please review and resubmit.'}${existing.missing_documents?.length ? html` Missing: ${existing.missing_documents.map((k) => m.documents_checklist.find((d) => d.key === k)?.label || k).join(', ')}.` : ''}</div>` : ''}
        <ol class="stepper" aria-label="Progress">${STEPS.map((s, i) => html`<li class="${i < step ? 'done' : ''}" ${i === step ? raw('aria-current="step"') : ''}><span class="n">${i < step ? '✓' : i + 1}</span>${s}<span class="sr-only">${i < step ? ' (done)' : i === step ? ' (current)' : ''}</span></li>`)}</ol>
        <form class="card form" id="apf" novalidate><h2 tabindex="-1" id="steph">Step ${step + 1} of 3: ${STEPS[step]}</h2>
        ${step === 0 ? html`
          ${field({ id: 'business_name', label: 'Business name', required: true, value: st.business_name, attrs: 'maxlength="120"' })}
          <div class="grid g2">${field({ id: 'type', label: 'Business type', type: 'select', required: true, value: st.type, options: [{ value: '', label: 'Choose a type' }, ...m.business_types.map((b) => ({ value: b.key, label: b.label }))] })}
          ${field({ id: 'district', label: 'District', type: 'select', required: true, value: st.district, options: [{ value: '', label: 'Choose a district' }, ...m.districts.map((d) => ({ value: d.id, label: d.name }))] })}</div>
          <div class="grid g2">${field({ id: 'destination_id', label: 'Nearest listed destination', type: 'select', opt: true, value: st.destination_id, options: [{ value: '', label: st.district ? 'None / not listed' : 'Choose a district first' }, ...m.destinations.filter((d) => d.district === st.district).map((d) => ({ value: d.id, label: d.name }))] })}
          ${field({ id: 'capacity', label: `Capacity (${unit()})`, type: 'number', required: true, value: st.capacity, attrs: 'min="1" max="5000" inputmode="numeric"' })}</div>
          ${isStay() ? field({ id: 'beds', label: 'Beds', type: 'number', opt: true, value: st.beds, attrs: 'min="0" max="20000" inputmode="numeric"' }) : ''}
          <fieldset class="fld"><legend class="lbl">Languages spoken</legend><div class="chips">${m.languages.map((l) => html`<label class="check"><input type="checkbox" name="languages" value="${l}" ${st.languages.includes(l) ? raw('checked') : ''}>${l}</label>`)}</div></fieldset>`
        : step === 1 ? html`
          <p>${st.type ? html`Required for a <strong>${m.business_types.find((b) => b.key === st.type)?.label}</strong> are marked <span class="pill info noicon">Required</span>.` : 'Choose a business type first.'} Tick each document you have ready.</p>
          <fieldset class="stack section"><legend class="sr-only">Documents</legend>${m.documents_checklist.map((d) => html`<label class="check ${req.includes(d.key) ? 'req' : ''}"><input type="checkbox" name="doc" value="${d.key}" ${st.documents[d.key] ? raw('checked') : ''}><span>${d.label} ${req.includes(d.key) ? html`<span class="pill info noicon">Required</span>` : html`<span class="muted small">(if applicable)</span>`}</span></label>`)}</fieldset>
          <p class="hint section" id="docnote" aria-live="polite"></p>
          <p class="flag amber section">Checklist for orientation only; verify requirements with the issuing authority. See <a href="#/rules">Rules & licences</a>.</p>`
        : html`
          ${kv([['Business name', st.business_name], ['Type', m.business_types.find((b) => b.key === st.type)?.label], ['District', m.districts.find((d) => d.id === st.district)?.name], ['Destination', m.destinations.find((d) => d.id === st.destination_id)?.name || 'None'],
            ['Capacity', `${st.capacity} ${unit()}`], ...(isStay() ? [['Beds', st.beds || '—']] : []), ['Languages', st.languages.join(', ')],
            ['Documents ticked', `${req.filter((k) => st.documents[k]).length} of ${req.length} required`]])}
          ${req.some((k) => !st.documents[k]) ? html`<p class="flag amber section">Some required documents are not ticked: ${req.filter((k) => !st.documents[k]).map((k) => m.documents_checklist.find((d) => d.key === k)?.label).join(', ')}. You can still submit, but the officer will likely request changes.</p>` : html`<p class="flag green section">All required documents are ticked.</p>`}
          ${field({ id: 'notes', label: 'Notes for the officer', type: 'textarea', opt: true, value: st.notes, rows: 3, attrs: 'maxlength="1000"' })}`}
        <div class="btnrow section">${step > 0 ? html`<button type="button" class="btn ghost" id="back">Back</button>` : ''}<button type="submit" class="btn primary">${step < 2 ? 'Continue' : existing ? 'Resubmit application' : 'Submit application'}</button></div></form>
        <div id="apres" aria-live="polite"></div>`);
      const form = $('#apf', box);
      if (step === 0) {
        form.querySelector('#district').addEventListener('change', (e) => { collect(form); st.district = e.target.value; st.destination_id = ''; draw(); $('#district', box).focus(); });
        form.querySelector('#type').addEventListener('change', (e) => { collect(form); st.type = e.target.value; draw(); $('#type', box).focus(); });
      }
      if (step === 1) {
        const upd = () => { const missing = req.filter((k) => !form.querySelector(`input[value="${k}"]`).checked).length; $('#docnote', box).textContent = req.length ? `${req.length - missing} of ${req.length} required documents ticked.` : ''; };
        form.addEventListener('change', upd);
        upd();
      }
      $('#back', box)?.addEventListener('click', () => { collect(form); step--; draw(); $('#steph', box).focus(); });
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        collect(form);
        if (step === 0) {
          const errs = {};
          if (st.business_name.length < 3) errs.business_name = 'Enter the business name (at least 3 characters).';
          if (!st.type) errs.type = 'Choose the business type.';
          if (!st.district) errs.district = 'Choose the district.';
          const c = Number(st.capacity);
          if (!Number.isInteger(c) || c < 1 || c > 5000) errs.capacity = 'Enter a whole number from 1 to 5000.';
          if (st.beds !== '' && (!Number.isInteger(Number(st.beds)) || Number(st.beds) < 0)) errs.beds = 'Enter a whole number or leave blank.';
          if (Object.keys(errs).length) { showErrors(form, errs); return; }
        }
        if (step < 2) { step++; draw(); $('#steph', box).focus(); return; }
        const body = {
          business_name: st.business_name, type: st.type, district: st.district, destination_id: st.destination_id || null, capacity: Number(st.capacity),
          beds: isStay() && st.beds !== '' ? Number(st.beds) : null, languages: st.languages, documents: Object.fromEntries(m.documents_checklist.map((d) => [d.key, !!st.documents[d.key]])), notes: st.notes || null,
        };
        const btn = form.querySelector('button[type=submit]');
        busy(btn, true, 'Submitting…');
        try {
          const a = existing ? await api('/business/applications/' + encodeURIComponent(existing.id), { method: 'PUT', body }) : await api('/business/applications', { method: 'POST', body });
          toast(`Application ${a.id} ${existing ? 'resubmitted' : 'submitted'}`);
          go('/business/applications/' + a.id);
        } catch (err) {
          busy(btn, false);
          if (err.status === 422 && Object.keys(apiFieldErrors(err)).length) { step = 0; draw(); showErrors($('#apf', box), apiFieldErrors(err), err.message); }
          else mount($('#apres', box), errorBox(err, { retry: false }));
        }
      });
    };
    const collect = (form) => {
      const fd = new FormData(form);
      if (step === 0) {
        ['business_name', 'type', 'district', 'destination_id', 'capacity', 'beds'].forEach((k) => { if (fd.has(k)) st[k] = (fd.get(k) || '').toString().trim(); });
        st.languages = fd.getAll('languages').map(String);
      } else if (step === 1) {
        const on = new Set(fd.getAll('doc').map(String));
        m.documents_checklist.forEach((d) => { st.documents[d.key] = on.has(d.key); });
      } else if (fd.has('notes')) st.notes = (fd.get('notes') || '').toString().trim();
    };
    draw();
  });
}

export async function application(ctx) {
  const el = ctx.el;
  mount(el, html`${head('', 'Application', '')}<div id="ad"></div>`);
  await load($('#ad', el), async () => {
    const [a, m] = await Promise.all([api('/business/applications/' + encodeURIComponent(ctx.params.id)), meta()]);
    const lbl = (k) => m.documents_checklist.find((d) => d.key === k)?.label || k;
    mount(el, html`${roleSubnav('')}${crumbs([['Dashboard', '#/business'], [a.id]])}
      <div class="pagehead"><div><p class="eyebrow">${a.kind === 'renewal' ? 'Renewal' : 'New registration'} · ${a.id}</p><h1>${a.business_name}</h1><div class="chips section">${statusPill(a.status)}${a.reg_no ? html`<span class="pill info noicon mono">${a.reg_no}</span>` : ''}</div></div>
        ${a.status === 'changes_requested' ? html`<a class="btn primary" href="${href('/business/apply', { edit: a.id })}">Update and resubmit</a>` : ''}</div>
      ${a.reason ? html`<p class="flag ${a.status === 'rejected' ? 'red' : a.status === 'approved' ? 'green' : 'amber'}"><strong>Officer remark:</strong> ${a.reason}</p>` : ''}
      ${a.status === 'approved' && a.business_id ? html`<p class="flag green">Approved. Registration number <strong class="mono">${a.reg_no}</strong>. <a href="${href('/business/certificate/' + a.business_id)}">View certificate</a></p>` : ''}
      <div class="split"><section class="card"><h2>Details</h2>${kv([['Type', a.type_label], ['District', a.district_name], ['Destination', a.destination_name || '—'], ['Capacity', `${a.capacity} ${a.capacity_unit}`], ...(a.beds != null ? [['Beds', a.beds]] : []), ['Languages', (a.languages || []).join(', ')], ['Submitted', fmtDateTime(a.submitted_at)], ['Updated', fmtDateTime(a.updated_at)]])}
          <h3 class="section">Documents</h3><ul class="plain stack section">${(a.required_documents || []).map((k) => html`<li>${a.documents?.[k] ? html`<span class="pill ok">Ticked</span>` : html`<span class="pill bad">Missing</span>`} ${lbl(k)}</li>`)}</ul></section>
        <section class="card"><h2>Status timeline</h2>${appTimeline(a)}</section></div>`);
  });
}

export async function certificate(ctx) {
  const el = ctx.el;
  mount(el, html`${head('', 'Registration certificate', '')}<div id="cd"></div>`);
  await load($('#cd', el), async () => {
    const b = await api('/business/businesses/' + encodeURIComponent(ctx.params.id));
    mount(el, html`${roleSubnav('')}${crumbs([['Dashboard', '#/business'], ['Certificate']])}
      <h1 class="sr-only">Registration certificate: ${b.name}</h1>
      <article class="cert" aria-label="Registration certificate">
        <p class="eyebrow">Tourism business registration · demo</p>
        <h2>${b.name}</h2>
        <p class="regno mono">${b.reg_no}</p>
        <div class="chips">${statusPill(b.status)}${verifiedPill(b.verified)}</div>
        ${kv([['Type', b.type_label], ['District', b.district_name], ['Destination', b.destination_name || '—'], ['Capacity', `${b.capacity} ${b.capacity_unit}`], ['Registered on', fmtDate(b.registered_on)], ['Valid until', fmtDate(b.valid_until)], ['Days left', b.days_to_expiry != null ? String(b.days_to_expiry) : '—']])}
        <p class="watermark">DEMO · not a real certificate</p>
      </article>
      <div class="btnrow section">${b.open_renewal_id ? html`<a class="btn ghost" href="${href('/business/applications/' + b.open_renewal_id)}">Renewal under review</a>` : html`<button type="button" class="btn primary" id="renew" ${b.renewal_due || b.status === 'expired' ? '' : raw('aria-describedby="rn-hint"')}>Renew registration</button>`}
        <button type="button" class="btn ghost" id="print">Print</button><a class="btn ghost" href="${href('/verify', { reg: b.reg_no })}">Public verification page</a></div>
      ${!b.renewal_due && b.status === 'active' && !b.open_renewal_id ? html`<p class="hint" id="rn-hint">Renewal opens 60 days before expiry. You can try now; the portal will tell you if it is too early.</p>` : ''}`);
    $('#print', el).addEventListener('click', () => window.print());
    $('#renew', el)?.addEventListener('click', (e) => renew(e.currentTarget, b.id));
  });
}

async function myStays() {
  const r = await api('/business/businesses');
  return r.items;
}
const bizSelect = (items, cur) => html`<div class="fld"><label class="lbl" for="bsel">Business</label><select class="field" id="bsel" name="b">${items.map((b) => html`<option value="${b.id}" ${b.id === cur ? raw('selected') : ''}>${b.name} (${b.reg_no})</option>`)}</select></div>`;

export async function occupancy(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business/occupancy', 'Monthly occupancy', 'Stays report room nights once a month. HOI-connected hotels report daily and automatically; days already reported by HOI are not overwritten.')}<div id="oc"></div>`);
  await load($('#oc', el), async () => {
    const all = await myStays();
    const stays = all.filter((b) => b.reports_occupancy);
    if (!stays.length) { mount($('#oc', el), empty('No stays to report for', 'Occupancy reporting applies to hotels and homestays with an active registration.')); return; }
    let cur = stays.find((b) => b.id === ctx.query.b)?.id || stays[0].id;
    const box = $('#oc', el);
    const now = new Date();
    const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const ym = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const draw = async () => {
      const b = stays.find((x) => x.id === cur);
      setQuery({ b: cur });
      mount(box, html`<div class="split"><form class="card form" id="of" novalidate><h2>Submit a month</h2>
          ${stays.length > 1 ? bizSelect(stays, cur) : html`<p class="small muted">${b.name} · <span class="mono">${b.reg_no}</span></p>`}
          ${b.hoi_connected ? html`<p class="flag blue">This stay is connected to HOI: daily occupancy arrives automatically. Use this form only for days HOI did not report.</p>` : ''}
          ${field({ id: 'month', label: 'Month', type: 'month', required: true, value: ym(lastMonth), attrs: `max="${ym(now)}"` })}
          ${field({ id: 'rooms_available', label: 'Rooms available per night', type: 'number', required: true, value: b.capacity, hint: `Registered capacity: ${b.capacity} ${b.capacity_unit}.`, attrs: `min="0" max="${b.capacity}" inputmode="numeric"` })}
          ${field({ id: 'occupied_room_nights', label: 'Occupied room nights in the month', type: 'number', required: true, hint: 'Sum over all nights of rooms that were occupied. Example: 6 rooms, 20 nights full = 120.', attrs: 'min="0" max="200000" inputmode="numeric"' })}
          <p class="hint" id="pctprev" aria-live="polite"></p>
          <button class="btn primary" type="submit">Submit occupancy</button><div id="ores" class="section" aria-live="polite"></div></form>
        <section class="card" aria-labelledby="oh-h"><h2 id="oh-h">History</h2><div id="ohist"></div></section></div>`);
      const form = $('#of', box);
      $('#bsel', box)?.addEventListener('change', (e) => { cur = e.target.value; draw(); });
      const prev = () => {
        const fd = new FormData(form);
        const [y, mo] = String(fd.get('month') || '').split('-').map(Number);
        const ra = Number(fd.get('rooms_available'));
        const on = Number(fd.get('occupied_room_nights'));
        if (!y || !ra || !fd.get('occupied_room_nights')) { $('#pctprev', box).textContent = ''; return; }
        const days = (y === now.getFullYear() && mo === now.getMonth() + 1) ? now.getDate() : new Date(y, mo, 0).getDate();
        $('#pctprev', box).textContent = `About ${num((100 * on) / (ra * days), 1)}% occupancy over ${days} days (maximum ${num(ra * days)} room nights).`;
      };
      form.addEventListener('input', prev);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const month = String(fd.get('month') || '');
        const ra = fd.get('rooms_available');
        const on = fd.get('occupied_room_nights');
        const errs = {};
        if (!/^\d{4}-\d{2}$/.test(month)) errs.month = 'Choose a month (YYYY-MM).';
        else if (month > ym(now)) errs.month = 'The month cannot be in the future.';
        if (ra === '' || !Number.isInteger(Number(ra)) || Number(ra) < 0 || Number(ra) > b.capacity) errs.rooms_available = `Enter a whole number from 0 to ${b.capacity}.`;
        if (on === '' || !Number.isInteger(Number(on)) || Number(on) < 0) errs.occupied_room_nights = 'Enter a whole number of room nights.';
        else if (!errs.month && !errs.rooms_available) {
          const [yy, mm] = month.split('-').map(Number);
          const nd = (yy === now.getFullYear() && mm === now.getMonth() + 1) ? now.getDate() : new Date(yy, mm, 0).getDate();
          if (Number(on) > Number(ra) * nd) errs.occupied_room_nights = `At most ${Number(ra) * nd} (${ra} rooms × ${nd} nights).`;
        }
        if (Object.keys(errs).length) { showErrors(form, errs); return; }
        clearErrors(form);
        const btn = form.querySelector('button[type=submit]');
        busy(btn, true, 'Submitting…');
        try {
          const r = await api(`/business/businesses/${encodeURIComponent(cur)}/occupancy`, { method: 'POST', body: { month, rooms_available: Number(ra), occupied_room_nights: Number(on) } });
          mount($('#ores', box), html`<p class="flag green" role="status"><strong>Saved for ${fmtMonth(r.month)}:</strong> ${r.occupancy_pct != null ? num(r.occupancy_pct, 1) + '% occupancy' : ''} over ${r.days_written} days${r.days_skipped_ingested ? ` (${r.days_skipped_ingested} days already reported by HOI were kept)` : ''}. ${r.replaced ? `${r.replaced} earlier day entries replaced.` : ''}</p>`);
          announce('Occupancy saved');
          hist();
        } catch (err) {
          if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message);
          else mount($('#ores', box), errorBox(err, { retry: false }));
        } finally { busy(btn, false); }
      });
      const hist = () => load($('#ohist', box), async () => {
        const h = await api(`/business/businesses/${encodeURIComponent(cur)}/occupancy`);
        const months = (h.months || []).slice().reverse();
        if (!months.length) { mount($('#ohist', box), empty('No occupancy reported yet')); return; }
        const hb = $('#ohist', box);
        hb.replaceChildren(lineChart({ title: 'Occupancy by month', sub: `${b.name}`, x: months.map((x) => x.month), series: [{ label: 'Occupancy', values: months.map((x) => x.occupancy_pct) }], unit: '%', yMin: 0, yMax: 100, height: 220, xFmt: (v) => fmtMonth(v) }));
        const t = document.createElement('div');
        t.className = 'section';
        mount(t, table([{ key: 'm', label: 'Month' }, { key: 'd', label: 'Days reported', num: true }, { key: 'o', label: 'Occupied / available nights', num: true }, { key: 'p', label: 'Occupancy', num: true }, { key: 's', label: 'Source' }],
          (h.months || []).slice(0, 6).map((x) => ({ m: fmtMonth(x.month), d: x.days_reported, o: `${num(x.occupied_room_nights)} / ${num(x.rooms_available_nights)}`, p: x.occupancy_pct != null ? num(x.occupancy_pct, 1) + '%' : '—', s: srcLabel(x.sources) })), 'Last 6 months'));
        hb.appendChild(t);
      }, { skel: 'block' });
      hist();
    };
    draw();
  });
}
function srcLabel(s) {
  const L = { i: 'HOI (automatic)', m: 'monthly form', s: 'demo data' };
  return Object.entries(s || {}).map(([k, v]) => `${L[k] || k}: ${v} d`).join(', ') || '—';
}

export async function apiKeys(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business/api-keys', 'API keys for HOI', 'Hotels run with HOI can send daily occupancy to the portal automatically, so you never fill the monthly form.')}<div id="ak"></div>`);
  await load($('#ak', el), async () => {
    const stays = (await myStays()).filter((b) => b.reports_occupancy);
    if (!stays.length) { mount($('#ak', el), empty('No stays to connect', 'API keys are for hotels and homestays with an active registration.')); return; }
    let cur = stays.find((b) => b.id === ctx.query.b)?.id || stays[0].id;
    const box = $('#ak', el);
    const draw = () => {
      const b = stays.find((x) => x.id === cur);
      setQuery({ b: cur });
      mount(box, html`<div class="split"><div class="stack">
          <section class="card"><h2>Generate a key</h2>
            ${stays.length > 1 ? bizSelect(stays, cur) : html`<p class="small muted">${b.name} · <span class="mono">${b.reg_no}</span></p>`}
            <form id="kf" class="form section" novalidate>${field({ id: 'label', label: 'Label', opt: true, placeholder: 'e.g. HOI front desk', attrs: 'maxlength="60"' })}<button class="btn primary" type="submit">Generate API key</button></form>
            <div id="newkey" aria-live="polite"></div></section>
          <section class="card"><h2>Keys for ${b.name}</h2><div id="klist"></div></section></div>
        <aside class="card"><h2>How it works</h2>
          <ol class="bullets"><li>Generate a key here. It is shown <strong>once</strong>; the portal stores only a hash.</li><li>Paste it into HOI (Settings → State portal).</li><li>HOI sends one record per day. Re-sending a date replaces it (idempotent).</li><li>Revoke a key at any time; HOI then gets “401 wrong key”.</li></ol>
          <h3 class="section">For developers</h3>
          <pre class="keybox section">POST /api/v1/ingest/occupancy
X-API-Key: uthp_…
{"date": "2026-10-12",
 "rooms_available": 24,
 "rooms_occupied": 19,
 "staff_count": 14,
 "staff_flagged": 1}</pre>
          <p class="hint">Staff numbers are only shown added up across many businesses, never for one business.</p></aside></div>`);
      $('#bsel', box)?.addEventListener('change', (e) => { cur = e.target.value; draw(); });
      const form = $('#kf', box);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const label = $('#label', box).value.trim() || null;
        const btn = form.querySelector('button[type=submit]');
        busy(btn, true, 'Generating…');
        try {
          const k = await api(`/business/businesses/${encodeURIComponent(cur)}/api-keys`, { method: 'POST', body: { label } });
          mount($('#newkey', box), html`<div class="flag amber section" role="alert"><strong>Copy this key now.</strong> ${k.warning || 'It is shown only once.'}</div>
            <div class="keybox" id="thekey">${k.api_key}</div><div class="btnrow section">${copyBtn(k.api_key, 'Copy API key')}<button type="button" class="btn sm ghost" id="hidekey">I have saved it, hide</button></div>`);
          $('#hidekey', box).addEventListener('click', () => { mount($('#newkey', box), html`<p class="hint">Key hidden. It cannot be shown again.</p>`); });
          form.reset();
          list();
        } catch (err) {
          mount($('#newkey', box), errorBox(err, { retry: false }));
        } finally { busy(btn, false); }
      });
      const list = () => load($('#klist', box), async () => {
        const r = await api(`/business/businesses/${encodeURIComponent(cur)}/api-keys`);
        mount($('#klist', box), r.items.length ? html`<div class="list">${r.items.map((k) => html`<div class="item"><div class="main"><strong>${k.label || 'Unlabelled key'}</strong><div class="sub mono">${k.prefix}…</div>
            <div class="sub">Created ${fmtDateTime(k.created_at)} · ${k.last_used_at ? 'last used ' + relTime(k.last_used_at) : 'never used'}</div></div>
            <div class="side">${k.revoked ? html`<span class="pill neutral">Revoked</span>` : html`<span class="pill ok">Active</span><button type="button" class="btn sm danger" data-revoke="${k.id}">Revoke</button>`}</div></div>`)}</div>`
          : empty('No keys yet', 'Generate one to connect HOI.'));
        $$('[data-revoke]', box).forEach((btn) => btn.addEventListener('click', async () => {
          if (!(await confirmDialog('Revoke this key? HOI will stop reporting until you add a new key.', { ok: 'Revoke key', danger: true }))) return;
          try { await api(`/business/businesses/${encodeURIComponent(cur)}/api-keys/${encodeURIComponent(btn.dataset.revoke)}`, { method: 'DELETE' }); toast('Key revoked'); list(); } catch (err) { toast(err.message, 'err'); }
        }));
      }, { skel: 'list', n: 2 });
      list();
    };
    draw();
  });
}
