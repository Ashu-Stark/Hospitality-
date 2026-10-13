// Business hiring area: overview (posts, sent interest requests, shortlist), post a job, applicants per post,
// candidate search with a transparent match score, candidate profile with interest request and contact reveal.
// Needs an ACTIVE registration (the API answers 403 otherwise and the pages say so).
import { html, mount, href, load, $, $$, raw, field, showErrors, clearErrors, apiFieldErrors, busy, crumbs, fmtDate, toast, empty, confirmDialog, collapseFilters, announce, moreList } from '../ui.js';
import { api, meta, jobsMeta } from '../api.js';
import { go, setQuery } from '../router.js';
import { roleSubnav } from './common.js';
import { appPill, intPill, payText, typeText, skillTags, matchBadge, whyChips, skillOptions, districtOptions, serverPager, openThread } from './jobs.js';

const head = (path, title, sub, extra = '') => html`${roleSubnav('/business/hiring')}<div class="pagehead"><div><p class="eyebrow">Business · hiring</p><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ''}</div>${extra}</div>`;
const NO_ACTIVE = 'Hiring needs a business with an active registration. Renew or finish your registration first.';

function contactBox(c) {
  if (!c) return html`<p class="lockbox"><span aria-hidden="true">🔒</span> Contact details are shared only after the candidate accepts your interest request.</p>`;
  return html`<div class="flag green"><strong>Contact shared by the candidate</strong><br>${c.phone ? html`Phone: <span class="mono">${c.phone}</span>` : ''}${c.phone && c.email ? html`<br>` : ''}${c.email ? html`Email: <span class="mono">${c.email}</span>` : ''}${c.synthetic ? html`<br><span class="small">${c.note}</span>` : ''}</div>`;
}

function candCard(c, { job } = {}) {
  return html`<article class="jobcard cand">
    <div class="jc-top"><h2 class="h3"><a href="${href('/business/hiring/candidates/' + c.code, job ? { job } : {})}">${c.display_name}</a></h2>${matchBadge(c.match)}</div>
    <p class="sub">${c.headline}</p>
    <div class="chips">${skillTags(c.skills.slice(0, 3), true)}</div>
    <p class="jfacts">${c.any_district ? 'Any district' : c.district_names.join(', ')}<br>${typeText(c)} · ${payText(c.pay_min, c.pay_max)}</p>
    ${whyChips(c.match, 2)}
    <div class="jc-foot"><span class="small muted mono">${c.code}</span>${c.interest ? intPill(c.interest.status) : ''}${c.shortlisted ? html`<span class="pill info noicon">Shortlisted</span>` : ''}${c.synthetic ? html`<span class="pill syn">Sample</span>` : ''}</div>
  </article>`;
}

// ------------------------------------------------------------------ overview
export async function overview(ctx) {
  const el = ctx.el;
  const tab = ['posts', 'interests', 'shortlist'].includes(ctx.query.tab) ? ctx.query.tab : 'posts';
  mount(el, html`${head('/business/hiring', 'Hiring', 'Your job posts, requests to candidates and shortlist.', html`<div class="btnrow"><a class="btn primary" href="#/business/hiring/new">Post a job</a><a class="btn ghost" href="#/business/hiring/candidates">Search candidates</a></div>`)}<div id="ho"></div>`);
  await load($('#ho', el), async () => {
    const mine = await api('/jobs/mine');
    const s = mine.summary;
    const box = $('#ho', el);
    mount(box, html`${mine.can_hire ? '' : html`<p class="flag amber">${NO_ACTIVE} <a href="#/business">Business dashboard</a></p>`}
      <div class="kpis k2">
        <div class="kpi"><span class="k">Open job posts</span><span class="v">${s.open_posts}</span></div>
        <div class="kpi ${s.new_applications ? 'warn' : ''}"><span class="k">New applications</span><span class="v">${s.new_applications}</span><span class="small muted">${s.applications} in total</span></div>
        <div class="kpi"><span class="k">Requests awaiting reply</span><span class="v">${s.interests_pending}</span></div>
        <div class="kpi ok"><span class="k">Accepted (contact shared)</span><span class="v">${s.interests_accepted}</span></div></div>
      <div class="tabs section"><div class="pillnav" role="tablist" aria-label="Hiring lists">
        ${[['posts', `Job posts (${mine.total})`], ['interests', 'Interest requests'], ['shortlist', `Shortlist (${s.shortlisted})`]].map(([k, l]) => html`<button type="button" role="tab" id="ht-${k}" aria-controls="hpanel" data-tab="${k}">${l}</button>`)}</div></div>
      <div id="hpanel" role="tabpanel" tabindex="-1" class="section"></div>`);
    let cur = tab;
    const panel = $('#hpanel', box);
    const show = () => {
      $$('[role=tab]', box).forEach((b) => { const on = b.dataset.tab === cur; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
      panel.setAttribute('aria-labelledby', 'ht-' + cur);
      setQuery({ tab: cur === 'posts' ? '' : cur });
      if (cur === 'posts') return drawPosts(panel, mine.items, () => overview(ctx));
      return load(panel, cur === 'interests' ? () => drawInterests(panel) : () => drawShortlist(panel), { skel: 'list', n: 3 });
    };
    $$('[role=tab]', box).forEach((b, i, all) => {
      b.addEventListener('click', () => { cur = b.dataset.tab; show(); });
      b.addEventListener('keydown', (e) => { const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (!d) return; e.preventDefault(); const n = all[(i + d + all.length) % all.length]; cur = n.dataset.tab; show(); n.focus(); });
    });
    show();
  });
}

function drawPosts(panel, items, reload) {
  if (!items.length) { mount(panel, empty('No job posts yet', 'Post your first job: it takes about two minutes.', html`<a class="btn primary" href="#/business/hiring/new">Post a job</a>`)); return; }
  mount(panel, moreList(items, (j) => html`<div class="item"><div class="main"><a class="t" href="${href('/business/hiring/jobs/' + j.id)}">${j.title}</a>
      <div class="sub">${j.business_name} · ${j.district_name} · ${typeText(j)} · ${j.status === 'open' ? 'closes ' + fmtDate(j.closes_on, { noYear: true }) : 'closed' + (j.closed_reason ? ' (' + j.closed_reason + ')' : '')}</div></div>
    <div class="side">${j.status === 'open' ? html`<span class="pill ok">Open</span>` : html`<span class="pill neutral">Closed</span>`}${j.applications_new ? html`<span class="pill warn">${j.applications_new} new</span>` : ''}
      <a class="btn sm ghost" href="${href('/business/hiring/jobs/' + j.id)}">Applicants (${j.applications_total})</a>
      ${j.status === 'open' ? html`<button type="button" class="btn sm ghost" data-close="${j.id}">Close</button>` : ''}</div></div>`, 6));
  $$('[data-close]', panel).forEach((b) => b.addEventListener('click', () => closePost(b, b.dataset.close, reload)));
}

async function closePost(btn, id, reload) {
  const filled = await confirmDialog('Close this job post? Choose "Filled" if you hired someone through the portal (this helps the time-to-fill statistics).', { ok: 'Close as filled' });
  const reason = filled ? 'filled' : (await confirmDialog('Close it without hiring (withdraw the post)?', { ok: 'Withdraw post', danger: true })) ? 'withdrawn' : null;
  if (!reason) return;
  busy(btn, true, '…');
  try { await api('/jobs/' + encodeURIComponent(id), { method: 'PATCH', body: { status: 'closed', closed_reason: reason }, auth: true }); toast('Job post closed'); reload(); } catch (e) { busy(btn, false); toast(e.message, 'err'); }
}

async function drawInterests(panel) {
  const r = await api('/candidates/interests');
  if (!r.items.length) { mount(panel, empty('No requests sent', 'Search candidates and send an interest request to the ones you like.', html`<a class="btn primary" href="#/business/hiring/candidates">Search candidates</a>`)); return; }
  mount(panel, moreList(r.items, (i) => html`<div class="item"><div class="main"><a class="t" href="${href('/business/hiring/candidates/' + i.candidate?.code)}">${i.candidate?.display_name || 'Deleted profile'}</a>
      <div class="sub">${i.candidate?.headline || ''}${i.job ? ` · for ${i.job.title}` : ''} · sent ${fmtDate(i.created_at)}</div>
      ${i.candidate?.contact ? html`<div class="sub">Contact: <span class="mono">${i.candidate.contact.phone || ''}${i.candidate.contact.email ? ' · ' + i.candidate.contact.email : ''}</span>${i.candidate.contact.synthetic ? ' (synthetic placeholder)' : ''}</div>` : ''}</div>
    <div class="side">${intPill(i.status)}${i.can_message ? html`<button type="button" class="btn sm ghost" data-thread="${i.id}" data-title="${i.candidate?.display_name || ''}">Messages${i.messages ? ` (${i.messages})` : ''}</button>` : ''}</div></div>`, 6));
  $$('[data-thread]', panel).forEach((b) => b.addEventListener('click', () => openThread(b.dataset.thread, 'Messages: ' + b.dataset.title)));
}

async function drawShortlist(panel) {
  const r = await api('/candidates/shortlist');
  if (!r.items.length) { mount(panel, empty('Shortlist is empty', 'Use “Shortlist” on a candidate to keep them here.')); return; }
  mount(panel, moreList(r.items, (c) => html`<div class="item"><div class="main"><a class="t" href="${href('/business/hiring/candidates/' + c.code)}">${c.display_name}</a>
      <div class="sub">${c.headline} · ${c.any_district ? 'any district' : c.district_names.join(', ')}</div></div>
    <div class="side">${c.interest ? intPill(c.interest.status) : ''}<button type="button" class="btn sm ghost" data-unsl="${c.code}">Remove</button></div></div>`, 6));
  $$('[data-unsl]', panel).forEach((b) => b.addEventListener('click', async () => {
    try { await api(`/candidates/${encodeURIComponent(b.dataset.unsl)}/shortlist`, { method: 'DELETE' }); toast('Removed from shortlist'); drawShortlist(panel); } catch (e) { toast(e.message, 'err'); }
  }));
}

// ------------------------------------------------------------------ post a job
export async function newJob(ctx) {
  const el = ctx.el;
  mount(el, html`${head('/business/hiring/new', 'Post a job', 'Shown on the public job board until the closing date. Do not ask candidates for fees.')}<div id="nj"></div>`);
  await load($('#nj', el), async () => {
    const [mine, m, jm] = await Promise.all([api('/jobs/mine'), meta(), jobsMeta()]);
    const box = $('#nj', el);
    if (!mine.can_hire) { mount(box, html`<p class="flag amber">${NO_ACTIVE}</p><a class="btn ghost" href="#/business">Business dashboard</a>`); return; }
    const biz = mine.active_businesses;
    const in30 = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
    const today = new Date().toISOString().slice(0, 10);
    mount(box, html`<form class="form" id="jf" novalidate><div class="grid g2">
      <fieldset class="card"><legend class="lbl">The job</legend>
        ${field({ id: 'business_id', label: 'Business', type: 'select', required: true, options: biz.map((b) => ({ value: b.id, label: b.name })) })}
        ${field({ id: 'title', label: 'Job title', required: true, placeholder: 'e.g. Cook for the yatra season', attrs: 'maxlength="80"' })}
        <div class="fld"><label class="lbl" for="skill1">Main skill</label><select class="field" id="skill1" name="skills" required>${skillOptions(jm, '', 'Choose a skill')}</select></div>
        <div class="fld"><label class="lbl" for="skill2">Second skill <span class="opt">(optional)</span></label><select class="field" id="skill2" name="skill2">${skillOptions(jm, '', 'None')}</select></div>
        <div class="fld"><label class="lbl" for="destination_id">Place <span class="opt">(optional)</span></label><select class="field" id="destination_id" name="destination_id"></select></div>
        ${field({ id: 'description', label: 'Description', type: 'textarea', rows: 5, required: true, hint: '20-1000 characters: duties, timings, what you provide.', attrs: 'maxlength="1000"' })}
      </fieldset>
      <fieldset class="card"><legend class="lbl">Terms</legend>
        <div class="chips" role="radiogroup" aria-label="Job type">${jm.job_types.map((x, i) => html`<label class="check"><input type="radio" name="job_type" value="${x.key}" ${i === 0 ? raw('checked') : ''}>${x.label}</label>`)}</div>
        <div class="grid g2 section" id="season">${field({ id: 'season_from', label: 'Season starts', type: 'date', attrs: `min="${today}"` })}${field({ id: 'season_to', label: 'Season ends', type: 'date', attrs: `min="${today}"` })}</div>
        <div class="grid g2">${field({ id: 'pay_min', label: 'Pay from (₹/month)', type: 'number', opt: true, attrs: 'min="0" max="500000" step="500" inputmode="numeric"' })}${field({ id: 'pay_max', label: 'to (₹/month)', type: 'number', opt: true, attrs: 'min="0" max="500000" step="500" inputmode="numeric"' })}</div>
        <div class="chips"><label class="check"><input type="checkbox" name="accommodation">Accommodation provided</label><label class="check"><input type="checkbox" name="food">Meals provided</label></div>
        <div class="grid g2 section">${field({ id: 'openings', label: 'Openings', type: 'number', value: '1', required: true, attrs: 'min="1" max="50" inputmode="numeric"' })}${field({ id: 'closes_on', label: 'Applications close on', type: 'date', value: in30, required: true, attrs: `min="${today}"` })}</div>
        <p class="lbl">Languages needed <span class="opt">(optional)</span></p><div class="chips">${['Hindi', 'English', 'Garhwali', 'Kumaoni', 'Nepali'].map((l) => html`<label class="check"><input type="checkbox" name="languages" value="${l}">${l}</label>`)}</div>
      </fieldset></div>
      <div class="btnrow section"><button class="btn primary" type="submit">Publish job post</button><a class="btn ghost" href="#/business/hiring">Cancel</a></div></form>`);
    const form = $('#jf', box);
    const destSel = $('#destination_id', form);
    const fillDest = () => {
      const b = biz.find((x) => x.id === form.business_id.value);
      const ds = m.destinations.filter((d) => d.district === b.district);
      mount(destSel, html`<option value="">${m.districts.find((d) => d.id === b.district)?.name || ''} (district)</option>${ds.map((d) => html`<option value="${d.id}" ${d.id === b.destination_id ? raw('selected') : ''}>${d.name}</option>`)}`);
    };
    fillDest();
    form.business_id.addEventListener('change', fillDest);
    const seasonVis = () => { $('#season', form).hidden = form.querySelector('input[name=job_type]:checked').value !== 'seasonal'; };
    form.addEventListener('change', (e) => { if (e.target.name === 'job_type') seasonVis(); });
    seasonVis();
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const s = (k) => (fd.get(k) || '').toString().trim();
      const n = (k) => (s(k) === '' ? null : Number(s(k)));
      const jt = s('job_type');
      const body = {
        business_id: s('business_id'), title: s('title'), skills: [s('skills'), s('skill2')].filter((x, i, a) => x && a.indexOf(x) === i), destination_id: s('destination_id') || null,
        job_type: jt, season_from: jt === 'seasonal' ? s('season_from') || null : null, season_to: jt === 'seasonal' ? s('season_to') || null : null,
        pay_min: n('pay_min'), pay_max: n('pay_max'), accommodation: !!fd.get('accommodation'), food: !!fd.get('food'), openings: n('openings') || 1,
        languages: fd.getAll('languages'), description: s('description'), closes_on: s('closes_on'),
      };
      const errs = {};
      if (body.title.length < 3) errs.title = 'Enter a job title.';
      if (!body.skills.length) errs.skills = 'Choose the main skill.';
      if (body.description.length < 20) errs.description = 'Write at least 20 characters.';
      if (jt === 'seasonal' && !body.season_from) errs.season_from = 'Seasonal jobs need a start date.';
      if (jt === 'seasonal' && !body.season_to) errs.season_to = 'Seasonal jobs need an end date.';
      if (!body.closes_on) errs.closes_on = 'Choose a closing date.';
      if (Object.keys(errs).length) { showErrors(form, errs); return; }
      clearErrors(form);
      const btn = form.querySelector('button[type=submit]');
      busy(btn, true, 'Publishing…');
      try {
        const j = await api('/jobs', { method: 'POST', body, auth: true });
        toast('Job post published');
        go('/business/hiring/jobs/' + j.id);
      } catch (err) {
        busy(btn, false);
        showErrors(form, apiFieldErrors(err), err.message);
      }
    });
  });
}

// ------------------------------------------------------------------ applicants of one post
export async function applicants(ctx) {
  const el = ctx.el;
  const id = ctx.params.id;
  mount(el, html`${roleSubnav('/business/hiring')}${crumbs([['Hiring', '#/business/hiring'], ['Applicants']])}<h1 class="sr-only">Applicants</h1><div id="aj"></div>`);
  const draw = () => load($('#aj', el), async () => {
    const r = await api(`/jobs/${encodeURIComponent(id)}/applications`);
    const j = r.job;
    mount($('#aj', el), html`<div class="pagehead"><div><p class="eyebrow">Applicants · ${j.status === 'open' ? 'open post' : 'closed post'}</p><h1>${j.title}</h1>
        <p>${j.business_name} · ${j.district_name} · ${typeText(j)} · ${payText(j.pay_min, j.pay_max)}</p></div>
        <div class="btnrow"><a class="btn ghost" href="${href('/jobs/' + j.id)}">Public view</a><a class="btn ghost" href="${href('/business/hiring/candidates', { job: j.id })}">Find more candidates</a>${j.status === 'open' ? html`<button type="button" class="btn ghost" id="closej">Close post</button>` : ''}</div></div>
      <p class="small muted">${r.total} applicant${r.total === 1 ? '' : 's'}, best match first. Opening this list marks new applications as viewed. Contact details appear only after a candidate accepts your request.</p>
      <div class="list section" id="apps">${r.items.length ? r.items.map(appRow) : empty('No applications yet', 'Search candidates and send interest requests to invite them.')}</div>`);
    $('#closej', el)?.addEventListener('click', (e) => closePost(e.currentTarget, j.id, draw));
    wireApps($('#apps', el), j, draw);
  }, { skel: 'list', n: 4 });
  await draw();
}

const NEXT_LABEL = { viewed: 'Viewed', shortlisted: 'Shortlist', contacted: 'Mark contacted', not_selected: 'Not selected' };
function appRow(a) {
  const c = a.candidate;
  return html`<div class="item appl"><div class="main"><div class="rowx"><a class="t" href="${href('/business/hiring/candidates/' + c.code)}">${c.display_name}</a>${matchBadge(a.match)}</div>
      <div class="sub">${c.headline} · applied ${fmtDate(a.applied_at)}</div>
      ${a.note ? html`<div class="sub">Note: “${a.note}”</div>` : ''}${whyChips(a.match, 4)}
      ${c.contact ? html`<div class="sub">Contact: <span class="mono">${c.contact.phone || ''}${c.contact.email ? ' · ' + c.contact.email : ''}</span>${c.contact.synthetic ? ' (synthetic placeholder)' : ''}</div>` : ''}</div>
    <div class="side">${appPill(a.status)}${c.interest ? intPill(c.interest.status) : ''}
      ${a.next_statuses.filter((s) => s !== 'viewed').map((s) => html`<button type="button" class="btn sm ${s === 'not_selected' ? 'ghost' : 'ghost'}" data-st="${s}" data-app="${a.id}">${NEXT_LABEL[s]}</button>`)}
      ${!c.interest ? html`<button type="button" class="btn sm primary" data-req="${c.code}">Request contact</button>` : ''}
      <button type="button" class="btn sm ghost" data-thread="${a.id}" data-title="${c.display_name}">Messages${a.messages ? ` (${a.messages})` : ''}</button></div></div>`;
}

function wireApps(box, j, reload) {
  $$('[data-st]', box).forEach((b) => b.addEventListener('click', async () => {
    busy(b, true, '…');
    try { await api(`/jobs/applications/${encodeURIComponent(b.dataset.app)}/status`, { method: 'POST', body: { status: b.dataset.st } }); toast('Status updated'); reload(); } catch (e) { busy(b, false); toast(e.message, 'err'); }
  }));
  $$('[data-req]', box).forEach((b) => b.addEventListener('click', async () => {
    busy(b, true, 'Sending…');
    try { await api(`/candidates/${encodeURIComponent(b.dataset.req)}/interest`, { method: 'POST', body: { job_id: j.id, message: `About your application for ${j.title}: may we have your contact details?` } }); toast('Request sent. Contact appears when the candidate accepts.'); reload(); } catch (e) { busy(b, false); toast(e.message, 'err'); }
  }));
  $$('[data-thread]', box).forEach((b) => b.addEventListener('click', () => openThread(b.dataset.thread, 'Messages: ' + b.dataset.title, reload)));
}

// ------------------------------------------------------------------ candidate search
export async function candidates(ctx) {
  const el = ctx.el;
  const q = ctx.query;
  const f = { job: q.job || '', skill: q.skill || '', district: q.district || '', available_from: q.available_from || '', available_to: q.available_to || '', exp_min: q.exp_min || '', language: q.language || '', page: Number(q.page) || 1 };
  mount(el, html`${head('/business/hiring/candidates', 'Search candidates', 'Public profiles only. Ranked by a transparent match score; contact details stay hidden until a candidate accepts your request.')}<div id="cs"></div>`);
  await load($('#cs', el), async () => {
    const [mine, m, jm] = await Promise.all([api('/jobs/mine'), meta(), jobsMeta()]);
    const box = $('#cs', el);
    if (!mine.can_hire) { mount(box, html`<p class="flag amber">${NO_ACTIVE}</p>`); return; }
    const open = mine.items.filter((j) => j.status === 'open');
    mount(box, html`<form class="card tight filters" id="cf" aria-label="Filter candidates">
        <div class="fld"><label class="lbl" for="cf-j">Match against</label><select class="field" id="cf-j" name="job"><option value="">My filters</option>${open.map((j) => html`<option value="${j.id}" ${f.job === j.id ? raw('selected') : ''}>Job: ${j.title}</option>`)}</select></div>
        <div class="fld"><label class="lbl" for="cf-s">Skill</label><select class="field" id="cf-s" name="skill">${skillOptions(jm, f.skill)}</select></div>
        <div class="fld"><label class="lbl" for="cf-d">District</label><select class="field" id="cf-d" name="district">${districtOptions(m, f.district)}</select></div>
        <div class="fld"><label class="lbl" for="cf-e">Experience at least</label><select class="field" id="cf-e" name="exp_min"><option value="">Any</option>${[1, 2, 3, 5, 10].map((y) => html`<option value="${y}" ${String(y) === f.exp_min ? raw('selected') : ''}>${y}+ years</option>`)}</select></div>
        <div class="fld"><label class="lbl" for="cf-l">Language</label><select class="field" id="cf-l" name="language"><option value="">Any</option>${jm.languages.filter((l) => l !== 'Other').map((l) => html`<option ${l === f.language ? raw('selected') : ''}>${l}</option>`)}</select></div>
        <div class="fld"><label class="lbl" for="cf-af">Available from</label><input class="field" type="date" id="cf-af" name="available_from" value="${f.available_from}"></div>
        <div class="fld"><label class="lbl" for="cf-at">Available until</label><input class="field" type="date" id="cf-at" name="available_to" value="${f.available_to}"></div>
      </form><div id="cl" class="section" aria-live="polite"></div>`);
    const form = $('#cf', box);
    collapseFilters(form, 'Filters');
    const list = $('#cl', box);
    const draw = () => load(list, async () => {
      setQuery({ ...f, page: f.page > 1 ? f.page : '' });
      const query = { job_id: f.job || undefined, skill: f.skill || undefined, district: f.district || undefined, exp_min: f.exp_min || undefined, language: f.language || undefined, available_from: f.available_from || undefined, available_to: f.available_to || undefined, page: f.page };
      const r = await api('/candidates', { query });
      const against = r.matched_against?.title ? `your job “${r.matched_against.title}”` : r.matched_against ? 'your filters' : null;
      mount(list, r.items.length ? html`<p class="small muted resline"><strong>${r.total} candidate${r.total === 1 ? '' : 's'}</strong>${against ? ` · match scored against ${against}` : ' · set a skill, district or job to get a match score'}</p>
          <div class="jobgrid">${r.items.map((c) => candCard(c, { job: f.job }))}</div>`
        : empty('No candidates match', 'Remove a filter: try any district or a lower experience level.'));
      serverPager(list, r, (p) => { f.page = p; draw().then(() => list.scrollIntoView({ block: 'start' })); });
      announce(`${r.total} candidates`);
    }, { skel: 'cards', n: 6, label: 'Searching…' });
    form.addEventListener('change', () => { const fd = new FormData(form); Object.keys(f).forEach((k) => { if (k !== 'page') f[k] = (fd.get(k) || '').toString(); }); f.page = 1; draw(); });
    form.addEventListener('submit', (e) => e.preventDefault());
    await draw();
  });
}

// ------------------------------------------------------------------ one candidate
export async function candidate(ctx) {
  const el = ctx.el;
  const code = ctx.params.code;
  const jobId = ctx.query.job || '';
  mount(el, html`${roleSubnav('/business/hiring')}${crumbs([['Hiring', '#/business/hiring'], ['Candidates', '#/business/hiring/candidates'], [code]])}<h1 class="sr-only">Candidate</h1><div id="cd"></div>`);
  const draw = () => load($('#cd', el), async () => {
    const [c, mine] = await Promise.all([api('/candidates/' + encodeURIComponent(code), { query: { job_id: jobId || undefined } }), api('/jobs/mine')]);
    const open = mine.items.filter((j) => j.status === 'open');
    const box = $('#cd', el);
    mount(box, html`<div class="pagehead"><div><p class="eyebrow">Candidate · <span class="mono">${c.code}</span>${c.synthetic ? html` <span class="pill syn">Sample</span>` : ''}</p><h1>${c.display_name}</h1><p>${c.headline}</p></div>
        <div class="btnrow">${matchBadge(c.match)}<button type="button" class="btn ghost" id="sl" aria-pressed="${String(!!c.shortlisted)}">${c.shortlisted ? 'Shortlisted ✓' : 'Shortlist'}</button></div></div>
      <div class="split">
        <section class="card" aria-labelledby="cp-h"><h2 id="cp-h">Profile</h2>
          ${c.match ? whyChips(c.match, 6) : ''}
          <dl class="facts section">
            <dt>Skills</dt><dd><div class="chips">${skillTags(c.skills, true)}</div></dd>
            <dt>Languages</dt><dd>${c.languages.join(', ')}</dd>
            <dt>Districts</dt><dd>${c.any_district ? 'Any district in Uttarakhand' : c.district_names.join(', ')}</dd>
            <dt>Availability</dt><dd>${typeText(c)}</dd>
            <dt>Expected pay</dt><dd>${payText(c.pay_min, c.pay_max)}</dd>
            ${c.certifications.length ? html`<dt>Certificates</dt><dd>${c.certifications.join(', ')}<br><span class="small muted">${c.certifications_note}</span></dd>` : ''}
          </dl>
          ${c.bio ? html`<h3 class="section">About</h3><p class="prewrap">${c.bio}</p>` : ''}
          <p class="hint section">Profiles never include gender, age, religion, caste, family details, photo or address.</p></section>
        <aside class="card" aria-labelledby="ct-h"><h2 id="ct-h">Contact</h2>${contactBox(c.contact)}<div id="intbox" class="section"></div></aside>
      </div>`);
    const ib = $('#intbox', box);
    if (c.interest) {
      mount(ib, html`<p>Your request: ${intPill(c.interest.status)} <span class="small muted">sent ${fmtDate(c.interest.created_at)}</span></p>
        ${c.interest.can_message ? html`<button type="button" class="btn ghost" id="msg">Messages</button>` : c.interest.status === 'pending' ? html`<p class="small muted">You will see the contact here when the candidate accepts.</p>` : ''}`);
      $('#msg', ib)?.addEventListener('click', () => openThread(c.interest.id, 'Messages: ' + c.display_name));
    } else {
      mount(ib, html`<form id="inf" class="form" novalidate><h3>Send an interest request</h3>
        ${open.length ? field({ id: 'job_id', label: 'For job', type: 'select', opt: true, value: jobId, options: [{ value: '', label: 'General interest' }, ...open.map((j) => ({ value: j.id, label: j.title }))] }) : ''}
        ${field({ id: 'message', label: 'Short message', type: 'textarea', rows: 3, opt: true, value: 'Namaste, we are hiring and liked your profile. Would you like to talk?', attrs: 'maxlength="500"' })}
        <button class="btn primary" type="submit">Send request</button><p class="hint">One request per candidate. They choose whether to share their contact.</p></form>`);
      const form = $('#inf', ib);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const btn = form.querySelector('button[type=submit]');
        busy(btn, true, 'Sending…');
        try {
          await api(`/candidates/${encodeURIComponent(c.code)}/interest`, { method: 'POST', body: { job_id: (fd.get('job_id') || '') || null, message: (fd.get('message') || '').toString().trim() || null } });
          toast('Interest request sent');
          draw();
        } catch (err) { busy(btn, false); showErrors(form, apiFieldErrors(err), err.message); }
      });
    }
    $('#sl', box).addEventListener('click', async (e) => {
      const b = e.currentTarget;
      const on = b.getAttribute('aria-pressed') === 'true';
      try {
        await api(`/candidates/${encodeURIComponent(c.code)}/shortlist`, { method: on ? 'DELETE' : 'PUT' });
        b.setAttribute('aria-pressed', String(!on));
        b.textContent = on ? 'Shortlist' : 'Shortlisted ✓';
        toast(on ? 'Removed from shortlist' : 'Added to shortlist');
      } catch (err) { toast(err.message, 'err'); }
    });
  }, { skel: 'page' });
  await draw();
}

