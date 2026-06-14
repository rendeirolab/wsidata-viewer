<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
  import { setColoring } from "../lib/viewer.js";
  import { buildScheme } from "../lib/color.js";

  let { name }: { name: string } = $props();

  let L = $derived(appState.layers[name]);
  let pickable = $derived(
    (L?.columns ?? []).filter(
      (c) => c.kind === "numeric" || c.kind === "categorical",
    ),
  );
  let selected = $derived(L?.coloring.column ?? "");

  function onChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    if (!L) return;
    if (!v) {
      setColoring(name, { column: null });
      return;
    }
    const col = pickable.find((c) => c.name === v);
    if (!col) return;
    setColoring(name, { column: col.name, meta: col, scheme: buildScheme(col) });
  }
</script>

{#if pickable.length > 0}
  <div class="style-row">
    <label>Color by</label>
    <select class="col-select" value={selected} onchange={onChange}>
      <option value="">— flat color —</option>
      {#each pickable as c}
        <option value={c.name}>{c.name} ({c.kind})</option>
      {/each}
    </select>
  </div>
{/if}
