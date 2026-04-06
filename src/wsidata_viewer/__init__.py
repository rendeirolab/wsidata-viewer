"""wsidata-viewer — interactive web viewer for wsidata whole slide images."""
from __future__ import annotations

from ._accessor import ViewerAccessor  # registers wsi.viewer on import
from ._server import SlideSpec, create_app

__all__ = ["show_wsi", "create_app", "SlideSpec", "ViewerAccessor"]


def show_wsi(wsi_or_list, shapes=None, **kwargs):
    """Display one or more WSIData objects in an interactive viewer.

    In Jupyter, returns a :class:`~wsidata_viewer._widget.WSIViewer` that
    renders as an inline iframe.  Outside Jupyter, starts a local server and
    opens a browser tab.

    Parameters
    ----------
    wsi_or_list:
        A single WSIData object or a list of WSIData objects.
    shapes:
        Shape keys to overlay. ``None`` = all keys in each slide's shapes.

    See :func:`wsidata_viewer._widget.show_wsi` for full parameter docs.
    """
    from ._widget import show_wsi as _show

    if not _is_jupyter():
        _open_browser(wsi_or_list, shapes=shapes, **kwargs)
        return None

    return _show(wsi_or_list, shapes=shapes, **kwargs)


def _is_jupyter() -> bool:
    try:
        shell = get_ipython().__class__.__name__  # type: ignore[name-defined]  # noqa: F821
        return shell == "ZMQInteractiveShell"
    except NameError:
        return False


def _open_browser(wsi_or_list, shapes=None, port=None, host="127.0.0.1",
                  tile_size=254, jpeg_quality=80, **_):
    """Fallback for non-Jupyter: start server and open browser."""
    import webbrowser

    from ._utils import find_free_port, start_server_thread

    app = create_app(wsi_or_list, tile_size=tile_size, jpeg_quality=jpeg_quality,
                     shape_keys=shapes)

    if port is None:
        port = find_free_port()

    start_server_thread(app, host=host, port=port)
    url = f"http://{host}:{port}"
    print(f"Viewer ready → {url}")
    webbrowser.open(url)
