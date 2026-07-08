# xd-link-export

English | [中文](README.zh.md)

`xd-link-export` is an Adobe XD link export skill. It exports XD share links into reusable screenshots and metadata.

It is mainly built for design-share-link-to-frontend, design analysis, and automated asset preparation workflows.

## Features

### Supported link types

- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/variables/`
- `https://xd.adobe.com/view/SHARE_ID/grid`

### Screenshot export

- remove viewer chrome and outer blank margins
- export native `artboard-1x.png` by default, with optional `artboard-2x.png`
- use XD specs zoom, SVG artboard rect geometry, and XD thumbnail reference validation for stable long-page capture

### Metadata export

- page-level `metadata.json`
- version-level `xd-metadata.json`
- version-level `pages.json`

### Versioned output

- group output by XD project title and version tag
- keep repeated exports for the same page without overwriting earlier runs

## Files

```text
.
├── .gitignore                                           # Ignore local output and editor cache
├── README.md                                            # Project README in English
├── README.zh.md                                         # Project README in Chinese
└── skills/
    └── xd-link-export/
        ├── SKILL.md                                     # Skill entry instructions
        ├── requirements.txt                             # Python dependencies for the exporter
        ├── agents/
        │   └── openai.yaml                              # Skill UI metadata
        ├── references/
        │   ├── capture-rules.md                         # Capture rules and metadata source notes
        │   └── output-layout.md                         # Export folder and file layout
        └── scripts/
            ├── export_xd_page_bundle.py                 # Metadata and page-bundle orchestration
            └── capture_xd_artboard.py                   # Native artboard screenshot capture
```

## Install

To use it inside a repository:

```text
.agents/
  skills/
    xd-link-export/
```

Copy or symlink `skills/xd-link-export/` into that location.

## Dependencies

- Python packages are declared in `skills/xd-link-export/requirements.txt`
- If `playwright` is missing, run:

```powershell
cd skills/xd-link-export
pip install -r requirements.txt
```

- If the host machine already has Chrome, no extra browser download is required
- If Chrome is unavailable, install Playwright's bundled Chromium:

```powershell
python -m playwright install chromium
```

## Run

```powershell
cd skills/xd-link-export
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/grid"
```

By default, all pages are exported. Select pages with one `--pages` argument:

```powershell
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/grid" `
  --pages "1-3,16,25-30"
```

`--pages` accepts forms like `1`, `1-5,4-7,19`, and `01,02,03,13-18`.

By default, the exporter writes only `1x`. Use `--scales "1,2"` for both `1x` and `2x`, or `--scales "2"` for only `2x`. Accepted forms are `1`, `2`, `1,2`, and `2,1`; values above `2` are invalid.

Page errors are always collected while the batch continues. If any page or requested scale fails, the final process exit code is non-zero and the JSON summary includes `errors`.

Use `--parallel` only with `--scales "1,2"` or `--scales "2,1"` to run separate 1x and 2x scale workers at the same time.

Capture uses `domcontentloaded` plus XD canvas/zoom/overlay readiness checks. Before writing a PNG, it compares the captured artboard against XD's own thumbnail reference so loading masks are not committed as final output. `--wait-ms` is the maximum UI readiness wait, not a fixed sleep after every navigation.

## Output

```text
.xd-export/
  PROJECT_TITLE - VERSION_TAG/
    xd-metadata.json
    pages.json
    PAGE_INDEX-SCREEN_SLUG/
      artboard-1x.png
      artboard-2x.png  # when --scales includes 2
      metadata.json
```

Page outputs are staged under `.tmp/` first and committed to the final page folder only after every requested scale succeeds and passes reference validation. If a previous page folder is incomplete or visually stale, the next successful run repairs that stable folder instead of creating a duplicate timestamped folder; timestamp suffixes are reserved for repeated complete exports.

## Related

- [skills/xd-link-export/SKILL.md](skills/xd-link-export/SKILL.md)
- [skills/xd-link-export/references/capture-rules.md](skills/xd-link-export/references/capture-rules.md)
- [skills/xd-link-export/references/output-layout.md](skills/xd-link-export/references/output-layout.md)
