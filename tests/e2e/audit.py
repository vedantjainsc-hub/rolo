"""In-page audits: horizontal scroll, touch targets, input font size, text contrast."""
from __future__ import annotations

AUDIT_JS = r"""
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width < 2 || r.height < 2) return false;
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    if (cs.clip === 'rect(0px, 0px, 0px, 0px)' || cs.clipPath === 'inset(50%)') return false;
    return true;
  };
  const desc = (el) => {
    const t = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || '').trim().slice(0, 40);
    return `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} "${t}"`;
  };
  const out = { hscroll: null, smallTargets: [], smallInputs: [], lowContrast: [] };
  out.hscroll = { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
                  bodyScrollWidth: document.body.scrollWidth };

  // Touch targets >= 44x44 (checkbox wrapped in a >=44px label counts as the label).
  for (const el of document.querySelectorAll('a[href], button, input, textarea, select, summary, [role="button"], [role="menuitem"]')) {
    if (!vis(el)) continue;
    let r = el.getBoundingClientRect();
    if (el.matches('input[type=checkbox], input[type=radio]')) {
      const lab = el.closest('label');
      if (lab) r = lab.getBoundingClientRect();
    }
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5) {
      out.smallTargets.push(`${desc(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  // Inputs >= 16px font.
  for (const el of document.querySelectorAll('input:not([type=checkbox]):not([type=radio]), textarea, select')) {
    if (!vis(el)) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 16) out.smallInputs.push(`${desc(el)} ${fs}px`);
  }
  // Contrast (WCAG AA): 4.5 normal, 3.0 large (>=24px, or >=18.66px bold).
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const blend = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const bgOf = (el) => {
    const stack = [];
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; }
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = stack.length - 1; i >= 0; i--) bg = blend(stack[i], bg);
    return bg;
  };
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const tn = walker.currentNode;
    if (!tn.textContent.trim()) continue;
    const el = tn.parentElement;
    if (!el || seen.has(el) || !vis(el)) continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    // Effective opacity along ancestors (disabled buttons are exempt from WCAG contrast).
    if (el.closest('[disabled], [aria-disabled="true"]')) continue;
    let op = 1; for (let n = el; n; n = n.parentElement) op *= parseFloat(getComputedStyle(n).opacity);
    const fg0 = parse(cs.color); if (!fg0) continue;
    const bg = bgOf(el);
    const fg = blend({ ...fg0, a: fg0.a * op }, bg);
    const L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (bold && size >= 18.66)) ? 3 : 4.5;
    if (ratio + 0.01 < need) out.lowContrast.push(`${desc(el)} ratio ${ratio.toFixed(2)} < ${need} (fg ${cs.color}, ${size}px, opacity ${op.toFixed(2)})`);
  }
  // Placeholders (also text): check against white.
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (!vis(el) || el.value) continue;
    const c = parse(getComputedStyle(el, '::placeholder').color);
    if (!c) continue;
    const bg = bgOf(el); const fg = blend(c, bg);
    const ratio = (Math.max(lum(fg), lum(bg)) + 0.05) / (Math.min(lum(fg), lum(bg)) + 0.05);
    if (ratio < 4.5) out.lowContrast.push(`placeholder of ${desc(el)} ratio ${ratio.toFixed(2)}`);
  }
  return out;
}
"""


def audit(page) -> dict:
    return page.evaluate(AUDIT_JS)
