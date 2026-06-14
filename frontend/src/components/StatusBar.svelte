<script lang="ts">
  import { appState } from "../lib/stores.svelte.js";
</script>

<div id="status" class="fp">{appState.statusText}</div>
