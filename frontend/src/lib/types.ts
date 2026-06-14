/**
 * API contract types. Mirror the response shapes of `_server.py`. If a
 * Python endpoint changes shape, change it here and TypeScript will flag
 * every caller that needs to adapt.
 */

// ── Bootstrap payload (injected via <script id="bootstrap">) ──────────
export interface Bootstrap {
  slide_id: number;
  slide_name: string;
  slide_width: number;
  slide_height: number;
  dzi_url: string;
  properties: SlideProperties;
  layer_colors: string[];
  multi_slide: boolean;
}

export interface SlideProperties {
  mpp: number | null;
  magnification: number | null;
  n_level: number;
  level_shape: [number, number][]; // [h, w] per level
  [key: string]: unknown;          // python `to_dict()` may include extras
}

// ── /slides ───────────────────────────────────────────────────────────
export interface SlideListEntry {
  id: number;
  name: string;
  width: number | null;
  height: number | null;
  active: boolean;
}

// ── POST /slides/{id}/select ──────────────────────────────────────────
export interface SelectResponse {
  id: number;
  name: string;
  slide_width: number;
  slide_height: number;
  properties: SlideProperties;
}

// ── /slides/{id}/overlays ─────────────────────────────────────────────
export interface OverlayMeta {
  name: string;
  color: string;
  n_features: number;
}

// ── /slides/{id}/overlays/{name}/columns ──────────────────────────────
export type ColumnMeta =
  | { name: string; kind: "numeric"; min: number; max: number }
  | { name: string; kind: "categorical"; categories: string[] };

// ── Layer state (client-side) ─────────────────────────────────────────
export type FetchState = "idle" | "loading" | "loaded" | "error";
export type RendererKind = "canvas" | "webgl";
export type RenderMode = "points" | "polygons";

export interface LayerStyle {
  strokeColor: string;
  strokeWidth: number;
  fillEnabled: boolean;
  fillColor: string;
  fillAlpha: number;
  pointRadius: number;
  pointAlpha: number;
}

export type ColoringScheme =
  | { kind: "categorical"; map: Record<string, string> }
  | { kind: "numeric"; min: number; max: number };

export type LayerColoring =
  | { column: null }
  | { column: string; meta: ColumnMeta; scheme: ColoringScheme };

// GeoJSON narrowing — we only handle the geometries this viewer needs
export interface GeoJsonFeature {
  type?: "Feature";
  geometry: Geometry | null;
  properties: Record<string, unknown> | null;
}
export type Geometry =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] }
  | { type: "Point"; coordinates: [number, number] }
  | { type: "MultiPoint"; coordinates: [number, number][] }
  | { type: "GeometryCollection"; geometries: Geometry[] };

export interface FgbSizeValue {
  bytes: number;
  estimated: boolean;
  sample_features: number;
}

export interface FgbInfo {
  points: FgbSizeValue;
  polygons: FgbSizeValue;
}

export interface LayerState {
  meta: OverlayMeta;
  fetchState: FetchState;
  visible: boolean;
  renderer: RendererKind;
  renderMode: RenderMode;
  featureCount: number;
  fgbInfo: FgbInfo | null;
  fgbInfoState: "idle" | "loading" | "loaded" | "error";
  columns: ColumnMeta[];
  coloring: LayerColoring;
  errorMsg: string | null;
}
