// Small accessible SVG chart module (no libraries): line, vertical bar (grouped / stacked / per-bar colour),
// horizontal bar, heatmap, sparkline. Every chart: title, legend (>= 2 series), axes to scale, tooltip on hover and
// keyboard focus (arrow keys), an aria-live readout, and a "View as table" toggle. Redraws at the real container width.
import { html, mount, esc, table, num } from './ui.js';

// Validated categorical order (dataviz reference palette, light mode).
export const PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
// Crowd bands are status colours: always shown with their text label as well.
export const BAND_FILL = { low: '#2e8540', moderate: '#c98a00', high: '#e0631f', very_high: '#b42318' };
export const BAND_TINT = {
  low: ['#cfeccd', '#0a4d10'], moderate: ['#ffe39a', '#4d3200'], high: ['#f8b48a', '#5c1f06'], very_high: ['#c62f22', '#ffffff'],
};
export const BAND_LABEL = { low: 'Quiet', moderate: 'Normal', high: 'Busy', very_high: 'Very busy' };
export const bandOf = (v) => (v == null ? null : v < 40 ? 'low' : v < 65 ? 'moderate' : v < 85 ? 'high' : 'very_high');

let uid = 0;
const TXT = 6.4; // approx px per character at 11px

function niceTicks(min, max, count = 5) {
  if (min === max) { max = min + 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const e = step0 / mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { lo, hi, ticks };
}
const compact = (v) => {
  const a = Math.abs(v);
  if (a >= 1e7) return num(v / 1e7, 1) + ' cr';
  if (a >= 1e5) return num(v / 1e5, 1) + ' L';
  if (a >= 1e3) return num(v / 1e3, 1) + 'k';
  return num(v, 1);
};
function barPath(x, y, w, h, r = 4, down = false) {
  if (h <= 0 || w <= 0) return '';
  r = Math.min(r, w / 2, h);
  if (down) return `M${x},${y}h${w}v${h - r}q0,${r} ${-r},${r}h${-(w - 2 * r)}q${-r},0 ${-r},${-r}z`;
  return `M${x},${y + h}v${-(h - r)}q0,${-r} ${r},${-r}h${w - 2 * r}q${r},0 ${r},${r}v${h - r}z`;
}
const trunc = (s, n) => (s.length > n ? s.slice(0, Math.max(1, n - 1)) + '…' : s);

/** Shared frame: header, legend, plot, tooltip, table toggle, live readout. */
function frame({ title, sub, legend, tableHtml, note, compactMode, scroll }) {
  const id = 'ch' + ++uid;
  const fig = document.createElement('figure');
  fig.className = 'chart' + (compactMode ? ' compact' : '') + (scroll ? ' scroll' : '');
  fig.setAttribute('aria-labelledby', id + '-t');
  mount(fig, html`<div class="chart-head"><div><h3 id="${id}-t">${title}</h3>${sub ? html`<div class="sub">${sub}</div>` : ''}</div>
    <button type="button" class="btn sm ghost tbtoggle" aria-expanded="false" aria-controls="${id}-tb">View as table</button></div>
    ${legend ? html`<div class="legend">${legend}</div>` : ''}
    <div class="plot" id="${id}-p"></div><div class="tip" hidden></div>
    <div class="ctable" id="${id}-tb" hidden>${tableHtml}</div>
    ${note ? html`<p class="note">${note}</p>` : ''}<div class="sr-only" aria-live="polite"></div>`);
  const plot = fig.querySelector('.plot');
  const tb = fig.querySelector('.ctable');
  const btn = fig.querySelector('.tbtoggle');
  btn.addEventListener('click', () => {
    const show = tb.hidden;
    tb.hidden = !show;
    plot.hidden = show;
    fig.querySelector('.legend')?.toggleAttribute('hidden', show);
    btn.setAttribute('aria-expanded', String(show));
    btn.textContent = show ? 'View as chart' : 'View as table';
  });
  return { fig, plot, tip: fig.querySelector('.tip'), live: fig.querySelector('[aria-live]'), id, title };
}

/** Wire hover + keyboard to slots. nav: 'x' | 'y' | 'grid'. draw(width) -> {svg, slots, height}. */
function interactive(f, draw, nav = 'x') {
  let slots = [];
  let cur = null; // index or [r,c]
  let width = 0;
  const { plot, tip, live, fig } = f;
  function paint() {
    const w = Math.max(280, Math.floor(plot.clientWidth || fig.clientWidth - 36 || 600));
    if (w === width && plot.firstChild) return;
    width = w;
    const out = draw(w);
    slots = out.slots;
    plot.innerHTML = out.svg; // built from escaped strings only
    const svg = plot.querySelector('svg');
    svg.setAttribute('tabindex', '0');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', f.title + '. Use the arrow keys to read values, or choose View as table.');
    svg.addEventListener('pointermove', onMove);
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('keydown', onKey);
    svg.addEventListener('focus', () => { if (cur == null) cur = nav === 'grid' ? [0, 0] : 0; show(true); });
    svg.addEventListener('blur', hide);
    cur = null;
  }
  const getSlot = () => (cur == null ? null : nav === 'grid' ? slots[cur[0]]?.[cur[1]] : slots[cur]);
  function show(announce) {
    const s = getSlot();
    const svg = plot.querySelector('svg');
    const layer = svg?.querySelector('.hover');
    if (!s || !layer) return hide();
    layer.innerHTML = s.hl || '';
    tip.innerHTML = s.tip;
    // CSP forbids style attributes in markup: colour swatches through the DOM.
    tip.querySelectorAll('i.sw[data-c]').forEach((i) => { i.style.background = i.dataset.c; });
    tip.hidden = false;
    const pr = plot.getBoundingClientRect();
    const fr = fig.getBoundingClientRect();
    const sx = plot.scrollLeft || 0;
    let left = pr.left - fr.left + s.tx - sx + 14;
    const tw = tip.offsetWidth;
    if (left + tw > fr.width - 8) left = pr.left - fr.left + s.tx - sx - tw - 14;
    tip.style.left = Math.max(6, left) + 'px';
    tip.style.top = Math.max(6, pr.top - fr.top + s.ty - tip.offsetHeight / 2) + 'px';
    if (announce) live.textContent = tip.textContent;
  }
  function hide() {
    tip.hidden = true;
    const layer = plot.querySelector('.hover');
    if (layer) layer.innerHTML = '';
  }
  function onMove(e) {
    const svg = e.currentTarget;
    const r = svg.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    if (nav === 'grid') {
      cur = null;
      slots.forEach((row, ri) => row.forEach((s, ci) => { if (s && x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h) cur = [ri, ci]; }));
      if (cur) show(false); else hide();
      return;
    }
    let best = null;
    let bd = Infinity;
    slots.forEach((s, i) => { const d = Math.abs((nav === 'y' ? s.cy : s.cx) - (nav === 'y' ? y : x)); if (d < bd) { bd = d; best = i; } });
    cur = best;
    show(false);
  }
  function onKey(e) {
    const k = e.key;
    if (k === 'Escape') { hide(); return; }
    if (nav === 'grid') {
      if (!cur) cur = [0, 0];
      let [r, c] = cur;
      if (k === 'ArrowRight') c++; else if (k === 'ArrowLeft') c--; else if (k === 'ArrowDown') r++; else if (k === 'ArrowUp') r--;
      else if (k === 'Home') c = 0; else if (k === 'End') c = slots[r].length - 1; else return;
      e.preventDefault();
      r = Math.max(0, Math.min(slots.length - 1, r));
      c = Math.max(0, Math.min(slots[r].length - 1, c));
      cur = [r, c];
    } else {
      const fwd = nav === 'y' ? 'ArrowDown' : 'ArrowRight';
      const back = nav === 'y' ? 'ArrowUp' : 'ArrowLeft';
      let i = cur ?? 0;
      if (k === fwd) i++; else if (k === back) i--; else if (k === 'Home') i = 0; else if (k === 'End') i = slots.length - 1; else return;
      e.preventDefault();
      cur = Math.max(0, Math.min(slots.length - 1, i));
    }
    show(true);
    const s = getSlot();
    if (s && plot.scrollWidth > plot.clientWidth) {
      if (s.tx - plot.scrollLeft > plot.clientWidth - 40 || s.tx < plot.scrollLeft) plot.scrollLeft = s.tx - plot.clientWidth / 2;
    }
  }
  const ro = new ResizeObserver(() => { requestAnimationFrame(() => { if (fig.isConnected && !plot.hidden) paint(); }); });
  ro.observe(fig);
  requestAnimationFrame(paint);
  return f.fig;
}

function legendHtml(series, kind = 'box') {
  if (series.length < 2) return '';
  return html`${series.map((s, i) => html`<span><i class="${kind === 'line' ? 'line' : ''}" data-c="${s.color || PALETTE[i % PALETTE.length]}"></i>${s.label}</span>`)}`;
}
function colorLegend(fig) {
  fig.querySelectorAll('.legend i[data-c]').forEach((i) => { i.style.background = i.dataset.c; });
}
function seriesTable(xLabels, series, unit = '', caption = '') {
  const cols = [{ key: 'x', label: 'Period' }, ...series.map((s, i) => ({ key: 's' + i, label: s.label + (unit ? ` (${unit})` : ''), num: true }))];
  const rows = xLabels.map((x, j) => {
    const r = { x };
    series.forEach((s, i) => { r['s' + i] = s.values[j] == null ? 'no data' : num(s.values[j], 1); });
    return r;
  });
  return table(cols, rows, caption);
}
function tipHtml(title, lines) {
  return `<b>${esc(title)}</b>` + lines.map((l) => `<div>${l.c ? `<i class="sw" data-c="${esc(l.c)}"></i>` : ''}${esc(l.t)}</div>`).join('');
}

function yAxis(ticks, y, L, R, fmt) {
  return `<g class="grid">${ticks.map((t) => `<line x1="${L}" x2="${R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/>`).join('')}</g>` +
    `<g class="ylab">${ticks.map((t) => `<text x="${L - 6}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${esc(fmt(t))}</text>`).join('')}</g>`;
}
function xLabels(labels, xpos, base, innerW, fmt, minGap = 64) {
  const n = labels.length;
  const maxLabels = Math.max(2, Math.floor(innerW / minGap));
  const step = Math.max(1, Math.ceil(n / maxLabels));
  let out = '';
  for (let i = 0; i < n; i += step) out += `<text x="${xpos(i).toFixed(1)}" y="${base + 16}" text-anchor="middle">${esc(fmt(labels[i], i))}</text>`;
  return out;
}

/**
 * Line chart. opts: {title, sub, x: [labels], series: [{label, values, color}], unit, xFmt, yMin, yMax, height, note, refLines: [{y,label}]}
 */
export function lineChart(o) {
  const series = o.series.map((s, i) => ({ ...s, color: s.color || PALETTE[i % PALETTE.length] }));
  const xFmt = o.xFmt || ((v) => v);
  const unit = o.unit || '';
  const f = frame({ title: o.title, sub: o.sub, legend: legendHtml(series, 'line'), tableHtml: seriesTable(o.x.map((v, i) => xFmt(v, i, true)), series, unit, o.title), note: o.note });
  f.plot.style.minHeight = (o.height || 220) + 'px'; // reserve space before the first paint (no layout shift)
  colorLegend(f.fig);
  const all = series.flatMap((s) => s.values).filter((v) => v != null);
  const { lo, hi, ticks } = niceTicks(o.yMin ?? Math.min(0, ...all), o.yMax ?? Math.max(...all, 1));
  const fmtY = (v) => (unit === '%' ? v + '%' : compact(v));
  const draw = (W) => {
    const H = o.height || (W < 500 ? 220 : 260);
    const L = Math.max(...ticks.map((t) => fmtY(t).length)) * TXT + 14;
    const endLabels = series.length > 1 && series.length <= 4 && W > 520;
    const R = W - (endLabels ? 96 : 14);
    const T = 10, B = H - 26;
    const n = o.x.length;
    const x = (i) => L + (n === 1 ? (R - L) / 2 : (i * (R - L)) / (n - 1));
    const y = (v) => B - ((v - lo) / (hi - lo)) * (B - T);
    let svg = `<svg class="c" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
    svg += yAxis(ticks, y, L, R, fmtY);
    (o.refLines || []).forEach((r) => {
      svg += `<line x1="${L}" x2="${R}" y1="${y(r.y)}" y2="${y(r.y)}" stroke="#b42318" stroke-dasharray="4 4" stroke-width="1"/><text x="${R}" y="${y(r.y) - 4}" text-anchor="end">${esc(r.label)}</text>`;
    });
    svg += `<g class="axis"><line x1="${L}" x2="${R}" y1="${B}" y2="${B}"/></g>`;
    svg += xLabels(o.x, x, B, R - L, (v, i) => xFmt(v, i, false));
    series.forEach((s) => {
      let d = '';
      let pen = false;
      s.values.forEach((v, i) => {
        if (v == null) { pen = false; return; }
        d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1);
        pen = true;
      });
      svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      if (n <= 16) s.values.forEach((v, i) => { if (v != null) svg += `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${s.color}" stroke="#fff" stroke-width="1.5"/>`; });
      if (endLabels) {
        let li = s.values.length - 1;
        while (li > 0 && s.values[li] == null) li--;
        if (s.values[li] != null) svg += `<text x="${R + 6}" y="${y(s.values[li]) + 4}" font-weight="600">${esc(trunc(s.label, 14))}</text>`;
      }
    });
    svg += `<g class="hover"></g></svg>`;
    const slots = o.x.map((xl, i) => {
      const vals = series.map((s) => s.values[i]);
      const ys = vals.filter((v) => v != null).map(y);
      const ty = ys.length ? Math.min(...ys) : (T + B) / 2;
      return {
        cx: x(i), tx: x(i), ty,
        tip: tipHtml(xFmt(xl, i, true), series.map((s, k) => ({ c: s.color, t: `${s.label}: ${vals[k] == null ? 'no data' : num(vals[k], 1) + (unit === '%' ? '%' : unit ? ' ' + unit : '')}` }))),
        hl: `<line class="cross" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${B}"/>` + series.map((s, k) => (vals[k] == null ? '' : `<circle cx="${x(i)}" cy="${y(vals[k])}" r="5" fill="${s.color}" stroke="#fff" stroke-width="2"/>`)).join(''),
      };
    });
    return { svg, slots };
  };
  return finish(f, draw, 'x');
}

/**
 * Vertical bars. opts: {title, sub, x, series, stacked, unit, xFmt, colorFn(i, v, s) -> colour, valueLabels, height, note,
 *   refLines, yMax, tipExtra(i) -> string, legendItems: [{label,color}] (custom legend, e.g. crowd bands)}
 */
export function barChart(o) {
  const series = o.series.map((s, i) => ({ ...s, color: s.color || PALETTE[i % PALETTE.length] }));
  const xFmt = o.xFmt || ((v) => v);
  const unit = o.unit || '';
  const legend = o.legendItems ? html`${o.legendItems.map((l) => html`<span><i data-c="${l.color}"></i>${l.label}</span>`)}` : legendHtml(series);
  const f = frame({ title: o.title, sub: o.sub, legend, tableHtml: o.tableHtml || seriesTable(o.x.map((v, i) => xFmt(v, i, true)), series, unit, o.title), note: o.note, compactMode: o.compact });
  f.plot.style.minHeight = (o.height || 220) + 'px';
  colorLegend(f.fig);
  const n = o.x.length;
  let maxV = 0, minV = 0;
  for (let i = 0; i < n; i++) {
    if (o.stacked) { let p = 0, q = 0; series.forEach((s) => { const v = s.values[i] || 0; if (v >= 0) p += v; else q += v; }); maxV = Math.max(maxV, p); minV = Math.min(minV, q); }
    else series.forEach((s) => { const v = s.values[i]; if (v != null) { maxV = Math.max(maxV, v); minV = Math.min(minV, v); } });
  }
  const { lo, hi, ticks } = niceTicks(minV, o.yMax ?? Math.max(maxV, 1), o.height && o.height < 180 ? 4 : 5);
  const fmtY = (v) => (unit === '%' ? v + '%' : compact(v));
  const draw = (W) => {
    const H = o.height || (W < 500 ? 220 : 260);
    const L = Math.max(...ticks.map((t) => fmtY(t).length)) * TXT + 14;
    const R = W - 10;
    const T = o.valueLabels ? 18 : 10;
    const twoLine = !!o.xSub;
    const B = H - (twoLine ? 40 : 26);
    const bw = (R - L) / n;
    const y = (v) => B - ((v - lo) / (hi - lo)) * (B - T);
    const cx = (i) => L + bw * i + bw / 2;
    let svg = `<svg class="c" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
    svg += yAxis(ticks, y, L, R, fmtY);
    (o.refLines || []).forEach((r) => {
      svg += `<line x1="${L}" x2="${R}" y1="${y(r.y)}" y2="${y(r.y)}" stroke="#52514e" stroke-dasharray="4 4" stroke-width="1"><title>${esc(r.label)}</title></line>`;
    });
    const groupW = Math.min(bw * 0.72, o.stacked ? 44 : 22 * series.length + 10);
    for (let i = 0; i < n; i++) {
      if (o.stacked) {
        let pos = 0, neg = 0;
        const w = groupW;
        const x0 = cx(i) - w / 2;
        series.forEach((s, k) => {
          const v = s.values[i];
          if (!v) return;
          const top = k === series.length - 1 || series.slice(k + 1).every((z) => !z.values[i]);
          if (v > 0) {
            const y1 = y(pos + v), y0 = y(pos);
            svg += top ? `<path d="${barPath(x0, y1, w, y0 - y1 - (pos ? 2 : 0))}" fill="${s.color}"/>` : `<rect x="${x0}" y="${y1}" width="${w}" height="${Math.max(0, y0 - y1 - (pos ? 2 : 0))}" fill="${s.color}"/>`;
            pos += v;
          } else {
            const y0 = y(neg), y1 = y(neg + v);
            svg += `<rect x="${x0}" y="${y0}" width="${w}" height="${y1 - y0}" fill="${s.color}"/>`;
            neg += v;
          }
        });
      } else {
        const w = Math.max(2, (groupW - 2 * (series.length - 1)) / series.length);
        series.forEach((s, k) => {
          const v = s.values[i];
          if (v == null) return;
          const x0 = cx(i) - groupW / 2 + k * (w + 2);
          const col = o.colorFn ? o.colorFn(i, v, s) : s.color;
          svg += v >= 0 ? `<path d="${barPath(x0, y(v), w, y(0) - y(v))}" fill="${col}"/>` : `<path d="${barPath(x0, y(0), w, y(v) - y(0), 4, true)}" fill="${col}"/>`;
          if (o.valueLabels && series.length === 1) svg += `<text x="${x0 + w / 2}" y="${(v >= 0 ? y(v) - 4 : y(v) + 12)}" text-anchor="middle" font-weight="600" fill="#0b0b0b">${esc(o.valueFmt ? o.valueFmt(v) : num(v))}</text>`;
        });
      }
    }
    svg += `<g class="axis"><line x1="${L}" x2="${R}" y1="${y(0)}" y2="${y(0)}"/></g>`;
    const minGap = o.minLabelGap || 44;
    const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((R - L) / minGap))));
    for (let i = 0; i < n; i += step) {
      svg += `<text x="${cx(i)}" y="${B + 16}" text-anchor="middle">${esc(xFmt(o.x[i], i, false))}</text>`;
      if (twoLine) svg += `<text x="${cx(i)}" y="${B + 30}" text-anchor="middle">${esc(o.xSub(i))}</text>`;
    }
    svg += `<g class="hover"></g></svg>`;
    const slots = o.x.map((xl, i) => {
      const lines = series.map((s) => ({ c: o.colorFn ? o.colorFn(i, s.values[i], s) : s.color, t: `${s.label}: ${s.values[i] == null ? 'no data' : (o.valueFmt ? o.valueFmt(s.values[i]) : num(s.values[i], 1) + (unit === '%' ? '%' : unit ? ' ' + unit : ''))}` }));
      if (o.stacked && series.length > 1) lines.push({ t: 'Total: ' + num(series.reduce((a, s) => a + (s.values[i] || 0), 0), 1) });
      if (o.tipExtra) { const ex = o.tipExtra(i); if (ex) lines.push({ t: ex }); }
      const top = Math.min(...series.map((s) => (s.values[i] == null ? B : y(Math.max(0, s.values[i])))));
      return { cx: cx(i), tx: cx(i), ty: top, tip: tipHtml(xFmt(xl, i, true), lines), hl: `<rect class="hl" x="${L + bw * i}" y="${T}" width="${bw}" height="${B - T}"/>` };
    });
    return { svg, slots };
  };
  return finish(f, draw, 'x');
}

/** Horizontal bars. opts: {title, sub, items: [{label, value, color?, extra?}], unit, max, valueFmt, note} */
export function hbarChart(o) {
  const items = o.items;
  const unit = o.unit || '';
  const vf = o.valueFmt || ((v) => num(v, 1) + (unit === '%' ? '%' : unit ? ' ' + unit : ''));
  const tbl = table([{ key: 'label', label: o.labelHead || 'Item' }, { key: 'v', label: o.valueHead || 'Value', num: true }, ...(items.some((i) => i.extra) ? [{ key: 'extra', label: 'Note' }] : [])],
    items.map((i) => ({ label: i.label, v: i.value == null ? 'no data' : vf(i.value), extra: i.extra || '' })), o.title);
  const f = frame({ title: o.title, sub: o.sub, legend: o.legendItems ? html`${o.legendItems.map((l) => html`<span><i data-c="${l.color}"></i>${l.label}</span>`)}` : '', tableHtml: tbl, note: o.note });
  f.plot.style.minHeight = (items.length * 30 + 8) + 'px';
  colorLegend(f.fig);
  const max = o.max ?? Math.max(...items.map((i) => i.value || 0), 1);
  const draw = (W) => {
    const rowH = 30;
    const H = items.length * rowH + 8;
    const LW = Math.min(Math.max(...items.map((i) => i.label.length)) * TXT + 16, W * 0.42);
    const maxChars = Math.floor((LW - 4) / TXT);
    const valW = Math.max(...items.map((i) => vf(i.value ?? 0).length)) * TXT + 10;
    const L = LW + 4, R = W - valW;
    const x = (v) => L + (Math.max(0, v) / max) * (R - L);
    let svg = `<svg class="c" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
    items.forEach((it, i) => {
      const yy = 4 + i * rowH;
      const col = it.color || PALETTE[0];
      svg += `<text x="${LW}" y="${yy + 18}" text-anchor="end" fill="#0b0b0b">${esc(trunc(it.label, maxChars))}</text>`;
      svg += `<rect x="${L}" y="${yy + 6}" width="${R - L}" height="16" rx="4" fill="#f4f4f2"/>`;
      if (it.value != null) svg += `<rect x="${L}" y="${yy + 6}" width="${Math.max(2, x(it.value) - L)}" height="16" rx="4" fill="${col}"/>`;
      svg += `<text x="${R + 6}" y="${yy + 18}" font-weight="600" fill="#0b0b0b">${esc(it.value == null ? '—' : vf(it.value))}</text>`;
    });
    svg += `<g class="hover"></g></svg>`;
    const slots = items.map((it, i) => ({
      cy: 4 + i * rowH + 14, cx: 0, tx: Math.min(x(it.value || 0), W - 60), ty: 4 + i * rowH + 14,
      tip: tipHtml(it.label, [{ c: it.color || PALETTE[0], t: (o.valueHead || 'Value') + ': ' + (it.value == null ? 'no data' : vf(it.value)) }, ...(it.extra ? [{ t: it.extra }] : [])]),
      hl: `<rect class="hl" x="0" y="${4 + i * rowH}" width="${W}" height="${rowH}"/>`,
    }));
    return { svg, slots };
  };
  return finish(f, draw, 'y');
}

/**
 * Heatmap. opts: {title, sub, rows: [{label, values}], cols: [labels], colFmt, colKind: ['past'|'current'|'outlook'], cell(v) -> {fill, text, label}, legendItems, note}
 */
export function heatmap(o) {
  const colFmt = o.colFmt || ((c) => c);
  const cols = [{ key: 'label', label: o.rowHead || 'Row' }, ...o.cols.map((c, j) => ({ key: 'c' + j, label: colFmt(c, j, true), num: true }))];
  const rows = o.rows.map((r) => { const x = { label: r.label }; r.values.forEach((v, j) => { x['c' + j] = v == null ? '—' : String(v) + (o.cell(v).label ? ' ' + o.cell(v).label : ''); }); return x; });
  const legend = html`${(o.legendItems || []).map((l) => html`<span><i data-c="${l.color}"></i>${l.label}</span>`)}`;
  const f = frame({ title: o.title, sub: o.sub, legend, tableHtml: table(cols, rows, o.title), note: o.note, scroll: true });
  colorLegend(f.fig);
  const draw = (W) => {
    const LW = Math.min(Math.max(...o.rows.map((r) => r.label.length)) * TXT + 16, W < 500 ? 110 : 170);
    const maxChars = Math.floor((LW - 4) / TXT);
    const n = o.cols.length;
    const cw = Math.max(30, Math.floor((W - LW - 4) / n));
    const ch = 26;
    const top = o.colKind ? 40 : 24;
    const totalW = LW + cw * n + 4;
    const H = top + o.rows.length * ch + 6;
    let svg = `<svg class="c" viewBox="0 0 ${totalW} ${H}" width="${totalW}" height="${H}">`;
    if (o.colKind) {
      const firstOut = o.colKind.indexOf('outlook');
      const cur = o.colKind.indexOf('current');
      const split = cur >= 0 ? cur : firstOut;
      if (split > 0) {
        svg += `<text x="${LW + (split * cw) / 2}" y="12" text-anchor="middle" font-weight="600">Past weeks</text>`;
        svg += `<text x="${LW + split * cw + ((n - split) * cw) / 2}" y="12" text-anchor="middle" font-weight="600">This week + outlook (estimate)</text>`;
        svg += `<line x1="${LW + split * cw - 1}" x2="${LW + split * cw - 1}" y1="2" y2="${H}" stroke="#0b0b0b" stroke-width="2"/>`;
      }
    }
    const step = cw < 40 ? 2 : 1;
    o.cols.forEach((c, j) => { if (j % step === 0) svg += `<text x="${LW + j * cw + cw / 2}" y="${top - 8}" text-anchor="middle">${esc(colFmt(c, j, false))}</text>`; });
    const slots = [];
    o.rows.forEach((r, i) => {
      const yy = top + i * ch;
      svg += `<text x="${LW - 8}" y="${yy + 17}" text-anchor="end" fill="#0b0b0b">${esc(trunc(r.label, maxChars))}</text>`;
      const rs = [];
      r.values.forEach((v, j) => {
        const xx = LW + j * cw;
        const c = v == null ? { fill: '#f4f4f2', text: '#6b6a65' } : o.cell(v);
        svg += `<rect x="${xx + 1}" y="${yy + 1}" width="${cw - 2}" height="${ch - 2}" rx="4" fill="${c.fill}"/>`;
        svg += `<text x="${xx + cw / 2}" y="${yy + 17}" text-anchor="middle" fill="${c.text}" font-weight="600">${v == null ? '–' : esc(String(v))}</text>`;
        rs.push({
          x: xx, y: yy, w: cw, h: ch, tx: xx + cw / 2, ty: yy + ch / 2,
          tip: tipHtml(r.label, [{ t: colFmt(o.cols[j], j, true) + (o.colKind ? ` (${o.colKind[j]})` : '') }, { c: c.fill, t: v == null ? 'no data' : `Index ${v}` + (c.label ? ` · ${c.label}` : '') }]),
          hl: `<rect x="${xx}" y="${yy}" width="${cw}" height="${ch}" rx="5" fill="none" stroke="#0b0b0b" stroke-width="2"/>`,
        });
      });
      slots.push(rs);
    });
    svg += `<g class="hover"></g></svg>`;
    return { svg, slots };
  };
  return finish(f, draw, 'grid');
}

function finish(f, draw, nav) {
  return interactive(f, draw, nav);
}

/** Tiny sparkline (decorative; the caller states the trend in text). */
export function sparkline(values, color = PALETTE[0]) {
  const v = values.filter((x) => x != null);
  if (v.length < 2) return '';
  const W = 120, H = 34;
  const mn = Math.min(...v), mx = Math.max(...v);
  const x = (i) => (i * W) / (values.length - 1);
  const y = (val) => H - 3 - ((val - mn) / (mx - mn || 1)) * (H - 6);
  let d = '';
  let pen = false;
  values.forEach((val, i) => { if (val == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(val).toFixed(1); pen = true; });
  const lx = x(values.length - 1), ly = y(v[v.length - 1]);
  return `<svg class="spark" viewBox="-2 0 ${W + 4} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/><circle cx="${lx}" cy="${ly}" r="2.5" fill="${color}"/></svg>`;
}

/** Tiny decorative 24-bar strip (the caller states the takeaway in text). hl: Set of highlighted indexes. */
export function miniBars(values, hl = new Set(), color = PALETTE[0], hlColor = '#2e8540') {
  const n = values.length;
  if (!n) return '';
  const W = 120, H = 28, gap = 1;
  const bw = (W - gap * (n - 1)) / n;
  const mx = Math.max(...values, 1);
  let s = `<svg class="minibars" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false">`;
  values.forEach((v, i) => {
    const h = v > 0 ? Math.max(2, (v / mx) * (H - 2)) : 1;
    s += `<rect x="${(i * (bw + gap)).toFixed(2)}" y="${(H - h).toFixed(2)}" width="${bw.toFixed(2)}" height="${h.toFixed(2)}" rx="1" fill="${v > 0 ? (hl.has(i) ? hlColor : color) : '#d9d8d3'}"/>`;
  });
  return s + '</svg>';
}

export const bandLegend = () => Object.keys(BAND_FILL).map((k) => ({ label: BAND_LABEL[k], color: BAND_FILL[k] }));
export const bandTintLegend = () => Object.keys(BAND_TINT).map((k) => ({ label: BAND_LABEL[k], color: BAND_TINT[k][0] }));
export const bandCell = (v) => { const b = bandOf(v); return { fill: BAND_TINT[b][0], text: BAND_TINT[b][1], label: BAND_LABEL[b] }; };
