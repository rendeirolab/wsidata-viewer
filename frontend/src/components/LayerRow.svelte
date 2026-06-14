<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
  import { fetchLayer, setLayerVisible } from "../lib/viewer.js";
  import StylePanel from "./StylePanel.svelte";

  let { name }: { name: string } = $props();

  let L = $derived(appState.layers[name]);
  let style = $derived(appState.layerStyles[name]);
  let open = $derived(appState.styleOpen[name] ?? false);

  function toggleVisible(e: Event) {
    const target = e.target as HTMLInputElement;
    if (!L) return;
    if (target.checked && (L.fetchState === "idle" || L.fetchState === "error")) {
      fetchLayer(name);
    } else {
      setLayerVisible(name, target.checked);
    }
  }

  function toggleStylePanel() {
    appState.styleOpen[name] = !open;
  }

  function clickLabel() {
    if (!L) return;
    const nextVisible = !L.visible;
    setLayerVisible(name, nextVisible);
    if (nextVisible && (L.fetchState === "idle" || L.fetchState === "error")) {
      fetchLayer(name);
    }
  }
</script>

{#if L && style}
  <div>
    <div class="layer-row">
      <input type="checkbox" checked={L.visible} onchange={toggleVisible} />
      <div class="swatch" style="background: {style.strokeColor}" onclick={toggleStylePanel} title="Style options"></div>
      <label class="layer-name" title={name} onclick={clickLabel}>{name}</label>
      <span class="layer-n">
        {#if L.fetchState === "loading"}
          <span class="layer-spinner">↻</span>
        {:else if L.fetchState === "error"}
          <span title={L.errorMsg ?? "error"}>!</span>
        {:else if L.fetchState === "loaded"}
          {L.featureCount.toLocaleString()}
        {:else}
          —
        {/if}
      </span>
      <button class="style-btn" title="Style options" onclick={toggleStylePanel}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>

    <div class="layer-style" class:open>
      <StylePanel {name} />
    </div>
  </div>
{/if}
