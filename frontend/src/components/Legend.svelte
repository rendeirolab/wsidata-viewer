<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";

  let { name }: { name: string } = $props();

  let coloring = $derived(appState.layers[name]?.coloring);
</script>

{#if coloring && coloring.column !== null}
  <div class="layer-legend">
    {#if coloring.scheme.kind === "categorical"}
      {#each Object.entries(coloring.scheme.map) as [cat, color]}
        <div class="legend-item">
          <span class="legend-swatch" style="background: {color}"></span>
          <span>{cat}</span>
        </div>
      {/each}
    {:else}
      <div class="legend-gradient"></div>
      <div class="legend-minmax">
        <span>{coloring.scheme.min.toFixed(2)}</span>
        <span>{coloring.scheme.max.toFixed(2)}</span>
      </div>
    {/if}
  </div>
{/if}
