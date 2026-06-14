/**
 * Per-feature bbox precompute + viewport helpers. Ported from `viewer.html`
 * (geomBbox, buildBboxArray).
 */

import type { GeoJsonFeature, Geometry } from "./types.js";

function geomBbox(g: Geometry, out: [number, number, number, number]): void {
  switch (g.type) {
    case "Polygon":
      for (const ring of g.coordinates)
        for (const [x, y] of ring) {
          if (x < out[0]) out[0] = x;
          if (y < out[1]) out[1] = y;
          if (x > out[2]) out[2] = x;
          if (y > out[3]) out[3] = y;
        }
      break;
    case "MultiPolygon":
      for (const poly of g.coordinates)
        for (const ring of poly)
          for (const [x, y] of ring) {
            if (x < out[0]) out[0] = x;
            if (y < out[1]) out[1] = y;
            if (x > out[2]) out[2] = x;
            if (y > out[3]) out[3] = y;
          }
      break;
    case "Point": {
      const [x, y] = g.coordinates;
      if (x < out[0]) out[0] = x;
      if (y < out[1]) out[1] = y;
      if (x > out[2]) out[2] = x;
      if (y > out[3]) out[3] = y;
      break;
    }
    case "MultiPoint":
      for (const [x, y] of g.coordinates) {
        if (x < out[0]) out[0] = x;
        if (y < out[1]) out[1] = y;
        if (x > out[2]) out[2] = x;
        if (y > out[3]) out[3] = y;
      }
      break;
    case "GeometryCollection":
      for (const sub of g.geometries) geomBbox(sub, out);
      break;
  }
}

/** Float32Array of [minX, minY, maxX, maxY] per feature, flat. */
export function buildBboxArray(feats: GeoJsonFeature[]): Float32Array {
  const arr = new Float32Array(feats.length * 4);
  for (let i = 0; i < feats.length; i++) {
    const o: [number, number, number, number] = [
      Infinity,
      Infinity,
      -Infinity,
      -Infinity,
    ];
    const geom = feats[i].geometry;
    if (geom) geomBbox(geom, o);
    arr[i * 4] = o[0];
    arr[i * 4 + 1] = o[1];
    arr[i * 4 + 2] = o[2];
    arr[i * 4 + 3] = o[3];
  }
  return arr;
}

// Even-odd ray cast — for canvas hit-test.
export function pointInRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    if (
      yi > y !== yj > y &&
      x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi
    ) {
      inside = !inside;
    }
  }
  return inside;
}

export function pointInPolygon(
  x: number,
  y: number,
  rings: number[][][],
): boolean {
  if (!rings.length) return false;
  if (!pointInRing(x, y, rings[0])) return false;
  for (let i = 1; i < rings.length; i++) {
    if (pointInRing(x, y, rings[i])) return false; // hole
  }
  return true;
}
