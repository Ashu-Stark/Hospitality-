// Illustrative photos from Wikimedia Commons (CC BY / CC BY-SA / CC0 / PD), served from /img/photos (CSP: img-src 'self').
// The manifest img/photos/credits.json maps an id (destination id, "exp-<experience id>", "hero") to file + attribution.
// Pages call photo(id) synchronously; app.js awaits loadPhotos() once before the first render. Missing ids -> null,
// and callers keep their illustration fallback.
import { html } from './ui.js';

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
  if (!p) return '';
  return html`<a class="${cls}" href="${p.source_url}" target="_blank" rel="noopener">${creditText(p)}<span class="sr-only"> (opens in a new tab)</span></a>`;
}

/** Page header photo (destination / experience detail) with an attribution overlay. */
export function photoHead(id) {
  const p = photo(id);
  if (!p) return '';
  return html`<figure class="photohead">${img(p, { size: 'lg', eager: true })}<figcaption>${credit(p)}</figcaption></figure>`;
}

/** Short line under a group of thumbnails (thumbnails sit inside links, so their credits live on the credits page). */
export const thumbsNote = () => html`<p class="hint photonote">Photos: Wikimedia Commons contributors (CC BY / CC BY-SA), illustrative only. <a href="#/credits">Photo credits</a></p>`;
