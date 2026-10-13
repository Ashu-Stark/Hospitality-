// Grievance: file (ticket id + tracking code shown once, with copy buttons) and track (status timeline).
import { html, mount, href, $, field, showErrors, clearErrors, apiFieldErrors, busy, copyBtn, crumbs, fmtDateTime, fmtDate, statusPill, announce, errorBox, relTime, lastUpdated } from '../ui.js';
import { api, meta } from '../api.js';
import { t } from '../i18n.js';

let lastFiled = null; // {ticket_id, tracking_code} kept in memory only (never in the URL)
const CHAIN = ['received', 'assigned', 'in_progress', 'resolved'];
const LABEL = { received: 'Received', assigned: 'Assigned to the district office', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' };

export async function file(ctx) {
  const el = ctx.el;
  const m = await meta();
  const q = ctx.query;
  mount(el, html`<div class="pagehead"><div><h1>${t('file')}</h1>
      <p>Tell the district tourism office what went wrong. You get a ticket id and a 6-digit tracking code.</p></div></div>
    <div class="split"><form class="card form" id="gf" novalidate aria-describedby="g-intro">
      <p id="g-intro" class="small muted">Fields marked optional can be left blank. The office tries to reply within ${m.grievance_sla_days} days.</p>
      ${field({ id: 'category', label: 'What is it about?', type: 'select', required: true, value: q.category || '', options: [{ value: '', label: 'Choose a category' }, ...m.grievance_categories.map((c) => ({ value: c.key, label: c.label }))] })}
      ${field({ id: 'district', label: 'District where it happened', type: 'select', required: true, value: q.district || '', options: [{ value: '', label: 'Choose a district' }, ...m.districts.map((d) => ({ value: d.id, label: d.name }))] })}
      ${field({ id: 'business_reg_no', label: 'Business registration number', opt: true, value: q.reg || '', placeholder: 'UK-HMS-RUD-00001', hint: 'If you know it. You can find it on the certificate, bill or in the directory.', attrs: 'autocapitalize="characters" spellcheck="false" maxlength="30"' })}
      ${field({ id: 'description', label: 'What happened?', type: 'textarea', required: true, hint: 'At least 10 characters. Include date, place and what you expect. Do not include passwords or card numbers.', attrs: 'maxlength="2000"' })}
      <p class="hint" id="desc-count" aria-live="polite">0 / 2000</p>
      ${field({ id: 'contact', label: 'Phone or email for follow-up', opt: true, hint: 'Visible to officials only, never shown publicly.', attrs: 'maxlength="120" autocomplete="email"' })}
      <button class="btn primary" type="submit">Send complaint</button>
    </form>
    <aside class="card" aria-labelledby="g-how"><h2 id="g-how">What happens next</h2>
      <ol class="timeline section">${CHAIN.map((s) => html`<li class="todo"><strong>${LABEL[s]}</strong></li>`)}</ol>
      <p class="small muted">Emergency? Dial <strong>112</strong>. This form is not monitored around the clock.</p></aside></div>
    <div id="gres" aria-live="polite"></div>`);
  const form = $('#gf', el);
  const desc = $('#description', el);
  desc.addEventListener('input', () => { $('#desc-count', el).textContent = `${desc.value.length} / 2000`; });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      category: fd.get('category'), district: fd.get('district'), description: (fd.get('description') || '').toString().trim(),
      business_reg_no: (fd.get('business_reg_no') || '').toString().trim().toUpperCase() || null, contact: (fd.get('contact') || '').toString().trim() || null,
    };
    const errs = {};
    if (!body.category) errs.category = 'Choose a category.';
    if (!body.district) errs.district = 'Choose the district.';
    if (body.description.length < 10) errs.description = 'Describe what happened in at least 10 characters.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Submitting…');
    try {
      const r = await api('/grievances', { method: 'POST', body });
      lastFiled = { ticket_id: r.ticket_id, tracking_code: r.tracking_code };
      mount(el, html`${crumbs([['Home', '#/'], ['File a grievance', '#/grievance'], ['Submitted']])}
        <section class="ticket anim" aria-labelledby="ok-h"><p class="pill ok">Submitted</p><h1 id="ok-h" class="section">We got your complaint</h1>
          <p class="lead section">Save both numbers now. ${r.message}</p>
          <div class="codes"><div class="code"><div><div class="l">Ticket id</div><div class="v">${r.ticket_id}</div></div>${copyBtn(r.ticket_id, 'Copy ticket id')}</div>
            <div class="code"><div><div class="l">Tracking code (shown once)</div><div class="v">${r.tracking_code}</div></div>${copyBtn(r.tracking_code, 'Copy tracking code')}</div></div>
          ${field2([['Category', r.category_label], ['District', r.district_name], ['Reply by', fmtDate(r.sla_due_at)], ['Status', statusPill(r.status)]])}
          <div class="btnrow section"><a class="btn primary" href="${href('/grievance/track', { ticket: r.ticket_id })}">Track this grievance</a><button type="button" class="btn ghost" id="printbtn">Print</button><a class="btn ghost" href="#/">Back to home</a></div>
        </section>`);
      $('#printbtn', el).addEventListener('click', () => window.print());
      $('#ok-h', el).setAttribute('tabindex', '-1');
      $('#ok-h', el).focus();
      announce(`Complaint sent. Ticket ${r.ticket_id}, tracking code ${r.tracking_code.split('').join(' ')}.`);
    } catch (err) {
      busy(btn, false);
      if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message);
      else mount($('#gres', el), errorBox(err, { retry: false }));
    }
  });
}
const field2 = (pairs) => html`<dl class="facts section">${pairs.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;

export async function track(ctx) {
  const el = ctx.el;
  const pre = lastFiled && (!ctx.query.ticket || ctx.query.ticket === lastFiled.ticket_id) ? lastFiled : null;
  mount(el, html`<div class="pagehead"><div><h1>${t('track')}</h1><p>Enter the ticket id and the 6-digit tracking code you received when filing.</p></div></div>
    <form class="card form" id="tf" novalidate><div class="grid g2">
      ${field({ id: 'ticket_id', label: 'Ticket id', required: true, value: ctx.query.ticket || pre?.ticket_id || '', placeholder: 'UTHP-G-000041', attrs: 'autocapitalize="characters" spellcheck="false" maxlength="20"' })}
      ${field({ id: 'tracking_code', label: 'Tracking code', required: true, value: pre?.tracking_code || '', placeholder: '6 digits', attrs: 'inputmode="numeric" autocomplete="off" maxlength="6" pattern="[0-9]{6}"' })}
      </div><button class="btn primary" type="submit">Check status</button></form>
    <div id="tres" class="section" aria-live="polite"></div>`);
  const form = $('#tf', el);
  const run = async () => {
    const fd = new FormData(form);
    const ticket_id = (fd.get('ticket_id') || '').toString().trim().toUpperCase();
    const tracking_code = (fd.get('tracking_code') || '').toString().trim();
    const errs = {};
    if (ticket_id.length < 5) errs.ticket_id = 'Enter the ticket id, for example UTHP-G-000041.';
    if (!/^\d{6}$/.test(tracking_code)) errs.tracking_code = 'The tracking code is exactly 6 digits.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Checking…');
    try {
      const g = await api('/grievances/track', { method: 'POST', body: { ticket_id, tracking_code } });
      mount($('#tres', el), timelineCard(g));
      announce(`Status: ${LABEL[g.status] || g.status}`);
    } catch (err) {
      mount($('#tres', el), err.status === 404 ? html`<div class="vres bad" role="alert"><div class="ico" aria-hidden="true">✕</div><div><h2>No match</h2><p>${err.message} Check both numbers; the code is case-sensitive digits only.</p></div></div>` : errorBox(err, { retry: false }));
    } finally {
      busy(btn, false);
    }
  };
  form.addEventListener('submit', (e) => { e.preventDefault(); run(); });
  if (pre) await run();
}

export function timelineCard(g, { officer = false } = {}) {
  const reached = new Set((g.timeline || []).map((x) => x.status));
  const chain = g.status === 'closed' ? [...CHAIN.filter((s) => reached.has(s)), 'closed'] : CHAIN;
  const curIdx = chain.indexOf(g.status);
  return html`<section class="card" aria-labelledby="tl-h">
    <div class="sechead"><div><p class="eyebrow">Ticket ${g.ticket_id}</p><h2 id="tl-h">${LABEL[g.status] || g.status}</h2></div>
      <div class="chips">${statusPill(g.status)}${g.overdue ? html`<span class="pill bad">Past SLA</span>` : g.resolved_at ? '' : html`<span class="pill neutral">Due ${fmtDate(g.sla_due_at)}</span>`}</div></div>
    <dl class="facts">${[['Category', g.category_label], ['District', g.district_name], ['Filed', fmtDateTime(g.created_at)], ['Last update', `${fmtDateTime(g.updated_at)} (${relTime(g.updated_at)})`], ...(g.business_reg_no ? [['Business reg. no.', g.business_reg_no]] : [])].map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>
    <h3 class="section">Progress</h3>
    <ol class="timeline section">${chain.map((s, i) => html`<li class="${i <= curIdx ? 'done' : 'todo'}"><strong>${LABEL[s]}</strong><span class="sr-only">${i <= curIdx ? ' (done)' : ' (not yet)'}</span></li>`)}</ol>
    <h3 class="section">Updates</h3>
    <ol class="timeline section">${(g.timeline || []).slice().reverse().map((x) => html`<li class="done"><strong>${LABEL[x.status] || x.status}</strong>${x.public === false ? html` <span class="pill neutral noicon">Internal note</span>` : ''}
      <div class="when">${fmtDateTime(x.at)}${officer && x.by ? ' · ' + x.by : ''}</div>${x.note ? html`<div>${x.note}</div>` : ''}</li>`)}</ol>
  </section>`;
}
