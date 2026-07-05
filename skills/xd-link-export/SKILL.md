---
name: xd-link-export
description: Export a reusable page bundle from Adobe XD share links, especially `xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`, `.../screen/SCREEN_ID/specs/`, `.../screen/SCREEN_ID/variables/`, and `.../grid` routes. Use when Codex needs to capture clean 1x and 2x artboard images, collect page-level source and capture metadata, remove viewer chrome and outer blank areas, preserve long mobile screens by using a large browser viewport, and write the results under `.xd-export/` inside the current project.
---

# XD Link Export

Use this skill to turn an Adobe XD web share/specs link into reusable local artifacts for later frontend work.

## Dependencies

- Python packages are declared in `requirements.txt`
- If `playwright` or `Pillow` is missing, run:

```powershell
pip install -r requirements.txt
```

- If the host machine already has Chrome, the exporter uses it directly
- If Chrome is unavailable, install Playwright's bundled Chromium:

```powershell
python -m playwright install chromium
```

## Quick Start

Run the exporter first:

```powershell
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/"
```

Accepted URL shapes include:

- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/variables/`
- `https://xd.adobe.com/view/SHARE_ID/grid`

If the input route does not contain a `screenId`, the exporter resolves metadata from that route and then captures the first artboard through its canonical `screen/.../specs/` page.

This writes a bundle to:

```text
.xd-export/PROJECT_TITLE - VERSION_TAG/PAGE_INDEX-SCREEN_SLUG/
```

It also writes version-level XD metadata to:

```text
.xd-export/PROJECT_TITLE - VERSION_TAG/xd-metadata.json
```

And a version-level page index to:

```text
.xd-export/PROJECT_TITLE - VERSION_TAG/pages.json
```

The bundle contains:

- `artboard-1x.png`
- `artboard-2x.png`
- `metadata.json`

## Workflow

1. Accept any XD `view/...` route that exposes `window.prototypeData`, but prefer a direct `screen/.../specs/` URL whenever possible.
2. Open the link with a large browser viewport so tall mobile designs can fit without losing the bottom.
3. Read `window.prototypeData` directly from the HTML response instead of parsing visible browser labels.
4. Use the top-level `modifiedDate` and the artboards array inside `window.prototypeData` to resolve version tag, page index, page count, titles, and design dimensions.
5. Group exports under a normalized version folder such as `Sample Project - v07040010`.
6. Launch the browser with a preference for the host Chrome installation and fall back to Playwright's bundled Chromium when Chrome is unavailable.
7. If the input route is not already `screen/.../specs/`, resolve the target page first and then capture from its canonical specs route.
8. Capture the render canvas from the browser surface in memory and lock the crop height to the XD design ratio.
9. Export normalized `1x` and `2x` artboard images directly into the page folder root.
10. Write a single `metadata.json` file that combines page source fields and capture details.
11. Update `pages.json` so each screen keeps its latest export directory and a history of repeated exports.

## Read These References When Needed

- Read [references/capture-rules.md](references/capture-rules.md) when the link behavior is confusing, the screen is long, or the page falls back between normal viewer and specs mode.
- Read [references/output-layout.md](references/output-layout.md) when you need to know where files are written or which output file another skill should consume.

## Notes

- Direct `canvas.toDataURL()` is not trustworthy for XD viewer captures; XD uses a WebGL render path and the result can be a black frame.
- Prefer browser-surface clipped capture of the canvas element.
- Keep exported artifacts in the project-local `.xd-export/` folder unless the user explicitly requests another location.
- Keep only the final `1x` and `2x` images by default; do not persist intermediate screenshots unless the skill is explicitly being debugged.
- Do not rely on localized UI labels such as "Link updated", "Viewport size", or "Design size" for metadata extraction.
- Treat the current skill scope as capture-only; add future resource, text, and element workflows as separate capabilities rather than overloading the capture entrypoint.
