<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
  import { url } from "../lib/api.js";
  import { selectSlide } from "../lib/viewer.js";

  // Lazy-load thumbnail when card scrolls into view. Reusable Svelte action.
  function lazyThumb(node: HTMLImageElement, src: string) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            node.src = src;
            observer.disconnect();
            return;
          }
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(node);
    return {
      destroy() { observer.disconnect(); },
    };
  }

  // 1×1 transparent gif used until intersection triggers
  const PLACEHOLDER =
    "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
</script>

<div id="slide-panel">
  {#each appState.slides as s (s.id)}
    <div
      class="slide-card"
      class:active={s.active}
      onclick={() => selectSlide(s.id)}
      role="button"
      tabindex="0"
      onkeydown={(e) => { if (e.key === "Enter") selectSlide(s.id); }}
    >
      <img src={PLACEHOLDER} alt={s.name} use:lazyThumb={url.slideThumb(s.id)} />
      <div class="slide-card-name" title={s.name}>{s.name}</div>
    </div>
  {/each}
</div>
