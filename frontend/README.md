# wsidata-viewer frontend

Svelte 5 + TypeScript + Vite. Compiles to `../src/wsidata_viewer/static/`
which the Python wheel ships verbatim — Python users **never** need Node.

## Dev loop

```bash
# 1) Python server (port 8000)
wsidata-viewer path/to/slide.svs --port 8000 --no-open

# 2) In another terminal — Vite with HMR
cd frontend
npm install     # first time only
npm run dev     # → http://localhost:5173
```

Vite proxies `/slides/*`, `/favicon.*` to the Python server.

## Build for production

```bash
cd frontend
npm run build
# → ../src/wsidata_viewer/static/{main.js,main.css}
```

Commit `src/wsidata_viewer/static/` to git so plain `pip install` works.

## Layout

- `src/main.ts` — bootstrap (reads `<script id="bootstrap">`, mounts `<App/>`)
- `src/App.svelte` — layout shell
- `src/lib/` — pure TS modules
  - `types.ts` — API + state types (the contract with `_server.py`)
  - `api.ts` — typed `fetch` wrappers + URL builders
  - `stores.ts` — Svelte 5 `$state` runes (global state)
  - `color.ts` — palette + viridis interp
  - `bbox.ts` — geometry bbox + viewport helpers
  - `osd.ts` — OpenSeadragon init + pub-sub
  - `canvas2d.ts` — Canvas2D overlay renderer
  - `deck.ts` — deck.gl WebGL layer factory
- `src/components/` — Svelte components
