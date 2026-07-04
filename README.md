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
- export normalized `artboard-1x.png` and `artboard-2x.png`
- keep long-page capture stable with a large browser viewport and ratio-locked crop

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
        ├── agents/
        │   └── openai.yaml                              # Skill UI metadata
        ├── references/
        │   ├── capture-rules.md                         # Capture rules and metadata source notes
        │   └── output-layout.md                         # Export folder and file layout
        └── scripts/
            ├── export_xd_page_bundle.py                 # Main XD page export script
            └── capture/
                └── crop_xd_artboard.py                  # Artboard crop detection and normalized image export
```

## Install

To use it inside a repository:

```text
.agents/
  skills/
    xd-link-export/
```

Copy or symlink `skills/xd-link-export/` into that location.

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
