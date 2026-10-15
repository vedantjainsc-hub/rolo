// Generates the Rolo PWA icons (navy square with a white index card) as PNGs
// using only Node built-ins. Run: npm run icons
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");
mkdirSync(OUT, { recursive: true });

const NAVY = [0x0b, 0x1f, 0x3a];
const WHITE = [0xff, 0xff, 0xff];
const LINE = [0xd9, 0xe0, 0xe8];
const GOLD = [0xb8, 0x92, 0x5a];

function inRoundRect(x, y, rx, ry, w, h, r) {
  if (x < rx || y < ry || x > rx + w || y > ry + h) return false;
  const cx = Math.min(Math.max(x, rx + r), rx + w - r);
  const cy = Math.min(Math.max(y, ry + r), ry + h - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

// Shapes in unit coordinates (0..1). `scale` shrinks art for maskable safe zone.
function colorAt(u, v, { rounded, scale }) {
  // Outer background
  if (rounded && !inRoundRect(u, v, 0, 0, 1, 1, 0.18)) return null;
  const s = (t) => 0.5 + (t - 0.5) * scale;
  const card = { x: s(0.2), y: s(0.3), w: 0.6 * scale, h: 0.42 * scale, r: 0.05 * scale };
  if (inRoundRect(u, v, card.x, card.y, card.w, card.h, card.r)) {
    const dot = { cx: s(0.3), cy: s(0.4), r: 0.035 * scale };
    if ((u - dot.cx) ** 2 + (v - dot.cy) ** 2 <= dot.r ** 2) return GOLD;
    const bar = (y, w) => inRoundRect(u, v, s(0.36), s(y), w * scale, 0.04 * scale, 0.02 * scale);
    if (bar(0.38, 0.36)) return NAVY;
    if (bar(0.5, 0.4)) return LINE;
    if (bar(0.6, 0.28)) return LINE;
    return WHITE;
  }
  // Tab on top of the card (rolodex style)
  if (inRoundRect(u, v, s(0.3), s(0.24), 0.14 * scale, 0.1 * scale, 0.025 * scale)) return WHITE;
  return NAVY;
}

function render(size, opts) {
  const SS = 4;
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const c = colorAt((x + (sx + 0.5) / SS) / size, (y + (sy + 0.5) / SS) / size, opts);
          if (c) { r += c[0]; g += c[1]; b += c[2]; a += 255; }
        }
      }
      const n = SS * SS;
      const covered = a / 255 || 1;
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = Math.round(r / covered);
      raw[o + 1] = Math.round(g / covered);
      raw[o + 2] = Math.round(b / covered);
      raw[o + 3] = Math.round(a / n);
    }
  }
  return png(size, size, raw);
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(w, h, raw) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const files = [
  ["icon-192.png", 192, { rounded: true, scale: 1 }],
  ["icon-512.png", 512, { rounded: true, scale: 1 }],
  ["icon-maskable-512.png", 512, { rounded: false, scale: 0.78 }],
  ["apple-touch-icon.png", 180, { rounded: false, scale: 0.9 }],
];
for (const [name, size, opts] of files) {
  writeFileSync(join(OUT, name), render(size, opts));
  console.log("wrote", name);
}
