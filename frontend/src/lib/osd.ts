/**
 * OpenSeadragon init + tiny pub-sub. Owns the imperative `viewer.open(...)`
 * lifecycle. Svelte components treat the OSD-mounted div as an uncontrolled
 * escape hatch — no vdom touches inside #osd.
 */

import OpenSeadragon from "openseadragon";

export type OSDEventKind = "update-viewport" | "open" | "zoom" | "pan" | "canvas-click";

export interface OSDHandle {
  viewer: OpenSeadragon.Viewer;
  /** Replace the tile source with the given DZI URL. */
  setTileSource(dziUrl: string): void;
  /** Imperatively zoom by a factor about the current center. */
  zoomBy(factor: number): void;
  goHome(): void;
  /** Convert an image-space (x,y) to viewer-element-space [px, py]. */
  imgPxToElement(x: number, y: number): [number, number];
  /** Current viewport bbox in image coords [minX,minY,maxX,maxY]. */
  viewportImageBbox(): [number, number, number, number] | null;
  /** Screen-CSS px per image-px at the current zoom. */
  screenPxPerImagePx(): number;
  dispose(): void;
}

export function initOSD(opts: {
  element: HTMLElement;
  tileSource: string;
}): OSDHandle {
  const viewer = OpenSeadragon({
    element: opts.element,
    tileSources: opts.tileSource,
    showNavigationControl: false,
    showNavigator: false,
    minZoomLevel: 0.2,
    maxZoomLevel: 40,
    visibilityRatio: 0.5,
    constrainDuringPan: false,
    defaultZoomLevel: 0,
    animationTime: 0.25,
    blendTime: 0.1,
    // Disable click-to-zoom — conflicts with tooltip / hit-test on click.
    // Keep drag/pinch/wheel/dblclick intact.
    gestureSettingsMouse:   { clickToZoom: false, dblClickToZoom: true },
    gestureSettingsTouch:   { clickToZoom: false, dblClickToZoom: true },
    gestureSettingsPen:     { clickToZoom: false, dblClickToZoom: true },
    gestureSettingsUnknown: { clickToZoom: false, dblClickToZoom: true },
  });
  // CSS background on the container itself — OSD types don't expose `background`.
  opts.element.style.background = "#0d0d0d";

  const setTileSource = (dziUrl: string) => {
    viewer.open(dziUrl);
  };

  const zoomBy = (factor: number) => {
    viewer.viewport.zoomBy(factor, viewer.viewport.getCenter());
    viewer.viewport.applyConstraints();
  };

  const goHome = () => viewer.viewport.goHome(true);

  const imgPxToElement = (x: number, y: number): [number, number] => {
    const vpPt = viewer.viewport.imageToViewportCoordinates(
      new OpenSeadragon.Point(x, y),
    );
    const elPt = viewer.viewport.viewportToViewerElementCoordinates(vpPt);
    return [elPt.x, elPt.y];
  };

  const viewportImageBbox = (): [number, number, number, number] | null => {
    if (!viewer.viewport) return null;
    const b = viewer.viewport.getBounds();
    const tl = viewer.viewport.viewportToImageCoordinates(
      new OpenSeadragon.Point(b.x, b.y),
    );
    const br = viewer.viewport.viewportToImageCoordinates(
      new OpenSeadragon.Point(b.x + b.width, b.y + b.height),
    );
    return [
      Math.min(tl.x, br.x),
      Math.min(tl.y, br.y),
      Math.max(tl.x, br.x),
      Math.max(tl.y, br.y),
    ];
  };

  const screenPxPerImagePx = (): number => {
    const [x0] = imgPxToElement(0, 0);
    const [x1] = imgPxToElement(1000, 0);
    return Math.abs(x1 - x0) / 1000;
  };

  return {
    viewer,
    setTileSource,
    zoomBy,
    goHome,
    imgPxToElement,
    viewportImageBbox,
    screenPxPerImagePx,
    dispose() {
      viewer.destroy();
    },
  };
}

// Zoom slider helpers — log-scale mapping between slider [0..1] and zoom.
export const ZOOM_MIN = 0.2;
export const ZOOM_MAX = 40;
export function zoomToSlider(z: number): number {
  return (Math.log(z) - Math.log(ZOOM_MIN)) / (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN));
}
export function sliderToZoom(v: number): number {
  return Math.exp(Math.log(ZOOM_MIN) + v * (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN)));
}
