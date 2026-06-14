/**
 * Color palette + viridis interpolation + categorical scheme builder.
 * Ported verbatim from `viewer.html` (CAT_PALETTE, overflowHue, hslToHex,
 * interpolateNumericColor, buildScheme).
 *
 * Note: `_server.py:_LAYER_COLORS` must match `CAT_PALETTE` here. If you
 * edit one, edit the other.
 */

import type { ColoringScheme, ColumnMeta } from "./types.js";

export const CAT_PALETTE = [
  "#4488ff",
  "#ff4444",
  "#44bb44",
  "#ff8800",
  "#aa44ff",
  "#00bbbb",
  "#ffcc00",
  "#ff44aa",
];

const GOLDEN_RATIO_CONJUGATE = 0.6180339887498949;

function hslToHex(h: number, s: number, l: number): string {
  const ss = s / 100;
  const ll = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = ss * Math.min(ll, 1 - ll);
  const f = (n: number) => {
    const c =
      ll - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return Math.round(255 * c).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/** Distinct overflow hue when categorical map exceeds the palette. */
export function overflowHue(i: number): string {
  const hue = ((i + 1) * GOLDEN_RATIO_CONJUGATE * 360) % 360;
  const sat = 65 + (i % 3) * 10;
  const lig = 55 + ((i >> 1) % 2) * 10;
  return hslToHex(hue, sat, lig);
}

export function buildScheme(colMeta: ColumnMeta): ColoringScheme {
  if (colMeta.kind === "categorical") {
    const map: Record<string, string> = {};
    colMeta.categories.forEach((cat, i) => {
      map[cat] =
        i < CAT_PALETTE.length
          ? CAT_PALETTE[i]
          : overflowHue(i - CAT_PALETTE.length);
    });
    return { kind: "categorical", map };
  }
  return { kind: "numeric", min: colMeta.min, max: colMeta.max };
}

/** 5-stop viridis approximation. */
export function interpolateNumericColor(
  value: number,
  scheme: { min: number; max: number },
): string {
  const t =
    scheme.max === scheme.min
      ? 0
      : Math.max(0, Math.min(1, (value - scheme.min) / (scheme.max - scheme.min)));
  const stops: [number, number, number][] = [
    [68, 1, 84],
    [59, 82, 139],
    [33, 145, 140],
    [94, 201, 98],
    [253, 231, 37],
  ];
  const seg = t * (stops.length - 1);
  const lo = Math.floor(seg);
  const hi = Math.min(Math.ceil(seg), stops.length - 1);
  const f = seg - lo;
  const r = Math.round(stops[lo][0] + f * (stops[hi][0] - stops[lo][0]));
  const g = Math.round(stops[lo][1] + f * (stops[hi][1] - stops[lo][1]));
  const b = Math.round(stops[lo][2] + f * (stops[hi][2] - stops[lo][2]));
  return `#${hh(r)}${hh(g)}${hh(b)}`;
}

function hh(n: number): string {
  return n.toString(16).padStart(2, "0");
}

/** "#rrggbb" → "r,g,b" for CSS rgba() */
export function hexRgb(h: string): string {
  const n = parseInt(h.replace("#", ""), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

/** "#rrggbb" + alpha (0-255) → [r,g,b,a] for deck.gl */
export function hexToRgbArr(h: string, alpha: number): [number, number, number, number] {
  const n = parseInt(h.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, alpha];
}
