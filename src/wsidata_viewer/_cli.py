"""Command-line entry point."""
from __future__ import annotations

from pathlib import Path

import click


@click.command("wsidata-viewer")
@click.argument("slides", metavar="SLIDE...", nargs=-1, type=click.Path(exists=True))
@click.option("--table", "table_path", default=None, metavar="FILE",
              type=click.Path(exists=True),
              help="CSV, TSV, or Excel file with a 'wsi_path' column and optional 'store_path' column.")
@click.option("--shapes", "shape_keys", default=None, metavar="KEY1,KEY2",
              help="Comma-separated list of wsi.shapes keys to overlay (default: all).")
@click.option("--port", default=None, type=int, show_default=True,
              help="Port to listen on (default: auto-select free port).")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Hostname to bind.")
@click.option("--tile-size", default=254, show_default=True,
              help="DZI effective tile size in pixels.")
@click.option("--jpeg-quality", default=80, show_default=True,
              help="JPEG encoding quality for tile images.")
@click.option("--open/--no-open", "open_browser", default=True,
              help="Open the viewer in the default browser.")
@click.option("--store", "zarr_store", default=None, metavar="PATH",
              help="Path to the .zarr store for shape/table data (default: auto).")
@click.option("--workers", default=4, show_default=True,
              help="Number of parallel workers for opening slides.")
def main(
    slides: tuple[str, ...],
    table_path: str | None,
    shape_keys: str | None,
    port: int | None,
    host: str,
    tile_size: int,
    jpeg_quality: int,
    open_browser: bool,
    zarr_store: str | None,
    workers: int,
) -> None:
    """Launch an interactive viewer for one or more whole slide images.

    SLIDE... can be one or more file paths supported by the installed wsidata
    readers (e.g. .svs, .tif, .ndpi).

    Use --table to load slides from a CSV, TSV, or Excel file instead.
    The table must have a ``wsi_path`` column and may have an optional
    ``store_path`` column with the per-slide zarr store path.

    For multiple slides the first slide is opened with its zarr store (shapes
    available immediately).  All remaining slides are opened reader-only in
    parallel and their zarr stores are loaded lazily when first selected.
    """
    click.echo("Loading libraries …", err=True)

    import threading
    import webbrowser
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from wsidata import open_wsi

    from ._server import SlideSpec, create_app
    from ._utils import find_free_port

    # ── Collect slide entries (wsi_path, store_path|None) ────────────────
    # CLI args have no per-slide store; table rows may specify one.
    slide_entries: list[tuple[str, str | None]] = [
        (str(p), None) for p in slides
    ]

    if table_path:
        slide_entries.extend(_entries_from_table(table_path))

    if not slide_entries:
        raise click.UsageError(
            "Provide at least one SLIDE path or use --table to specify a table file."
        )

    # zarr_store CLI flag is used as the fallback when a row has no store_path.
    fallback_zarr = zarr_store if zarr_store is not None else "auto"

    # ── Open slides in parallel ───────────────────────────────────────────
    # Slide 0 (the initial active slide): full open with zarr store.
    # Slides 1..N: reader-only (store=None) — zarr loaded lazily on first select.
    n = len(slide_entries)
    click.echo(
        f"Opening {n} slide{'s' if n > 1 else ''} "
        f"({'parallel' if n > 1 else 'single'}) …",
        err=True,
    )

    results: list[SlideSpec | None] = [None] * n

    def _open_active(wsi_path: str, store: str) -> SlideSpec:
        wsi = open_wsi(wsi_path, store=store)
        return SlideSpec(wsi=wsi, path=wsi_path, zarr_store=store, zarr_loaded=True)

    def _open_reader_only(wsi_path: str, store: str) -> SlideSpec:
        wsi = open_wsi(wsi_path, store=None)
        return SlideSpec(wsi=wsi, path=wsi_path, zarr_store=store, zarr_loaded=False)

    with ThreadPoolExecutor(max_workers=min(workers, n)) as pool:
        future_to_idx = {}
        for i, (wsi_path, store_path) in enumerate(slide_entries):
            # Each entry's store: explicit per-row value, else CLI fallback
            store = store_path if store_path is not None else fallback_zarr
            fn = _open_active if i == 0 else _open_reader_only
            future_to_idx[pool.submit(fn, wsi_path, store)] = i

        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            wsi_path, _ = slide_entries[i]
            try:
                spec = future.result()
                results[i] = spec
                label = "(active, zarr loaded)" if i == 0 else "(reader-only)"
                shapes_info = ""
                if spec.zarr_loaded and spec.wsi.shapes:
                    shapes_info = f", shapes: {', '.join(spec.wsi.shapes)}"
                click.echo(f"  [{i}] {wsi_path} {label}{shapes_info}", err=True)
            except Exception as exc:
                click.echo(f"  [{i}] ERROR opening {wsi_path}: {exc}", err=True)
                raise click.ClickException(f"Failed to open slide: {wsi_path}") from exc

    specs: list[SlideSpec] = results  # type: ignore[assignment]

    # ── Start server ──────────────────────────────────────────────────────
    if port is None:
        port = find_free_port()

    parsed_keys = [k.strip() for k in shape_keys.split(",")] if shape_keys else None
    app = create_app(specs, tile_size=tile_size, jpeg_quality=jpeg_quality,
                     shape_keys=parsed_keys)
    url = f"http://{host}:{port}"

    if open_browser:
        @app.on_event("startup")
        async def _open_browser():
            threading.Timer(0.5, webbrowser.open, args=[url]).start()

    click.echo(
        f"Viewer → {url}  ({n} slide{'s' if n != 1 else ''}, Ctrl-C to stop)",
        err=True,
    )
    _run_with_graceful_shutdown(app, host=host, port=port)


def _run_with_graceful_shutdown(app, host: str, port: int) -> None:
    """Run uvicorn with escalating Ctrl-C handling.

    First SIGINT  → graceful shutdown (drain in-flight requests, run app
                    shutdown handlers — resources released).
    Second SIGINT → force exit (uvicorn aborts request loop immediately).
    Third+ SIGINT → os._exit(130), bypass interpreter cleanup.
    """
    import os
    import signal

    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    sigint_count = {"n": 0}
    original_handler = signal.getsignal(signal.SIGINT)

    def _handler(signum, frame):
        sigint_count["n"] += 1
        n = sigint_count["n"]
        if n == 1:
            click.echo(
                "\nCtrl-C: graceful shutdown … "
                "(hit Ctrl-C again to force, 3x to kill)",
                err=True,
            )
            server.should_exit = True
        elif n == 2:
            click.echo("Ctrl-C x2: forcing shutdown …", err=True)
            server.force_exit = True
        else:
            click.echo("Ctrl-C x3: killing process.", err=True)
            os._exit(130)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    # uvicorn's own signal handlers would override ours; disable them.
    server.install_signal_handlers = lambda: None  # type: ignore[assignment]

    try:
        server.run()
    finally:
        try:
            signal.signal(signal.SIGINT, original_handler)
        except Exception:
            pass


def _entries_from_table(table_path: str) -> list[tuple[str, str | None]]:
    """Read slide entries from a CSV/TSV/Excel file using pandas.

    The file must have a ``wsi_path`` column.  An optional ``store_path``
    column may specify a per-slide zarr store path.  Rows where ``wsi_path``
    is empty or the file does not exist are skipped with a warning.
    """
    import pandas as pd

    p = Path(table_path)
    suffix = p.suffix.lower()

    if suffix in (".xls", ".xlsx", ".xlsm", ".xlsb", ".odf", ".ods", ".odt"):
        df = pd.read_excel(p)
    elif suffix in (".tsv", ".txt"):
        df = pd.read_csv(p, sep="\t")
    else:
        df = pd.read_csv(p)

    if "wsi_path" not in df.columns:
        raise click.BadParameter(
            f"Table file '{table_path}' must have a 'wsi_path' column. "
            f"Found columns: {list(df.columns)}",
            param_hint="--table",
        )

    has_store = "store_path" in df.columns
    entries: list[tuple[str, str | None]] = []

    for _, row in df.iterrows():
        raw = str(row["wsi_path"]).strip()
        if not raw or raw in ("nan", "None"):
            continue
        resolved = Path(raw).expanduser()
        if not resolved.exists():
            click.echo(f"Warning: slide path not found: {raw}", err=True)
            continue
        store: str | None = None
        if has_store:
            raw_store = str(row["store_path"]).strip()
            if raw_store and raw_store not in ("nan", "None"):
                store = str(Path(raw_store).expanduser())
        entries.append((str(resolved), store))

    return entries
