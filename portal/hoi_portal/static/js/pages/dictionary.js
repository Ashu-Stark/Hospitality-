// Tourism & hospitality dictionary: A-Z letter index, category filter, search, term detail with related terms.
import { html, mount, href, load, $, $$, empty, raw, crumbs, lastUpdated, announce, collapseFilters, pager } from '../ui.js';
import { api } from '../api.js';
import { setQuery } from '../router.js';

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

export async function list(ctx) {
  const el = ctx.el;
  const f = { letter: '', category: '', q: '', ...ctx.query };
  mount(el, html`<div class="pagehead"><div><h1>Tourism & hospitality dictionary</h1>
      <p>Plain-language meanings, in English and Hindi.</p></div></div>
    <div id="dl"></div>`);
  await load($('#dl', el), async () => {
    const r = await api('/dictionary');
    const box = $('#dl', el);
    mount(box, html`<form class="card tight filters" id="dfm" aria-label="Filter terms">
        <div class="fld"><label class="lbl" for="d-q">Search terms</label><input class="field" id="d-q" name="q" type="search" value="${f.q}" placeholder="e.g. RevPAR, homestay"></div>
        <div class="fld"><label class="lbl" for="d-cat">Category</label><select class="field" id="d-cat" name="category"><option value="">All categories</option>
          ${r.categories.map((c) => html`<option ${f.category === c ? raw('selected') : ''}>${c}</option>`)}</select></div>
        <div class="fld"><button type="reset" class="btn ghost">Clear</button></div></form>
      <nav class="letters" id="dlet" aria-label="Jump to letter"></nav>
      <p class="small muted" id="dcnt" aria-live="polite"></p><div id="dterms"></div>`);
    const form = $('#dfm', box);
    collapseFilters(form);
    const draw = () => {
      const q = f.q.toLowerCase();
      const base = r.items.filter((x) => (!f.category || x.category === f.category) && (!q || [x.term, x.hindi, x.definition].join(' ').toLowerCase().includes(q)));
      const avail = new Set(base.map((x) => x.letter));
      const items = base.filter((x) => !f.letter || x.letter === f.letter);
      mount($('#dlet', box), html`<a href="#/dictionary" data-l="" aria-current="${String(!f.letter)}">All</a>${LETTERS.map((L) => (avail.has(L) ? html`<a href="#/dictionary" data-l="${L}" aria-current="${String(f.letter === L)}" aria-label="Terms starting with ${L}">${L}</a>` : html`<span aria-hidden="true">${L}</span>`))}`);
      $$('[data-l]', box).forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); f.letter = a.dataset.l; setQuery(f); draw(); }));
      $('#dcnt', box).textContent = `${items.length} of ${r.total} terms`;
      if (!items.length) { mount($('#dterms', box), empty('No terms match', 'Try a shorter word or another category.')); return; }
      pager($('#dterms', box), items, (slice) => html`<div class="cards">${slice.map((x) => html`<a class="card tight dcard-term" href="${href('/dictionary/' + x.id)}"><strong>${x.term}</strong>${x.hindi ? html` <span lang="hi" class="muted">${x.hindi}</span>` : ''}
          <span class="tag">${x.category}</span><span class="small clamp2">${x.definition}</span></a>`)}</div>`, 12);
    };
    form.addEventListener('input', () => { const fd = new FormData(form); f.q = (fd.get('q') || '').toString().trim(); f.category = (fd.get('category') || '').toString(); setQuery(f); draw(); });
    form.addEventListener('reset', () => setTimeout(() => { f.q = ''; f.category = ''; f.letter = ''; setQuery(f); draw(); }));
    form.addEventListener('submit', (e) => e.preventDefault());
    draw();
  }, { skel: 'cards', n: 6 });
}

export async function term(ctx) {
  const el = ctx.el;
  mount(el, html`${crumbs([['Home', '#/'], ['Dictionary', '#/dictionary'], ['…']])}<h1 class="sr-only">Term</h1><div id="dt"></div>`);
  await load($('#dt', el), async () => {
    const x = await api('/dictionary/' + encodeURIComponent(ctx.params.id));
    mount(el, html`${crumbs([['Home', '#/'], ['Dictionary', '#/dictionary'], [x.term]])}
      <article class="card">
        <p class="eyebrow">${x.category}</p>
        <h1>${x.term}</h1>
        ${x.hindi ? html`<p class="lead section"><span class="muted small">Hindi:</span> <span lang="hi">${x.hindi}</span></p>` : ''}
        <h2 class="section">Meaning</h2><p class="lead">${x.definition}</p>
        ${x.example ? html`<h2 class="section">Example</h2><blockquote class="flag blue">${x.example}</blockquote>` : ''}
        ${x.related_items?.length ? html`<h2 class="section">Related terms</h2><div class="chips section">${x.related_items.map((r) => html`<a class="chipbtn" href="${href('/dictionary/' + r.id)}">${r.term}</a>`)}</div>` : ''}
        <p class="section"><a href="${href('/dictionary', { letter: x.letter })}">More terms under ${x.letter}</a></p>
      </article>
      ${lastUpdated(null, 'Plain-language explanation for orientation; not a legal definition')}`);
  });
}
