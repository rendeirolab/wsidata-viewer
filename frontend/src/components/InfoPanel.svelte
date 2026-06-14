<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";

  let open = $state(true);
</script>

<div id="info-panel" class="fp">
  <div class="fp-header" onclick={() => (open = !open)}>
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    <span class="fp-title">Slide info</span>
    <span class="fp-chevron">{open ? "▾" : "▸"}</span>
  </div>
  <div class="fp-body" class:collapsed={!open}>
    <div class="info-row"><span class="info-key">Width</span><span class="info-val">{appState.slideWidth} px</span></div>
    <div class="info-row"><span class="info-key">Height</span><span class="info-val">{appState.slideHeight} px</span></div>
    {#if appState.currentMpp}
      <div class="info-row"><span class="info-key">MPP</span><span class="info-val">{appState.currentMpp.toFixed(4)} µm/px</span></div>
    {/if}
    {#if appState.bootstrap.properties.magnification}
      <div class="info-row"><span class="info-key">Mag</span><span class="info-val">{Math.round(appState.bootstrap.properties.magnification)}×</span></div>
    {/if}
    <hr class="info-divider">
    <div class="info-row"><span class="info-key">Levels</span><span class="info-val">{appState.bootstrap.properties.n_level}</span></div>
    {#each appState.bootstrap.properties.level_shape as s, i}
      <div class="info-row"><span class="info-key">Level {i}</span><span class="info-val">{s[1]} × {s[0]}</span></div>
    {/each}
    <hr class="info-divider">
    <div class="info-row"><span class="info-key">Zoom</span><span class="info-val">{appState.zoom ? appState.zoom.toFixed(3) + "×" : "—"}</span></div>
    <div class="info-row"><span class="info-key">Center</span><span class="info-val">{Math.round(appState.centerImg.x)}, {Math.round(appState.centerImg.y)} px</span></div>
  </div>
</div>
