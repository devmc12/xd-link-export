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

## Why Large Browser Viewports Matter

Long mobile designs often have:

- a viewport size such as `750 x 1526`
- a larger design size such as `750 x 2007`

If the browser viewport is too small, XD still renders the screen but the visible design area may not contain the full height. Use a large browser viewport so the entire long design can fit in specs mode.

## Why Direct JS Canvas Export Fails

The XD viewer render surface is commonly a WebGL canvas. Calling `canvas.toDataURL()` may return a black image. The reliable path is:

1. locate the visible canvas element
2. read its CSS bounding box
3. read its intrinsic `canvas.width` and `canvas.height`
4. capture the canvas region from the browser surface at the matching scale

Keep this canvas capture in memory unless the task is specifically debugging the viewer. The default export should retain only the final `1x` and `2x` artboard images, written directly into the page folder root.

## Metadata Source

Do not derive page metadata from localized visible labels in the browser UI.

Prefer this source order:

1. `window.prototypeData` embedded in the HTML response
2. HTML meta tags such as `og:title` or `twitter:title` only as a fallback for missing titles

## Ratio-Locked Crop

When the artboard has large pale areas, plain “non-white bounding box” detection can trim the bottom too early.

Use this correction:

1. detect the artboard width inside the canvas
2. read the XD design width and height from specs
3. infer the full cropped height from the design ratio

This keeps the crop aligned with the intended XD artboard size.
