// One card builder per content type, all on the shared image-led mediaCard (ui.js). Photos come from the Wikimedia
// Commons manifest (photos.js) with a fallback chain, e.g. a festival without its own photo uses its destination's.
import { html, href, mediaCard, bandPill, impactPill, monthChips, monthName, num, fmtDate, icon, verifiedPill } from './ui.js';
import { cover, photo } from './photos.js';

const stripSample = (t) => String(t || '').replace(/^SAMPLE:\s*/i, '');
const rating = (r) => (r != null ? html`<span class="rating">${icon('star')}${r}</span>` : '');
export const rupees = (lo, hi, unit = '') => (lo == null && hi == null ? '' : `₹${num(lo ?? hi)}${hi != null && lo != null && hi !== lo ? '–' + num(hi) : ''}${unit}`);
const hours = (h) => (h >= 6 ? 'Full day' : `${num(h, 1)} h`);

/** Destination: photo, name, district, best months, today's crowd pill, temperature if cached, one-line why go. */
export function destCard(x, { eager = false } = {}) {
  const w = x.weather_now;
  return mediaCard({
    href: href('/destinations/' + x.id),
    media: cover([x.id], { eager }),
    badge: x.crowd_today ? bandPill(x.crowd_today.band) : '',
    kicker: `${x.district_name} · ${x.division}`,
    kickerIcon: 'pin',
    title: x.name,
    line: x.why_go || '',
    facts: [
      ['calendar', x.best_months?.length ? 'Best in ' + monthChips(x.best_months, 2).join(', ') : 'Good all year'],
      ['temp', w?.available && w.temperature_c != null ? `${Math.round(w.temperature_c)}°C now` : ''],
      ['people', x.local_experiences ? `${x.local_experiences} thing${x.local_experiences > 1 ? 's' : ''} to do` : ''],
    ],
  });
}

/** Registered stay (hotel or homestay) from the registry; photo = its destination. */
export function stayCard(b) {
  return mediaCard({
    href: href('/directory/' + b.id),
    media: cover([b.destination_id], { seed: b.id }),
    badge: b.verified ? html`<span class="pill info">Verified</span>` : '',
    kicker: `${b.type_label} · ${b.destination_name || b.district_name}`,
    kickerIcon: b.type,
    title: b.name,
    facts: [['stay', `${b.capacity} ${b.capacity_unit}`], ['lang', (b.languages || []).slice(0, 3).join(', ')]],
    foot: html`${rating(b.rating)}<span class="mono small">${b.reg_no}</span>`,
  });
}

/** Any registered business (directory): type icon, verified, rating; no photo (the type icon leads). */
export function bizCard(b) {
  return mediaCard({
    href: href('/directory/' + b.id),
    kicker: b.type_label,
    kickerIcon: b.type,
    title: b.name,
    line: b.destination_name && b.destination_name !== b.district_name ? `${b.destination_name}, ${b.district_name}` : b.district_name,
    foot: html`<span>${rating(b.rating)}</span><span class="row">${b.status !== 'active' ? html`<span class="pill bad">${b.status}</span>` : ''}${verifiedPill(b.verified)}</span>`,
    cls: 'bizcard',
  });
}

/** Community-hosted local experience. */
// Each experience type has one photo of its own; a small set of fitting alternates per type keeps several cards of the
// same type (e.g. two home meals at one place) from showing the same picture. The pick is deterministic (grid order +
// a hash of the experience id), and a shared `used` set lets a grid skip photos it already shows.
const LX_PHOTOS = {
  home_meal: ['lx-home_meal', 'lx-farm_stay', 'exp-culture', 'fest-harela'],
  farm_stay: ['lx-farm_stay', 'fest-harela', 'exp-culture'],
  village_walk: ['lx-village_walk', 'exp-culture', 'lx-farm_stay'],
  nature_walk: ['lx-nature_walk', 'dhanaulti', 'chopta'],
  birding: ['lx-birding', 'chopta', 'lx-nature_walk'],
  folk_music: ['lx-folk_music', 'fest-nanda-devi-fair', 'fest-uttarayani-fair'],
  heritage_walk: ['lx-heritage_walk', 'fest-uttarayani-fair', 'bageshwar'],
  artisan_workshop: ['lx-artisan_workshop', 'exp-culture'],
};
export const LX_SHORT = { home_meal: 'Home meal', nature_walk: 'Nature walk', heritage_walk: 'Heritage walk', farm_stay: 'Farm day', folk_music: 'Folk music', artisan_workshop: 'Craft workshop' };
const hashStr = (s) => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
export function lxPhotoIds(e, used) {
  const set = (LX_PHOTOS[e.type] || ['lx-' + e.type]).filter((id) => photo(id));
  if (!set.length) return [e.destination_id];
  // The type's own photo first; when a grid already shows it, an alternate chosen by the experience id.
  const rest = set.slice(1);
  const start = rest.length ? hashStr(e.id) % rest.length : 0;
  const order = [set[0], ...rest.slice(start), ...rest.slice(0, start)];
  const pick = order.find((id) => !used?.has(id)) || order[0];
  used?.add(pick);
  return [pick, e.destination_id];
}
const hostName = (e) => (e.host?.name || '').replace(/,\s*[^,]*$/, (m) => (e.destination_name && m.includes(e.destination_name) ? '' : m));
/** localCard(e) or items.map(localCards()) to vary photos across one grid. */
export function localCard(e, _i, _a, used = null) {
  const host = hostName(e);
  return mediaCard({
    href: href('/experiences/local/' + e.id),
    media: cover(lxPhotoIds(e, used), { seed: e.id }),
    badge: html`<span class="pill noicon typechip">${icon(e.type)}<span>${LX_SHORT[e.type] || e.type_label}</span></span>`,
    kicker: e.destination_name === e.district_name ? e.destination_name : `${e.destination_name}, ${e.district_name}`,
    kickerIcon: 'pin',
    title: e.title,
    line: host ? html`Hosted by <strong>${host}</strong>` : '',
    facts: [['clock', hours(e.duration_hours)], ['people', `${e.group_min}-${e.group_max} people`], ['rupee', rupees(e.price_min, e.price_max, ' per person')]],
    foot: html`<span>Local ${e.host?.type_label?.toLowerCase() || 'host'}</span>${e.host?.verified ? html`<span class="pill info">Verified host</span>` : ''}`,
  });
}
/** Mapper for one grid: items.map(localCards()) never repeats a photo while the type sets allow it. */
export function localCards() {
  const used = new Set();
  return (e) => localCard(e, 0, null, used);
}

/** Festival or event: photo, month window, crowd impact. */
export function festCard(e, { hz = false } = {}) {
  const dests = e.destination_ids || [];
  return mediaCard({
    href: href('/festivals', { view: 'list', q: stripSample(e.name) }),
    media: cover(['fest-' + e.id, ...dests], { seed: e.id }),
    badge: impactPill(e.crowd_impact),
    kicker: e.start_date ? fmtDate(e.start_date, { noYear: true }) + (e.end_date && e.end_date !== e.start_date ? ' – ' + fmtDate(e.end_date, { noYear: true }) : '') : e.window || (e.months || []).map((m) => monthName(m, true)).join('–'),
    kickerIcon: 'calendar',
    title: stripSample(e.name),
    line: e.description || '',
    facts: [['pin', (e.destination_names || []).join(', ') || (e.district_names?.length > 3 ? 'Across the state' : (e.district_names || []).join(', '))]],
    foot: html`<span>Dates change each year</span>`,
    cls: hz ? 'hz' : '',
  });
}

/** Sample trip (itinerary): photo of the first stop, days, stops count. */
export function tripCard(i) {
  const first = i.stops?.[0]?.destination_id;
  return mediaCard({
    href: href('/plan/itineraries/' + i.id),
    media: cover(['itin-' + i.id, first], { seed: i.id }),
    badge: html`<span class="pill neutral noicon">${i.suggested_days_total} days</span>`,
    kicker: i.theme_name,
    kickerIcon: 'route',
    title: i.name,
    line: i.stops.map((s) => s.name).join(' → '),
    facts: [['pin', `${i.stops.length} stops`], ['calendar', `${i.suggested_days_total} days`]],
  });
}

/** Job post: skill icon, district, pay, season; HOI staffing requests are labelled. */
export function jobCard(j, { matchBadge = '' } = {}) {
  const sk = j.skills?.[0];
  const cat = sk?.category || 'operations';
  const season = j.season_from && j.season_to ? `${fmtDate(j.season_from, { noYear: true })} – ${fmtDate(j.season_to, { noYear: true })}` : j.job_type_label;
  return mediaCard({
    href: href('/jobs/' + j.id),
    kicker: (j.skills || []).map((s) => s.label).slice(0, 2).join(' · '),
    kickerIcon: cat === 'adventure' ? 'adventure_operator' : cat,
    title: j.title,
    line: `${j.business_name}`,
    badge: j.via_hoi ? html`<span class="pill hoipill noicon">Urgent: hotel short of staff</span>` : '',
    facts: [['pin', j.destination_name && j.destination_name !== j.district_name ? `${j.destination_name}, ${j.district_name}` : j.district_name], ['rupee', rupees(j.pay_min, j.pay_max, ' / month') || 'Pay on request'], ['calendar', season], ['people', `${j.openings} opening${j.openings > 1 ? 's' : ''}`]],
    foot: html`<span>Closes ${fmtDate(j.closes_on, { noYear: true })}</span>${matchBadge}${j.applied ? html`<span class="pill ok">Applied</span>` : ''}`,
    cls: 'jobc',
  });
}

/** Staffing agency block offer (pooled workers, counts only). */
export function offerCard(o) {
  const a = o.agency || {};
  return mediaCard({
    href: href('/directory/' + a.id),
    kicker: o.skill?.label || 'Pooled staff',
    kickerIcon: 'staffing_agency',
    title: `${o.workers} workers ready`,
    line: `${fmtDate(o.available_from, { noYear: true })} – ${fmtDate(o.available_to)} · ${o.destination_name || o.district_name}`,
    facts: [['staffing_agency', a.name], ['pin', `Serves ${(a.districts_served || []).map((d) => d.name).slice(0, 3).join(', ')}`]],
    foot: html`<span>${rating(a.rating)}</span><span class="row">${a.verified ? html`<span class="pill info">Verified</span>` : ''}</span>`,
    cls: 'offerc',
  });
}
