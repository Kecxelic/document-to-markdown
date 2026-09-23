# document-to-markdown

[English](#english) | [中文](#中文)

An agent skill that converts **PDF / EPUB / DOCX** into clean, navigable Markdown — one entry point, per-format adapters, and an agent-review pass after the tool-based first conversion.

## English

### What it does

| Format | Converter | Outline handling |
|--------|-----------|------------------|
| PDF  | MinerU VLM (OCR) | chapter detection, numbering-level repair, page-residue cleanup |
| EPUB | Pandoc | semantic headings; auto `single-title` vs `chapter-h1` policy |
| DOCX | Pandoc + agent review | Word headings kept; bold / numbered pseudo-headings judged per document |
| DOC  | refused with guidance | save as DOCX with WPS or another office suite first |

- Unified entry point `scripts/convert.py <file-or-folder>`: recursive batch discovery, one failed file does not block the rest of the batch.
- Output layout: auditable `temp/` intermediates, and a final `<book>/` directory containing `images/`, the Markdown, and the archived source file.
- Heading policy `auto`: one title H1 for articles / reports / papers, parallel chapter H1s for books — never flattening past H6 or merging distinct levels just to pass a check.
- Images: extracted and link-verified; EMF/WMF from DOCX rasterized to PNG.
- Optional `parallel-repair` mode (content + formatting repair through parallel agents) — only fires when the request literally contains `并行多智能体修复` or `[parallel-repair]`.

### Install

```bash
git clone https://github.com/Kecxelic/document-to-markdown.git ~/.agents/skills/document-to-markdown
```

Adjust the target path to your host's skill directory (e.g. `~/.claude/skills/`, `~/.agents/skills/`).

### Requirements

- Python 3.10+ (developed and tested on 3.12)
- [Pandoc](https://pandoc.org) for EPUB and DOCX
- PDF only: a free [MinerU](https://mineru.net) API token in `~/.mineru/mineru.conf`:

  ```text
  mineru_token=<your_token>
  ```

  Create one at <https://mineru.net/apiManage/token>.

### Usage

Just ask your agent in natural language ("convert this PDF to Markdown"), or invoke the skill explicitly:

```text
$document-to-markdown <file-or-folder>
```

The converter script also runs standalone:

```bash
python ~/.agents/skills/document-to-markdown/scripts/convert.py "paper.pdf"
```

### Tests

```bash
python -m unittest discover -s ~/.agents/skills/document-to-markdown/tests -v
```

### Limitations

PDF quality depends on MinerU and scan/OCR quality; complex EPUB CSS, fixed layouts and DRM, and complex DOCX layouts (text boxes, tracked changes) are not guaranteed; DRM removal is not supported. See [SKILL.md](SKILL.md) for the full behavioral contract.

## 中文

一个把 **PDF / EPUB / DOCX** 统一转换为干净、可导航 Markdown 的 agent skill：单一入口，内部按格式分发适配器，工具初转之后再由 agent 审查修复。

### 功能

- **PDF**：MinerU VLM（OCR），章节识别、编号层级修复、页面残留清理
- **EPUB**：Pandoc，语义标题；自动在「唯一书名 H1」与「并列章级 H1」之间决策
- **DOCX**：Pandoc + agent 审查，保留 Word 标题，粗体 / 编号伪标题按具体文档判断；EMF/WMF 自动转 PNG
- **DOC**：拒绝直接转换，提示先用 WPS 或其他办公软件另存为 DOCX
- 统一入口 `scripts/convert.py`：文件夹递归批转，单个失败不影响同批其他文件
- 输出结构：`temp/` 可审计中间产物 + 最终 `<book>/`（`images/`、Markdown、归档的源文件）
- 标题策略自动决策：文章 / 报告 / 论文用唯一书名 H1，单文件书籍保留并列章级 H1；不为通过校验而压平层级（不产生 H7、不合并不同层级）
- 可选 `parallel-repair` 高成本修复模式，仅在请求逐字包含 `并行多智能体修复` 或 `[parallel-repair]` 时启用

### 安装

```bash
git clone https://github.com/Kecxelic/document-to-markdown.git ~/.agents/skills/document-to-markdown
```

目标路径按你的宿主 skill 目录调整（如 `~/.claude/skills/`、`~/.agents/skills/`）。

### 依赖

- Python 3.10+（在 3.12 上开发测试）
- [Pandoc](https://pandoc.org)（EPUB 与 DOCX 转换）
- 仅 PDF 需要：[MinerU](https://mineru.net) 免费 API token，写入 `~/.mineru/mineru.conf`：

  ```text
  mineru_token=<your_token>
  ```

  在 <https://mineru.net/apiManage/token> 创建。

### 使用

直接对 agent 说「把这份 PDF / EPUB / DOCX 转成 Markdown」，或显式调用：

```text
$document-to-markdown <文件或文件夹>
```

脚本也可以单独运行：

```bash
python ~/.agents/skills/document-to-markdown/scripts/convert.py "论文.pdf"
```

### 已知限制

PDF 质量取决于 MinerU 与扫描 / OCR 质量；EPUB 复杂 CSS、固定版式与 DRM，DOCX 复杂排版、文本框、修订标记不保证保真；不移除 DRM。完整行为契约见 [SKILL.md](SKILL.md)。

## License

[MIT](LICENSE)
