# Capture Rules

## Preferred Input

Accept these URL shapes:

1. `.../screen/SCREEN_ID/specs/`
2. `.../screen/SCREEN_ID/`
3. `.../screen/SCREEN_ID/variables/`
4. `.../grid`
5. generic `.../view/.../`

Direct `screen/.../specs/` links are the most stable for screen-specific exports.
Read metadata from any accepted route first, then capture selected artboards through their canonical `screen/.../specs/` URLs.

Page selection:

- Omit `--pages` to export all artboards. `--all` is only the explicit form of the default.
- Use `--pages "1"` for one page.
- Use `--pages "1-5,4-7,19"` for mixed ranges and single pages.
- Use `--pages "01,02,03,13-18"` when page numbers have leading zeros.
- De-duplicate overlaps while preserving first-seen order.
- Page failures are always collected while the batch continues.
- Return a non-zero process exit code if any selected page or requested scale fails.

Scale selection:

- Omit `--scales` to export `1x` only.
- Use `--scales "1,2"` or `--scales "2,1"` to export both native scales.
- Use `--scales "2"` to export only `2x`.
- Reject empty values, non-numeric values, `0`, and values above `2`.
- Use `--parallel` only when both `1` and `2` are requested; it runs scale workers in parallel, not page workers.

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

Capture in scale-major order. For example, a `1,2` request should run all selected pages for one scale, then all selected pages for the other scale, instead of doing `page 1 1x -> page 1 2x -> page 2 1x -> page 2 2x`.

Reuse one browser context and one specs page per scale worker. Navigate that page between selected artboards, but do not switch between `100%` and `200%` inside the same loaded page. This avoids cross-scale XD zoom state pollution while avoiding full browser startup per page.

Wait for `domcontentloaded`, then wait for the visible canvas, zoom input, SVG overlay, and a nonzero artboard rect. Treat `--wait-ms` as the maximum readiness wait, not as a fixed post-navigation sleep.

After geometry and native-pixel checks pass, compare a low-resolution artboard preview with XD's own thumbnail component from `window.prototypeData`. Retry while the preview differs too much from the thumbnail reference. This catches blank frames and loading masks, including cases where no spinner is visible. When reusing an existing page directory, validate the existing final PNG against the same reference before deciding whether to create a timestamped duplicate or repair the stable folder.

## Why Direct JS Canvas Export Fails

The XD viewer render surface is commonly a WebGL canvas. Calling `canvas.toDataURL()` may return a black image. The reliable path is:

1. locate the visible canvas element
2. read the artboard boundary from `[data-auto="svgContainer"] svg rect`
3. verify the selected rect is fully inside the canvas bounds
4. compare the projected canvas backing pixels against the requested output size
5. hide the SVG overlay stroke
6. capture the artboard rect from the browser surface
7. validate the captured frame against the XD thumbnail reference before writing it as final output

The default export should retain only the final requested scale images, written directly into the page folder root.

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
