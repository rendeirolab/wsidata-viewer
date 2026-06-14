"""FastAPI application serving DZI tiles, GeoJSON overlays, and multi-slide support."""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from ._dzi import DZIInfo, get_dzi_tile

_log = logging.getLogger("wsidata_viewer")

if TYPE_CHECKING:
    from wsidata import WSIData

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_LOGO_PATH = _TEMPLATES_DIR / "logo.webp"

# Shared thread pool for blocking WSI reads and GeoJSON serialisation
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="wsi")
# Separate pool for thumbnail generation so DZI tiles / overlay fetches don't
# starve when the browser fires N thumbnail requests in parallel.
_thumb_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
# In-memory thumbnail cache keyed by slide index.
_thumb_cache: dict[int, bytes] = {}

# NOTE: keep this list in sync with `CAT_PALETTE` in
# `frontend/src/lib/color.ts`. The first overlay color is currently echoed
# from here through `/slides/{id}/overlays`; the TS palette is what the
# frontend actually USES for column-coloring. They should not drift.
_LAYER_COLORS = [
    "#4488ff",
    "#ff4444",
    "#44bb44",
    "#ff8800",
    "#aa44ff",
    "#00bbbb",
    "#ffcc00",
    "#ff44aa",
]

# Timeout in seconds for thumbnail generation before serving a placeholder
_THUMBNAIL_TIMEOUT = 10.0


@dataclass
class SlideSpec:
    """Holds a slide's WSIData object plus metadata needed for lazy loading.

    Lifecycle:
      * ``wsi=None``        — slide has not been opened yet. Will be opened
        reader-only on first thumbnail/properties access via
        :func:`_ensure_opened`.
      * ``wsi`` set, ``zarr_loaded=False`` — reader-only open. No shapes/tables.
        Will be upgraded to a zarr-backed WSI on first shape access.
      * ``wsi`` set, ``zarr_loaded=True``  — fully opened with shapes/tables.

    ``name`` is stored separately so ``/slides`` listing doesn't need the WSI.
    """

    wsi: WSIData | None = None
    path: str | Path | None = None      # original slide file path
    zarr_store: str | None = "auto"     # store arg passed to open_wsi on upgrade
    zarr_loaded: bool = True            # False → shapes not yet loaded
    name: str = ""                      # display name (defaults to path stem)
    # asyncio.Lock created lazily; serialises concurrent open attempts so a
    # burst of N thumbnail requests for the same slide opens it once, not N.
    _lock: asyncio.Lock | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not self.name:
            if self.wsi is not None and getattr(self.wsi, "name", None):
                self.name = self.wsi.name
            elif self.path is not None:
                self.name = Path(self.path).stem
            else:
                self.name = "slide"


def _placeholder_svg(name: str) -> bytes:
    """Return a minimal SVG used as a thumbnail when generation times out."""
    initials = "".join(w[0].upper() for w in name.split()[:2]) or "?"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="150" height="100">'
        f'<rect width="150" height="100" fill="#1a1a1a"/>'
        f'<text x="75" y="50" font-family="sans-serif" font-size="22" '
        f'fill="#444" text-anchor="middle" dominant-baseline="middle">{initials}</text>'
        f'</svg>'
    )
    return svg.encode()


def _make_thumbnail(wsi: WSIData, max_size: int = 256) -> bytes:
    """Return JPEG bytes of a small thumbnail for the slide.

    Prefers the reader's native ``get_thumbnail`` (e.g. openslide's hardware-
    accelerated path) over decoding the lowest pyramid level by hand. Falls
    back to a manual ``read_region`` only when the reader can't produce a
    thumbnail of that size (e.g. image smaller than ``max_size``).
    """
    from io import BytesIO

    from PIL import Image

    arr = None
    reader = getattr(wsi, "reader", None)
    if reader is not None and hasattr(reader, "get_thumbnail"):
        try:
            arr = reader.get_thumbnail(max_size)
        except Exception:
            arr = None

    if arr is None:
        # Fallback: decode the lowest pyramid level
        props = wsi.properties
        best_level = props.n_level - 1
        lh, lw = props.level_shape[best_level]
        arr = wsi.read_region(0, 0, lw, lh, level=best_level)

    img = Image.fromarray(arr)
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


async def _ensure_opened(spec: SlideSpec, *, with_zarr: bool, loop=None) -> None:
    """Ensure ``spec.wsi`` is opened (and optionally zarr-loaded).

    Safe to call concurrently from many request handlers — a per-spec lock
    serialises the actual open work so N concurrent thumbnail requests for an
    unopened slide only pay the open cost once.
    """
    # Fast path — fully ready and shapes loaded (or not required)
    if spec.wsi is not None and (not with_zarr or spec.zarr_loaded):
        return

    if loop is None:
        loop = asyncio.get_running_loop()

    if spec._lock is None:
        spec._lock = asyncio.Lock()

    async with spec._lock:
        # Re-check after acquiring the lock
        if spec.wsi is not None and (not with_zarr or spec.zarr_loaded):
            return

        if spec.path is None:
            # Nothing we can do — caller passed a bare SlideSpec without a path
            if spec.wsi is None:
                raise HTTPException(
                    status_code=500,
                    detail="Slide has no path and no preloaded WSI",
                )
            return

        from wsidata import open_wsi as _open_wsi

        if spec.wsi is None:
            # First-time open: reader-only unless caller asked for zarr now
            store = (spec.zarr_store or "auto") if with_zarr else None
            wsi = await loop.run_in_executor(
                _executor,
                lambda: _open_wsi(str(spec.path), store=store),
            )
            spec.wsi = wsi
            spec.zarr_loaded = with_zarr
            if not spec.name:
                spec.name = getattr(wsi, "name", "") or Path(spec.path).stem
        elif with_zarr and not spec.zarr_loaded:
            # Upgrade reader-only → zarr-backed
            store = spec.zarr_store or "auto"
            wsi = await loop.run_in_executor(
                _executor,
                lambda: _open_wsi(str(spec.path), store=store),
            )
            spec.wsi = wsi
            spec.zarr_loaded = True


def _normalize_specs(wsi_or_list) -> list[SlideSpec]:
    """Accept WSIData, list[WSIData], or list[SlideSpec] and return list[SlideSpec]."""
    from wsidata import WSIData as _WSIData  # avoid top-level import

    if isinstance(wsi_or_list, SlideSpec):
        return [wsi_or_list]
    if isinstance(wsi_or_list, _WSIData):
        return [SlideSpec(wsi=wsi_or_list)]
    # list
    specs = []
    for item in wsi_or_list:
        if isinstance(item, SlideSpec):
            specs.append(item)
        else:
            specs.append(SlideSpec(wsi=item))
    return specs


def create_app(
    wsi_or_list,
    tile_size: int = 254,
    jpeg_quality: int = 80,
    shape_keys: list[str] | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Parameters
    ----------
    wsi_or_list:
        A single ``WSIData``, a list of ``WSIData`` objects, or a list of
        :class:`SlideSpec` objects (used by the CLI for lazy zarr loading).
    tile_size:
        DZI effective tile size (without overlap pixels).
    jpeg_quality:
        JPEG encoding quality for tile images.
    shape_keys:
        Shape layer keys to expose.  ``None`` = all keys in each slide's shapes.
    """
    specs = _normalize_specs(wsi_or_list)
    if not specs:
        raise ValueError("wsi_or_list must contain at least one WSIData object")

    # Active-slide pointer. Only used so /slides list can report which slide
    # is currently active for fresh page loads / sidebar highlight sync.
    # Per-slide URL routes never consult this — they use the URL's slide_id.
    state = {"current": 0}

    # FlatGeobuf cache keyed by (slide_index, layer_name, representation).
    # Declared before
    # lifespan so the shutdown handler can clear it.
    _fgb_cache: dict[tuple[int, str, str], bytes] = {}
    _fgb_size_cache: dict[tuple[int, str, str], dict] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Startup: nothing eager — slides are opened lazily via _ensure_opened.
        yield
        # Shutdown: release resources.
        _log.info("Shutdown: releasing resources …")
        _fgb_cache.clear()
        _fgb_size_cache.clear()
        _thumb_cache.clear()
        for i, spec in enumerate(specs):
            wsi = spec.wsi
            if wsi is None:
                continue
            for attr in ("close", "_close", "release"):
                fn = getattr(wsi, attr, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception as exc:
                        _log.debug("slide %d %s() failed: %s", i, attr, exc)
        for ex in (_executor, _thumb_executor):
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception as exc:
                _log.debug("executor shutdown failed: %s", exc)
        _log.info("Shutdown complete.")

    app = FastAPI(title="wsidata-viewer", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

    # Mount the compiled Svelte bundle. Built by `cd frontend && npm run build`.
    # The directory is part of the wheel so Python users never need Node.
    if _STATIC_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="static",
        )

    def _resolve(slide_id: int) -> SlideSpec:
        if slide_id < 0 or slide_id >= len(specs):
            raise HTTPException(status_code=404, detail="Slide not found")
        return specs[slide_id]

    # ── Index page ────────────────────────────────────────────────────────
    # The HTML shell is a thin Jinja template that loads /static/main.js. All
    # dynamic state crosses into JS via a single <script id="bootstrap"> JSON
    # block — no Jinja-in-JS expressions, so the Svelte bundle never sees
    # template syntax.
    @app.get("/")
    async def index() -> HTMLResponse:
        # Friendly error if the frontend bundle hasn't been built yet —
        # e.g. someone editable-installed the repo before running `npm run
        # build`. (For wheel users `static/main.js` is always present.)
        if not (_STATIC_DIR / "main.js").exists():
            return HTMLResponse(
                "<!doctype html><meta charset=utf-8>"
                "<title>wsidata-viewer</title>"
                "<body style='font-family:sans-serif;padding:2em;background:#111;color:#ddd'>"
                "<h1>Frontend bundle missing</h1>"
                "<p>The compiled JS bundle was not found at "
                f"<code>{_STATIC_DIR}/main.js</code>.</p>"
                "<p>Build it:</p>"
                "<pre style='background:#000;padding:1em;border-radius:4px'>"
                "cd frontend\nnpm install\nnpm run build"
                "</pre>"
                "<p>Then reload this page.</p>",
                status_code=503,
            )
        await _ensure_opened(specs[0], with_zarr=True)
        wsi = specs[0].wsi
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)
        bootstrap = {
            "slide_id": 0,
            "slide_name": wsi.name,
            "slide_width": dzi_info.slide_width,
            "slide_height": dzi_info.slide_height,
            "dzi_url": "/slides/0/slide.dzi",
            "properties": wsi.properties.to_dict(),
            "layer_colors": _LAYER_COLORS,
            "multi_slide": (len(specs) > 1),
        }
        # ``main_css`` is a hint to the template: only emit the <link> if the
        # bundle actually built one (Svelte 5 may inline CSS depending on
        # config).
        main_css = (_STATIC_DIR / "main.css").exists()
        template = jinja_env.get_template("viewer.html")
        html = template.render(
            slide_name=wsi.name,
            bootstrap_json=json.dumps(bootstrap),
            main_css=main_css,
        )
        return HTMLResponse(html)

    # ── Favicon ───────────────────────────────────────────────────────────
    @app.get("/favicon.webp")
    @app.get("/favicon.ico")
    async def favicon() -> Response:
        if not _LOGO_PATH.exists():
            raise HTTPException(status_code=404, detail="favicon missing")
        return FileResponse(
            _LOGO_PATH,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # ── DZI descriptor (per-slide) ────────────────────────────────────────
    @app.get("/slides/{slide_id}/slide.dzi")
    async def dzi_descriptor(slide_id: int) -> Response:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=False)
        dzi_info = DZIInfo.from_wsi(spec.wsi, tile_size=tile_size, overlap=1)
        return Response(content=dzi_info.descriptor_xml(), media_type="application/xml")

    # ── DZI tiles (per-slide) ─────────────────────────────────────────────
    @app.get("/slides/{slide_id}/slide_files/{dzi_level}/{tile_name}.jpeg")
    async def tile(slide_id: int, dzi_level: int, tile_name: str) -> Response:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=False)
        wsi = spec.wsi
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)

        try:
            col_str, row_str = tile_name.split("_")
            col, row = int(col_str), int(row_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tile name, expected col_row")

        if dzi_level < 0 or dzi_level > dzi_info.max_level:
            raise HTTPException(status_code=404, detail="DZI level out of range")

        n_cols, n_rows = dzi_info.tile_count(dzi_level)
        if col < 0 or col >= n_cols or row < 0 or row >= n_rows:
            raise HTTPException(status_code=404, detail="Tile coordinates out of bounds")

        loop = asyncio.get_running_loop()
        jpeg_bytes = await loop.run_in_executor(
            _executor, get_dzi_tile, wsi, dzi_info, dzi_level, col, row, jpeg_quality,
        )
        return Response(
            content=jpeg_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # ── Slide properties (per-slide) ──────────────────────────────────────
    @app.get("/slides/{slide_id}/properties")
    async def slide_properties(slide_id: int) -> JSONResponse:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=False)
        return JSONResponse(spec.wsi.properties.to_dict())

    # ── Multi-slide list ──────────────────────────────────────────────────
    @app.get("/slides")
    async def list_slides() -> JSONResponse:
        """List all slides. Does NOT trigger lazy open — width/height are null
        for slides that haven't been opened yet. Frontend fetches per-slide
        properties on demand."""
        result = []
        for i, spec in enumerate(specs):
            entry = {
                "id": i,
                "name": spec.name,
                "width": None,
                "height": None,
                "active": i == state["current"],
            }
            if spec.wsi is not None:
                try:
                    h, w = spec.wsi.properties.shape
                    entry["width"] = w
                    entry["height"] = h
                except Exception:
                    pass
            result.append(entry)
        return JSONResponse(result)

    @app.get("/slides/{slide_id}/thumbnail.jpeg")
    async def slide_thumbnail(slide_id: int) -> Response:
        if slide_id < 0 or slide_id >= len(specs):
            raise HTTPException(status_code=404, detail="Slide not found")

        # In-memory cache hit — sub-ms response, no executor dispatch
        cached = _thumb_cache.get(slide_id)
        if cached is not None:
            return Response(
                content=cached,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )

        spec = specs[slide_id]
        loop = asyncio.get_running_loop()
        try:
            # Lazy-open the slide if it hasn't been opened yet (reader-only is
            # enough for a thumbnail — no zarr/shapes needed).
            await _ensure_opened(spec, with_zarr=False, loop=loop)
            wsi = spec.wsi
            jpeg_bytes = await asyncio.wait_for(
                loop.run_in_executor(_thumb_executor, _make_thumbnail, wsi),
                timeout=_THUMBNAIL_TIMEOUT,
            )
            _thumb_cache[slide_id] = jpeg_bytes
            return Response(
                content=jpeg_bytes,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except asyncio.TimeoutError:
            name = spec.name if spec.name else f"slide {slide_id}"
            return Response(
                content=_placeholder_svg(name),
                media_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=60"},
            )

    @app.post("/slides/{slide_id}/select")
    async def select_slide(slide_id: int) -> Response:
        """Mark a slide as active and return enough metadata to render it.

        Only requires a reader-only open (cheap). The zarr upgrade (shapes)
        is deferred until the first ``/slides/{id}/overlays`` request — this
        keeps slide-switch UI responsive even for large slides.
        """
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=False)

        state["current"] = slide_id
        wsi = spec.wsi
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)
        return JSONResponse({
            "id": slide_id,
            "name": spec.name or wsi.name,
            "slide_width": dzi_info.slide_width,
            "slide_height": dzi_info.slide_height,
            "properties": wsi.properties.to_dict(),
        })

    # ── Shape overlays (per-slide) ────────────────────────────────────────
    @app.get("/slides/{slide_id}/overlays")
    async def list_overlays(slide_id: int) -> JSONResponse:
        """Return the list of shape keys for the given slide. Triggers a zarr
        upgrade if the slide hasn't loaded shapes yet."""
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        all_keys = list(wsi.shapes.keys())
        keys = [k for k in all_keys if k in shape_keys] if shape_keys is not None else all_keys
        result = []
        for i, key in enumerate(keys):
            try:
                n = len(wsi.shapes[key])
            except Exception:
                n = 0
            result.append({
                "name": key,
                "color": _LAYER_COLORS[i % len(_LAYER_COLORS)],
                "n_features": n,
            })
        return JSONResponse(result)

    @app.get("/slides/{slide_id}/overlays/{name}/columns")
    async def overlay_columns(slide_id: int, name: str) -> JSONResponse:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")
        gdf = wsi.shapes[name]
        info = []
        for col in gdf.columns:
            if col == "geometry":
                continue
            s = gdf[col]
            if s.dtype.kind in ("i", "u", "f"):
                info.append({"name": col, "kind": "numeric",
                              "min": float(s.min()), "max": float(s.max())})
            else:
                cats = sorted(s.dropna().astype(str).unique().tolist())
                info.append({"name": col, "kind": "categorical", "categories": cats})
        return JSONResponse(info)

    @app.get("/slides/{slide_id}/overlays/{name}.geojson")
    async def overlay(slide_id: int, name: str) -> Response:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")
        loop = asyncio.get_running_loop()
        geojson_str = await loop.run_in_executor(_executor, wsi.shapes[name].to_json)
        return Response(content=geojson_str, media_type="application/json")

    def _point_gdf(gdf):
        gdf = gdf.copy()
        gdf.geometry = gdf.geometry.representative_point()
        return gdf

    def _build_fgb(gdf, *, as_points: bool = False) -> bytes:
        """Serialise GeoDataFrame to FlatGeobuf bytes via pyogrio."""
        from io import BytesIO

        if as_points:
            gdf = _point_gdf(gdf)

        buf = BytesIO()
        try:
            import pyogrio

            pyogrio.write_dataframe(gdf, buf, driver="FlatGeobuf")
        except Exception:
            gdf.to_file(buf, driver="FlatGeobuf")
        return buf.getvalue()

    def _estimate_fgb_size(gdf, *, as_points: bool = False, sample_size: int = 2000) -> dict:
        """Estimate FlatGeobuf byte size from a small row sample."""
        n = len(gdf)
        if n == 0:
            return {"bytes": 0, "estimated": False, "sample_features": 0}

        sample_n = min(sample_size, n)
        sample = gdf.iloc[:sample_n]
        sample_bytes = len(_build_fgb(sample, as_points=as_points))
        estimated = sample_n < n
        size = round(sample_bytes * (n / sample_n)) if estimated else sample_bytes
        return {
            "bytes": int(size),
            "estimated": estimated,
            "sample_features": int(sample_n),
        }

    async def _fgb_size_info(slide_id: int, name: str, representation: str) -> dict:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")

        key = (slide_id, name, representation)
        if key in _fgb_cache:
            return {
                "bytes": len(_fgb_cache[key]),
                "estimated": False,
                "sample_features": len(wsi.shapes[name]),
            }
        if key not in _fgb_size_cache:
            loop = asyncio.get_running_loop()
            _fgb_size_cache[key] = await loop.run_in_executor(
                _executor,
                partial(
                    _estimate_fgb_size,
                    wsi.shapes[name],
                    as_points=(representation == "points"),
                ),
            )
        return _fgb_size_cache[key]

    @app.get("/slides/{slide_id}/overlays/{name}/fgb-info")
    async def overlay_fgb_info(slide_id: int, name: str) -> JSONResponse:
        points = await _fgb_size_info(slide_id, name, "points")
        full = await _fgb_size_info(slide_id, name, "full")
        return JSONResponse({
            "points": points,
            "polygons": full,
        })

    @app.get("/slides/{slide_id}/overlays/{name}.points.fgb")
    async def overlay_points_fgb(slide_id: int, name: str) -> Response:
        """Return a point-cloud FlatGeobuf representation of an overlay.

        Large cell-segmentation layers can contain hundreds of thousands of
        small polygons. Sending those full polygons to the browser creates a
        huge nested GeoJSON object graph and can crash Chrome before JS can
        report an error. This endpoint preserves per-feature properties but
        uses representative points for WebGL overview rendering.
        """
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")

        key = (slide_id, name, "points")
        if key in _fgb_cache:
            data = _fgb_cache[key]
        else:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                _executor,
                partial(_build_fgb, wsi.shapes[name], as_points=True),
            )
            _fgb_cache[key] = data

        etag = f'W/"{hash((key, len(data))):x}"'
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=3600",
                "ETag": etag,
            },
        )

    @app.get("/slides/{slide_id}/overlays/{name}.fgb")
    async def overlay_fgb(slide_id: int, name: str) -> Response:
        spec = _resolve(slide_id)
        await _ensure_opened(spec, with_zarr=True)
        wsi = spec.wsi
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")

        key = (slide_id, name, "full")
        if key in _fgb_cache:
            data = _fgb_cache[key]
        else:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(_executor, _build_fgb, wsi.shapes[name])
            _fgb_cache[key] = data

        etag = f'W/"{hash((key, len(data))):x}"'
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=3600",
                "ETag": etag,
            },
        )

    return app
