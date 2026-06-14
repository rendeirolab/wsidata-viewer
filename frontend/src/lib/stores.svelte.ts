/**
 * Global mutable appState. Svelte 5 runes — every reference is fine-grained
 * reactive, so components/effects re-run on the exact field they read.
 *
 * `appState.layers` is a map keyed by overlay name. `appState.layerStyles` is
 * SEPARATE because styles persist across slide switches (matching the
 * existing UX where colors stay sticky between slides).
 */

import type {
  Bootstrap,
  LayerState,
  LayerStyle,
  SlideListEntry,
} from "./types.js";

export const WEBGL_THRESHOLD = 5000;

export function defaultStyle(color: string): LayerStyle {
  return {
    strokeColor: color,
    strokeWidth: 1,
    fillEnabled: true,
    fillColor: color,
    fillAlpha: 0.2,
    pointRadius: 2,
    pointAlpha: 0.12,
  };
}

function readBootstrap(): Bootstrap {
  const el = document.getElementById("bootstrap");
  if (!el || !el.textContent) {
    throw new Error("Missing <script id=\"bootstrap\"> bootstrap payload");
  }
  return JSON.parse(el.textContent) as Bootstrap;
}

const BOOTSTRAP = readBootstrap();

/**
 * Mutable state container. Use `appState.x = ...` to update reactively.
 * Named `appState` (not `state`) because Svelte 5 treats any identifier
 * called `state` as a store-subscription target (`$state` rune conflict).
 */
export const appState = $state({
  bootstrap: BOOTSTRAP,
  currentSlideId: BOOTSTRAP.slide_id,
  currentMpp: BOOTSTRAP.properties.mpp as number | null,
  slideName: BOOTSTRAP.slide_name,
  slideWidth: BOOTSTRAP.slide_width,
  slideHeight: BOOTSTRAP.slide_height,

  // Slide sidebar list (filled once /slides resolves)
  slides: [] as SlideListEntry[],

  // Per-slide overlay map. Cleared on slide switch.
  layers: {} as Record<string, LayerState>,
  // Ordered layer names — preserves the order returned by /overlays.
  layerOrder: [] as string[],

  // Persistent style overrides; survive slide switches by layer-name key.
  layerStyles: {} as Record<string, LayerStyle>,

  // Status bar text (zoom string)
  statusText: "",

  // Last reported zoom + center for info panel
  zoom: 0,
  centerImg: { x: 0, y: 0 },

  // Style-panel open/closed per layer
  styleOpen: {} as Record<string, boolean>,
});

/**
 * Aborts in-flight slide-scoped requests on switch. NOT in $state — Svelte
 * shouldn't track this; consumers grab `.signal` imperatively each call.
 */
class SelectControllerRef {
  current: AbortController | null = null;
  reset(): AbortSignal {
    if (this.current) this.current.abort();
    this.current = new AbortController();
    return this.current.signal;
  }
  get signal(): AbortSignal | undefined {
    return this.current?.signal;
  }
}
export const selectController = new SelectControllerRef();

/** Wipe overlay state for a fresh slide. Styles preserved by design. */
export function clearOverlayState(): void {
  appState.layers = {};
  appState.layerOrder = [];
}
