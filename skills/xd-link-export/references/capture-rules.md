# Capture Rules

## Preferred Input

Accept these URL shapes:

1. `.../screen/SCREEN_ID/specs/`
2. `.../screen/SCREEN_ID/`
3. `.../screen/SCREEN_ID/variables/`
4. `.../grid`
5. generic `.../view/.../`

Direct `screen/.../specs/` links are the most stable for screen-specific exports.
If the input route does not include a `screenId`, resolve metadata from that route first and then capture the first artboard through its canonical `screen/.../specs/` URL.

## Folder Naming

Read the project title, modified date, and artboards array from `window.prototypeData` in the HTML response.

Use them as the top-level version folder:

- `Sample Project - v07040010`

Then read the current page order from the artboards array index, for example page `18` out of `30`.

Use the current page index as the output folder prefix:

- `07-Sample-Mobile-Account-Screen`

Convert the top-level `window.prototypeData.modifiedDate` into a stable `vMMDDHHMM` tag. If the page folder already exists inside the same version folder, append a timestamp suffix instead of overwriting the earlier export.

## Why Specs Zoom Matters

Long mobile designs often have:

- a viewport size such as `750 x 1526`
- a larger design size such as `750 x 2007`

Use XD's own specs zoom control as the scale source:

- write `100` into `[data-auto="zoomInputBox"]` for `1x`
- write `200` into `[data-auto="zoomInputBox"]` for `2x`

Then wait until `[data-auto="svgContainer"] svg rect` has the expected CSS width:

- `designWidth` at `1x`
- `designWidth * 2` at `2x`

The browser viewport should be large enough for the requested zoom, but not blindly maximized. Very large viewports can reduce the canvas backing-pixel ratio and lower capture fidelity.

The capture implementation lives in `scripts/capture_xd_artboard.py`. The page bundle entrypoint should call it after metadata has resolved the canonical specs URL and artboard design size.

## Why Direct JS Canvas Export Fails

The XD viewer render surface is commonly a WebGL canvas. Calling `canvas.toDataURL()` may return a black image. The reliable path is:

1. locate the visible canvas element
2. read the artboard boundary from `[data-auto="svgContainer"] svg rect`
3. verify the selected rect is fully inside the canvas bounds
4. compare the projected canvas backing pixels against the requested output size
5. hide the SVG overlay stroke
6. capture the artboard rect from the browser surface

The default export should retain only the final `1x` and `2x` artboard images, written directly into the page folder root.

## Metadata Source

Do not derive page metadata from localized visible labels in the browser UI.

Prefer this source order:

1. `window.prototypeData` embedded in the HTML response
2. HTML meta tags such as `og:title` or `twitter:title` only as a fallback for missing titles

## Native Scale Validation

Do not infer artboard bounds from pixel color. White, pale, or empty designs can make content-based bounding boxes trim the artboard incorrectly.

For each requested scale, validate the raw source pixels before writing the final PNG:

1. compute `targetWidth = designWidth * scale`
2. compute `targetHeight = designHeight * scale`
3. compute `scaleX = canvas.width / canvasCssWidth`
4. compute `scaleY = canvas.height / canvasCssHeight`
5. compute the selected rect's projected raw width and height
6. require projected raw width and height to be at least the target output size

If this check fails, try another viewport. Do not resize an undersized capture and call it `2x`.
