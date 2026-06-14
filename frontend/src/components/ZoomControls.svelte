<script lang="ts">
  import { onMount } from "svelte";
  import { getOSD, isReady } from "../lib/viewer.js";
  import { appState } from "../lib/stores.svelte.js";
  import { ZOOM_MIN, ZOOM_MAX, zoomToSlider, sliderToZoom } from "../lib/osd.js";

  let sliderEl: HTMLInputElement;
  let sliderValue = "0.5";
  let dragging = false;

  function syncSlider(zoom: number) {
    if (dragging) return;
    const clamped = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom));
    sliderValue = String(zoomToSlider(clamped));
  }

  onMount(() => {
    if (!isReady()) return;
    const osd = getOSD();
    if (!osd) return;

    const syncCurrentZoom = () => syncSlider(osd.viewer.viewport.getZoom());
    const onZoom = (e: { zoom: number }) => syncSlider(e.zoom);

    osd.viewer.addHandler("open", syncCurrentZoom);
    osd.viewer.addHandler("zoom", onZoom);
    requestAnimationFrame(syncCurrentZoom);

    return () => {
      osd.viewer.removeHandler("open", syncCurrentZoom);
      osd.viewer.removeHandler("zoom", onZoom);
    };
  });

  function onInput() {
    dragging = true;
    const osd = getOSD();
    if (osd && sliderEl) {
      const z = sliderToZoom(parseFloat(sliderValue));
      osd.viewer.viewport.zoomTo(z);
    }
    dragging = false;
  }
  function zoomIn()  { getOSD()?.zoomBy(2); }
  function zoomOut() { getOSD()?.zoomBy(0.5); }
  function home()    { getOSD()?.goHome(); }
</script>

<div id="zoom-controls" class="fp">
  <button class="ctrl-btn" title="Zoom in" onclick={zoomIn}>
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      <line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
    </svg>
  </button>
  <div id="zoom-slider-row">
    <input bind:this={sliderEl} bind:value={sliderValue} type="range" id="zoom-slider" min="0" max="1" step="0.001" oninput={onInput} />
    <span id="zoom-slider-label">{appState.zoom ? appState.zoom.toFixed(2) + "×" : "—"}</span>
  </div>
  <button class="ctrl-btn" title="Zoom out" onclick={zoomOut}>
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      <line x1="8" y1="11" x2="14" y2="11"/>
    </svg>
  </button>
  <button class="ctrl-btn" title="Fit to screen" onclick={home}>
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>
      <line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
    </svg>
  </button>
</div>
