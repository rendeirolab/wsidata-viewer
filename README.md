# wsidata-viewer

Interactive web viewer for [wsidata](https://github.com/rendeirolab/wsidata) whole slide images.
Renders multi-resolution WSI files with [OpenSeadragon](https://openseadragon.github.io/) and overlays any shape layers stored in the `WSIData` object (tiles, tissue contours, annotations, etc.).

Works as a **CLI**, as an **inline Jupyter widget**, or via the `wsi.viewer` accessor.

Useful if you want to visualize your slide on a remote machine.

> Disclaimer: This is a vibe coding project.

---

## Installation

```bash
# Latest from GitHub
pip install git+https://github.com/rendeirolab/wsidata-viewer

# Or from PyPI (once released)
pip install wsidata-viewer
```

---

## Quick start

### Command line

```bash
# Single slide
wsidata-viewer slide.svs

# Multiple slides (thumbnail panel shown on the left)
wsidata-viewer slide1.svs slide2.svs slide3.ndpi

# Load slides from a table file
wsidata-viewer --table slides.csv
```

The viewer opens automatically in your default browser. Press `Ctrl-C` to stop the server.

### Jupyter / Python API

```python
from wsidata import open_wsi
import wsidata_viewer          # registers the wsi.viewer accessor

wsi = open_wsi("slide.svs")

# via accessor (recommended in Jupyter)
wsi.viewer.show()

# or directly
from wsidata_viewer import show_wsi
show_wsi(wsi)
```

In a Jupyter notebook this returns a widget that renders inline. Outside Jupyter it starts a local server and opens a browser tab.

---

## CLI reference

```
wsidata-viewer [OPTIONS] SLIDE...
```

| Option | Default | Description |
|---|---|---|
| `--table FILE` | — | CSV, TSV, or Excel file listing slides (see below) |
| `--shapes KEY1,KEY2` | all | Shape layer keys to overlay (comma-separated) |
| `--port INTEGER` | auto | Port for the local server |
| `--host TEXT` | `127.0.0.1` | Hostname to bind |
| `--tile-size INTEGER` | `254` | DZI tile size in pixels |
| `--jpeg-quality INTEGER` | `80` | JPEG quality for tile images |
| `--open / --no-open` | `--open` | Auto-open browser on start |
| `--store PATH` | auto | Fallback `.zarr` store path (default: auto-discover) |
| `--workers INTEGER` | `4` | Parallel workers for opening slides |

**Examples**

```bash
# Show only tissue contours on a fixed port
wsidata-viewer slide.svs --shapes tissues --port 8080

# Headless server (no browser), custom quality
wsidata-viewer slide.svs --no-open --jpeg-quality 90

# Provide an explicit zarr store
wsidata-viewer slide.svs --store slide.zarr

# Open many slides in parallel with more workers
wsidata-viewer *.svs --workers 8
```

### Table file format

Use `--table` to load slides from a CSV, TSV, or Excel file. The file must have a `wsi_path` column and may have an optional `store_path` column for per-slide zarr stores.

```
wsi_path,store_path
/data/slide1.svs,/zarr/slide1.zarr
/data/slide2.svs,
/data/slide3.ndpi,/other/location/slide3.zarr
```

Rows with an empty `store_path` fall back to `--store` (or auto-discovery).

---

## Python API reference

### `wsi.viewer.show(**kwargs)`

Open an interactive viewer for this slide. Automatically registered on `WSIData` when `wsidata_viewer` is imported.

```python
import wsidata_viewer
from wsidata import open_wsi

wsi = open_wsi("slide.svs")
wsi.viewer.show()                                  # all shapes
wsi.viewer.show(shapes=["tissues"], height="800px") # selected shapes, taller widget
```

### `wsi.viewer.app(**kwargs)`

Return the raw FastAPI application without starting a server. Useful for custom deployments or testing.

```python
app = wsi.viewer.app()
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

### `show_wsi(wsi_or_list, shapes=None, **kwargs)`

Display one or more `WSIData` objects. Accepts a single object or a list (shows multi-slide thumbnail panel).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `wsi_or_list` | `WSIData \| list[WSIData]` | — | Slide(s) to display |
| `shapes` | `list[str] \| None` | `None` | Shape keys to overlay; `None` = all |
| `port` | `int \| None` | auto | Local server port |
| `host` | `str` | `"127.0.0.1"` | Hostname to bind |
| `tile_size` | `int` | `254` | DZI tile size |
| `jpeg_quality` | `int` | `80` | JPEG tile quality |
| `height` | `str` | `"600px"` | Widget height (Jupyter only, CSS value) |

### `create_app(wsi_or_list, tile_size=254, jpeg_quality=80, shape_keys=None)`

Build and return the raw FastAPI application.

```python
from wsidata_viewer import create_app
import uvicorn

app = create_app([wsi1, wsi2], shape_keys=["tissues"])
uvicorn.run(app, host="0.0.0.0", port=8080)
```

---

## Server endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Viewer HTML page |
| `GET /slide.dzi` | DZI descriptor XML for the active slide |
| `GET /slide_files/{level}/{col}_{row}.jpeg` | DZI tile image |
| `GET /slide/properties` | Active slide metadata as JSON |
| `GET /slides` | List of all loaded slides (id, name, dimensions, active flag) |
| `GET /slides/{id}/thumbnail.jpeg` | Thumbnail JPEG for slide `id` |
| `POST /slides/{id}/select` | Switch the active slide |
| `GET /overlays` | List of shape layer names and assigned colors |
| `GET /overlays/{name}.geojson` | GeoJSON for a shape layer (fetched lazily) |
| `GET /overlays/{name}/columns` | Column metadata for a shape layer (kind, range/categories) |

---

## Viewer UI

- **Pan / zoom** — drag and scroll (or pinch on touch); zoom slider in the controls panel
- **Scale bar** — live physical scale (µm / mm) in the bottom-left, updates as you zoom
- **Layer sidebar** — toggle shape overlays on/off; shapes are fetched lazily on first enable
  - Per-layer style: stroke color, stroke width, fill
  - **Color by column** — color features by any GeoDataFrame column; categorical columns get a qualitative palette, numeric columns get a viridis gradient with a legend
- **Slide info panel** — dimensions, MPP, magnification, pyramid level count; updates on slide switch
- **Viewport info** — live zoom level and cursor coordinates in level-0 pixels
- **Multi-slide panel** — left-side thumbnail strip when multiple slides are loaded; thumbnails load lazily as you scroll; switching slides lazy-loads the zarr store for that slide

---

## How it works

```
WSIData
  │
  ├─ reader.read_region(x, y, w, h, level)   ← tile requests
  │     served as Deep Zoom Image (DZI) tiles via FastAPI
  │     reads from the optimal pyramid level to minimise data transfer
  │
  └─ shapes["key"]  GeoDataFrame             ← overlay data
        serialised to GeoJSON on first user request
              │
              ▼
        OpenSeadragon (tile rendering)
          + Canvas2D overlay (shapes, redrawn on every viewport update)
```

- Blocking `read_region` calls are offloaded to a thread pool so concurrent tile requests don't stall the async server.
- For multi-slide sessions the non-active slides are opened reader-only (no zarr) in parallel at startup. The zarr store for each slide is loaded lazily the first time that slide is selected.
- In Jupyter, the FastAPI server starts once per `WSIData` identity in a daemon thread and is reused across multiple `show_wsi()` calls.
