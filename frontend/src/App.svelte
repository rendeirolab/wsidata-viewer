<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { appState } from "./lib/stores.svelte.js";
  import * as viewer from "./lib/viewer.js";
  import { api } from "./lib/api.js";

  import SlidePanel from "./components/SlidePanel.svelte";
  import LayerPanel from "./components/LayerPanel.svelte";
  import InfoPanel from "./components/InfoPanel.svelte";
  import ZoomControls from "./components/ZoomControls.svelte";
  import ScaleBar from "./components/ScaleBar.svelte";
  import StatusBar from "./components/StatusBar.svelte";
  import FeatureTooltip from "./components/FeatureTooltip.svelte";

  let osdEl: HTMLDivElement;
  let overlayCanvas: HTMLCanvasElement;
  let deckCanvas: HTMLCanvasElement;
  let container: HTMLDivElement;

  $effect(() => {
    document.title = appState.slideName
      ? `${appState.slideName} | wsidata`
      : "wsidata";
  });

  onMount(async () => {
    viewer.mount({ osdEl, overlayCanvas, deckCanvas, container });

    // Initial layer list for slide 0
    await viewer.loadLayers(appState.currentSlideId);

    // Slide list (if multi-slide)
    if (appState.bootstrap.multi_slide) {
      try {
        appState.slides = await api.listSlides();
      } catch (err) {
        console.error("Failed to list slides:", err);
      }
    }
  });

  onDestroy(() => viewer.dispose());
</script>

<header>
  <span class="logo">wsidata</span>
  <span class="slide-name">{appState.slideName}</span>
</header>

<div id="main-row">
  {#if appState.bootstrap.multi_slide}
    <SlidePanel />
  {/if}

  <div id="viewer-container" bind:this={container}>
    <div id="osd" bind:this={osdEl}></div>
    <canvas id="overlay-canvas" bind:this={overlayCanvas}></canvas>
    <canvas id="deck-canvas" bind:this={deckCanvas}></canvas>

    <LayerPanel />
    <InfoPanel />
    <ZoomControls />
    <ScaleBar />
    <FeatureTooltip />
    <StatusBar />
  </div>
</div>
