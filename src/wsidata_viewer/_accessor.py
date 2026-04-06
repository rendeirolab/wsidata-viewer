"""WSIData .viewer accessor — register with ``import wsidata_viewer``."""
from __future__ import annotations

from wsidata.accessors import register_wsidata_accessor


@register_wsidata_accessor("viewer")
class ViewerAccessor:
    """Interactive viewer accessor for WSIData objects.

    Accessed via ``wsi.viewer``.  Automatically registered when
    ``wsidata_viewer`` is imported.

    Examples
    --------
    .. code-block:: python

        import wsidata_viewer          # registers the accessor
        from wsidata import open_wsi

        wsi = open_wsi("slide.svs")
        wsi.viewer.show()              # opens viewer (Jupyter iframe or browser)
    """

    def __init__(self, wsi) -> None:
        self._wsi = wsi

    def show(self, shapes: list[str] | None = None, **kwargs):
        """Open an interactive viewer for this slide.

        In Jupyter returns a :class:`~wsidata_viewer._widget.WSIViewer` iframe.
        Outside Jupyter opens a browser tab.

        Parameters
        ----------
        shapes:
            Shape keys to overlay.  ``None`` = all available shapes.
        **kwargs:
            Forwarded to :func:`~wsidata_viewer.show_wsi`
            (``port``, ``host``, ``tile_size``, ``jpeg_quality``, ``height``).
        """
        from . import show_wsi
        return show_wsi(self._wsi, shapes=shapes, **kwargs)

    def app(self, shapes: list[str] | None = None, **kwargs):
        """Return a FastAPI app for this slide without starting a server.

        Useful for embedding in existing ASGI applications or for testing.

        Parameters
        ----------
        shapes:
            Shape keys to expose.  ``None`` = all available shapes.
        **kwargs:
            Forwarded to :func:`~wsidata_viewer.create_app`
            (``tile_size``, ``jpeg_quality``).
        """
        from ._server import create_app
        return create_app(self._wsi, shape_keys=shapes, **kwargs)
