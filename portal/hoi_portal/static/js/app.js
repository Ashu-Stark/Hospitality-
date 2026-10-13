// UTHP (concept) web app entry: shell (header, menus, footer, text size, language) + route table.
import { route, start, render, onNavigate, go, parseHash } from './router.js';
import { html, mount, raw, $, $$, store, toast } from './ui.js';
import { t, getLang, setLang } from './i18n.js';
import { user, role, logout, isOfficial, homeOf } from './api.js';
import { MAIN, SECTIONS, sectionOf, BUSINESS_NAV, OFFICER_NAV, ADMIN_NAV, SEEKER_NAV } from './nav.js';
import * as home from './pages/home.js';
import * as dest from './pages/destinations.js';
import * as reg from './pages/registry.js';
import * as fest from './pages/festivals.js';
import * as dict from './pages/dictionary.js';
import * as info from './pages/info.js';
import * as griev from './pages/grievance.js';
import * as auth from './pages/auth.js';
import * as biz from './pages/business.js';
import * as off from './pages/officer.js';
import * as ops from './pages/officer_ops.js';
import * as plan from './pages/plan.js';
import * as jobs from './pages/jobs.js';
import * as hire from './pages/hiring.js';
import * as stays from './pages/stays.js';
import * as local from './pages/local.js';
import * as host from './pages/host.js';
import { loadPhotos } from './photos.js';

const OFF = ['district_officer', 'state_admin'];
const BIZ = ['business'];
const SEEK = ['job_seeker'];

route('/', home.home);
route('/search', home.search);
route('/experiences', local.list);
route('/experiences/local', local.list);
route('/experiences/themes', plan.experiences);
route('/experiences/local/:id', local.detail);
route('/experiences/:id', plan.experience);
route('/stays', stays.list);
route('/host', host.page);
route('/plan', plan.itineraries);
route('/plan/itineraries/:id', plan.itinerary);
route('/plan/circuits', plan.circuits);
route('/plan/map', plan.map);
route('/plan/reach', plan.reach);
route('/plan/services', plan.services);
route('/destinations', dest.list);
route('/destinations/:id', dest.detail);
route('/destinations/:id/:tab', dest.detail);
route('/directory', reg.directory);
route('/directory/:id', reg.business);
route('/verify', reg.verify);
route('/festivals', fest.festivals);
route('/dictionary', dict.list);
route('/dictionary/:id', dict.term);
route('/rules', info.rules);
route('/rules/:id', info.rule);
route('/helplines', info.helplines);
route('/about', info.about);
route('/accessibility', info.accessibility);
route('/sitemap', info.sitemap);
route('/credits', info.credits);
route('/grievance', griev.file);
route('/grievance/track', griev.track);
route('/signin', auth.signin);
route('/register', auth.register);
route('/business', biz.dashboard, { roles: BIZ });
route('/business/apply', biz.apply, { roles: BIZ });
route('/business/applications/:id', biz.application, { roles: BIZ });
route('/business/certificate/:id', biz.certificate, { roles: BIZ });
route('/business/occupancy', biz.occupancy, { roles: BIZ });
route('/business/api-keys', biz.apiKeys, { roles: BIZ });
route('/business/experiences', local.hostDashboard, { roles: BIZ });
route('/business/staffing', local.agencyDashboard, { roles: BIZ });
route('/jobs', jobs.board);
route('/jobs/hire', jobs.hire);
route('/jobs/about', jobs.about);
route('/jobs/agencies', jobs.agencies);
route('/jobs/:id', jobs.detail);
route('/seeker', jobs.seekerHome, { roles: SEEK });
route('/seeker/profile', jobs.profile, { roles: SEEK });
route('/business/hiring', hire.overview, { roles: BIZ });
route('/business/hiring/new', hire.newJob, { roles: BIZ });
route('/business/hiring/jobs/:id', hire.applicants, { roles: BIZ });
route('/business/hiring/candidates', hire.candidates, { roles: BIZ });
route('/business/hiring/candidates/:code', hire.candidate, { roles: BIZ });
route('/officer', off.analytics, { roles: OFF });
route('/officer/applications', ops.applications, { roles: OFF });
route('/officer/grievances', ops.grievances, { roles: OFF });
route('/officer/advisories', ops.advisories, { roles: OFF });
route('/officer/events', ops.events, { roles: OFF });
route('/officer/businesses', ops.businesses, { roles: OFF });
route('/officer/officers', ops.officers, { roles: ['state_admin'] });
route('/officer/audit', ops.audit, { roles: ['state_admin'] });

// ------------------------------------------------------------------ shell
let currentPath = parseHash().path;
const lbl = (k) => t(k);
const ICON = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 11l8-7 8 7v9H4z"/><path d="M10 20v-5h4v5"/></svg>',
  explore: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 20l6-14 4 8 3-4 5 10z"/></svg>',
  verify: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 3.5M12 17v.5"/></svg>',
  jobs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2M3 13h18"/></svg>',
  plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/></svg>',
  stays: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10M10 20v-5h4v5"/></svg>',
  exp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
};
function roleNav() {
  const r = role();
  if (r === 'business') return BUSINESS_NAV;
  if (r === 'job_seeker') return SEEKER_NAV;
  if (OFF.includes(r)) return r === 'state_admin' ? [...OFFICER_NAV, ...ADMIN_NAV] : OFFICER_NAV;
  return [];
}
const cur = (on) => (on ? html`aria-current="page"` : '');
function closeSignMenu(focus) {
  const menu = $('#signmenu');
  const sb = $('#signbtn');
  if (!menu || !sb) return;
  menu.hidden = true;
  sb.setAttribute('aria-expanded', 'false');
  if (focus) sb.focus();
}
document.addEventListener('click', (e) => { if (!e.target.closest('.menuwrap')) closeSignMenu(false); });

function drawShell() {
  const u = user();
  const sec = sectionOf(currentPath);
  mount($('#mainnav'), html`<div class="pillnav">${MAIN.map((k) => html`<a href="#${SECTIONS[k].home}" ${cur(sec === k)}>${lbl(SECTIONS[k].key)}</a>`)}</div>`);
  const dash = u ? homeOf(u.role) : null;
  const listBtn = !u || u.role !== 'business' ? html`<a class="btn sm ghost hide-sm listprop" href="#/host" ${cur(currentPath.startsWith('/host'))}>${lbl('list_property')}</a>` : '';
  mount($('#topactions'), u
    ? html`${listBtn}<a class="btn sm ${currentPath.startsWith(dash) ? 'dark' : 'ghost'}" href="#${dash}" title="${u.label || u.username}">${lbl('dashboard')}</a>
           <button type="button" class="btn sm ghost hide-sm" id="signout">${lbl('signout')}</button>`
    : html`${listBtn}<div class="menuwrap"><button type="button" class="btn sm primary" id="signbtn" aria-expanded="false" aria-controls="signmenu">${lbl('signin')} <span aria-hidden="true">▾</span></button>
        <div class="popmenu" id="signmenu" hidden><a href="#/signin?need=business">${lbl('business_signin')}</a><a href="#/signin?need=seeker">${lbl('seeker_signin')}</a><a href="#/signin?need=official">${lbl('officials_signin')}</a><a href="#/register">${lbl('create_account')}</a></div></div>`);
  $('#signout')?.addEventListener('click', doSignOut);
  const sb = $('#signbtn');
  if (sb) {
    const menu = $('#signmenu');
    sb.addEventListener('click', () => { menu.hidden = !menu.hidden; sb.setAttribute('aria-expanded', String(!menu.hidden)); if (!menu.hidden) menu.querySelector('a').focus(); });
    menu.addEventListener('keydown', (e) => {
      const items = $$('a', menu);
      const i = items.indexOf(document.activeElement);
      if (e.key === 'Escape') closeSignMenu(true);
      else if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    });
    menu.addEventListener('click', () => closeSignMenu(false));
  }
  // Section tabs (public sections only).
  const sn = $('#secnav');
  if (sec && SECTIONS[sec].items.length > 1) {
    sn.hidden = false;
    sn.setAttribute('aria-label', lbl(SECTIONS[sec].key) + ' pages');
    const items = SECTIONS[sec].items;
    const best = items.map(([, p]) => p).filter((p) => currentPath === p || currentPath.startsWith(p + '/')).sort((a, b) => b.length - a.length)[0];
    mount(sn, html`<div class="wrap"><div class="pillnav sub">${items.map(([n, p]) => html`<a href="#${p}" ${cur(p === best)}>${n}</a>`)}</div></div>`);
  } else { sn.hidden = true; sn.replaceChildren(); }
  // Mobile bottom tab bar.
  mount($('#tabbar'), html`<a href="#/" ${cur(currentPath === '/')}>${raw(ICON.home)}<span>${lbl('home')}</span></a>
    <a href="#/destinations" ${cur(sec === 'destinations')}>${raw(ICON.explore)}<span>${lbl('destinations')}</span></a>
    <a href="#/stays" ${cur(sec === 'stays')}>${raw(ICON.stays)}<span>${lbl('stays')}</span></a>
    <a href="#/experiences" ${cur(sec === 'experiences')}>${raw(ICON.exp)}<span>${lbl('experiences')}</span></a>
    <button type="button" id="morebtn" aria-expanded="false" aria-controls="moresheet" class="${(!sec && currentPath !== '/') || ['help', 'jobs', 'trips', 'host'].includes(sec) ? 'on' : ''}">${raw(ICON.more)}<span>${lbl('more')}</span></button>`);
  const rn = roleNav();
  mount($('#moresheet'), html`<div class="sheet-in" role="region" aria-label="${lbl('more')}">
    <div class="sheet-h"><strong>${lbl('more')}</strong><button type="button" class="btn sm ghost" id="sheetclose">${lbl('close')}</button></div>
    <a href="#/plan">${lbl('trips')}</a><a href="#/jobs">${lbl('jobs')}</a><a href="#/host">${lbl('list_property')}</a><a href="#/festivals">${lbl('festivals')}</a><a href="#/verify">${lbl('verify_biz')}</a>
    <div class="mn-h">${lbl('help')}</div><a href="#/helplines">${lbl('helplines')}</a><a href="#/grievance">${lbl('file')}</a><a href="#/grievance/track">${lbl('track')}</a>
    <a href="#/dictionary">${lbl('dictionary')}</a><a href="#/rules">${lbl('rules')}</a><a href="#/search">${lbl('search')}</a>
    ${rn.length ? html`<div class="mn-h">${u.role === 'business' ? lbl('business') : u.role === 'job_seeker' ? lbl('job_seeker') : lbl('officials')}</div>${rn.map(([k, p]) => html`<a href="#${p}" ${cur(currentPath === p)}>${lbl(k)}</a>`)}<button type="button" class="linkrow" id="signout2">${lbl('signout')}</button>`
      : html`<div class="mn-h">${lbl('signin')}</div><a href="#/signin?need=business">${lbl('business_signin')}</a><a href="#/signin?need=seeker">${lbl('seeker_signin')}</a><a href="#/signin?need=official">${lbl('officials_signin')}</a>`}
    <div class="mn-h">${lbl('about')}</div><a href="#/about">${lbl('about')}</a><a href="#/accessibility">${lbl('accessibility')}</a><a href="#/sitemap">${lbl('sitemap')}</a></div>`);
  $('#morebtn').addEventListener('click', () => toggleSheet());
  $('#sheetclose').addEventListener('click', () => { toggleSheet(false); $('#morebtn').focus(); });
  $('#signout2')?.addEventListener('click', doSignOut);
  mount($('#footlinks'), html`<a href="#/host">${lbl('list_property')}</a><a href="#/helplines">${lbl('help_short')}</a><a href="#/about">${lbl('about')}</a><a href="#/accessibility">${lbl('accessibility')}</a><a href="#/sitemap">${lbl('sitemap')}</a><a href="#/credits">${lbl('credits')}</a><a href="#/grievance">${lbl('file')}</a><a href="#/signin?need=official">${lbl('officials_signin')}</a>`);
  document.documentElement.classList.add('booted');
  $('#skip-link').textContent = lbl('skip');
  $('#ts-label').textContent = lbl('textsize');
  $('#u-sitemap').textContent = lbl('sitemap');
  $('#u-help').textContent = lbl('help_short');
  $('#u-a11y').textContent = lbl('accessibility');
  const lt = $('#lang-toggle');
  lt.textContent = getLang() === 'hi' ? 'English' : 'हिन्दी';
  lt.lang = getLang() === 'hi' ? 'en' : 'hi';
  lt.setAttribute('aria-label', getLang() === 'hi' ? 'Switch to English' : 'हिन्दी में देखें (Switch to Hindi)');
}
async function doSignOut() { toggleSheet(false); await logout(); toast('Signed out'); go('/'); }
function toggleSheet(force) {
  const sh = $('#moresheet');
  const open = force ?? sh.hidden;
  sh.hidden = !open;
  $('#morebtn')?.setAttribute('aria-expanded', String(open));
  if (open) sh.querySelector('a')?.focus();
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#moresheet').hidden) { toggleSheet(false); $('#morebtn')?.focus(); }
});
$('#moresheet').addEventListener('click', (e) => { if (e.target.closest('a') || e.target === $('#moresheet')) toggleSheet(false); });

// Text size A- A A+ (remembered).
const SIZES = { '-1': 'fs-s', '0': '', '1': 'fs-l', '2': 'fs-xl' };
function applySize(v) {
  const root = document.documentElement;
  Object.values(SIZES).forEach((c) => c && root.classList.remove(c));
  if (SIZES[v]) root.classList.add(SIZES[v]);
  $$('.textsize button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.fs === v || (v === '2' && b.dataset.fs === '1'))));
  store('uthp.fs', v);
}
$$('.textsize button').forEach((b) => b.addEventListener('click', () => {
  const cur = store('uthp.fs') || '0';
  let v = b.dataset.fs;
  if (v === '1' && (cur === '1' || cur === '2')) v = cur === '1' ? '2' : '1';
  applySize(v);
}));
applySize(store('uthp.fs') || '0');

$('#lang-toggle').addEventListener('click', () => {
  setLang(getLang() === 'hi' ? 'en' : 'hi');
  drawShell();
  render();
});

onNavigate((path) => { currentPath = path; toggleSheet(false); drawShell(); });
window.addEventListener('session', () => drawShell());
window.addEventListener('auth-expired', () => {
  toast('Your session has ended. Please sign in again.', 'err');
});

// Officials pages share a sub-navigation rendered by the pages themselves; expose helpers.
export { isOfficial };
drawShell();
// The photo manifest is tiny; load it before the first render so cards and headers can use it synchronously.
loadPhotos().then(start);

// The skip link must not change the hash (the router owns it): move focus instead.
$('#skip-link').addEventListener('click', (e) => {
  e.preventDefault();
  const m = $('#main');
  m.focus();
  m.scrollIntoView();
});
// In-page jump links (data-jump="section-id") for long pages, without touching the hash.
document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-jump]');
  if (!a) return;
  e.preventDefault();
  const target = document.getElementById(a.dataset.jump);
  if (!target) return;
  target.setAttribute('tabindex', '-1');
  target.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  target.focus({ preventScroll: true });
});
