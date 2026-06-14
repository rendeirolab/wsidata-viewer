/**
 * deck.gl integration for high-feature-count layers (>= WEBGL_THRESHOLD).
 * Singleton Deck instance lives here; layer factories pull from store appState.
 */

import { Deck, OrthographicView } from "@deck.gl/core";
import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";

import type {
  GeoJsonFeature,
  LayerColoring,
  LayerStyle,
  OverlayMeta,
} from "./types.js";
import { hexToRgbArr, interpolateNumericColor } from "./color.js";

export interface DeckHandle {
  deck: Deck;
  setLayers(layers: Layer[]): void;
  setView(target: [number, number], zoom: number): void;
  pick(x: number, y: number, radius?: number): {
    layerId: string;
    properties: Record<string, unknown>;
  } | null;
  redraw(): void;
  dispose(): void;
}

const POINT_DETAIL_START_SCALE = 0.04;
const POINT_DETAIL_FULL_SCALE = 0.18;

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

function pointDetailProgress(screenPxPerImagePx: number): number {
  if (!Number.isFinite(screenPxPerImagePx) || screenPxPerImagePx <= 0) return 0;
  return smoothstep(
    clamp01(
      (screenPxPerImagePx - POINT_DETAIL_START_SCALE) /
        (POINT_DETAIL_FULL_SCALE - POINT_DETAIL_START_SCALE),
    ),
  );
}

export function pointVisibilityBucket(screenPxPerImagePx: number): number {
  return Math.round(pointDetailProgress(screenPxPerImagePx) * 24);
}

function effectivePointAlpha(baseAlpha: number, screenPxPerImagePx: number): number {
  const base = clamp01(baseAlpha);
  const detail = Math.min(0.98, Math.max(base * 6, base + 0.8));
  return base + (detail - base) * pointDetailProgress(screenPxPerImagePx);
}

function effectivePointRadius(baseRadius: number, screenPxPerImagePx: number): number {
  const base = Math.max(0.25, baseRadius);
  const detail = Math.min(10, Math.max(base * 2, base + 3));
  return base + (detail - base) * pointDetailProgress(screenPxPerImagePx);
}

export function initDeck(opts: {
  canvas: HTMLCanvasElement;
  slideWidth: number;
  slideHeight: number;
}): DeckHandle {
  // deck.gl's generic-typing for views vs viewState is fiddly; the runtime
  // behaviour is correct so we use `unknown`-casts at the type boundary.
  const deck = new Deck({
    canvas: opts.canvas,
    views: [new OrthographicView({ flipY: true })],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    initialViewState: {
      target: [opts.slideWidth / 2, opts.slideHeight / 2, 0],
      zoom: 0,
    } as any,
    controller: false,
    layers: [],
  }) as unknown as Deck;

  return {
    deck,
    setLayers(layers) {
      deck.setProps({ layers });
    },
    setView(target, zoom) {
      deck.setProps({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        viewState: { target: [target[0], target[1], 0], zoom } as any,
      });
    },
    pick(x, y, radius = 2) {
      const info = deck.pickObject({ x, y, radius });
      if (!info || !info.object) return null;
      const f = info.object as GeoJsonFeature;
      const layerId =
        typeof info.layer?.id === "string"
          ? info.layer.id.replace(/^wsi-/, "")
          : "";
      return { layerId, properties: f.properties ?? {} };
    },
    redraw() {
      deck.redraw(true as unknown as string);
    },
    dispose() {
      deck.finalize();
    },
  };
}

/** Build a single deck.gl layer for an overlay. */
export function buildWebglLayer(
  meta: OverlayMeta,
  feats: GeoJsonFeature[],
  style: LayerStyle,
  coloring: LayerColoring,
  screenPxPerImagePx = 0,
): Layer | null {
  const fillAlpha = style.fillEnabled ? Math.round(style.fillAlpha * 255) : 0;
  const pointAlpha = style.fillEnabled
    ? Math.round(effectivePointAlpha(style.pointAlpha, screenPxPerImagePx) * 255)
    : 0;
  const pointRadius = effectivePointRadius(style.pointRadius, screenPxPerImagePx);
  const lineAlpha = 230; // 0.9 * 255

  const getFillColor = (f: GeoJsonFeature): [number, number, number, number] => {
    if (coloring.column === null) return hexToRgbArr(style.fillColor, fillAlpha);
    const v = f.properties?.[coloring.column];
    let c: string;
    if (coloring.scheme.kind === "categorical") {
      c = coloring.scheme.map[String(v)] ?? "#888888";
    } else {
      c = v != null
        ? interpolateNumericColor(Number(v), coloring.scheme)
        : "#888888";
    }
    return hexToRgbArr(c, fillAlpha);
  };
  const getLineColor = (f: GeoJsonFeature): [number, number, number, number] => {
    if (coloring.column === null) return hexToRgbArr(style.strokeColor, lineAlpha);
    const v = f.properties?.[coloring.column];
    let c: string;
    if (coloring.scheme.kind === "categorical") {
      c = coloring.scheme.map[String(v)] ?? "#888888";
    } else {
      c = v != null
        ? interpolateNumericColor(Number(v), coloring.scheme)
        : "#888888";
    }
    return hexToRgbArr(c, lineAlpha);
  };

  // Detect geometry type from first valid feature
  const first = feats.find(f => f.geometry);
  if (!first || !first.geometry) return null;
  const isPoint =
    first.geometry.type === "Point" || first.geometry.type === "MultiPoint";

  const updateTriggers = {
    getFillColor: [
      style.fillColor,
      style.fillEnabled,
      style.fillAlpha,
      style.pointAlpha,
      pointAlpha,
      coloring,
    ],
    getLineColor: [style.strokeColor, coloring],
    getLineWidth: [style.strokeWidth],
    getRadius: [style.pointRadius, pointRadius],
  };

  if (isPoint) {
    const getPointFillColor = (f: GeoJsonFeature): [number, number, number, number] => {
      const c = getFillColor(f);
      return [c[0], c[1], c[2], pointAlpha];
    };

    return new ScatterplotLayer<GeoJsonFeature>({
      id: `wsi-${meta.name}`,
      data: feats,
      pickable: true,
      getPosition: (f) => {
        const g = f.geometry;
        if (g && g.type === "Point") return [g.coordinates[0], g.coordinates[1], 0];
        if (g && g.type === "MultiPoint") return [g.coordinates[0][0], g.coordinates[0][1], 0];
        return [0, 0, 0];
      },
      getRadius: pointRadius,
      radiusUnits: "pixels",
      getFillColor: getPointFillColor,
      stroked: false,
      filled: style.fillEnabled,
      updateTriggers,
    });
  }

  return new PolygonLayer<GeoJsonFeature>({
    id: `wsi-${meta.name}`,
    data: feats,
    pickable: true,
    getPolygon: (f) => {
      const g = f.geometry;
      if (!g) return [];
      if (g.type === "Polygon") return g.coordinates;
      if (g.type === "MultiPolygon") return g.coordinates[0]; // simplification: outer poly only
      return [];
    },
    getFillColor,
    getLineColor,
    stroked: true,
    filled: style.fillEnabled,
    lineWidthUnits: "pixels",
    getLineWidth: style.strokeWidth,
    updateTriggers,
  });
}
