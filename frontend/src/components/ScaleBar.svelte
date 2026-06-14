<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
  import { getOSD } from "../lib/viewer.js";

  const NICE_STEPS_UM = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];

  function compute() {
    const osd = getOSD();
    if (!osd || !appState.currentMpp || !osd.viewer.viewport) {
      return { visible: false, barPx: 0, label: "" };
    }
    const s = osd.screenPxPerImagePx();
    if (s <= 0) return { visible: false, barPx: 0, label: "" };
    const maxUm = (120 / s) * appState.currentMpp;
    let niceUm = NICE_STEPS_UM[0];
    for (const step of NICE_STEPS_UM) {
      if (step <= maxUm) niceUm = step;
      else break;
    }
    const barPx = Math.round((niceUm / appState.currentMpp) * s);
    const label = niceUm >= 1000 ? `${niceUm / 1000} mm` : `${niceUm} µm`;
    return { visible: true, barPx, label };
  }

  // Re-derives any time zoom changes (appState.zoom is set by osd zoom handler)
  let bar = $derived.by(() => {
    void appState.zoom; // dependency
    void appState.currentMpp;
    return compute();
  });
</script>

{#if bar.visible}
  <div id="scale-bar">
    <div id="scale-bar-line" style="width: {bar.barPx}px"></div>
    <div id="scale-bar-label">{bar.label}</div>
  </div>
{/if}
