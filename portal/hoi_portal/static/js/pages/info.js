// Rules & licences explainer, helplines & advisories, About, Accessibility statement, Sitemap, Photo credits.
import { html, mount, href, load, $, $$, empty, raw, crumbs, lastUpdated, announce, collapseFilters, moreList } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { t } from '../i18n.js';
import { advisoryRow } from './common.js';
import { SITEMAP } from '../nav.js';
import { photos, photosNote, img } from '../photos.js';

function ruleCard(r, m, full = false) {
  const types = (r.business_types || []).map((k) => m.business_types.find((b) => b.key === k)?.label || k);
  return html`<article class="card rulecard" aria-labelledby="r-${r.id}">
    <h2 id="r-${r.id}" class="h3">${full ? r.title : html`<a href="${href('/rules/' + r.id)}">${r.title}</a>`} <span class="pill warn">Verify</span></h2>
    <p class="small"><strong>Who needs it:</strong> ${r.who_needs_it}</p>
    ${full ? '' : raw('<details class="more"><summary>What it covers, documents, where to apply</summary>')}
    <dl class="ruledl">
      <dt>What it covers</dt><dd>${r.what_it_covers}</dd>
      <dt>Typical documents</dt><dd><ul class="bullets">${(r.typical_documents || []).map((d) => html`<li>${d}</li>`)}</ul></dd>
      <dt>Where to apply</dt><dd>${r.where_to_apply}</dd>
    </dl>
    ${full ? '' : raw('</details>')}
    ${types.length ? html`<div class="chips">${types.map((x) => html`<span class="tag">${x}</span>`)}</div>` : ''}
  </article>`;
}

export async function rules(ctx) {
  const el = ctx.el;
  const f = { business_type: '', q: '', ...ctx.query };
  mount(el, html`<div class="pagehead"><div><h1>Rules, licences & schemes</h1>
      <p>Which registrations and permits a tourism business commonly needs.</p></div></div>
    <p class="flag amber"><strong>Orientation only, not legal advice.</strong> Verify current requirements, fees and forms with the issuing authority. No section numbers or fees are given on purpose.</p>
    <form class="card tight filters" id="rlf" aria-label="Filter rules"></form>
    <div id="rl" class="section" aria-live="polite"></div>`);
  const m = await meta();
  const form = $('#rlf', el);
  mount(form, html`<div class="fld"><label class="lbl" for="rl-q">Search</label><input class="field" id="rl-q" name="q" type="search" value="${f.q}" placeholder="e.g. fire, food, permit"></div>
    <div class="fld"><label class="lbl" for="rl-t">My business is a…</label><select class="field" id="rl-t" name="business_type"><option value="">Any business type</option>
      ${m.business_types.map((b) => html`<option value="${b.key}" ${f.business_type === b.key ? raw('selected') : ''}>${b.label}</option>`)}</select></div>`);
  collapseFilters(form);
  const refresh = () => load($('#rl', el), async () => {
    setQuery(f);
    const r = await api('/rules', { query: { business_type: f.business_type || undefined, q: f.q || undefined } });
    mount($('#rl', el), r.items.length ? html`<div class="grid g2 rulegrid">${r.items.map((x) => ruleCard(x, m))}</div>${lastUpdated(null)}` : empty('No cards match', 'Clear the search or choose another business type.'));
    announce(`${r.items.length} cards`);
  }, { skel: 'cards', n: 4 });
  let tmr;
  form.addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(() => { const fd = new FormData(form); f.q = (fd.get('q') || '').toString().trim(); f.business_type = (fd.get('business_type') || '').toString(); refresh(); }, 300); });
  form.addEventListener('submit', (e) => e.preventDefault());
  await refresh();
}

export async function rule(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Rules', '#/rules'], ['…']])}<h1 class="sr-only">Rule</h1><div id="r1"></div>`);
  await load($('#r1', el), async () => {
    const [r, m] = await Promise.all([api('/rules/' + encodeURIComponent(ctx.params.id)), meta()]);
    mount(el, html`${crumbs([['Home', '#/'], ['Rules, licences & schemes', '#/rules'], [r.title]])}<h1 class="section">${r.title}</h1><div class="section">${ruleCard(r, m, true)}</div>
      <p class="section"><a href="#/rules">All rules and licences</a></p>${lastUpdated(null, 'Summary for orientation, verify with the issuing authority')}`);
  });
}

export async function helplines(ctx) {
  const el = ctx.el;
  const f = { district: '', kind: '', ...ctx.query };
  mount(el, html`<div class="pagehead"><div><h1>Helplines & alerts</h1><p>Emergency numbers, and road and weather alerts posted by district offices.</p></div></div>
    <div class="split"><section class="card" aria-labelledby="adv-h"><h2 id="adv-h">Active alerts</h2>
        <form class="filters" id="af" aria-label="Filter advisories"></form><div id="al" class="section" aria-live="polite"></div></section>
      <div class="stack"><section class="card" aria-labelledby="hl-h"><h2 id="hl-h">Helplines</h2><div id="hl"></div></section>
      <section class="card tight" aria-labelledby="do-h"><h2 id="do-h" class="h3">District tourism office</h2><div id="dofc"></div></section></div></div>
    <div id="upd"></div>`);
  load($('#hl', el), async () => {
    const h = await api('/helplines');
    mount($('#hl', el), html`<p class="flag red"><strong>Emergency: dial 112.</strong> Works from any phone across India.</p>
      <ul class="plain stack section">${h.items.map((x) => html`<li class="scard n"><div class="rowx"><span>${x.scope}</span></div><div class="big">${x.name}</div>
        ${x.number ? html`<a class="mono" href="tel:${x.number.split(' ')[0]}">${x.number}</a>` : html`<span class="muted">To be filled by the department</span>`}${x.note ? html`<div class="small">${x.note}</div>` : ''}</li>`)}</ul>
      <p class="hint section">${h.note}</p>`);
  });
  load($('#dofc', el), async () => {
    const o = await api('/district-offices');
    const box = $('#dofc', el);
    const show = (id) => {
      const x = o.items.find((i) => i.district === id) || o.items[0];
      mount(box.querySelector('#dores'), html`<p><strong>${x.office}</strong></p><p class="small muted">${x.note}</p>`);
    };
    mount(box, html`<div class="fld"><label class="lbl" for="do-d">Your district</label><select class="field" id="do-d">${o.items.map((x) => html`<option value="${x.district}" ${f.district === x.district ? raw('selected') : ''}>${x.district_name}</option>`)}</select></div><div id="dores" aria-live="polite"></div>`);
    box.querySelector('#do-d').addEventListener('change', (e) => show(e.target.value));
    show(f.district || o.items[0].district);
  }, { skel: 'list', n: 1 });
  const m = await meta();
  const form = $('#af', el);
  mount(form, html`<div class="fld"><label class="lbl" for="a-d">District</label><select class="field" id="a-d" name="district"><option value="">All districts</option>${m.districts.map((d) => html`<option value="${d.id}" ${f.district === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></div>
    <div class="fld"><label class="lbl" for="a-k">Kind</label><select class="field" id="a-k" name="kind"><option value="">All kinds</option>${m.advisory_kinds.map((k) => html`<option value="${k}" ${f.kind === k ? raw('selected') : ''}>${k[0].toUpperCase() + k.slice(1)}</option>`)}</select></div>`);
  const refresh = () => load($('#al', el), async () => {
    setQuery(f);
    const a = await api('/advisories', { query: { district: f.district || undefined, kind: f.kind || undefined } });
    const counts = Object.entries(a.by_district || {});
    mount($('#al', el), html`${a.items.length ? moreList(a.items, (x) => advisoryRow(x), 5) : empty('No active advisories', 'Nothing is posted for this filter. Conditions in the hills change quickly; check locally.')}
      ${counts.length && !f.district ? html`<p class="small muted section">By district: ${counts.map(([k, v]) => `${m.districts.find((d) => d.id === k)?.name || k} ${v}`).join(' · ')}</p>` : ''}
      ${a.items.some((x) => x.sample) ? html`<p class="hint">Alerts marked Sample are illustrative, not real road status.</p>` : ''}`);
    mount($('#upd', el), lastUpdated(a.items[0]?.posted_at, 'Advisories marked Sample are illustrative'));
  }, { skel: 'list', n: 3 });
  form.addEventListener('change', () => { const fd = new FormData(form); f.district = (fd.get('district') || '').toString(); f.kind = (fd.get('kind') || '').toString(); refresh(); });
  await refresh();
}

export function about(ctx) {
  mount(ctx.el, html`${crumbs([['Home', '#/'], ['About']])}
    <article class="card prose"><p class="eyebrow">About this concept</p><h1>About UTHP (concept)</h1>
      <p class="flag amber section"><strong>Concept prototype for the AI-Tourism Hackathon 2026, not an official Government of Uttarakhand website.</strong> Data is sample/synthetic unless marked otherwise. No government emblem, seal or logo is used.</p>
      <h2>What it is</h2>
      <p>The Uttarakhand Tourism & Hospitality Portal (UTHP) is a concept for one place where visitors, tourism businesses and district officials meet. It is part of the HOI (Hospitality Operations Intelligence) project.</p>
      <h2>Who it is for</h2>
      <ul class="bullets"><li><strong>Visitors</strong>, without signing in: search everything, plan a trip with live weather, road advisories and a crowd estimate, verify a business, file and track a grievance, read the dictionary.</li>
        <li><strong>Businesses</strong>: apply for and renew registration, see officer remarks, submit monthly occupancy, or connect HOI with an API key so occupancy is reported automatically.</li>
        <li><strong>District tourism officers</strong>: review applications, handle grievances within the SLA, post advisories and events, and see analytics for their own district only.</li>
        <li><strong>State admin</strong>: all districts, officer accounts and state analytics.</li></ul>
      <h2>Where the data comes from</h2>
      <ul class="bullets"><li><strong>Live weather</strong>: Open-Meteo forecast model data, cached for 30 minutes. Warning thresholds are assumptions, not official criteria.</li>
        <li><strong>Destinations, routes, seasonality, festivals, helplines, rules</strong>: a small curated reference set; every fact is approximate and marked “verify”.</li>
        <li><strong>Businesses, occupancy, arrivals, grievances, applications</strong>: <strong>synthetic</strong> data generated for the demo. Names are obviously synthetic (for example “Sample Homestay 014”).</li>
        <li><strong>Crowd level</strong>: an estimate from occupancy, the festival calendar, weekends and season; never a headcount.</li>
        <li><strong>Workforce figures</strong>: aggregated from HOI-connected stays and hidden when fewer than 5 businesses contribute (k-anonymity).</li></ul>
      <h2>Privacy</h2><p>Grievance contact details are visible only to officials. The tracking code is shown once. API keys are stored only as hashes.</p>
      ${lastUpdated(null)}</article>`);
}

export function accessibility(ctx) {
  mount(ctx.el, html`${crumbs([['Home', '#/'], ['Accessibility statement']])}
    <article class="card prose"><p class="eyebrow">Statement</p><h1>Accessibility statement</h1>
      <p>We aim for this concept portal to meet WCAG 2.1 level AA and follow the Guidelines for Indian Government Websites (GIGW) practices, even though it is not a government website.</p>
      <h2>What you can do here</h2>
      <ul class="bullets"><li>Use a <strong>Skip to main content</strong> link as the first item on every page.</li>
        <li>Change the <strong>text size</strong> with A-, A and A+ at the top of every page (your choice is remembered).</li>
        <li>Switch navigation labels to <strong>Hindi</strong> (हिन्दी). Hindi labels are drafts pending review by native speakers; content stays in English for now.</li>
        <li>Operate everything by <strong>keyboard</strong>: a visible focus ring, arrow keys in tabs and charts, Escape to close menus and dialogs.</li>
        <li>Read every chart as a <strong>table</strong> with the “View as table” button. Charts also announce values when you move through them with arrow keys.</li>
        <li>Status is never shown by colour alone: pills carry text and symbols (✓, !, ✕).</li>
        <li>The layout works from 360 px phones to wide screens and respects “reduce motion” settings.</li></ul>
      <h2>Known limitations</h2>
      <ul class="bullets"><li>Destination and festival content is in English only.</li><li>Map views are not provided; locations are given as text and approximate coordinates.</li>
        <li>The calendar grid shows short labels on phones; the list view gives full details.</li></ul>
      <h2>Feedback</h2><p>If something is hard to use, please tell us through the <a href="#/grievance">grievance form</a> (choose “Other”).</p>
      ${lastUpdated(null)}</article>`);
}

export function sitemap(ctx) {
  mount(ctx.el, html`${crumbs([['Home', '#/'], ['Sitemap']])}<h1>Sitemap</h1><p class="lead section">Every page of the portal. Pages under “sign in” need an account.</p>
    <div class="grid g3 section">${SITEMAP.map(([h, items]) => html`<section class="card"><h2>${h}</h2><ul class="bullets">${items.map(([n, p]) => html`<li><a href="#${p}">${n}</a></li>`)}</ul></section>`)}</div>
    ${lastUpdated(null)}`);
}

const KIND_LABEL = [['hero', 'Home page'], ['destination', 'Destinations'], ['experience', 'Experiences']];
export function credits(ctx) {
  const all = photos();
  mount(ctx.el, html`${crumbs([['Home', '#/'], ['Photo credits']])}
    <div class="pagehead"><div><h1>Photo credits</h1><p>Every photo on this portal, with its author and licence.</p></div></div>
    <p class="flag amber">${photosNote() || 'Illustrative photos from Wikimedia Commons.'} Each photo was resized and compressed; nothing else was changed. Photos licensed CC BY-SA may be reused under the same licence.</p>
    ${all.length ? KIND_LABEL.filter(([k]) => all.some((p) => p.kind === k)).map(([k, label]) => html`<section class="section" aria-labelledby="pc-${k}"><h2 id="pc-${k}">${label}</h2>
      <ul class="plain creditlist">${all.filter((p) => p.kind === k).map((p) => html`<li>${img(p)}<div><strong>${p.alt}</strong>
        <span class="small">Author: ${p.author}</span>
        <span class="small">Licence: ${p.license_url ? html`<a href="${p.license_url}" target="_blank" rel="noopener">${p.license}<span class="sr-only"> (opens in a new tab)</span></a>` : p.license}</span>
        <span class="small">Source: <a href="${p.source_url}" target="_blank" rel="noopener">${p.title}<span class="sr-only"> (Wikimedia Commons, opens in a new tab)</span></a> · ${p.modified}</span></div></li>`)}</ul></section>`)
      : html`<p class="muted section">No photos are loaded.</p>`}
    <p class="hint section">Places without a suitable freely licensed photo show a drawn illustration instead.</p>
    ${lastUpdated(null)}`);
}
