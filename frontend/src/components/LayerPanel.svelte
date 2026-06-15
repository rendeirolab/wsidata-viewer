<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
  import { loadLayers } from "../lib/viewer.js";
  import LayerRow from "./LayerRow.svelte";

  let open = $state(true);
  let isLoading = $derived(appState.layerListState === "loading");
</script>

<div id="layers-panel" class="fp">
  <div class="fp-header" onclick={() => (open = !open)}>
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="12 2 22 8.5 12 15 2 8.5"/>
      <polyline points="2 15.5 12 22 22 15.5"/>
      <polyline points="2 11 12 17.5 22 11"/>
    </svg>
    <span class="fp-title">Layers</span>
    {#if appState.layerOrder.length > 0}
      <span class="fp-badge">{appState.layerOrder.length}</span>
    {/if}
    <span class="fp-chevron">{open ? "▾" : "▸"}</span>
  </div>
  <div class="fp-body" class:collapsed={!open}>
    <div id="layer-controls">
      {#if isLoading}
        <div class="layers-status">
          <span class="layer-spinner">↻</span>
          <span>Loading layer data...</span>
        </div>
      {:else if appState.layerListState === "error"}
        <div class="layers-status error" title={appState.layerListError ?? "Failed to load layers"}>
          Failed to load layers
        </div>
      {:else if appState.layerOrder.length === 0}
        <div class="no-layers">No shapes in wsi.shapes</div>
      {:else}
        {#each appState.layerOrder as name (name)}
          <LayerRow {name} />
        {/each}
      {/if}
    </div>
    <button class="refresh-btn" onclick={() => loadLayers()} disabled={isLoading}>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="23 4 23 10 17 10"/>
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
      </svg>
      Refresh layers
    </button>
  </div>
</div>
