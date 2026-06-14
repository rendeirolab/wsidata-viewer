<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { onTooltip } from "../lib/viewer.js";

  let layerName = $state("");
  let entries = $state<[string, unknown][]>([]);
  let visible = $state(false);
  let posX = $state(0);
  let posY = $state(0);
  let containerEl = $state<HTMLDivElement | null>(null);
  let unsub: (() => void) | null = null;

  function formatVal(v: unknown): string {
    if (v == null) return "—";
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
    return String(v);
  }

  onMount(() => {
    unsub = onTooltip((p) => {
      if (!p) {
        visible = false;
        return;
      }
      layerName = p.layerName;
      entries = Object.entries(p.properties ?? {});

      // Clamp inside the viewer-container so the tooltip never escapes off-canvas
      const container = document.getElementById("viewer-container");
      if (!container) return;
      const rect = container.getBoundingClientRect();
      let x = p.x - rect.left + 12;
      let y = p.y - rect.top + 12;
      visible = true;
      // Defer measurement to next tick so DOM has rendered
      requestAnimationFrame(() => {
        if (!containerEl) return;
        const tw = containerEl.offsetWidth;
        const th = containerEl.offsetHeight;
        if (x + tw > rect.width - 4) x = p.x - rect.left - tw - 12;
        if (y + th > rect.height - 4) y = p.y - rect.top - th - 12;
        posX = Math.max(4, x);
        posY = Math.max(4, y);
      });
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") visible = false;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  onDestroy(() => unsub?.());
</script>

{#if visible}
  <div id="feature-tooltip" bind:this={containerEl} style="left: {posX}px; top: {posY}px">
    <div class="tt-hdr">
      <span class="tt-layer">{layerName}</span>
      <button class="tt-close" title="Close" onclick={() => (visible = false)}>×</button>
    </div>
    <div>
      {#if entries.length === 0}
        <div class="tt-row"><span class="tt-key">no properties</span></div>
      {:else}
        {#each entries as [k, v]}
          <div class="tt-row">
            <span class="tt-key">{k}</span>
            <span class="tt-val" title={formatVal(v)}>{formatVal(v)}</span>
          </div>
        {/each}
      {/if}
    </div>
  </div>
{/if}
