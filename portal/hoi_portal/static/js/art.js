// Experience illustrations: our own simple line drawings in one style (64x64, 2.4 px rounded strokes, one accent fill).
// Decorative only (aria-hidden); the tile text names the experience.
const wrap = (body) => `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const EXP_ART = {
  temple: wrap('<path d="M32 8v6"/><path d="M26 22l6-8 6 8z" fill="var(--acc)"/><path d="M22 30h20l-4-8H26z"/><path d="M18 54V34h28v20"/><path d="M14 54h36"/><path d="M28 54V44a4 4 0 018 0v10"/><path d="M18 34h28"/>'),
  peak: wrap('<path d="M6 52l16-26 8 12 8-16 20 30z"/><path d="M38 22l5 8-4-1-3 4-3-5" fill="var(--acc)"/><path d="M22 26l3 5-3-1-2 3"/><path d="M20 52l6-6 4 3 6-7"/>'),
  leaf: wrap('<path d="M14 50C14 26 30 12 52 12c0 22-14 38-38 38z" fill="var(--acc)"/><path d="M14 50L40 24"/><path d="M24 40h10M30 34v-8"/>'),
  lotus: wrap('<path d="M32 46c-6-6-6-16 0-24 6 8 6 18 0 24z" fill="var(--acc)"/><path d="M32 46c-10 0-18-6-20-14 8-1 15 3 20 14z"/><path d="M32 46c10 0 18-6 20-14-8-1-15 3-20 14z"/><path d="M12 52h40"/>'),
  lake: wrap('<path d="M6 40l12-16 8 9 10-15 22 22"/><path d="M8 46c6 3 10-3 16 0s10 3 16 0 10-3 16 0" stroke="var(--acc)"/><path d="M12 53c6 3 10-3 16 0s10 3 16 0"/><circle cx="48" cy="14" r="4"/>'),
  drum: wrap('<ellipse cx="32" cy="22" rx="16" ry="6" fill="var(--acc)"/><path d="M16 22v18c0 3.3 7.2 6 16 6s16-2.7 16-6V22"/><path d="M16 30l8 14M48 30l-8 14M24 27l8 19 8-19"/><path d="M10 10l10 8M54 10l-10 8"/>'),
};
// Accent + tile tint per experience (decorative; text stays ink colour for contrast).
export const EXP_TONE = {
  spiritual: { acc: '#f3b38a', bg: '#fff1e8', fg: '#a8400f' },
  adventure: { acc: '#bcd4ff', bg: '#e8f1ff', fg: '#1557c0' },
  wildlife: { acc: '#a7e3ad', bg: '#ecfbea', fg: '#0a6b12' },
  wellness: { acc: '#d8cff8', bg: '#f3f0ff', fg: '#4a3aa7' },
  leisure: { acc: '#9fd8e6', bg: '#e6f6fa', fg: '#0b5f73' },
  culture: { acc: '#f2cd6f', bg: '#fff6df', fg: '#7a5000' },
};
/** Apply tone colours to tiles rendered with data-tone (CSP: styles set through the DOM, not attributes). */
export function paintTones(root) {
  root.querySelectorAll('[data-tone]').forEach((el) => {
    const t = EXP_TONE[el.dataset.tone];
    if (!t) return;
    el.style.setProperty('--acc', t.acc);
    el.style.setProperty('--tbg', t.bg);
    el.style.setProperty('--tfg', t.fg);
  });
}
