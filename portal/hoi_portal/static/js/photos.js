// Illustrative photos from Wikimedia Commons (CC BY / CC BY-SA / CC0 / PD), served from /img/photos (CSP: img-src 'self').
// The manifest img/photos/credits.json maps an id (destination id, "exp-<experience id>", "hero") to file + attribution.
// Pages call photo(id) synchronously; app.js awaits loadPhotos() once before the first render. Missing ids -> null,
// and callers keep their illustration fallback.
import { html, bandPill, landscape } from './ui.js';

const BASE = 'img/photos/';
let byId = new Map();
let all = [];
let note = '';
let ready = null;

export function loadPhotos() {
  if (!ready) {
    ready = fetch(BASE + 'credits.json', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : { images: [] }))
      .then((d) => {
        all = Array.isArray(d.images) ? d.images : [];
        note = d.note || '';
        byId = new Map(all.map((p) => [p.id, p]));
      })
      .catch(() => { /* photos are optional; illustrations remain */ });
  }
  return ready;
}
export const photo = (id) => byId.get(id) || null;
export const photos = () => all;
export const photosNote = () => note;

/** First manifest entry among ids (e.g. ['fest-harela', 'nainital']), else null. */
export const firstPhoto = (ids) => (ids || []).map((i) => byId.get(i)).find(Boolean) || null;

/** Card cover: the first available photo among ids, else the generated landscape (decorative, alt=""). */
export function cover(ids, { seed, eager = false } = {}) {
  const p = firstPhoto(Array.isArray(ids) ? ids : [ids]);
  return p ? img(p, { cls: 'mc-img', alt: '', eager }) : html`<span class="mc-art">${landscape(seed || (Array.isArray(ids) ? ids[0] : ids))}</span>`;
}

/** Plain-text attribution: "Photo: <author>, <licence> (Wikimedia Commons)". */
export const creditText = (p) => `Photo: ${p.author}, ${p.license} (Wikimedia Commons)`;

/** <img> for a manifest entry. size: 'sm' (480 px) or 'lg'. Lazy unless eager; width/height reserve space. */
export function img(p, { size = 'sm', cls = '', eager = false, alt } = {}) {
  if (!p) return '';
  const sm = size === 'sm' && p.file_sm;
  const w = sm ? 480 : p.width;
  const h = Math.round((p.height / p.width) * w);
  return html`<img class="${cls}" src="${BASE + (sm ? p.file_sm : p.file)}" alt="${alt ?? p.alt}" width="${w}" height="${h}" ${eager ? '' : html`loading="lazy"`} decoding="async">`;
}

/** Linked attribution line (opens the Commons file page in a new tab). */
export function credit(p, cls = 'pcredit') {
  // Per-photo captions are not shown on pages; every credit is listed on #/credits (linked in the footer).
  if (!p || cls !== 'force') return '';
  return html`<a class="${cls}" href="${p.source_url}" target="_blank" rel="noopener">${creditText(p)}<span class="sr-only"> (opens in a new tab)</span></a>`;
}

/** Page header photo (destination / experience detail) with an attribution overlay. */
export function photoHead(id) {
  const p = photo(id);
  if (!p) return '';
  return html`<figure class="photohead">${img(p, { size: 'lg', eager: true })}</figure>`;
}

/** Short line under a group of thumbnails (thumbnails sit inside links, so their credits live on the credits page). */
export const thumbsNote = () => '';

/**
 * Full-bleed destination card: the photo (or the generated landscape when there is none) fills the card,
 * a bottom scrim keeps white text >= 4.5:1, and the crowd band pill always sits top-right on its own row.
 * crowd: { index, band } or null.
 */
export function coverCard({ id, url, name, sub, extra = '', crowd, cls = '' }) {
  const p = photo(id);
  return html`<a class="pcard ${cls} ${p ? '' : 'nophoto'}" href="${url}">
    <span class="pc-bg" aria-hidden="true">${p ? img(p, { cls: 'pc-img', alt: '' }) : landscape(id)}</span>
    <span class="pc-txt"><b class="pc-name">${name}</b><span class="pc-sub">${sub}</span>${extra}
      ${crowd ? html`<span class="pc-score"><span class="sr-only">Crowd index </span>${crowd.index}<small>/100</small></span>` : ''}</span>
    <span class="pc-top">${crowd ? bandPill(crowd.band, null, '') : html`<span class="pill neutral">Crowd: no estimate</span>`}</span></a>`;
}
