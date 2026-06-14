import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { resolve } from "node:path";

// In dev (`npm run dev`) Vite serves index.html and proxies all server-side
// routes to the FastAPI dev server at 127.0.0.1:8000.
// In build (`npm run build`) we emit a *Python-server-hosted* bundle into
// ../src/wsidata_viewer/static/ ; the Python `viewer.html` template loads
// /static/main.js at runtime. No CDN, no Node at install time.

const PY_DEV = "http://127.0.0.1:8000";

const PROXY = {
  "/slides": PY_DEV,
  "/favicon.ico": PY_DEV,
  "/favicon.webp": PY_DEV,
  // anything else that might be added later
} satisfies Record<string, string>;

export default defineConfig({
  plugins: [svelte()],
  root: ".",
  server: {
    port: 5173,
    strictPort: true,
    proxy: PROXY,
  },
  build: {
    outDir: resolve(__dirname, "../src/wsidata_viewer/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    target: "es2022",
    rollupOptions: {
      input: resolve(__dirname, "src/main.ts"),
      output: {
        // Stable filenames so Python's <script src="/static/main.js"> works
        // without reading a manifest. Vite would otherwise hash them.
        entryFileNames: "main.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: (info) => {
          if (info.name && /\.css$/.test(info.name)) return "main.css";
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
