---
name: xd-link-export
description: Export reusable page bundles from Adobe XD share links, especially `xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`, `.../screen/SCREEN_ID/specs/`, `.../screen/SCREEN_ID/variables/`, and `.../grid` routes. Use when Codex needs to capture all pages or selected page ranges as clean native 1x/2x artboard images through XD specs zoom, collect page-level source and capture metadata, remove viewer chrome and outer blank areas, preserve long mobile screens, and write the results under `.xd-export/` inside the current project.
---

# XD Link Export

Use this skill to turn an Adobe XD web share/specs link into reusable local artifacts for later frontend work.

## Dependencies

- Python packages are declared in `requirements.txt`
- If `playwright` is missing, run:

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
  --url "https://xd.adobe.com/view/SHARE_ID/grid"
```

By default, this exports all XD pages. Use `--pages` to select pages:

```powershell
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/grid" `
  --pages "1-3,16,25-30"
```

Accepted `--pages` forms include `1`, `1-5,4-7,19`, and `01,02,03,13-18`. Ranges are 1-based, inclusive, and de-duplicated in first-seen order. Use `--all` only when you want to make the default explicit.

By default, this exports native `1x` images only. Use `--scales "1,2"` to export both `1x` and `2x`, or `--scales "2"` to export only `2x`. Accepted scale forms are `1`, `2`, `1,2`, and `2,1`; scale values above `2` are invalid.

Page failures are always collected and the exporter continues through the remaining pages. If any selected page or scale fails, the final process exit code is non-zero and the JSON summary includes `errors`.

Use `--parallel` only when `--scales` contains both `1` and `2`. It runs separate scale workers for `1x` and `2x`; with a single scale it has no effect.

Accepted URL shapes include:

- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/variables/`
- `https://xd.adobe.com/view/SHARE_ID/grid`

The exporter reads `window.prototypeData` once, resolves selected artboards from the manifest, then captures each page through its canonical `screen/.../specs/` page.

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
- `artboard-2x.png` when `--scales` includes `2`
- `metadata.json`

## Workflow

1. Accept any XD `view/...` route that exposes `window.prototypeData`; use `--pages` for a single page, ranges, or mixed lists.
2. Open the input route first and read `window.prototypeData` directly from the HTML response instead of parsing visible browser labels.
3. If `--pages` is omitted, export all artboards; `--all` is the explicit equivalent.
4. Use the top-level `modifiedDate` and the artboards array inside `window.prototypeData` to resolve version tag, page index, page count, titles, and design dimensions.
5. Group exports under a normalized version folder such as `Sample Project - v07040010`.
6. Launch one browser for metadata with a preference for the host Chrome installation and fall back to Playwright's bundled Chromium when Chrome is unavailable.
7. Capture in scale-major order: reuse one specs page per scale worker, run all selected pages for one scale, then all selected pages for the next scale.
8. Use `scripts/capture_xd_artboard.py` for screenshot capture, not metadata extraction.
9. Navigate with `domcontentloaded`, then wait for XD canvas, zoom input, and SVG artboard rect readiness instead of sleeping for a fixed delay.
10. Read the artboard boundary from `[data-auto="svgContainer"] svg rect`, verify the canvas backing pixels are large enough for the requested scale, and capture the rect directly from the browser surface.
11. Stage requested native artboard images under `.tmp/` first, then commit them into the page folder root only after all requested scales succeed.
12. Write a single `metadata.json` file that combines page source fields and capture details.
13. Update `pages.json` only for complete page exports so failed partial captures do not become canonical output directories.

## Read These References When Needed

- Read [references/capture-rules.md](references/capture-rules.md) when the link behavior is confusing, the screen is long, or the page falls back between normal viewer and specs mode.
- Read [references/output-layout.md](references/output-layout.md) when you need to know where files are written or which output file another skill should consume.

## Notes

- Direct `canvas.toDataURL()` is not trustworthy for XD viewer captures; XD uses a WebGL render path and the result can be a black frame.
- Prefer browser-surface clipped capture of XD's artboard overlay rect.
- Keep exported artifacts in the project-local `.xd-export/` folder unless the user explicitly requests another location.
- Keep only the final requested scale images; do not persist intermediate screenshots unless the skill is explicitly being debugged.
- Do not rely on localized UI labels such as "Link updated", "Viewport size", or "Design size" for metadata extraction.
- Keep `scripts/export_xd_page_bundle.py` as the metadata and bundle orchestration entrypoint; add resource, text, and element extraction as separate scripts that consume the same XD metadata.
- Prefer `--pages "N"` over screen-id URL guessing when the user asks for page N.
- Use `--parallel` for `--scales "1,2"` only when two simultaneous scale workers are acceptable for the machine/network; it does not parallelize pages.
