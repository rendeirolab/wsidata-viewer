"""Deep Zoom Image (DZI) math and tile generation."""
from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from wsidata import WSIData


@dataclass
class DZIInfo:
    """Metadata describing a DZI tile source derived from a WSI."""

    slide_width: int
    slide_height: int
    tile_size: int  # effective tile size (without overlap)
    overlap: int
    format: str = "jpeg"

    @property
    def max_level(self) -> int:
        """DZI max level index (corresponds to full resolution)."""
        return math.ceil(math.log2(max(self.slide_width, self.slide_height)))

    @classmethod
    def from_wsi(cls, wsi: WSIData, tile_size: int = 254, overlap: int = 1) -> DZIInfo:
        h, w = wsi.properties.shape
        return cls(slide_width=w, slide_height=h, tile_size=tile_size, overlap=overlap)

    def descriptor_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008"'
            f' Format="{self.format}" Overlap="{self.overlap}" TileSize="{self.tile_size}">'
            f'<Size Width="{self.slide_width}" Height="{self.slide_height}"/>'
            "</Image>"
        )

    def level_dimensions(self, dzi_level: int) -> tuple[int, int]:
        """Return (width, height) of the image at this DZI level."""
        scale = 2 ** (self.max_level - dzi_level)
        return (
            max(1, math.ceil(self.slide_width / scale)),
            max(1, math.ceil(self.slide_height / scale)),
        )

    def tile_count(self, dzi_level: int) -> tuple[int, int]:
        """Return (n_cols, n_rows) tile grid at this DZI level."""
        lw, lh = self.level_dimensions(dzi_level)
        return math.ceil(lw / self.tile_size), math.ceil(lh / self.tile_size)


def get_dzi_tile(
    wsi: WSIData,
    dzi_info: DZIInfo,
    dzi_level: int,
    col: int,
    row: int,
    jpeg_quality: int = 80,
) -> bytes:
    """Read a DZI tile from the WSI and return JPEG bytes.

    x, y passed to wsi.read_region are level-0 coordinates; width/height
    are in the requested WSI pyramid level's coordinate space (openslide
    convention).
    """
    ts = dzi_info.tile_size
    overlap = dzi_info.overlap

    # Pixels per DZI pixel in level-0 space
    dz_scale = 2 ** (dzi_info.max_level - dzi_level)

    # Tile bounds in DZI-level coordinates (inclusive of overlap pixels)
    lw, lh = dzi_info.level_dimensions(dzi_level)
    x0 = col * ts - (0 if col == 0 else overlap)
    y0 = row * ts - (0 if row == 0 else overlap)
    x1 = min((col + 1) * ts + overlap, lw)
    y1 = min((row + 1) * ts + overlap, lh)
    tile_w = x1 - x0
    tile_h = y1 - y0

    # Convert tile origin to level-0 pixel coordinates
    l0_x = int(x0 * dz_scale)
    l0_y = int(y0 * dz_scale)

    # Choose the best WSI pyramid level whose downsample ≤ dz_scale
    level_downsamples = wsi.properties.level_downsample
    wsi_level = 0
    for i, ds in enumerate(level_downsamples):
        if ds <= dz_scale:
            wsi_level = i

    # Width/height in the chosen WSI level's pixel space
    wsi_ds = level_downsamples[wsi_level]
    read_w = max(1, round(tile_w * dz_scale / wsi_ds))
    read_h = max(1, round(tile_h * dz_scale / wsi_ds))

    region = wsi.read_region(l0_x, l0_y, read_w, read_h, level=wsi_level)

    img = Image.fromarray(region)
    if img.size != (tile_w, tile_h):
        img = img.resize((tile_w, tile_h), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    return buf.getvalue()
