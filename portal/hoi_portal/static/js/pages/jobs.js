// Hiring board, public + job-seeker side: job board (filters, match score for signed-in seekers), job detail with apply,
// "Hire staff" and "How it works & privacy" pages, the seeker's own area (dashboard, profile form) and the shared
// message-thread drawer. Contact details are never shown here; the API only returns them to an accepted business.
import { html, mount, href, load, $, $$, raw, field, showErrors, clearErrors, apiFieldErrors, busy, crumbs, fmtDate, fmtDateTime, toast, empty, confirmDialog, drawer, collapseFilters, num, announce, moreList, MONTH_NAMES, statusPill, errorBox } from '../ui.js';
import { api, meta, jobsMeta, role, user } from '../api.js';
import { go, setQuery } from '../router.js';
import { roleSubnav } from './common.js';
import { jobCard as jobMediaCard, offerCard } from '../cards.js';
import { statTile, takeaway } from '../ui.js';

// ------------------------------------------------------------------ shared bits (also used by hiring.js)
const APP_STATUS = { applied: ['info', 'Applied'], viewed: ['violet', 'Viewed'], shortlisted: ['ok', 'Shortlisted'], contacted: ['ok', 'Contacted'], not_selected: ['neutral', 'Not selected'], withdrawn: ['neutral', 'Withdrawn'] };
const INT_STATUS = { pending: ['warn', 'Awaiting reply'], accepted: ['ok', 'Accepted'], declined: ['neutral', 'Declined'], withdrawn: ['neutral', 'Withdrawn'] };
export const appPill = (s) => { const [c, l] = APP_STATUS[s] || ['neutral', s]; return html`<span class="pill ${c}">${l}</span>`; };
export const intPill = (s) => { const [c, l] = INT_STATUS[s] || ['neutral', s]; return html`<span class="pill ${c}">${l}</span>`; };
export const payText = (lo, hi) => (lo == null && hi == null ? 'Pay not stated' : `₹${num(lo ?? hi)}${hi != null && lo != null && hi !== lo ? '–' + num(hi) : ''} / month`);
export function typeText(j) {
  const t = j.job_type_label || j.availability_label || '';
  const from = j.season_from || j.available_from;
  const to = j.season_to || j.available_to;
  if (from && to) return `${t} · ${fmtDate(from, { noYear: true })} – ${fmtDate(to)}`;
  if (from) return `${t} · from ${fmtDate(from)}`;
  return t;
}
export const skillTags = (skills, years = false) => html`${skills.map((s) => html`<span class="tag">${s.label}${years && s.years != null ? ` · ${s.years} yr${s.years === 1 ? '' : 's'}` : ''}</span>`)}`;
export function matchBadge(m) {
  if (!m || m.score == null) return '';
  const cls = m.score >= 70 ? 'hi' : m.score >= 40 ? 'mid' : 'lo';
  return html`<span class="match ${cls}" title="Match score: a rule of thumb from skills, district, availability and language"><b>${m.score}</b><small>% match</small></span>`;
}
export function whyChips(m, n = 4) {
  if (!m?.why?.length) return '';
  return html`<ul class="why" aria-label="Why this match">${m.why.slice(0, n).map((w) => html`<li class="${w.ok ? (w.partial ? 'part' : 'yes') : 'no'}"><span aria-hidden="true">${w.ok ? (w.partial ? '~' : '✓') : '✕'}</span>${w.text}</li>`)}</ul>`;
}
export function skillOptions(jm, sel = '', blank = 'Any skill') {
  return html`${blank ? html`<option value="">${blank}</option>` : ''}${jm.skill_categories.map((c) => html`<optgroup label="${c.label}">${jm.skills.filter((s) => s.category === c.key).map((s) => html`<option value="${s.key}" ${s.key === sel ? raw('selected') : ''}>${s.label}</option>`)}</optgroup>`)}`;
}
export const districtOptions = (m, sel = '', blank = 'Any district') => html`${blank ? html`<option value="">${blank}</option>` : ''}${m.districts.map((d) => html`<option value="${d.id}" ${d.id === sel ? raw('selected') : ''}>${d.name}</option>`)}`;
/** Previous / Next for server-paged lists; calls go(page). */
export function serverPager(el, res, goTo) {
  const pages = Math.max(1, Math.ceil(res.total / res.page_size));
  if (pages <= 1) return;
  const nav = document.createElement('nav');
  nav.className = 'pager';
  nav.setAttribute('aria-label', 'Pages');
  mount(nav, html`<button type="button" class="btn sm ghost" data-pg="${res.page - 1}" ${res.page <= 1 ? raw('disabled') : ''}>Previous</button><span class="small">Page ${res.page} of ${pages} · ${res.total} results</span><button type="button" class="btn sm ghost" data-pg="${res.page + 1}" ${res.page >= pages ? raw('disabled') : ''}>Next</button>`);
  el.appendChild(nav);
  $$('[data-pg]', nav).forEach((b) => b.addEventListener('click', () => goTo(Number(b.dataset.pg))));
}

/** Message thread for an application (JA-...) or an interest request (INT-...), in a side drawer. */
export function openThread(id, title = 'Messages', onClose) {
  const dw = drawer(title, { onClose });
  const draw = async () => {
    const t = await api('/jobs/threads/' + encodeURIComponent(id));
    const th = t.thread;
    mount(dw.body, html`<p class="small muted">${th.job ? html`About <strong>${th.job.title}</strong> · ` : ''}with ${th.other_party}</p>
      <div class="msgs section" role="log" aria-label="Messages">${t.items.length ? t.items.map((m) => html`<div class="msg ${m.mine ? 'me' : ''}"><p>${m.text}</p><span class="small muted">${m.mine ? 'You' : th.other_party} · ${fmtDateTime(m.at)}</span></div>`) : html`<p class="muted">No messages yet.</p>`}</div>
      ${th.can_send ? html`<form id="mf" class="form section" novalidate>${field({ id: 'mtext', label: 'Your message', type: 'textarea', rows: 3, attrs: 'maxlength="1000" name="text"', hint: th.note })}<button class="btn primary" type="submit">Send</button></form>`
        : html`<p class="flag amber section">${th.kind === 'interest' ? 'Messages open once the candidate accepts the request.' : 'This conversation is closed.'}</p>`}`);
    const box = $('.msgs', dw.body);
    box.scrollTop = box.scrollHeight;
    const form = $('#mf', dw.body);
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const ta = $('#mtext', form);
      const v = ta.value.trim();
      if (!v) { showErrors(form, { mtext: 'Write a message first.' }); return; }
      const btn = form.querySelector('button[type=submit]');
      busy(btn, true, 'Sending…');
      try {
        await api('/jobs/threads/' + encodeURIComponent(id), { method: 'POST', body: { text: v } });
        await draw();
        $('#mtext', dw.body)?.focus();
        announce('Message sent');
      } catch (err) {
        busy(btn, false);
        showErrors(form, {}, err.message);
      }
    });
  };
  load(dw.body, draw, { skel: 'list', n: 3 });
  return dw;
}

// ------------------------------------------------------------------ public job board
export const jobCard = (j) => jobMediaCard(j, { matchBadge: matchBadge(j.match) });

export async function board(ctx) {
  const el = ctx.el;
  const r = role();
  const f = { skill: ctx.query.skill || '', district: ctx.query.district || '', type: ctx.query.type || '', month: ctx.query.month || '', q: ctx.query.q || '', source: ctx.query.source || '', page: Number(ctx.query.page) || 1 };
  const [m, jm] = await Promise.all([meta(), jobsMeta()]);
  const actions = r === 'job_seeker' ? html`<a class="btn ghost" href="#/seeker">My job search</a>`
    : r === 'business' ? html`<a class="btn primary" href="#/business/hiring/new">Post a job</a>`
      : html`<a class="btn primary" href="#/register?as=seeker">Create a job-seeker profile</a><a class="btn ghost" href="#/jobs/hire">Hire staff</a>`;
  mount(el, html`<div class="pagehead"><div><p class="eyebrow">Jobs in tourism &amp; hospitality</p><h1>Find work in Uttarakhand tourism</h1>
      <p id="jsum">Hotels, homestays, treks, rafting and transport. Apply here; employers never see your phone or email until you accept.</p></div><div class="btnrow">${actions}</div></div>
    <form class="card tight filters" id="jf" aria-label="Filter jobs">
      <div class="fld"><label class="lbl" for="jf-s">Skill</label><select class="field" id="jf-s" name="skill">${skillOptions(jm, f.skill)}</select></div>
      <div class="fld"><label class="lbl" for="jf-d">District</label><select class="field" id="jf-d" name="district">${districtOptions(m, f.district)}</select></div>
      <div class="fld"><label class="lbl" for="jf-t">Job type</label><select class="field" id="jf-t" name="type"><option value="">Any type</option>${jm.job_types.map((x) => html`<option value="${x.key}" ${f.type === x.key ? raw('selected') : ''}>${x.label}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="jf-m">Work in month</label><select class="field" id="jf-m" name="month"><option value="">Any month</option>${MONTH_NAMES.map((n, i) => html`<option value="${i + 1}" ${String(i + 1) === f.month ? raw('selected') : ''}>${n}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="jf-q">Search</label><input class="field" id="jf-q" name="q" type="search" value="${f.q}" maxlength="80" placeholder="e.g. cook, Auli"></div>
      <div class="fld"><label class="check"><input type="checkbox" name="source" value="hoi" ${f.source ? raw('checked') : ''}> Urgent: hotels short of staff</label></div>
    </form>
    <div id="jl" class="section" aria-live="polite"></div>`);
  const form = $('#jf', el);
  collapseFilters(form, 'Filters');
  const list = $('#jl', el);
  const draw = () => load(list, async () => {
    setQuery({ ...f, page: f.page > 1 ? f.page : '' });
    const res = await api('/jobs', { query: { skill: f.skill || undefined, district: f.district || undefined, type: f.type || undefined, month: f.month || undefined, q: f.q || undefined, source: f.source || undefined, page: f.page }, auth: r === 'job_seeker' });
    const from = (res.page - 1) * res.page_size + 1;
    mount(list, res.items.length ? html`<p class="small muted resline"><strong>${res.total} open job${res.total === 1 ? '' : 's'}</strong>, ${num(res.openings)} openings${res.hoi_requests ? ` · ${res.hoi_requests} urgent` : ''} · showing ${from}–${from + res.items.length - 1}${res.matched_to_profile ? ' · ranked by match to your profile' : ''}</p>
        <div class="mcgrid g3c">${res.items.map(jobCard)}</div>`
      : empty('No open jobs match', 'Clear a filter or try another district or month.'));
    serverPager(list, res, (p) => { f.page = p; draw().then(() => list.scrollIntoView({ block: 'start' })); });
    announce(`${res.total} jobs`);
  }, { skel: 'cards', n: 6, label: 'Loading jobs…' });
  let tmr;
  const read = () => { const fd = new FormData(form); ['skill', 'district', 'type', 'month', 'q', 'source'].forEach((k) => { f[k] = (fd.get(k) || '').toString().trim(); }); f.page = 1; draw(); };
  form.addEventListener('change', (e) => { if (e.target.name !== 'q') read(); });
  form.addEventListener('input', (e) => { if (e.target.name === 'q') { clearTimeout(tmr); tmr = setTimeout(read, 350); } });
  form.addEventListener('submit', (e) => { e.preventDefault(); read(); });
  await draw();
}

export async function detail(ctx) {
  const el = ctx.el;
  const u = user();
  mount(el, html`${crumbs([['Jobs', '#/jobs'], ['…']])}<h1 class="sr-only">Job</h1><div id="jd"></div>`);
  await load($('#jd', el), async () => {
    const j = await api('/jobs/' + encodeURIComponent(ctx.params.id), { auth: !!u });
    const perks = [j.accommodation && 'Accommodation', j.food && 'Meals'].filter(Boolean);
    mount(el, html`${crumbs([['Jobs', '#/jobs'], [j.title]])}
      <div class="pagehead"><div><p class="eyebrow">${j.job_type_label} job · ${j.district_name}</p><h1>${j.title}</h1>
        <p><a href="${href('/directory/' + j.business_id)}">${j.business_name}</a>${j.business_type_label ? ` · ${j.business_type_label}` : ''} · <span class="mono">${j.business_reg_no || ''}</span></p></div>
        <div class="btnrow">${statusPill(j.status === 'open' ? 'open' : 'closed', j.status === 'open' ? 'Open' : 'Closed')}</div></div>
      <div class="split">
        <section class="card" aria-labelledby="jd-h"><h2 id="jd-h">About the job</h2>
          <dl class="facts">
            <dt>Where</dt><dd>${j.destination_name ? j.destination_name + ', ' : ''}${j.district_name}</dd>
            <dt>Type</dt><dd>${typeText(j)}</dd>
            <dt>Pay</dt><dd>${payText(j.pay_min, j.pay_max)}</dd>
            <dt>Provided</dt><dd>${perks.length ? perks.join(', ') : 'Not stated'}</dd>
            <dt>Openings</dt><dd>${j.openings}</dd>
            ${j.languages.length ? html`<dt>Languages</dt><dd>${j.languages.join(', ')}</dd>` : ''}
            <dt>Closes</dt><dd>${fmtDate(j.closes_on)} · posted ${fmtDate(j.posted_at)}</dd>
          </dl>
          ${j.via_hoi ? html`<p class="notice section"><strong>Urgent:</strong> this hotel is short of staff for these dates. Agencies can reply from their page, and you can apply yourself.</p>` : ''}
          ${j.agency_responses?.length ? html`<h3 class="section">Agency responses</h3><ul class="lines">${j.agency_responses.map((x) => html`<li><span class="pill ok">${x.workers} workers</span><a href="${href('/directory/' + x.agency_business_id)}">${x.agency?.name || x.agency_business_id}</a><span class="muted small">${x.note || ''}</span></li>`)}</ul>` : ''}
          <h3 class="section">Skills needed</h3><div class="chips">${skillTags(j.skills)}</div>
          <h3 class="section">Description</h3><p class="prewrap">${j.description}</p>
          <p class="hint section">Pay and terms are stated by the employer. Never pay a fee to get a job; report it via <a href="#/grievance">File a complaint</a>.</p>
        </section>
        <aside class="card" id="applybox" aria-labelledby="ap-h"></aside>
      </div>`);
    applyBox($('#applybox', el), j);
  });
}

function applyBox(box, j) {
  const r = role();
  const next = '/jobs/' + j.id;
  if (r === 'business') {
    mount(box, j.applications ? html`<h2 id="ap-h">Your job post</h2><p>${j.applications_total} application(s), ${j.applications_new} new.</p><a class="btn primary" href="${href('/business/hiring/jobs/' + j.id)}">Manage applicants</a>`
      : html`<h2 id="ap-h">Hiring?</h2><p class="small">This post belongs to another business.</p><a class="btn ghost" href="#/business/hiring">Your hiring dashboard</a>`);
    return;
  }
  if (r !== 'job_seeker') {
    mount(box, html`<h2 id="ap-h">Apply</h2><p class="small">Apply with a free job-seeker profile. Your phone and email stay private until you accept an employer's request.</p>
      <div class="btnrow section"><a class="btn primary" href="${href('/register', { as: 'seeker', next })}">Create a profile</a><a class="btn ghost" href="${href('/signin', { need: 'seeker', next })}">Sign in</a></div>`);
    return;
  }
  if (!j.has_profile) {
    mount(box, html`<h2 id="ap-h">Apply</h2><p class="small">Create your profile first (about 5 minutes). Then you can apply in one click.</p><a class="btn primary" href="${href('/seeker/profile', { next })}">Create my profile</a>`);
    return;
  }
  const a = j.my_application;
  if (a) {
    mount(box, html`<h2 id="ap-h">Your application</h2>${matchBadge(j.match)}<p class="section">${appPill(a.status)} <span class="small muted">applied ${fmtDate(a.applied_at)}</span></p>
      <div class="btnrow section">${a.can_message ? html`<button type="button" class="btn ghost" id="ap-msg">Messages${a.messages ? ` (${a.messages})` : ''}</button>` : ''}<a class="btn ghost" href="#/seeker">My job search</a></div>`);
    $('#ap-msg', box)?.addEventListener('click', () => openThread(a.id, 'Messages: ' + j.title));
    return;
  }
  if (j.status !== 'open') { mount(box, html`<h2 id="ap-h">Apply</h2><p>This job is closed.</p>`); return; }
  mount(box, html`<h2 id="ap-h">Your match</h2><div class="rowx">${matchBadge(j.match)}</div>${whyChips(j.match, 6)}
    <p class="hint">${j.match?.basis || ''}</p>
    <form class="form section" id="apf" novalidate>${field({ id: 'note', label: 'Short note to the employer', type: 'textarea', rows: 3, opt: true, attrs: 'maxlength="500"', hint: 'Up to 500 characters. Do not include your phone number; it is shared only if you accept a request.' })}
      <button class="btn primary" type="submit">Apply</button></form>`);
  const form = $('#apf', box);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Applying…');
    try {
      const res = await api(`/jobs/${encodeURIComponent(j.id)}/apply`, { method: 'POST', body: { note: $('#note', form).value.trim() || null }, auth: true });
      toast('Application sent');
      j.my_application = res;
      applyBox(box, j);
      $('h2', box)?.focus?.();
    } catch (err) {
      busy(btn, false);
      showErrors(form, apiFieldErrors(err), err.message);
    }
  });
}

export async function hire(ctx) {
  const el = ctx.el;
  const r = role();
  mount(el, html`<div class="pagehead"><div><p class="eyebrow">Jobs · for employers</p><h1>Hire staff for your tourism business</h1>
      <p>Post seasonal or permanent jobs and find local cooks, guides, drivers, housekeeping and front-office staff.</p></div>
      <div class="btnrow">${r === 'business' ? html`<a class="btn primary" href="#/business/hiring/new">Post a job</a><a class="btn ghost" href="#/business/hiring">Hiring dashboard</a>`
        : html`<a class="btn primary" href="${href('/signin', { need: 'business', next: '/business/hiring' })}">Business sign in</a><a class="btn ghost" href="#/register">Create business account</a>`}</div></div>
    <ol class="steps3">
      <li class="card tight"><strong>1. Post a job</strong><p class="small">Skills, place, season dates, pay, stay and meals. Needs an <b>active registration</b> on this portal.</p></li>
      <li class="card tight"><strong>2. Find candidates</strong><p class="small">Filter by skill, district, availability, experience and language. A transparent match score explains every ranking.</p></li>
      <li class="card tight"><strong>3. Ask, then talk</strong><p class="small">Send an interest request. You see the phone and email only after the candidate accepts; until then, use portal messages.</p></li>
    </ol>
    <section class="sec2" aria-labelledby="ag-h"><div class="sechead"><div><h2 id="ag-h">Need several people at once?</h2><p class="sub">Registered staffing agencies offer pooled local workers for the season.</p></div><a href="#/jobs/agencies">All agency offers</a></div><div id="ofr"></div></section>
    <p class="flag blue section">Fair hiring: profiles have no gender, age, religion, caste, family details, photo or address, and the match score never uses them. <a href="#/jobs/about">How it works &amp; privacy</a></p>`);
  await load($('#ofr', el), async () => {
    const o = await api('/staffing/offers');
    mount($('#ofr', el), o.items.length ? html`<div class="mcgrid g3c">${o.items.slice(0, 3).map(offerCard)}</div>` : html`<p class="muted">No agency offers right now.</p>`);
  }, { skel: 'cards', n: 3 });
}

// Staffing agencies: block offers of pooled workers + how HOI staffing requests reach agencies.
export async function agencies(ctx) {
  const el = ctx.el;
  const [m, jm] = await Promise.all([meta(), jobsMeta()]);
  const f = { skill: ctx.query.skill || '', district: ctx.query.district || '' };
  mount(el, html`<div class="pagehead"><div><p class="eyebrow">Jobs · staffing agencies</p><h1>Staffing agencies</h1>
      <p class="lead2">Agencies keep a team of local workers ready for the busy season. When a hotel is short of staff, the agencies that can help get a message.</p></div>
      <a class="btn primary" href="${href('/host')}">Register an agency</a></div>
    <div id="akp"></div>
    <form class="card tight filters" id="af" aria-label="Filter offers">
      <div class="fld"><label class="lbl" for="af-s">Skill</label><select class="field" id="af-s" name="skill">${skillOptions(jm, f.skill)}</select></div>
      <div class="fld"><label class="lbl" for="af-d">District</label><select class="field" id="af-d" name="district">${districtOptions(m, f.district)}</select></div></form>
    <div id="al" class="section"></div>`);
  const form = $('#af', el);
  const draw = () => load($('#al', el), async () => {
    setQuery(f);
    const [o, hoi] = await Promise.all([api('/staffing/offers', { query: { skill: f.skill || undefined, district: f.district || undefined } }), api('/jobs', { query: { source: 'hoi', page_size: 1 } })]);
    mount($('#akp', el), html`<div class="kpis k4">${statTile({ label: 'Workers on offer', value: num(o.workers) })}${statTile({ label: 'Block offers', value: o.total })}
      ${statTile({ label: 'Hotels needing staff now', value: hoi.total, tone: hoi.total ? 'warn' : '', note: html`<a href="${href('/jobs', { source: 'hoi' })}">See requests</a>` })}</div>`);
    mount($('#al', el), o.items.length ? html`<div class="mcgrid g3c">${o.items.map(offerCard)}</div>` : empty('No offers match', 'Try another skill or district.'));
  }, { skel: 'cards', n: 6 });
  form.addEventListener('change', () => { const fd = new FormData(form); f.skill = fd.get('skill') || ''; f.district = fd.get('district') || ''; draw(); });
  await draw();
}

export async function about(ctx) {
  const el = ctx.el;
  mount(el, html`<div class="pagehead"><div><p class="eyebrow">Jobs</p><h1>How the hiring board works</h1><p>Plain-language rules for job seekers and employers.</p></div></div><div id="ab"></div>`);
  await load($('#ab', el), async () => {
    const jm = await jobsMeta();
    const w = jm.match.weights;
    mount($('#ab', el), html`<div class="grid g2">
      <section class="card" aria-labelledby="ab-s"><h2 id="ab-s">For job seekers</h2><ol class="bullets numbered">
        <li>Create a free account and a short profile: skills, years, languages, districts, availability, expected pay.</li>
        <li>Browse jobs; each shows how well it matches your profile and why.</li>
        <li>Apply with a short note, and follow the status: applied, viewed, shortlisted, contacted or not selected.</li>
        <li>Accept or decline employers' interest requests. Accepting shares your phone and email with that employer only.</li></ol>
        <a class="btn primary section" href="#/register?as=seeker">Create a job-seeker profile</a></section>
      <section class="card" aria-labelledby="ab-p"><h2 id="ab-p">${jm.consent_notice.title}: privacy</h2><ul class="bullets">${jm.consent_notice.points.map((p) => html`<li>${p}</li>`)}</ul></section>
    </div>
    <section class="card section" aria-labelledby="ab-m"><h2 id="ab-m">The match score</h2>
      <p>A rule of thumb from four things only: <strong>skills and years</strong> (${w.skills} points), <strong>district</strong> (${w.district}), <strong>availability</strong> (${w.availability}) and <strong>language</strong> (${w.language}). If a job does not set one of them, the others are rescaled to 100. The weights are assumptions for this prototype, not a validated model; treat the score as a sorting aid, not a judgement.</p>
      <p class="small muted">No protected attribute exists in a profile, so none can influence the score.</p></section>
`);
  });
}

// ------------------------------------------------------------------ job seeker area
const seekHead = (path, title, sub, extra = '') => html`${roleSubnav(path)}<div class="pagehead"><div><p class="eyebrow">Job seeker</p><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ''}</div>${extra}</div>`;

export async function seekerHome(ctx) {
  const el = ctx.el;
  mount(el, html`${seekHead('/seeker', 'My job search', '', html`<div class="btnrow"><a class="btn primary" href="#/jobs">Find jobs</a></div>`)}<div id="sh"></div>`);
  await load($('#sh', el), async () => {
    const [d, ints, apps] = await Promise.all([api('/me/seeker'), api('/me/seeker/interests'), api('/me/seeker/applications')]);
    const box = $('#sh', el);
    if (!d.profile) {
      mount(box, html`<section class="card" aria-labelledby="np-h"><h2 id="np-h">Start with your profile</h2><p>Skills, languages, districts and when you can work. Employers see it only on this portal, never your phone or email.</p>
        <a class="btn primary section" href="#/seeker/profile">Create my profile</a></section>`);
      return;
    }
    const p = d.profile;
    const s = d.summary;
    mount(box, html`<div class="kpis k2">
        <div class="kpi"><span class="k">Active applications</span><span class="v">${s.applications_active}</span></div>
        <div class="kpi ${s.shortlisted ? 'ok' : ''}"><span class="k">Shortlisted or contacted</span><span class="v">${s.shortlisted}</span></div>
        <div class="kpi ${s.interests_pending ? 'warn' : ''}"><span class="k">Requests waiting for you</span><span class="v">${s.interests_pending}</span></div>
        <div class="kpi"><span class="k">Profile ${p.code}</span><span class="v vtext">${p.visibility === 'public' ? 'Visible to employers' : 'Hidden'}</span><a class="small" href="#/seeker/profile">Edit profile</a></div></div>
      <section class="section" aria-labelledby="ir-h"><div class="sechead"><h2 id="ir-h">Interest requests from employers</h2></div><div id="irl"></div></section>
      <section class="section" aria-labelledby="ap-h"><div class="sechead"><h2 id="ap-h">My applications</h2><a href="#/jobs">Find more jobs</a></div><div id="apl"></div></section>`);
    drawInterests($('#irl', box), ints.items, () => seekerHome(ctx));
    drawApps($('#apl', box), apps.items, () => seekerHome(ctx));
  });
}

function drawInterests(box, items, reload) {
  if (!items.length) { mount(box, html`<p class="muted">No requests yet. Employers can send one when your profile is visible.</p>`); return; }
  const order = { pending: 0, accepted: 1, declined: 2, withdrawn: 3 };
  items = items.slice().sort((a, b) => order[a.status] - order[b.status]);
  mount(box, moreList(items, (i) => html`<div class="item"><div class="main"><strong>${i.business_name}</strong>
      <div class="sub">${[i.business_type_label, i.district_name].filter(Boolean).join(' · ')}${i.job ? html` · about <a href="${href('/jobs/' + i.job.id)}">${i.job.title}</a>` : ''} · ${fmtDate(i.created_at)}</div>
      ${i.message ? html`<div class="sub">“${i.message}”</div>` : ''}${i.status === 'pending' ? html`<div class="hint">${i.accept_note}</div>` : ''}</div>
    <div class="side">${intPill(i.status)}${i.status === 'pending' ? html`<button type="button" class="btn sm primary" data-acc="${i.id}">Accept</button><button type="button" class="btn sm ghost" data-dec="${i.id}">Decline</button>` : ''}
      ${i.can_message ? html`<button type="button" class="btn sm ghost" data-thread="${i.id}" data-title="${i.business_name}">Messages${i.messages ? ` (${i.messages})` : ''}</button>` : ''}</div></div>`, 4));
  const decide = async (b, action) => {
    if (action === 'accept' && !(await confirmDialog('Accept this request? Your phone and email will be shared with this business only.', { ok: 'Accept and share contact' }))) return;
    busy(b, true, '…');
    try { await api(`/me/seeker/interests/${encodeURIComponent(b.dataset.acc || b.dataset.dec)}`, { method: 'POST', body: { action } }); toast(action === 'accept' ? 'Accepted: contact shared' : 'Declined'); reload(); } catch (e) { busy(b, false); toast(e.message, 'err'); }
  };
  $$('[data-acc]', box).forEach((b) => b.addEventListener('click', () => decide(b, 'accept')));
  $$('[data-dec]', box).forEach((b) => b.addEventListener('click', () => decide(b, 'decline')));
  $$('[data-thread]', box).forEach((b) => b.addEventListener('click', () => openThread(b.dataset.thread, 'Messages: ' + b.dataset.title, reload)));
}

function drawApps(box, items, reload) {
  if (!items.length) { mount(box, empty('No applications yet', 'Browse jobs ranked by how well they match your profile.', html`<a class="btn primary" href="#/jobs">Find jobs</a>`)); return; }
  mount(box, moreList(items, (a) => html`<div class="item"><div class="main"><a class="t" href="${href('/jobs/' + a.job.id)}">${a.job.title}</a>
      <div class="sub">${a.job.business_name} · ${a.job.district_name} · applied ${fmtDate(a.applied_at)}${a.job.status !== 'open' ? ' · post closed' : ''}</div></div>
    <div class="side">${appPill(a.status)}${a.can_message ? html`<button type="button" class="btn sm ghost" data-thread="${a.id}" data-title="${a.job.title}">Messages${a.messages ? ` (${a.messages})` : ''}</button>` : ''}
      ${['applied', 'viewed', 'shortlisted'].includes(a.status) ? html`<button type="button" class="btn sm ghost" data-wd="${a.id}">Withdraw</button>` : ''}</div></div>`, 5));
  $$('[data-thread]', box).forEach((b) => b.addEventListener('click', () => openThread(b.dataset.thread, 'Messages: ' + b.dataset.title, reload)));
  $$('[data-wd]', box).forEach((b) => b.addEventListener('click', async () => {
    if (!(await confirmDialog('Withdraw this application?', { ok: 'Withdraw', danger: true }))) return;
    try { await api(`/me/seeker/applications/${encodeURIComponent(b.dataset.wd)}/withdraw`, { method: 'POST' }); toast('Application withdrawn'); reload(); } catch (e) { toast(e.message, 'err'); }
  }));
}

export async function profile(ctx) {
  const el = ctx.el;
  const next = ctx.query.next;
  mount(el, html`${seekHead('/seeker/profile', 'My profile', 'What employers on this portal can see, and how they can reach you after you accept.')}<div id="pf"></div>`);
  await load($('#pf', el), async () => {
    const [own, m, jm] = await Promise.all([api('/me/seeker/profile'), meta(), jobsMeta()]);
    profileForm($('#pf', el), own.profile, own.consent_notice, m, jm, next);
  });
}

function profileForm(box, p, notice, m, jm, next) {
  const editing = !!p;
  const skills = p?.skills?.length ? p.skills.map((s) => ({ key: s.key, years: s.years })) : [{ key: '', years: 0 }];
  const certsKnown = jm.certification_suggestions;
  const certs = p?.certifications || [];
  const otherCerts = certs.filter((c) => !certsKnown.includes(c)).join(', ');
  const chk = (name, value, on, label) => html`<label class="check"><input type="checkbox" name="${name}" value="${value}" ${on ? raw('checked') : ''}>${label}</label>`;
  mount(box, html`<form class="form" id="prf" novalidate>
    ${editing ? html`<p class="flag ${p.visibility === 'public' ? 'green' : 'amber'}">Profile <strong>${p.code}</strong> is ${p.visibility === 'public' ? 'visible to businesses with an active registration' : 'hidden from search'}. Last updated ${fmtDate(p.updated_at)}.</p>` : ''}
    <div class="grid g2 section">
      <fieldset class="card"><legend class="lbl">About you</legend>
        ${field({ id: 'display_name', label: 'Display name', required: true, value: p?.display_name || '', hint: 'First name only is recommended (e.g. “Meena”).', attrs: 'maxlength="40" autocomplete="given-name"' })}
        ${field({ id: 'headline', label: 'Headline', required: true, value: p?.headline || '', placeholder: 'e.g. Trek guide, 6 years on Garhwal routes', attrs: 'maxlength="120"' })}
        ${field({ id: 'bio', label: 'Short bio', type: 'textarea', rows: 3, opt: true, value: p?.bio || '', hint: 'Up to 500 characters. Do not include age, religion, caste, family details or address.', attrs: 'maxlength="500"' })}
      </fieldset>
      <fieldset class="card"><legend class="lbl">Skills and years of experience</legend><div id="skrows"></div>
        <button type="button" class="btn sm ghost" id="addsk">Add a skill</button><p class="hint">Up to 8 skills, 0-40 years each.</p>
        <p class="lbl section">Certificates <span class="opt">(self-declared, not verified)</span></p>
        <div class="chips">${certsKnown.map((c) => chk('cert', c, certs.includes(c), c))}</div>
        ${field({ id: 'cert_other', label: 'Other certificates', opt: true, value: otherCerts, hint: 'Separate with commas.', attrs: 'maxlength="300"' })}
      </fieldset>
      <fieldset class="card"><legend class="lbl">Languages you speak</legend><div class="chips">${jm.languages.map((l) => chk('lang', l, (p?.languages || ['Hindi']).includes(l), l))}</div>
        <p class="lbl section">Preferred districts</p><div class="chips">${m.districts.map((d) => chk('dist', d.id, (p?.districts || []).includes(d.id), d.name))}</div>
        <p class="hint">Leave all unticked if you can work anywhere in Uttarakhand.</p></fieldset>
      <fieldset class="card"><legend class="lbl">Availability and pay</legend>
        <div class="chips" role="radiogroup" aria-label="Kind of work">${jm.job_types.map((x) => html`<label class="check"><input type="radio" name="availability" value="${x.key}" ${(p?.availability || 'seasonal') === x.key ? raw('checked') : ''}>${x.label}</label>`)}</div>
        <div class="grid g2 section">${field({ id: 'available_from', label: 'Available from', type: 'date', opt: true, value: p?.available_from || '' })}${field({ id: 'available_to', label: 'Available until', type: 'date', opt: true, value: p?.available_to || '' })}</div>
        <div class="grid g2">${field({ id: 'pay_min', label: 'Expected pay from (₹/month)', type: 'number', opt: true, value: p?.pay_min ?? '', attrs: 'min="0" max="500000" step="500" inputmode="numeric"' })}${field({ id: 'pay_max', label: 'to (₹/month)', type: 'number', opt: true, value: p?.pay_max ?? '', attrs: 'min="0" max="500000" step="500" inputmode="numeric"' })}</div>
      </fieldset>
      <fieldset class="card"><legend class="lbl">Contact (private)</legend>
        <p class="small"><span aria-hidden="true">🔒</span> Never shown publicly. Shared only with a business after you accept its interest request.</p>
        ${field({ id: 'phone', label: 'Phone', type: 'tel', value: p?.phone || '', attrs: 'maxlength="20" autocomplete="tel" inputmode="tel"' })}
        ${field({ id: 'email', label: 'Email', type: 'email', opt: true, value: p?.email || '', hint: 'Phone or email: at least one.', attrs: 'maxlength="120" autocomplete="email"' })}
      </fieldset>
      <fieldset class="card"><legend class="lbl">Visibility</legend>
        <label class="check"><input type="radio" name="visibility" value="public" ${(p?.visibility || 'public') === 'public' ? raw('checked') : ''}><span><b>Visible</b><br><span class="small">Businesses with an active registration can find you in search.</span></span></label>
        <label class="check section"><input type="radio" name="visibility" value="hidden" ${p?.visibility === 'hidden' ? raw('checked') : ''}><span><b>Hidden</b><br><span class="small">Not in search. Businesses you applied to can still see your profile.</span></span></label>
      </fieldset>
    </div>
    ${editing ? '' : html`<section class="card section consent" aria-labelledby="cn-h"><h2 id="cn-h" class="h3">${notice.title}</h2><ul class="bullets">${notice.points.map((x) => html`<li>${x}</li>`)}</ul>
      <label class="check req section"><input type="checkbox" name="consent" id="consent"><span>I have read this and want to create my profile.</span></label></section>`}
    <div class="btnrow section"><button class="btn primary" type="submit">${editing ? 'Save changes' : 'Create my profile'}</button>
      ${editing ? html`<button type="button" class="btn danger" id="delp">Delete my profile</button>` : ''}</div>
  </form>`);
  const form = $('#prf', box);
  const rows = $('#skrows', form);
  const drawRows = () => {
    mount(rows, html`${skills.map((s, i) => html`<div class="skrow"><div class="fld"><label class="lbl" for="sk-${i}">Skill ${i + 1}</label><select class="field" id="sk-${i}" data-i="${i}" name="${i === 0 ? 'skills' : 'sk' + i}">${skillOptions(jm, s.key, 'Choose a skill')}</select></div>
      <div class="fld"><label class="lbl" for="yr-${i}">Years</label><input class="field" id="yr-${i}" data-y="${i}" type="number" min="0" max="40" value="${s.years}" inputmode="numeric"></div>
      ${skills.length > 1 ? html`<button type="button" class="btn sm ghost" data-rm="${i}" aria-label="Remove skill ${i + 1}">Remove</button>` : ''}</div>`)}`);
    $$('[data-i]', rows).forEach((x) => x.addEventListener('change', () => { skills[+x.dataset.i].key = x.value; }));
    $$('[data-y]', rows).forEach((x) => x.addEventListener('input', () => { skills[+x.dataset.y].years = Math.max(0, Math.min(40, Number(x.value) || 0)); }));
    $$('[data-rm]', rows).forEach((x) => x.addEventListener('click', () => { skills.splice(+x.dataset.rm, 1); drawRows(); $('#addsk', form).focus(); }));
    $('#addsk', form).disabled = skills.length >= 8;
  };
  drawRows();
  $('#addsk', form).addEventListener('click', () => { skills.push({ key: '', years: 0 }); drawRows(); $(`#sk-${skills.length - 1}`, form).focus(); });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const str = (k) => (fd.get(k) || '').toString().trim();
    const numOrNull = (k) => (str(k) === '' ? null : Number(str(k)));
    const body = {
      display_name: str('display_name'), headline: str('headline'), bio: str('bio') || null,
      skills: skills.filter((s) => s.key).map((s) => ({ key: s.key, years: s.years })),
      certifications: [...fd.getAll('cert'), ...str('cert_other').split(',').map((x) => x.trim()).filter(Boolean)].slice(0, 8),
      languages: fd.getAll('lang'), districts: fd.getAll('dist'), availability: str('availability') || 'seasonal',
      available_from: str('available_from') || null, available_to: str('available_to') || null,
      pay_min: numOrNull('pay_min'), pay_max: numOrNull('pay_max'), phone: str('phone') || null, email: str('email') || null, visibility: str('visibility') || 'public',
    };
    const errs = {};
    if (body.display_name.length < 2) errs.display_name = 'Enter a display name (2-40 characters).';
    if (body.headline.length < 5) errs.headline = 'Write a short headline (at least 5 characters).';
    if (!body.skills.length) errs.skills = 'Choose at least one skill.';
    if (!body.phone && !body.email) errs.phone = 'Add a phone number or an email.';
    if (body.available_from && body.available_to && body.available_to < body.available_from) errs.available_to = 'This is before the start date.';
    if (body.pay_min != null && body.pay_max != null && body.pay_max < body.pay_min) errs.pay_max = 'Lower than the minimum.';
    if (!editing && !fd.get('consent')) errs.consent = 'Please tick to confirm you read the notice.';
    if (!body.languages.length) { showErrors(form, errs, 'Choose at least one language.'); return; }
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    if (!editing) body.consent = true;
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Saving…');
    try {
      await api('/me/seeker/profile', { method: editing ? 'PATCH' : 'POST', body });
      toast(editing ? 'Profile saved' : 'Profile created');
      if (next && /^\/jobs(\/|$)/.test(next)) location.hash = next; else go(editing ? '/seeker/profile' : '/jobs');
      if (editing) busy(btn, false);
    } catch (err) {
      busy(btn, false);
      const fe = apiFieldErrors(err);
      showErrors(form, fe, err.data?.errors?.find((x) => !x.field)?.message?.replace(/^Value error, /, '') || err.message);
    }
  });
  $('#delp', form)?.addEventListener('click', async () => {
    if (!(await confirmDialog('Delete your profile permanently? Your applications, interest requests and messages are deleted too. This cannot be undone.', { ok: 'Delete everything', danger: true }))) return;
    try {
      await api('/me/seeker/profile', { method: 'DELETE' });
      toast('Profile deleted');
      go('/seeker');
    } catch (e) { mount(box, errorBox(e, { retry: false })); }
  });
}
