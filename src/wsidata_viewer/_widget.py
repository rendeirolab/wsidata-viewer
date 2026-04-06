"""Jupyter display helper — embeds the viewer as an iframe."""
from __future__ import annotations

import atexit
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wsidata import WSIData

# key = cache_key (int or frozenset of int), value = (server, port)
_running_servers: dict = {}


class WSIViewer:
    """Wraps a running viewer URL so Jupyter renders it as an iframe.

    Returned by :func:`show_wsi`. Displays inline in JupyterLab,
    Jupyter Notebook, and VS Code notebooks via ``_repr_html_``.
    """

    def __init__(self, url: str, height: str = "600px"):
        self.url = url
        self.height = height

    def _repr_html_(self) -> str:
        return (
            f'<iframe src="{self.url}" '
            f'style="width:100%; height:{self.height}; border:none;" '
            f'allowfullscreen></iframe>'
        )

    def __repr__(self) -> str:
        return f"WSIViewer(url={self.url!r})"


def show_wsi(
    wsi_or_list,
    shapes: list[str] | None = None,
    *,
    port: int | None = None,
    host: str = "127.0.0.1",
    tile_size: int = 254,
    jpeg_quality: int = 80,
    height: str = "600px",
) -> WSIViewer:
    """Display one or more WSIData objects in an interactive viewer.

    In Jupyter, returns a :class:`WSIViewer` that renders as an inline iframe.
    Outside Jupyter, starts the server and opens a browser tab.

    Parameters
    ----------
    wsi_or_list:
        A single WSIData object or a list of WSIData objects to display.
    shapes:
        Shape keys to overlay. ``None`` = all keys in ``wsi.shapes``.
    port:
        Local server port. ``None`` auto-selects a free port.
    host:
        Hostname to bind.
    tile_size:
        DZI effective tile size in pixels.
    jpeg_quality:
        JPEG encoding quality for tile images.
    height:
        Iframe height (CSS value, Jupyter only).
    """
    from ._server import create_app
    from ._utils import find_free_port, start_server_thread

    # Normalise to list and build cache key
    if isinstance(wsi_or_list, list):
        wsi_list = wsi_or_list
        cache_key = frozenset(id(w) for w in wsi_list)
    else:
        wsi_list = [wsi_or_list]
        cache_key = id(wsi_or_list)

    if cache_key in _running_servers:
        _, _port = _running_servers[cache_key]
    else:
        app = create_app(wsi_list, tile_size=tile_size, jpeg_quality=jpeg_quality,
                         shape_keys=shapes)

        if port is None:
            port = find_free_port()

        server = start_server_thread(app, host=host, port=port)
        _running_servers[cache_key] = (server, port)
        _port = port

        atexit.register(lambda: server.__setattr__("should_exit", True))

    return WSIViewer(url=f"http://{host}:{_port}", height=height)
