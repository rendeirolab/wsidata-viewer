"""FastAPI application serving DZI tiles, GeoJSON overlays, and multi-slide support."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from jinja2 import Environment, FileSystemLoader

from ._dzi import DZIInfo, get_dzi_tile

import logging

_log = logging.getLogger("wsidata_viewer")

if TYPE_CHECKING:
    from wsidata import WSIData

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_LOGO_PATH = _TEMPLATES_DIR / "logo.webp"

# Shared thread pool for blocking WSI reads and GeoJSON serialisation
_executor = ThreadPoolExecutor(max_workers=4)

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
    """Holds a slide's WSIData object plus metadata needed for lazy zarr loading.

    When ``zarr_loaded`` is ``False`` the WSI was opened without a zarr store
    (reader-only, no shapes/tables).  The first time that slide becomes active
    it will be reopened with ``zarr_store`` so that shapes are available.
    """

    wsi: WSIData
    path: str | Path | None = None      # original slide file path
    zarr_store: str | None = "auto"     # store arg passed to open_wsi on upgrade
    zarr_loaded: bool = True            # False → shapes not yet loaded


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
    """Return JPEG bytes of a small thumbnail for the slide."""
    from io import BytesIO

    from PIL import Image

    props = wsi.properties
    best_level = props.n_level - 1
    lh, lw = props.level_shape[best_level]

    region = wsi.read_region(0, 0, lw, lh, level=best_level)
    img = Image.fromarray(region)
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


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

    # Mutable current-slide index
    state = {"current": 0}

    def current_spec() -> SlideSpec:
        return specs[state["current"]]

    def current_wsi() -> WSIData:
        return specs[state["current"]].wsi

    app = FastAPI(title="wsidata-viewer")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

    # ── Index page ────────────────────────────────────────────────────────
    @app.get("/")
    async def index() -> HTMLResponse:
        wsi = current_wsi()
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)
        template = jinja_env.get_template("viewer.html")
        html = template.render(
            slide_name=wsi.name,
            slide_width=dzi_info.slide_width,
            slide_height=dzi_info.slide_height,
            dzi_url="/slide.dzi",
            properties=wsi.properties.to_dict(),
            layer_colors=_LAYER_COLORS,
            multi_slide=(len(specs) > 1),
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

    # ── DZI descriptor ────────────────────────────────────────────────────
    @app.get("/slide.dzi")
    async def dzi_descriptor() -> Response:
        wsi = current_wsi()
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)
        return Response(content=dzi_info.descriptor_xml(), media_type="application/xml")

    # ── DZI tiles ─────────────────────────────────────────────────────────
    @app.get("/slide_files/{dzi_level}/{tile_name}.jpeg")
    async def tile(dzi_level: int, tile_name: str) -> Response:
        wsi = current_wsi()
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

    # ── Slide properties ──────────────────────────────────────────────────
    @app.get("/slide/properties")
    async def slide_properties() -> JSONResponse:
        return JSONResponse(current_wsi().properties.to_dict())

    # ── Multi-slide list ──────────────────────────────────────────────────
    @app.get("/slides")
    async def list_slides() -> JSONResponse:
        result = []
        for i, spec in enumerate(specs):
            props = spec.wsi.properties
            h, w = props.shape
            result.append({
                "id": i,
                "name": spec.wsi.name,
                "width": w,
                "height": h,
                "active": i == state["current"],
            })
        return JSONResponse(result)

    @app.get("/slides/{slide_id}/thumbnail.jpeg")
    async def slide_thumbnail(slide_id: int) -> Response:
        if slide_id < 0 or slide_id >= len(specs):
            raise HTTPException(status_code=404, detail="Slide not found")
        wsi = specs[slide_id].wsi
        loop = asyncio.get_running_loop()
        try:
            jpeg_bytes = await asyncio.wait_for(
                loop.run_in_executor(_executor, _make_thumbnail, wsi),
                timeout=_THUMBNAIL_TIMEOUT,
            )
            return Response(
                content=jpeg_bytes,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except asyncio.TimeoutError:
            return Response(
                content=_placeholder_svg(wsi.name),
                media_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=60"},
            )

    @app.post("/slides/{slide_id}/select")
    async def select_slide(slide_id: int) -> Response:
        if slide_id < 0 or slide_id >= len(specs):
            raise HTTPException(status_code=404, detail="Slide not found")

        spec = specs[slide_id]

        # Lazily upgrade to zarr-backed WSI the first time this slide is activated
        if not spec.zarr_loaded and spec.path is not None:
            from wsidata import open_wsi as _open_wsi

            loop = asyncio.get_running_loop()
            upgraded = await loop.run_in_executor(
                _executor,
                lambda: _open_wsi(str(spec.path), store=spec.zarr_store or "auto"),
            )
            spec.wsi = upgraded
            spec.zarr_loaded = True

        state["current"] = slide_id
        wsi = spec.wsi
        dzi_info = DZIInfo.from_wsi(wsi, tile_size=tile_size, overlap=1)
        return JSONResponse({
            "id": slide_id,
            "name": wsi.name,
            "slide_width": dzi_info.slide_width,
            "slide_height": dzi_info.slide_height,
            "properties": wsi.properties.to_dict(),
        })

    # ── Shape overlays ────────────────────────────────────────────────────
    @app.get("/overlays")
    async def list_overlays() -> JSONResponse:
        """Return the current list of shape keys — no GeoJSON, no columns."""
        wsi = current_wsi()
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

    @app.get("/overlays/{name}/columns")
    async def overlay_columns(name: str) -> JSONResponse:
        """Return column metadata for a shape layer (kind, range or categories)."""
        wsi = current_wsi()
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

    @app.get("/overlays/{name}.geojson")
    async def overlay(name: str) -> Response:
        """Serialise a GeoDataFrame from wsi.shapes to GeoJSON on the fly."""
        wsi = current_wsi()
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")
        loop = asyncio.get_running_loop()
        geojson_str = await loop.run_in_executor(_executor, wsi.shapes[name].to_json)
        return Response(content=geojson_str, media_type="application/json")

    # FlatGeobuf cache keyed by (slide_index, layer_name)
    _fgb_cache: dict[tuple[int, str], bytes] = {}

    def _build_fgb(gdf) -> bytes:
        """Serialise GeoDataFrame to FlatGeobuf bytes via pyogrio."""
        from io import BytesIO

        buf = BytesIO()
        # pyogrio.write_dataframe handles FlatGeobuf via GDAL driver
        try:
            import pyogrio

            pyogrio.write_dataframe(gdf, buf, driver="FlatGeobuf")
        except Exception:
            # Fallback to geopandas built-in (also uses pyogrio/fiona)
            gdf.to_file(buf, driver="FlatGeobuf")
        return buf.getvalue()

    @app.get("/overlays/{name}.fgb")
    async def overlay_fgb(name: str) -> Response:
        """Serve shape layer as FlatGeobuf binary for fast WebGL rendering."""
        wsi = current_wsi()
        if name not in wsi.shapes:
            raise HTTPException(status_code=404, detail=f"Shape '{name}' not found in wsi.shapes")

        key = (state["current"], name)
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

    # ── Graceful shutdown: release resources ─────────────────────────────
    @app.on_event("shutdown")
    async def _cleanup() -> None:
        _log.info("Shutdown: releasing resources …")
        # Drop FGB cache
        _fgb_cache.clear()
        # Close WSI handles (best-effort)
        for i, spec in enumerate(specs):
            wsi = spec.wsi
            for attr in ("close", "_close", "release"):
                fn = getattr(wsi, attr, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception as exc:
                        _log.debug("slide %d %s() failed: %s", i, attr, exc)
        # Shutdown shared executor (wait=False so 2nd Ctrl-C not blocked)
        try:
            _executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            _log.debug("executor shutdown failed: %s", exc)
        _log.info("Shutdown complete.")

    return app
