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
- export native `artboard-1x.png` and `artboard-2x.png`
- use XD specs zoom plus SVG artboard rect geometry for stable long-page capture

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
  --url "https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/"
```

## Output

```text
.xd-export/
  PROJECT_TITLE - VERSION_TAG/
    xd-metadata.json
    pages.json
    PAGE_INDEX-SCREEN_SLUG/
      artboard-1x.png
      artboard-2x.png
      metadata.json
```

## Related

- [skills/xd-link-export/SKILL.md](skills/xd-link-export/SKILL.md)
- [skills/xd-link-export/references/capture-rules.md](skills/xd-link-export/references/capture-rules.md)
- [skills/xd-link-export/references/output-layout.md](skills/xd-link-export/references/output-layout.md)
