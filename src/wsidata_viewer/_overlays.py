"""Convert wsi.shapes GeoDataFrames to GeoJSON for the frontend."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wsidata import WSIData


def build_overlays(
    wsi: WSIData,
    shape_keys: list[str] | None = None,
) -> dict[str, dict]:
    """Return a dict mapping shape key → GeoJSON FeatureCollection dict.

    Parameters
    ----------
    wsi:
        The WSIData object whose ``shapes`` dict is the source.
    shape_keys:
        Which keys to include. ``None`` means all keys in ``wsi.shapes``.
    """
    keys = shape_keys if shape_keys is not None else list(wsi.shapes.keys())
    return {
        key: json.loads(wsi.shapes[key].to_json())
        for key in keys
        if key in wsi.shapes
    }
