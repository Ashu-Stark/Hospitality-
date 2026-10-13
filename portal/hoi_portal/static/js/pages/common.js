// Helpers shared by page modules.
import { html, href, statusPill, verifiedPill, roadPill, fmtDateTime, fmtDate, relTime, samplePill, num, titleCase } from '../ui.js';
import { t } from '../i18n.js';
import { role, user } from '../api.js';
import { SEEKER_NAV } from '../nav.js';

export const ICONS = {
  plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 20l6-14 4 8 3-4 5 10z"/></svg>',
  verify: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
  festival: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  dict: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h11"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2"/></svg>',
  jobs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2M3 13h18"/></svg>',
  complaint: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/><path d="M12 8v4M12 14.5v.5"/></svg>',
};

/** Link target for a unified-search result. */
export function resultLink(type, it) {
  switch (type) {
    case 'destinations': return href('/destinations/' + it.id);
    case 'businesses': return href('/directory/' + it.id);
    case 'events': return href('/festivals', { view: 'list', q: it.name });
    case 'dictionary': return href('/dictionary/' + it.id);
    case 'rules': return href('/rules/' + it.id);
    case 'advisories': return it.destination_id ? href('/destinations/' + it.destination_id + '/roads') : href('/helplines');
    default: return '#/';
  }
}
export function resultTitle(type, it) {
  return it.name || it.term || it.title || it.id;
}
export function resultSub(type, it) {
  switch (type) {
    case 'destinations': return `${it.district_name || ''} · ${it.division || ''}`;
    case 'businesses': return `${it.type_label} · ${it.destination_name || it.district_name} · ${it.reg_no}`;
    case 'events': return `${it.window || ''} · ${(it.destination_names || []).join(', ') || (it.district_names || []).join(', ')}`;
    case 'dictionary': return `${it.category}${it.hindi ? ' · ' + it.hindi : ''}`;
    case 'rules': return it.who_needs_it || '';
    case 'advisories': return `${it.district_name || ''}${it.segment ? ' · ' + it.segment : ''}`;
    default: return '';
  }
}
export const TYPE_LABEL = {
  destinations: 'Destinations', businesses: 'Businesses', events: 'Festivals & events', dictionary: 'Travel words', rules: 'Rules & licences', advisories: 'Road alerts',
};

export function bizRow(b) {
  return html`<div class="item"><div class="main"><a class="t" href="${href('/directory/' + b.id)}">${b.name}</a>
    <div class="sub">${b.type_label} · ${b.destination_name || '—'}, ${b.district_name} · <span class="mono">${b.reg_no}</span>${b.rating != null ? ` · ★ ${b.rating}` : ''}</div></div>
    <div class="side">${statusPill(b.status)}${verifiedPill(b.verified)}${b.hoi_connected ? html`<span class="pill neutral noicon" title="Reports occupancy automatically from HOI">HOI</span>` : ''}</div></div>`;
}
const stripSample = (t) => String(t || '').replace(/^SAMPLE:\s*/i, '').replace(/^./, (c) => c.toUpperCase());
/** One-line advisory: status pill + title + place (detail on click). */
export function advisoryLine(a) {
  const to = a.destination_id ? href('/destinations/' + a.destination_id + '/roads') : href('/helplines', { district: a.district });
  return html`<li>${a.kind === 'road' || a.status ? roadPill(a.status) : html`<span class="pill info">${titleCase(a.kind)}</span>`}<a href="${to}">${stripSample(a.title)}</a><span class="muted small">${a.destination_name || a.district_name}</span>${a.sample ? samplePill() : ''}</li>`;
}
/** Advisory row with details. Sample advisories do not repeat their disclaimer text (one footnote per section instead). */
export function advisoryRow(a, { manage = false } = {}) {
  return html`<div class="item" data-id="${a.id}"><div class="main"><strong>${stripSample(a.title)}</strong>
    <div class="sub">${a.kind === 'road' ? 'Road' : a.kind === 'weather' ? 'Weather' : 'General'} · ${a.destination_name || a.district_name}${a.segment ? ' · ' + a.segment : ''} · posted ${relTime(a.posted_at)}${a.expires_at ? html` · ${a.active === false ? 'expired' : 'until'} ${fmtDate(a.expires_at, { noYear: true })}` : ''}</div>
    ${a.reason && (!a.sample || manage) ? html`<div class="sub">${a.reason}</div>` : ''}</div>
    <div class="side">${a.kind === 'road' || a.status ? roadPill(a.status) : ''}${a.sample ? samplePill() : ''}${a.active === false ? html`<span class="pill neutral">Expired</span>` : ''}${manage ? html`<button type="button" class="btn sm ghost" data-edit="${a.id}">Edit</button>${a.active !== false ? html`<button type="button" class="btn sm danger" data-expire="${a.id}">Withdraw</button>` : ''}` : ''}</div></div>`;
}

/** Sub-navigation for signed-in areas. */
export function roleSubnav(current) {
  const r = role();
  // Officials and businesses: the shell draws their sections as a left sidebar (phones: a "Section" drawer).
  if (r === 'business' || r === 'state_admin' || r === 'district_officer') return '';
  const items = SEEKER_NAV;
  const u = user();
  return html`<div class="whoami"><span class="pill info noicon">${u?.role_label || r}</span>${u?.district_name ? html`<span class="pill neutral noicon">District: ${u.district_name}</span>` : ''}<span>Signed in as <strong>${u?.username}</strong></span></div>
  <nav class="subnav section" aria-label="${r === 'business' ? 'Business' : r === 'job_seeker' ? 'Job seeker' : 'Officials'} sections"><div class="pillnav">${items.map(([k, p]) => html`<a href="#${p}" ${p === current ? html`aria-current="page"` : ''}>${t(k)}</a>`)}</div></nav>`;
}
export const kv = (pairs) => html`<dl class="facts">${pairs.filter((p) => p[1] !== undefined).map(([k, v]) => html`<dt>${k}</dt><dd>${v ?? '—'}</dd>`)}</dl>`;
export const fmtNum = num;
