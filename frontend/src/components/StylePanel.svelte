<script lang="ts">
  import { appState, WEBGL_THRESHOLD } from "../lib/stores.svelte.js";
  import { ensureLayerFgbInfo, rebuildAll, setLayerRenderMode } from "../lib/viewer.js";
  import type { RenderMode } from "../lib/types.js";
  import ColumnPicker from "./ColumnPicker.svelte";
  import Legend from "./Legend.svelte";

  let { name }: { name: string } = $props();

  let style = $derived(appState.layerStyles[name]);
  let L = $derived(appState.layers[name]);
  let renderSelectId = $derived(
    `render-mode-${name.replace(/[^A-Za-z0-9_-]/g, "_")}`,
  );
  let pointRadiusId = $derived(`${renderSelectId}-point-radius`);
  let pointAlphaId = $derived(`${renderSelectId}-point-alpha`);

  function update<K extends keyof typeof style>(key: K, value: typeof style[K]) {
    if (!style) return;
    style[key] = value;
    rebuildAll();
  }

  function updateRenderMode(e: Event) {
    setLayerRenderMode(name, (e.target as HTMLSelectElement).value as RenderMode);
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let unit = units[0];
    for (let i = 1; i < units.length && value >= 1024; i++) {
      value /= 1024;
      unit = units[i];
    }
    return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${unit}`;
  }

  let incomingFgb = $derived(L?.fgbInfo?.[L.renderMode]);

  $effect(() => {
    if (L && (L.meta.n_features ?? 0) >= WEBGL_THRESHOLD) {
      void ensureLayerFgbInfo(name);
    }
  });
</script>

{#if style && L}
  {#if (L.meta.n_features ?? 0) >= WEBGL_THRESHOLD}
    <div class="style-row">
      <label for={renderSelectId}>Render</label>
      <select id={renderSelectId} class="col-select" value={L.renderMode} onchange={updateRenderMode}>
        <option value="points">Points</option>
        <option value="polygons">Polygons</option>
      </select>
    </div>
    <div class="style-row">
      <span class="style-key">FGB</span>
      <span class="range-val fgb-size">
        {#if L.fgbInfoState === "loading"}
          estimating
        {:else if incomingFgb}
          {incomingFgb.estimated ? "~" : ""}{formatBytes(incomingFgb.bytes)}
        {:else}
          —
        {/if}
      </span>
    </div>
    {#if L.renderMode === "points"}
      <div class="style-row">
        <label for={pointRadiusId}>Point</label>
        <input id={pointRadiusId} type="range" min="0.5" max="5" step="0.25" value={style.pointRadius}
               oninput={(e) => update("pointRadius", parseFloat((e.target as HTMLInputElement).value))} />
        <span class="range-val">{style.pointRadius}px</span>
      </div>
      <div class="style-row">
        <label for={pointAlphaId}>Density</label>
        <input id={pointAlphaId} type="range" min="0.02" max="0.5" step="0.02" value={style.pointAlpha}
               oninput={(e) => update("pointAlpha", parseFloat((e.target as HTMLInputElement).value))} />
        <span class="range-val">{Math.round(style.pointAlpha * 100)}%</span>
      </div>
    {/if}
  {/if}

  <div class="style-row">
    <label>Stroke</label>
    <input type="color" value={style.strokeColor}
           oninput={(e) => update("strokeColor", (e.target as HTMLInputElement).value)} />
  </div>
  <div class="style-row">
    <label>Width</label>
    <input type="range" min="0.5" max="10" step="0.5" value={style.strokeWidth}
           oninput={(e) => update("strokeWidth", parseFloat((e.target as HTMLInputElement).value))} />
    <span class="range-val">{style.strokeWidth}px</span>
  </div>
  <div class="style-row">
    <label>Fill</label>
    <input type="checkbox" checked={style.fillEnabled}
           onchange={(e) => update("fillEnabled", (e.target as HTMLInputElement).checked)} />
    <input type="color" value={style.fillColor} disabled={!style.fillEnabled}
           oninput={(e) => update("fillColor", (e.target as HTMLInputElement).value)} />
  </div>
  <div class="style-row">
    <label>Alpha</label>
    <input type="range" min="0" max="1" step="0.05" value={style.fillAlpha} disabled={!style.fillEnabled}
           oninput={(e) => update("fillAlpha", parseFloat((e.target as HTMLInputElement).value))} />
    <span class="range-val">{Math.round(style.fillAlpha * 100)}%</span>
  </div>

  {#if L.columns.length > 0}
    <div class="col-section">
      <hr />
      <ColumnPicker {name} />
      <Legend {name} />
    </div>
  {/if}
{/if}
