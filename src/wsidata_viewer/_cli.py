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
@click.option("--workers", default=None, type=int,
              help="Parallel workers for opening slides (default: min(16, cpu*2)).")
@click.option("--eager", "eager", default=8, show_default=True,
              help="Number of slides to open eagerly at startup. The remainder "
                   "are opened on demand when the user clicks them. Set 0 to "
                   "open only slide 0.")
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
    workers: int | None,
    eager: int,
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

    # ── Open slides: hybrid eager + lazy ──────────────────────────────────
    # Slide 0: full open with zarr store (active, shapes available).
    # Slides 1..min(eager, n-1): reader-only parallel open (snappy thumbnails
    # + instant switching for the first batch).
    # Slides eager+1..n-1: NOT opened. Will be opened on demand by the server
    # via _ensure_opened() on first thumbnail/select request.
    n = len(slide_entries)

    if workers is None:
        import os
        workers = min(16, (os.cpu_count() or 4) * 2)

    eager_n = min(max(eager, 0), n - 1) if n > 1 else 0  # slides 1..eager_n
    eager_total = 1 + eager_n  # slide 0 + eager_n reader-only

    click.echo(
        f"Opening {eager_total} of {n} slide{'s' if n > 1 else ''} eagerly "
        f"(workers={workers}); remaining {n - eager_total} opened on demand …",
        err=True,
    )

    specs: list[SlideSpec] = [None] * n  # type: ignore[list-item]

    # Pre-populate ALL specs with path + name so /slides listing works without
    # opening anything. Eager ones get their .wsi filled in below.
    for i, (wsi_path, store_path) in enumerate(slide_entries):
        store = store_path if store_path is not None else fallback_zarr
        specs[i] = SlideSpec(
            wsi=None,
            path=wsi_path,
            zarr_store=store,
            zarr_loaded=False,
            name=Path(wsi_path).stem,
        )

    def _open_active(wsi_path: str, store: str):
        return open_wsi(wsi_path, store=store)

    def _open_reader_only(wsi_path: str, _store: str):
        return open_wsi(wsi_path, store=None)

    n_to_open = eager_total
    with ThreadPoolExecutor(max_workers=min(workers, max(n_to_open, 1))) as pool:
        future_to_idx = {}
        for i in range(n_to_open):
            wsi_path = slide_entries[i][0]
            store = specs[i].zarr_store or "auto"
            fn = _open_active if i == 0 else _open_reader_only
            future_to_idx[pool.submit(fn, wsi_path, store)] = i

        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            wsi_path, _ = slide_entries[i]
            try:
                wsi = future.result()
                spec = specs[i]
                spec.wsi = wsi
                spec.zarr_loaded = (i == 0)
                label = "(active, zarr loaded)" if i == 0 else "(reader-only)"
                shapes_info = ""
                if spec.zarr_loaded and spec.wsi.shapes:
                    shapes_info = f", shapes: {', '.join(spec.wsi.shapes)}"
                click.echo(f"  [{i}] {wsi_path} {label}{shapes_info}", err=True)
            except Exception as exc:
                click.echo(f"  [{i}] ERROR opening {wsi_path}: {exc}", err=True)
                raise click.ClickException(f"Failed to open slide: {wsi_path}") from exc

    if n > eager_total:
        click.echo(
            f"  [{eager_total}..{n - 1}] deferred — open on demand",
            err=True,
        )

    # ── Start server ──────────────────────────────────────────────────────
    if port is None:
        port = find_free_port()

    parsed_keys = [k.strip() for k in shape_keys.split(",")] if shape_keys else None
    app = create_app(specs, tile_size=tile_size, jpeg_quality=jpeg_quality,
                     shape_keys=parsed_keys)
    url = f"http://{host}:{port}"

    if open_browser:
        # Fire shortly after uvicorn starts binding the socket. A small delay
        # is enough — by 0.5 s uvicorn has the listener up and the browser
        # connect will be queued cleanly.
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
