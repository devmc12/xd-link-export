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
- 默认导出原生 `artboard-1x.png`，可选导出 `artboard-2x.png`
- 通过 XD specs zoom 和 SVG 画板 rect 几何，稳定导出长页面

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
        ├── requirements.txt                             # Python 依赖声明
        ├── agents/
        │   └── openai.yaml                              # Skill UI metadata
        ├── references/
        │   ├── capture-rules.md                         # 截图规则和 metadata 来源说明
        │   └── output-layout.md                         # 导出目录和文件布局说明
        └── scripts/
            ├── export_xd_page_bundle.py                 # Metadata 和页面 bundle 编排入口
            └── capture_xd_artboard.py                   # 原生画板截图脚本
```

## 安装

在目标仓库中这样放置：

```text
.agents/
  skills/
    xd-link-export/
```

把 `skills/xd-link-export/` 复制或软链接到这个位置即可。

## 依赖

- Python 依赖声明在 `skills/xd-link-export/requirements.txt` 里
- 如果缺少 `playwright`，执行：

```powershell
cd skills/xd-link-export
pip install -r requirements.txt
```

- 如果宿主机已经安装 Chrome，脚本会直接使用它
- 如果没有 Chrome，请安装 Playwright 自带的 Chromium：

```powershell
python -m playwright install chromium
```

## 运行

```powershell
cd skills/xd-link-export
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/grid"
```

默认导出全部页面。用一个 `--pages` 参数选择页码：

```powershell
python scripts/export_xd_page_bundle.py `
  --url "https://xd.adobe.com/view/SHARE_ID/grid" `
  --pages "1-3,16,25-30"
```

`--pages` 支持 `1`、`1-5,4-7,19`、`01,02,03,13-18`。

默认只导出 `1x`。用 `--scales "1,2"` 同时导出 `1x` 和 `2x`，或用 `--scales "2"` 只导出 `2x`。`--scales` 只接受 `1`、`2`、`1,2`、`2,1`，大于 `2` 的值无效。

批量导出时，页面或 scale 失败会被收集到 summary/errors，流程继续跑后续页面。只要有任何失败，最终进程退出码就是非 0，避免误判为全成功。

只有在 `--scales "1,2"` 或 `--scales "2,1"` 时才使用 `--parallel`，它会让 1x 和 2x 两个 scale worker 同时运行。

截图流程使用 `domcontentloaded` 加 XD canvas、zoom、overlay 的就绪检查。`--wait-ms` 是最大 UI 就绪等待时间，不是每次导航后的固定 sleep。

## 输出

```text
.xd-export/
  PROJECT_TITLE - VERSION_TAG/
    xd-metadata.json
    pages.json
    PAGE_INDEX-SCREEN_SLUG/
      artboard-1x.png
      artboard-2x.png  # 当 --scales 包含 2 时生成
      metadata.json
```

页面产物会先写入 `.tmp/`，只有所有请求的 scale 都成功后才提交到正式页面目录。如果之前的页面目录是不完整的，下一次成功运行会修复这个稳定目录，不会额外生成时间戳重复目录；时间戳后缀只用于重复导出已经完整成功的页面。

## 相关文档

- [skills/xd-link-export/SKILL.md](skills/xd-link-export/SKILL.md)
- [skills/xd-link-export/references/capture-rules.md](skills/xd-link-export/references/capture-rules.md)
- [skills/xd-link-export/references/output-layout.md](skills/xd-link-export/references/output-layout.md)
