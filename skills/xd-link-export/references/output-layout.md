# Output Layout

Default export root:

```text
.xd-export/
```

Each version creates a subfolder:

```text
.xd-export/PROJECT_TITLE - VERSION_TAG/PAGE_INDEX-SCREEN_SLUG/
```

Version-level files:

```text
.xd-export/PROJECT_TITLE - VERSION_TAG/
  xd-metadata.json
  pages.json
```

Use the top-level folder to separate different XD share revisions of the same project.

Preferred version tag format:

```text
vMMDDHHMM
```

Example:

```text
.xd-export/Sample Project - v07040010/07-Sample-Mobile-Account-Screen/
```

If the same complete page is exported again inside the same project-version folder, append a timestamp suffix to avoid overwriting the earlier run. If the existing stable page folder is incomplete, repair that folder on the next successful run instead of creating a duplicate timestamped folder.

Current bundle layout:

```text
xd-metadata.json
pages.json
07-Sample-Mobile-Account-Screen/
  artboard-1x.png
  artboard-2x.png  # when --scales includes 2
  metadata.json
```

Page folder layout:

```text
artboard-1x.png
artboard-2x.png  # when --scales includes 2
metadata.json
```

During capture, page outputs are first staged under `.tmp/`. Move the staged folder into the final page folder only after all requested scales, reference validation, and `metadata.json` are complete. Failed partial captures may leave `.tmp/.../capture-errors.json` for debugging, but they should not update `pages.json`.

Recommended downstream consumption:

- frontend or AI visual analysis: `artboard-2x.png` when present
- exact design-size image: `artboard-1x.png`
- page specs plus capture details: `metadata.json`
- raw XD response metadata snapshot: `xd-metadata.json`
- version-level page index with latest export pointers and export history: `pages.json`

File roles:

- `metadata.json`: merged page source plus capture details, including canonical screen URL, project title, screen title, screen index, viewport size, design size, XD zoom scale, selected SVG artboard rect, canvas bounds, projected raw size, output directory, and emitted file paths
- `xd-metadata.json`: raw `window.prototypeData` object extracted from the HTML response for the current XD share version
- `pages.json`: project-level page index. The `project.url` field points to the XD grid route. Each page entry stores its canonical screen URL, source fields, the latest exported page directory, and an `exports` history of directories so repeated exports of the same screen are preserved without duplicating per-file paths

Script roles:

- `scripts/export_xd_page_bundle.py`: metadata and page-bundle orchestration entrypoint
- `scripts/capture_xd_artboard.py`: native artboard screenshot capture using XD zoom and SVG rect geometry
