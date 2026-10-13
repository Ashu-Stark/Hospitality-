// Stays: registered hotels and homestays from the registry as photo cards (photo = the destination; businesses have
// no photos of their own in this prototype). Simple filters, best rated first, server paging.
import { html, mount, load, $, $$, raw, empty, announce, num, collapseFilters } from '../ui.js';
import { api, meta } from '../api.js';
import { setQuery } from '../router.js';
import { stayCard } from '../cards.js';
import { thumbsNote } from '../photos.js';
import { serverPager } from './jobs.js';

const KINDS = [['hotel,homestay', 'All stays'], ['homestay', 'Homestays'], ['hotel', 'Hotels']];

export async function list(ctx) {
  const el = ctx.el;
  const f = { type: ctx.query.type || 'hotel,homestay', district: ctx.query.district || '', destination: ctx.query.destination || '', verified: ctx.query.verified || '', page: Number(ctx.query.page) || 1 };
  const m = await meta();
  mount(el, html`<div class="pagehead"><div><h1>Stays</h1>
      <p class="lead2">Homestays and hotels with a registration number you can check. Photos show the place, not the stay.</p></div>
      <a class="btn ghost" href="#/verify">Verify a registration number</a></div>
    <div class="chiprow" role="group" aria-label="Type of stay" id="kinds"></div>
    <form class="card tight filters" id="sf" aria-label="Filter stays">
      <div class="fld"><label class="lbl" for="s-d">District</label><select class="field" id="s-d" name="district"><option value="">All districts</option>${m.districts.map((d) => html`<option value="${d.id}" ${f.district === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></div>
      <div class="fld"><label class="lbl" for="s-x">Destination</label><select class="field" id="s-x" name="destination"><option value="">All destinations</option>${m.destinations.map((d) => html`<option value="${d.id}" ${f.destination === d.id ? raw('selected') : ''}>${d.name}</option>`)}</select></div>
      <div class="fld"><label class="check"><input type="checkbox" name="verified" value="true" ${f.verified ? raw('checked') : ''}> Verified only</label></div>
    </form>
    <p class="small muted" id="scount" aria-live="polite"></p>
    <div id="sl"></div>${thumbsNote()}`);
  const form = $('#sf', el);
  collapseFilters(form);
  const kinds = () => {
    mount($('#kinds', el), html`${KINDS.map(([k, l]) => html`<button type="button" class="chipbtn" data-k="${k}" aria-pressed="${String(f.type === k)}">${l}</button>`)}`);
    $$('[data-k]', el).forEach((b) => b.addEventListener('click', () => { f.type = b.dataset.k; f.page = 1; kinds(); draw(); }));
  };
  const list = $('#sl', el);
  const draw = () => load(list, async () => {
    setQuery({ ...f, type: f.type === 'hotel,homestay' ? '' : f.type, page: f.page > 1 ? f.page : '' });
    const r = await api('/registry', { query: { type: f.type, district: f.district || undefined, destination: f.destination || undefined, verified: f.verified || undefined, status: 'active', sort: 'rating', page: f.page, page_size: 12 } });
    $('#scount', el).textContent = `${num(r.total)} stays, best rated first`;
    mount(list, r.items.length ? html`<div class="mcgrid g4c">${r.items.map(stayCard)}</div>` : empty('No stays match', 'Clear a filter or try another district.'));
    serverPager(list, r, (pg) => { f.page = pg; draw().then(() => $('#scount', el).scrollIntoView({ block: 'start' })); });
    announce($('#scount', el).textContent);
  }, { skel: 'cards', n: 8 });
  form.addEventListener('change', () => { const fd = new FormData(form); f.district = fd.get('district') || ''; f.destination = fd.get('destination') || ''; f.verified = fd.get('verified') || ''; f.page = 1; draw(); });
  form.addEventListener('submit', (e) => e.preventDefault());
  kinds();
  await draw();
}
