// The DOM probe the 2026-09-25 UI/UX study ran on every screen (paste into the console, or evaluate through
// Playwright's page.evaluate). It measures what the findings cite: interactive targets under 24x24 CSS px,
// text nodes by computed font size (and any under the 11 px floor), elements whose content overflows
// horizontally under an overflow rule, every visible .aug-content-header's control count and whether its
// rightmost control passes the viewport, inline-styled element count, and the live token contrast ratios.
(() => {
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const ctrls = [...document.querySelectorAll('button, a[href], [role=tab], input, select, textarea, [role=button]')].filter(vis);
  const small = ctrls.filter(el => { const r = el.getBoundingClientRect(); return r.height < 24 || r.width < 24; });
  const all = [...document.querySelectorAll('body *')].filter(vis);
  const sizes = {}; let under11 = 0;
  for (const el of all) {
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    sizes[fs] = (sizes[fs] || 0) + 1; if (fs < 11) under11++;
  }
  const overflow = all.filter(el => el.scrollWidth > el.clientWidth + 2 &&
      ['auto', 'scroll', 'hidden'].includes(getComputedStyle(el).overflowX))
    .map(el => ({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 40), sw: el.scrollWidth, cw: el.clientWidth }))
    .slice(0, 8);
  const headers = [...document.querySelectorAll('.aug-content-header')].filter(vis).map(h => {
    const r = h.getBoundingClientRect();
    const kids = [...h.querySelectorAll('button,[role=tab],select')].filter(vis);
    const right = Math.max(...kids.map(k => k.getBoundingClientRect().right));
    return { h: Math.round(r.height), w: Math.round(r.width), ctrls: kids.length, rightmostCtrl: Math.round(right),
      clipped: right > r.right + 1, offscreen: kids.filter(k => k.getBoundingClientRect().right > innerWidth).length };
  });
  const lum = hex => { const c = hex.replace('#', ''); const [r, g, b] = [0, 2, 4].map(i => parseInt(c.slice(i, i + 2), 16) / 255)
    .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const cr = (a, b) => { const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x); return +((l1 + 0.05) / (l2 + 0.05)).toFixed(2); };
  const s = getComputedStyle(document.documentElement); const g = n => s.getPropertyValue(n).trim();
  const bg0 = g('--bg-0');
  const tokens = { theme: document.documentElement.getAttribute('data-theme'), bg0,
    t1: cr(g('--t1'), bg0), t2: cr(g('--t2'), bg0), t3: cr(g('--t3'), bg0), t4: cr(g('--t4'), bg0),
    b0: cr(g('--b0'), bg0), b1: cr(g('--b1'), bg0) };
  return { url: location.search, vw: innerWidth, docW: document.documentElement.scrollWidth,
    controls: ctrls.length, smallTargets: small.length,
    smallSample: small.slice(0, 6).map(el => ({ t: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30),
      h: Math.round(el.getBoundingClientRect().height), w: Math.round(el.getBoundingClientRect().width) })),
    fontSizes: sizes, textUnder11px: under11, hOverflow: overflow, headers,
    inlineStyled: document.querySelectorAll('[style]').length, docH: document.documentElement.scrollHeight, tokens };
})();
