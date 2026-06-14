/**
 * Canvas2D overlay renderer. Pure: takes the per-frame state and draws.
 *
 * Spatial culling: skip features whose bbox doesn't intersect viewport.
 * LOD: skip features smaller than 1 screen pixel.
 */

import type { GeoJsonFeature, Geometry, LayerColoring, LayerStyle } from "./types.js";
import { hexRgb, interpolateNumericColor } from "./color.js";

export interface DrawContext {
  ctx: CanvasRenderingContext2D;
  imgPxToCanvas: (x: number, y: number) => [number, number];
  viewportBbox: [number, number, number, number] | null;
  screenPxPerImagePx: number;
}

export function drawLayer(
  dc: DrawContext,
  feats: GeoJsonFeature[],
  bbox: Float32Array | null,
  style: LayerStyle,
  coloring: LayerColoring,
): void {
  const { ctx } = dc;
  ctx.lineWidth = style.strokeWidth;

  const vp = dc.viewportBbox;
  const s = dc.screenPxPerImagePx;
  const minPxSize = 1;

  const shouldDraw = (i: number): boolean => {
    if (!vp || !bbox) return true;
    const minX = bbox[i * 4];
    const minY = bbox[i * 4 + 1];
    const maxX = bbox[i * 4 + 2];
    const maxY = bbox[i * 4 + 3];
    if (maxX < vp[0] || minX > vp[2] || maxY < vp[1] || minY > vp[3]) return false;
    if ((maxX - minX) * s < minPxSize && (maxY - minY) * s < minPxSize) return false;
    return true;
  };

  if (coloring.column === null) {
    // Fast flat-color path — set styles once, batch all features
    ctx.strokeStyle = `rgba(${hexRgb(style.strokeColor)},0.9)`;
    ctx.fillStyle = style.fillEnabled
      ? `rgba(${hexRgb(style.fillColor)},${style.fillAlpha})`
      : "transparent";
    for (let i = 0; i < feats.length; i++) {
      if (!shouldDraw(i)) continue;
      const g = feats[i].geometry;
      if (g) drawGeom(dc, g);
    }
    return;
  }

  // Per-feature color path
  for (let i = 0; i < feats.length; i++) {
    if (!shouldDraw(i)) continue;
    const f = feats[i];
    if (!f.geometry) continue;
    const val = f.properties?.[coloring.column];
    let color: string;
    if (coloring.scheme.kind === "categorical") {
      color = coloring.scheme.map[String(val)] ?? "#888888";
    } else {
      color = val != null
        ? interpolateNumericColor(Number(val), coloring.scheme)
        : "#888888";
    }
    ctx.strokeStyle = `rgba(${hexRgb(color)},0.9)`;
    ctx.fillStyle = style.fillEnabled
      ? `rgba(${hexRgb(color)},${style.fillAlpha})`
      : "transparent";
    drawGeom(dc, f.geometry);
  }
}

function drawGeom(dc: DrawContext, g: Geometry): void {
  switch (g.type) {
    case "Polygon":
      drawPoly(dc, g.coordinates);
      break;
    case "MultiPolygon":
      for (const p of g.coordinates) drawPoly(dc, p);
      break;
    case "Point":
      drawPt(dc, g.coordinates);
      break;
    case "MultiPoint":
      for (const p of g.coordinates) drawPt(dc, p);
      break;
    case "GeometryCollection":
      for (const sub of g.geometries) drawGeom(dc, sub);
      break;
  }
}

function drawPoly(dc: DrawContext, rings: number[][][]): void {
  const { ctx } = dc;
  ctx.beginPath();
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i++) {
      const [cx, cy] = dc.imgPxToCanvas(ring[i][0], ring[i][1]);
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    }
    ctx.closePath();
  }
  ctx.fill("evenodd");
  ctx.stroke();
}

function drawPt(dc: DrawContext, [x, y]: number[]): void {
  const { ctx } = dc;
  const [cx, cy] = dc.imgPxToCanvas(x, y);
  ctx.beginPath();
  ctx.arc(cx, cy, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}
