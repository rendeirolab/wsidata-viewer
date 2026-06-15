/**
 * Orchestration layer: stitches OSD, Canvas2D, deck.gl, and the global store
 * together. Components import the singleton from here; this file owns the
 * imperative side effects.
 *
 * State flow:
 *   - selectSlide(id):   abort prev fetches → reset overlay state → update store
 *                        → setTileSource → fetch /select → loadLayers
 *   - toggleLayer(name): fetch overlays/columns → buildBbox → push into store
 *                        → rebuildRenderers (canvas2d + deck.gl)
 *
 * Race prevention: every overlay-scoped fetch is keyed by the slideId that
 * was current at the moment the user clicked. If the user has since switched
 * slides we discard the response silently.
 */

import { api, isAbort, url } from "./api.js";
import { buildBboxArray } from "./bbox.js";
import { drawLayer, type DrawContext } from "./canvas2d.js";
import {
  buildWebglLayer,
  initDeck,
  pointVisibilityBucket,
  type DeckHandle,
} from "./deck.js";
import { initOSD, type OSDHandle } from "./osd.js";
import {
  defaultStyle,
  selectController,
  appState,
  WEBGL_THRESHOLD,
  clearOverlayState,
} from "./stores.svelte.js";
import type {
  GeoJsonFeature,
  LayerColoring,
  RenderMode,
  LayerState,
  OverlayMeta,
} from "./types.js";

interface ViewerSingleton {
  osd: OSDHandle | null;
  deck: DeckHandle | null;
  canvas: HTMLCanvasElement | null;
  deckCanvas: HTMLCanvasElement | null;
  ctx: CanvasRenderingContext2D | null;
  container: HTMLElement | null;
  canvasW: number;
  canvasH: number;
  ready: boolean;
}

const v: ViewerSingleton = {
  osd: null,
  deck: null,
  canvas: null,
  deckCanvas: null,
  ctx: null,
  container: null,
  canvasW: 0,
  canvasH: 0,
  ready: false,
};

type LayerPayload = {
  features: GeoJsonFeature[];
  bbox: Float32Array | null;
  renderMode: RenderMode;
};

// Keep large feature/coordinate arrays out of Svelte's deep reactive state.
// The pre-refactor viewer stored these as plain JS objects; doing the same
// here avoids proxying hundreds of thousands of polygon coordinate arrays.
const layerPayloads = new Map<string, LayerPayload>();
const layerRequestIds = new Map<string, number>();
let layerRequestSeq = 0;
let deckPointVisibilityBucket = -1;

function defaultRenderMode(meta: OverlayMeta): RenderMode {
  return (meta.n_features ?? 0) >= WEBGL_THRESHOLD ? "points" : "polygons";
}

function clearLayerPayloads(): void {
  layerPayloads.clear();
  layerRequestIds.clear();
  deckPointVisibilityBucket = -1;
}

// ── Public mount API used by App.svelte ───────────────────────────────
export function mount(opts: {
  osdEl: HTMLElement;
  overlayCanvas: HTMLCanvasElement;
  deckCanvas: HTMLCanvasElement;
  container: HTMLElement;
}): void {
  v.canvas = opts.overlayCanvas;
  v.deckCanvas = opts.deckCanvas;
  v.ctx = opts.overlayCanvas.getContext("2d");
  v.container = opts.container;

  v.osd = initOSD({
    element: opts.osdEl,
    tileSource: appState.bootstrap.dzi_url,
  });
  v.deck = initDeck({
    canvas: opts.deckCanvas,
    slideWidth: appState.bootstrap.slide_width || 1,
    slideHeight: appState.bootstrap.slide_height || 1,
  });

  const updateViewportState = (zoom?: number) => {
    if (!v.osd?.viewer.viewport) return;
    const z = zoom ?? v.osd.viewer.viewport.getZoom();
    appState.zoom = z;
    appState.statusText = `zoom ${z.toFixed(2)}×`;

    const c = v.osd.viewer.viewport.getCenter();
    const ip = v.osd.viewer.viewport.viewportToImageCoordinates(c);
    appState.centerImg = { x: ip.x, y: ip.y };
  };

  // Wire OSD events
  v.osd.viewer.addHandler("open", () => {
    resizeCanvas();
    updateViewportState();
    drawAll();
  });
  v.osd.viewer.addHandler("update-viewport", () => {
    updateViewportState();
    drawAll();
  });
  v.osd.viewer.addHandler("zoom", (e: { zoom: number }) => {
    updateViewportState(e.zoom);
  });
  v.osd.viewer.addHandler("pan", () => updateViewportState());
  // OSD's CanvasClickEvent type has `quick` and `originalEvent`. The .d.ts
  // does not narrow them precisely, so the handler is typed `(ev: any)`.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  v.osd.viewer.addHandler("canvas-click", (ev: any) => {
    if (!ev?.quick) return;
    const oe = ev.originalEvent as MouseEvent;
    handlePickClick(oe.clientX, oe.clientY);
  });

  new ResizeObserver(resizeCanvas).observe(opts.container);

  v.ready = true;
}

export function dispose(): void {
  v.osd?.dispose();
  v.deck?.dispose();
  v.osd = null;
  v.deck = null;
  clearLayerPayloads();
  v.ready = false;
}

// ── Canvas sizing ─────────────────────────────────────────────────────
export function resizeCanvas(): void {
  if (!v.container || !v.canvas || !v.ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = v.container.getBoundingClientRect();
  const pw = Math.round(rect.width * dpr);
  const ph = Math.round(rect.height * dpr);
  if (pw === v.canvasW && ph === v.canvasH) return;
  v.canvasW = pw;
  v.canvasH = ph;
  v.canvas.width = pw;
  v.canvas.height = ph;
  v.canvas.style.width = rect.width + "px";
  v.canvas.style.height = rect.height + "px";
  v.ctx.scale(dpr, dpr);
  // deck.gl manages its own backing store; just resize the CSS box.
  if (v.deckCanvas) {
    v.deckCanvas.style.width = rect.width + "px";
    v.deckCanvas.style.height = rect.height + "px";
  }
  v.deck?.redraw();
  drawAll();
}

// ── Per-frame draw ────────────────────────────────────────────────────
export function drawAll(): void {
  if (!v.osd || !v.ctx || !v.osd.viewer.viewport) return;
  const dpr = window.devicePixelRatio || 1;
  v.ctx.clearRect(0, 0, v.canvasW / dpr, v.canvasH / dpr);

  const dc: DrawContext = {
    ctx: v.ctx,
    imgPxToCanvas: v.osd.imgPxToElement.bind(v.osd),
    viewportBbox: v.osd.viewportImageBbox(),
    screenPxPerImagePx: v.osd.screenPxPerImagePx(),
  };

  let hasWebgl = false;
  for (const name of appState.layerOrder) {
    const L = appState.layers[name];
    if (!L) continue;
    if (L.renderer === "webgl") {
      hasWebgl = true;
      continue;
    }
    if (!L.visible || L.fetchState !== "loaded") continue;
    const payload = layerPayloads.get(name);
    if (!payload) continue;
    const style = appState.layerStyles[name] ?? defaultStyle(L.meta.color);
    drawLayer(dc, payload.features, payload.bbox, style, L.coloring);
  }
  if (hasWebgl) syncDeckViewport();
}

function currentScreenPxPerImagePx(): number {
  return v.osd?.screenPxPerImagePx() ?? 0;
}

function hasLoadedPointLayer(): boolean {
  for (const name of appState.layerOrder) {
    const L = appState.layers[name];
    if (!L || L.renderer !== "webgl" || !L.visible || L.fetchState !== "loaded") continue;
    const payload = layerPayloads.get(name);
    if (payload?.renderMode === "points") return true;
  }
  return false;
}

function syncDeckViewport(refreshPointVisibility = true): void {
  if (!v.deck || !v.osd?.viewer.viewport) return;
  const c = v.osd.viewer.viewport.getCenter();
  const ip = v.osd.viewer.viewport.viewportToImageCoordinates(c);
  const s = v.osd.screenPxPerImagePx();
  if (s <= 0) return;
  v.deck.setView([ip.x, ip.y], Math.log2(s));

  if (!refreshPointVisibility || !hasLoadedPointLayer()) return;
  const bucket = pointVisibilityBucket(s);
  if (bucket !== deckPointVisibilityBucket) {
    deckPointVisibilityBucket = bucket;
    rebuildDeckLayers(false);
  }
}

// ── Rebuild deck.gl layers (called whenever a layer's data/style changes) ─
export function rebuildDeckLayers(syncView = true): void {
  if (!v.deck) return;
  // Lazy import to avoid bundling deck/layers when not needed initially?
  // Already a hard dep — fine.
  const layers = [];
  const screenPxPerImagePx = currentScreenPxPerImagePx();
  deckPointVisibilityBucket = pointVisibilityBucket(screenPxPerImagePx);
  for (const name of appState.layerOrder) {
    const L = appState.layers[name];
    if (!L) continue;
    if (L.renderer !== "webgl") continue;
    if (!L.visible || L.fetchState !== "loaded") continue;
    const payload = layerPayloads.get(name);
    if (!payload) continue;
    const style = appState.layerStyles[name] ?? defaultStyle(L.meta.color);
    const layer = buildWebglLayer(
      L.meta,
      payload.features,
      style,
      L.coloring,
      screenPxPerImagePx,
    );
    if (layer) layers.push(layer);
  }
  v.deck.setLayers(layers);
  if (syncView) syncDeckViewport(false);
}

/** Rebuild deck + redraw canvas — call after any style/visibility/data change. */
export function rebuildAll(): void {
  rebuildDeckLayers();
  drawAll();
}

// ── Slide switching ───────────────────────────────────────────────────
let switchLock = false;

export async function selectSlide(id: number): Promise<void> {
  if (switchLock) return;
  switchLock = true;

  const signal = selectController.reset();
  appState.currentSlideId = id;
  clearOverlayState();
  appState.layerListState = "loading";
  appState.layerListError = null;
  clearLayerPayloads();
  v.deck?.setLayers([]);
  drawAll();

  // Update sidebar highlight optimistically
  for (const s of appState.slides) {
    s.active = s.id === id;
  }

  // DZI reload — OSD uses its own pipeline; tile URLs are per-slide.
  v.osd?.setTileSource(url.slideDzi(id) + `?_=${Date.now()}`);

  try {
    const info = await api.selectSlide(id, signal);
    if (id !== appState.currentSlideId) return; // stale

    appState.slideName = info.name;
    appState.slideWidth = info.slide_width;
    appState.slideHeight = info.slide_height;
    appState.currentMpp = info.properties.mpp;
    appState.bootstrap = {
      ...appState.bootstrap,
      slide_name: info.name,
      slide_width: info.slide_width,
      slide_height: info.slide_height,
      properties: info.properties,
    };

    await loadLayers(id, signal);
  } catch (err) {
    if (isAbort(err)) return;
    if (id === appState.currentSlideId) {
      appState.layerListState = "error";
      appState.layerListError = err instanceof Error ? err.message : String(err);
    }
    console.error("Slide switch failed:", err);
  } finally {
    switchLock = false;
  }
}

// ── Layer loading ─────────────────────────────────────────────────────
export async function loadLayers(slideId?: number, signal?: AbortSignal): Promise<void> {
  const id = slideId ?? appState.currentSlideId;
  const sig = signal ?? selectController.signal;
  appState.layerListState = "loading";
  appState.layerListError = null;
  try {
    const overlays = await api.listOverlays(id, sig);
    if (id !== appState.currentSlideId) return;
    clearLayerPayloads();
    v.deck?.setLayers([]);
    appState.layerOrder = overlays.map((m) => m.name);
    const next: Record<string, LayerState> = {};
    for (const m of overlays) {
      next[m.name] = {
        meta: m,
        fetchState: "idle",
        visible: false,
        renderer: "canvas",
        renderMode: defaultRenderMode(m),
        featureCount: 0,
        fgbInfo: null,
        fgbInfoState: "idle",
        columns: [],
        coloring: { column: null },
        errorMsg: null,
      };
      if (!appState.layerStyles[m.name]) {
        appState.layerStyles[m.name] = defaultStyle(m.color);
      }
    }
    appState.layers = next;
    appState.layerListState = "loaded";
  } catch (err) {
    if (isAbort(err)) return;
    if (id !== appState.currentSlideId) return;
    appState.layers = {};
    appState.layerOrder = [];
    appState.layerListState = "error";
    appState.layerListError = err instanceof Error ? err.message : String(err);
    console.error("Failed to load overlays:", err);
  }
}

export async function fetchLayer(name: string): Promise<void> {
  const L = appState.layers[name];
  if (!L) return;
  const requestId = ++layerRequestSeq;
  layerRequestIds.set(name, requestId);
  layerPayloads.delete(name);
  L.fetchState = "loading";
  L.visible = false;
  L.featureCount = 0;

  const slideId = appState.currentSlideId;
  const sig = selectController.signal;
  const useWebgl = (L.meta.n_features ?? 0) >= WEBGL_THRESHOLD;
  L.renderer = useWebgl ? "webgl" : "canvas";
  const renderMode = useWebgl ? L.renderMode : "polygons";
  L.renderMode = renderMode;

  try {
    const featsP = useWebgl
      ? renderMode === "points"
        ? api.overlayPointFgbFeatures(slideId, name, sig)
        : api.overlayFgbFeatures(slideId, name, sig)
      : api.overlayGeoJsonFeatures(slideId, name, sig);
    const columnsP = api
      .overlayColumns(slideId, name, sig)
      .catch(() => [] as LayerState["columns"]);

    const [feats, columns] = await Promise.all([featsP, columnsP]);
    if (slideId !== appState.currentSlideId) return;
    if (layerRequestIds.get(name) !== requestId) return;
    const current = appState.layers[name];
    if (!current) return;

    layerPayloads.set(name, {
      features: feats,
      bbox: current.renderer === "canvas" ? buildBboxArray(feats) : null,
      renderMode,
    });
    current.featureCount = feats.length;
    current.columns = columns;
    current.coloring = { column: null };
    current.fetchState = "loaded";
    current.visible = true;
    current.errorMsg = null;
    rebuildAll();
  } catch (err) {
    if (isAbort(err)) return;
    if (slideId !== appState.currentSlideId) return;
    if (layerRequestIds.get(name) !== requestId) return;
    const current = appState.layers[name];
    if (!current) return;
    current.fetchState = "error";
    current.visible = false;
    current.featureCount = 0;
    current.errorMsg = err instanceof Error ? err.message : String(err);
    console.error(`Layer "${name}" fetch failed:`, err);
  }
}

export function setLayerVisible(name: string, visible: boolean): void {
  const L = appState.layers[name];
  if (!L) return;
  L.visible = visible;
  rebuildAll();
}

export function setColoring(name: string, coloring: LayerColoring): void {
  const L = appState.layers[name];
  if (!L) return;
  L.coloring = coloring;
  rebuildAll();
}

export async function ensureLayerFgbInfo(name: string): Promise<void> {
  const L = appState.layers[name];
  if (!L || L.fgbInfo || L.fgbInfoState === "loading") return;
  if ((L.meta.n_features ?? 0) < WEBGL_THRESHOLD) return;

  L.fgbInfoState = "loading";
  const slideId = appState.currentSlideId;
  const sig = selectController.signal;
  try {
    const info = await api.overlayFgbInfo(slideId, name, sig);
    if (slideId !== appState.currentSlideId) return;
    const current = appState.layers[name];
    if (!current) return;
    current.fgbInfo = info;
    current.fgbInfoState = "loaded";
  } catch (err) {
    if (isAbort(err)) return;
    if (slideId !== appState.currentSlideId) return;
    const current = appState.layers[name];
    if (!current) return;
    current.fgbInfoState = "error";
  }
}

export function setLayerRenderMode(name: string, mode: RenderMode): void {
  const L = appState.layers[name];
  if (!L || L.renderMode === mode) return;

  L.renderMode = mode;
  layerRequestIds.set(name, ++layerRequestSeq);
  layerPayloads.delete(name);

  const shouldReload = L.visible || L.fetchState === "loading";
  L.fetchState = "idle";
  L.visible = false;
  L.featureCount = 0;
  L.errorMsg = null;
  rebuildAll();

  if (shouldReload) {
    void fetchLayer(name);
  }
}

// ── Hit-test / tooltip ────────────────────────────────────────────────
// The tooltip itself is a Svelte component; this just emits the result.
type TooltipPayload = { layerName: string; properties: Record<string, unknown>; x: number; y: number } | null;
const tooltipListeners = new Set<(p: TooltipPayload) => void>();
export function onTooltip(cb: (p: TooltipPayload) => void): () => void {
  tooltipListeners.add(cb);
  return () => tooltipListeners.delete(cb);
}
function emitTooltip(p: TooltipPayload): void {
  for (const cb of tooltipListeners) cb(p);
}

function handlePickClick(clientX: number, clientY: number): void {
  if (!v.osd || !v.container) return;
  const rect = v.container.getBoundingClientRect();
  const px = clientX - rect.left;
  const py = clientY - rect.top;

  // 1) deck.gl pick first (covers WebGL layers)
  if (v.deck) {
    const hit = v.deck.pick(px, py, 2);
    if (hit) {
      emitTooltip({ layerName: hit.layerId, properties: hit.properties, x: clientX, y: clientY });
      return;
    }
  }

  // 2) Canvas2D hit test
  const elPt = new (window as unknown as { OpenSeadragon: typeof import("openseadragon") }).OpenSeadragon.Point(px, py);
  const vp = v.osd.viewer.viewport.viewerElementToViewportCoordinates(elPt);
  const ip = v.osd.viewer.viewport.viewportToImageCoordinates(vp);
  const hit = hitTestCanvas2D(ip.x, ip.y);
  if (hit) emitTooltip({ ...hit, x: clientX, y: clientY });
  else emitTooltip(null);
}

import { pointInPolygon } from "./bbox.js";

function hitTestCanvas2D(
  imgX: number,
  imgY: number,
): { layerName: string; properties: Record<string, unknown> } | null {
  // Topmost first
  for (let li = appState.layerOrder.length - 1; li >= 0; li--) {
    const name = appState.layerOrder[li];
    const L = appState.layers[name];
    if (!L || L.renderer === "webgl") continue;
    if (!L.visible || L.fetchState !== "loaded") continue;
    const payload = layerPayloads.get(name);
    if (!payload) continue;
    const bbox = payload.bbox;
    if (!bbox) continue;
    for (let i = 0; i < payload.features.length; i++) {
      const minX = bbox[i * 4];
      const minY = bbox[i * 4 + 1];
      const maxX = bbox[i * 4 + 2];
      const maxY = bbox[i * 4 + 3];
      if (imgX < minX || imgX > maxX || imgY < minY || imgY > maxY) continue;
      const g = payload.features[i].geometry;
      if (!g) continue;
      let hit = false;
      if (g.type === "Polygon") hit = pointInPolygon(imgX, imgY, g.coordinates);
      else if (g.type === "MultiPolygon") {
        for (const poly of g.coordinates) {
          if (pointInPolygon(imgX, imgY, poly)) {
            hit = true;
            break;
          }
        }
      } else if (g.type === "Point" || g.type === "MultiPoint") {
        hit = true;
      }
      if (hit) return { layerName: name, properties: payload.features[i].properties ?? {} };
    }
  }
  return null;
}

// ── Imperative bindings exposed to Svelte components ──────────────────
export function getOSD(): OSDHandle | null { return v.osd; }
export function getDeck(): DeckHandle | null { return v.deck; }
export function isReady(): boolean { return v.ready; }

// Ignore the unused-feature parameter ESLint warning — Svelte action imports.
export type { GeoJsonFeature, OverlayMeta };
