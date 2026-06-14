/**
 * Typed wrappers around the FastAPI endpoints. Every URL goes through one
 * builder here so a server URL change is caught at every call site by tsc.
 *
 * All fetches accept an AbortSignal so callers can cancel in-flight requests
 * on slide switch (race-prevention pattern from `selectSlide`).
 */

import type {
  ColumnMeta,
  FgbInfo,
  OverlayMeta,
  SelectResponse,
  SlideListEntry,
  SlideProperties,
} from "./types.js";

// ── URL builders (single source of truth for URL shape) ───────────────
export const url = {
  slides:           ()            => `/slides`,
  slideSelect:      (id: number)  => `/slides/${id}/select`,
  slideThumb:       (id: number)  => `/slides/${id}/thumbnail.jpeg`,
  slideDzi:         (id: number)  => `/slides/${id}/slide.dzi`,
  slideProperties:  (id: number)  => `/slides/${id}/properties`,
  overlays:         (id: number)  => `/slides/${id}/overlays`,
  overlayColumns:   (id: number, name: string) =>
    `/slides/${id}/overlays/${encodeURIComponent(name)}/columns`,
  overlayFgbInfo:   (id: number, name: string) =>
    `/slides/${id}/overlays/${encodeURIComponent(name)}/fgb-info`,
  overlayFgb:       (id: number, name: string) =>
    `/slides/${id}/overlays/${encodeURIComponent(name)}.fgb`,
  overlayPointsFgb: (id: number, name: string) =>
    `/slides/${id}/overlays/${encodeURIComponent(name)}.points.fgb`,
  overlayGeoJson:   (id: number, name: string) =>
    `/slides/${id}/overlays/${encodeURIComponent(name)}.geojson`,
};

// ── Typed fetch helpers ───────────────────────────────────────────────
async function getJSON<T>(u: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(u, { signal });
  if (!r.ok) throw new Error(`${u}: ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  listSlides: (signal?: AbortSignal) =>
    getJSON<SlideListEntry[]>(url.slides(), signal),

  selectSlide: async (id: number, signal?: AbortSignal): Promise<SelectResponse> => {
    const r = await fetch(url.slideSelect(id), { method: "POST", signal });
    if (!r.ok) throw new Error(`select failed: ${r.status}`);
    return (await r.json()) as SelectResponse;
  },

  slideProperties: (id: number, signal?: AbortSignal) =>
    getJSON<SlideProperties>(url.slideProperties(id), signal),

  listOverlays: (id: number, signal?: AbortSignal) =>
    getJSON<OverlayMeta[]>(url.overlays(id), signal),

  overlayColumns: (id: number, name: string, signal?: AbortSignal) =>
    getJSON<ColumnMeta[]>(url.overlayColumns(id, name), signal),

  overlayFgbInfo: (id: number, name: string, signal?: AbortSignal) =>
    getJSON<FgbInfo>(url.overlayFgbInfo(id, name), signal),

  overlayGeoJsonFeatures: async (id: number, name: string, signal?: AbortSignal) => {
    const r = await fetch(url.overlayGeoJson(id, name), { signal });
    if (!r.ok) throw new Error(`${name}.geojson: ${r.status}`);
    const gj = (await r.json()) as { features?: unknown[] };
    return (gj.features ?? []) as import("./types.js").GeoJsonFeature[];
  },

  overlayFgbFeatures: async (id: number, name: string, signal?: AbortSignal) => {
    const r = await fetch(url.overlayFgb(id, name), { signal });
    if (!r.ok) throw new Error(`${name}.fgb: ${r.status}`);
    const buf = await r.arrayBuffer();
    // flatgeobuf import is lazy — only loaded when a layer crosses WEBGL_THRESHOLD
    const fgb = await import("flatgeobuf/lib/mjs/geojson.js");
    const result = fgb.deserialize(new Uint8Array(buf)) as { features?: unknown[] };
    return (result.features ?? []) as import("./types.js").GeoJsonFeature[];
  },

  overlayPointFgbFeatures: async (id: number, name: string, signal?: AbortSignal) => {
    const r = await fetch(url.overlayPointsFgb(id, name), { signal });
    if (!r.ok) throw new Error(`${name}.points.fgb: ${r.status}`);
    const buf = await r.arrayBuffer();
    const fgb = await import("flatgeobuf/lib/mjs/geojson.js");
    const result = fgb.deserialize(new Uint8Array(buf)) as { features?: unknown[] };
    return (result.features ?? []) as import("./types.js").GeoJsonFeature[];
  },
};

/**
 * Treats an AbortError as a non-failure — handy wrapper for catch blocks.
 * Returns true if the error should be considered "swallowable".
 */
export function isAbort(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    (err as { name?: string }).name === "AbortError"
  );
}
