# xd-link-export

[English](README.md) | 中文

`xd-link-export` 是一个 Adobe XD 链接导出 skill，用来把 XD 分享链接导出成可复用的页面截图和 metadata。

它主要服务于设计分享链接转前端、设计解析、自动化资源整理这类工作流。

## 功能

### 支持的链接类型

- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/`
- `https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/variables/`
- `https://xd.adobe.com/view/SHARE_ID/grid`

### 截图导出

- 去掉 viewer chrome 和外部空白边缘
- 导出标准化的 `artboard-1x.png` 和 `artboard-2x.png`
- 通过大视口和比例锁定裁切，稳定导出长页面

### Metadata 导出

- 页面级 `metadata.json`
- 版本级 `xd-metadata.json`
- 版本级 `pages.json`

### 版本化输出

- 按 XD 项目标题和版本号分组输出
- 同一页面重复导出时保留历史目录，不覆盖之前结果

## 文件

```text
.
├── .gitignore                                           # 忽略本地导出产物和编辑器缓存
├── README.md                                            # 英文项目说明
├── README.zh.md                                         # 中文项目说明
└── skills/
    └── xd-link-export/
        ├── SKILL.md                                     # Skill 入口说明
        ├── agents/
        │   └── openai.yaml                              # Skill UI metadata
        ├── references/
        │   ├── capture-rules.md                         # 截图规则和 metadata 来源说明
        │   └── output-layout.md                         # 导出目录和文件布局说明
        └── scripts/
            ├── export_xd_page_bundle.py                 # 主导出脚本
            └── capture/
                └── crop_xd_artboard.py                  # 画板裁切和标准化图片导出
```

## 安装

在目标仓库中这样放置：

```text
.agents/
  skills/
    xd-link-export/
```

把 `skills/xd-link-export/` 复制或软链接到这个位置即可。

## 运行

```powershell
cd skills/xd-link-export
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/screen/SCREEN_ID/specs/"
```

## 输出

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

## 相关文档

- [skills/xd-link-export/SKILL.md](skills/xd-link-export/SKILL.md)
- [skills/xd-link-export/references/capture-rules.md](skills/xd-link-export/references/capture-rules.md)
- [skills/xd-link-export/references/output-layout.md](skills/xd-link-export/references/output-layout.md)
