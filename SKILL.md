---
name: document-to-markdown
description: Use when converting PDF, EPUB, or DOCX files, books, papers, reports, or folders of documents to Markdown; rejecting legacy DOC files that must first be saved as DOCX with WPS or another office suite; extracting document images; repairing Markdown heading structure; publishing source files beside readable Markdown; or, only when explicitly requested with the exact parallel-repair trigger, repairing an already converted document's content and formatting through parallel agents.
---

# document-to-markdown

把 PDF、EPUB 和 DOCX 统一转换为带图片、原文件和可导航大纲的 Markdown。用户只调用一个 skill；格式差异由内部适配器处理。

## 模式路由

本 skill 有两个互斥模式，默认永远是普通模式：

- **普通转换/审查**：转换新文档，或由当前 agent 对已转换 Markdown 做常规检查与局部修复。适用于所有没有显式高成本授权的请求。
- **`parallel-repair`**：对已经转换的文档同时修复内容和格式，使用宿主原生的并行多智能体、独立审查、哈希门禁和最终原子发布。它只在用户当前请求逐字包含 `并行多智能体修复` 或 `[parallel-repair]` 时启用。

“修复文档”“提高质量”“繁体转简体”“优化 Obsidian 阅读体验”等近义表达都不得触发 `parallel-repair`。触发词还必须是要求立即执行文档修复的动作指令；讨论本规则、引用调用示例或明确说“不要并行多智能体修复”都不触发。没有精确触发词时，不得因为文档很长、存在双语参考或质量要求高而自行启动子 agent；也不要反问用户是否要开启高成本模式。精确触发词本身就是本次任务的大量 token 授权，但不授权覆盖或删除原文件。

一旦显式触发，先完整阅读 [显式并行多智能体修复](references/parallel-repair.md) 和 [worker 合同](references/parallel-worker-contracts.md)，把该流程加入工作计划，再执行任何写入。写入前必须用当前宿主的原生能力确认它支持并行 agent 和用户指定的 worker 模型；无法确认或无法选择该模型时，停止并汇报，不得静默换模型。确定性脚本不得直接调用任何模型厂商 API。

一句话调用示例：

```text
$document-to-markdown 并行多智能体修复《The PARA Method (English)》：参考《The PARA Method (繁體中文)》，用用户指定的 worker 模型生成简体中文版。
```

## 核心原则

本 skill 采用“工具初转 + agent 审查”的方式。转换脚本只提供候选 Markdown，不代表任务已经完成。agent 必须查看具体文档的实际结构与转换结果，判断标题、正文、表格和图片是否合理；规则是建议和异常信号，不得替代对当前文档的分析。

发现结果明显异常时，先停止发布并分析原因。能够从文档结构可靠判断时，按当前文档修复；不能可靠判断时，向用户汇报异常、证据和未完成项，不得把形式上通过校验的结果当作成功交付。

## 普通转换统一入口

```bash
python "<skill_dir>/scripts/convert.py" "<file_or_folder>"
```

文件夹输入会递归发现 PDF、EPUB、DOCX 和 DOC，跳过 `temp/` 与已经发布的成品。单个失败不会阻止同批其他文件，最终汇总成功数和失败数。

| 格式 | 转换器 | 大纲处理 |
|------|--------|----------|
| PDF | MinerU VLM | OCR/编号/章节/H2 稀缺性等 PDF 专用规则 |
| EPUB | Pandoc | 使用 EPUB 语义标题，按文档类型选择书名 H1 或章级 H1，并清理相对层级和空标题 |
| DOCX | Pandoc + agent 审查 | 保留 Word 标题；对自定义样式、粗体或编号段落按具体文档判断大纲 |
| DOC | 不转换 | 提示用户先用 WPS 或其他办公软件另存为 DOCX |

不要对 EPUB 或 DOCX 运行 PDF 的 OCR、页面残留、编号降级或前置页启发式规则。

## 标题策略

Markdown 语法本身不要求一个文件只能有一个 H1。“唯一书名 H1”的好处，是让普通文章、报告以及准备导出为 HTML、PDF 或 DOCX 的文档具有明确的文档标题；目录生成器、静态站点、无障碍阅读器和后续自动化也更容易把 H1 识别为整份文档的名称，而把 H2-H6 识别为正文层级。这是互操作性约定，不是 Markdown 的普遍真理。

单文件书籍可以合理地采用“每章一个 H1”。当多个 H1 确实代表并列章节时，这种结构能保留 EPUB 的章节语义、让 Obsidian 大纲更直观，并避免为了增加书名 H1 而把正文整体下移。如果下移会产生 H7，或把原本不同的 H5/H6 都压成 H6，强制唯一 H1 反而会破坏信息。不得为了形式上通过校验而静默压平标题层级。

转换默认使用 `auto`，由 agent 根据文档类型和实际大纲自行决定以下策略，不把 `single-title` / `chapter-h1` 当作选择题交给用户：

- `single-title`：文档中恰好一个书名 H1，正文标题位于 H2-H6。适用于文章、报告、论文、表单以及其他以一个整体标题统领正文的文档。
- `chapter-h1`：保留并列章节为 H1，书名由文件名、EPUB/DOCX 元数据或 frontmatter 承担。适用于单文件书籍、手册、教程或参考书，尤其是增加书名 H1 会超出 H6、合并不同层级时。

决策顺序如下：

1. 先根据 EPUB/DOCX 元数据、目录、章节编号、正文规模和顶级标题语义判断它是普通文档还是单文件书籍；不能只按扩展名判断。
2. 文章、报告、论文、表单等普通文档使用 `single-title`。
3. 书籍、手册、教程、参考书等单文件长文，若多个顶级标题是并列章节，使用 `chapter-h1`。
4. 对可能采用 `single-title` 的文档先统计 H1-H6。只有在整体下移后仍能一一保留原层级时才可采用；若会产生 H7 或合并不同层级，改用 `chapter-h1`。
5. 存在歧义时，agent 必须抽查开头、中部、结尾及目录后自行作出有证据的判断，并在交付说明中简述理由；不要仅为标题策略向用户提问。
6. 无论采用哪种策略，都必须排除代码块中的 `#`、删除空标题、检查层级连续性并抽查章节归属。策略名称不能替代语义审查。

统一入口默认自动判定：

```bash
python "<skill_dir>/scripts/convert.py" "<file_or_folder>"
```

脚本的 `auto` 只提供保守的格式与层级判定，不能理解全部文档语义。agent 审查后如果发现自动结果与文档类型不符，应自行用 `--heading-policy single-title` 或 `--heading-policy chapter-h1` 重新转换；这些参数是 agent 的执行手段，不要求用户选择。

## 表格策略

Markdown 管道表不支持合并单元格，转换工具（Pandoc、MinerU）遇到带 `rowspan`/`colspan` 的复杂表格时常退化为内联 HTML `<table>`，源码不可读、难以编辑。表格处理的目标是保留表格的**语义**，不是复刻**版式**：合并单元格常常只是原作者的排版捷径，不代表信息本身重复。决策顺序：

1. **先理解语义**：理想管道表是"一行一个实体（事项、专业、条目），一列一个属性"。先识别合并块对应的真实逻辑字段，再决定怎么写。
2. **语义重组优先**：当合并结构掩盖了真实字段时，重组为"一行一实体、一列一属性"。典型模式：某列在同一合并块下堆叠多行短句（如"考核内容"与"结果处理"被挤进同一列），应拆成并列的列；表头为空时补一个中性名称（如"环节"）。
3. **表单改写为标签块**：DOCX 表单常用表格当版式脚手架（字段名＋空白填写区、竖排合并标签、整块意见栏）。此类表格没有二维数据语义，不转成任何表格，改写为"加粗标签＋填写区/勾选清单"的顺序结构，竖排标签按文档惯例横排合并；仅把其中真正二维的部分（如年度计划"起始时间|完成内容"）保留为管道表。
4. **机械展开兜底**：当表格本就是逐行查询表——每行一个实体、合并列只是共享同一属性值（如专业目录共享可选论文形式）——把 `rowspan`/`colspan` 内容逐字重复到覆盖的每一行每一列即可。
5. **保留 HTML 仅限例外**：嵌套表格或语义纠缠到无法线性化时才保留，并在交付说明中写明原因。

无论哪种方式，单元格文字、标点逐字保留，不概括、不改写；该策略适用于 PDF、EPUB、DOCX 全部适配器，也适用于普通模式下对已转换 Markdown 的审查修复；成品中残留的 `<table>`、`rowspan`、`colspan` 按 HTML 残留处理。

## 最终输出

```text
<source_parent>/
  temp/                       # 可审计中间产物
  <book>/
    images/                   # 有图片时存在
    <book>.md
    <book>.pdf | <book>.epub | <book>.docx
```

源文件只在转换、图片校验和大纲校验成功后移入最终目录。最终目录或阶段目录已存在时拒绝覆盖。

`parallel-repair` 不使用上述“移动源文件”发布方式：主源与参考译本始终只读，候选内容写入 `temp/parallel-repair/<target>/`；只有三类独立审查与最终硬验收全部通过后，才把暂存成品原子发布为新的同级目标目录。它既修复内容（忠实性、术语、目标语言表达），也修复格式（标题、HTML 残留、图片、链接、列表与代码围栏），但不得无依据增删主源内容。

EPUB 通常沿用文件名作为 `<book>`；文件名过长、会触发 Windows 路径限制时，改用 EPUB 元数据书名，并清理非法字符、限制长度。

## PDF

PDF 适配器保留此前已验证的两阶段行为：

1. MinerU 转换、超页分块、下载与合并，写入 `temp/minerU_trans/`。
2. 清理结果写入 `temp/清理冗余/`，修复大纲并发布最终目录。

MinerU token 只从 `~/.mineru/mineru.conf` 读取：

```text
mineru_token=<your_token>
```

token 过期时（HTTP 401 `user authenticate failed`），到 https://mineru.net/apiManage/token 重新创建 key 并更新该文件。
统一入口保留 `--model`、`--language`、`--chunk-size`、`--no-upload`、`--work-dir`、`--ocr` 和可重复的 `--demote TXT`。EPUB/DOCX 的 `--heading-policy` 默认 `auto`。运行 `scripts/convert.py --help` 查看参数。

需要单独执行旧阶段时仍可使用：

```bash
python "<skill_dir>/scripts/mineru_convert.py" "<pdf_or_folder>"
python "<skill_dir>/scripts/fix_outline.py" "<pdf_or_folder>"
```

PDF 大纲规则包括：代码块免疫、`Article N` 页面残留清理、编号层级修复、中文/英文章节识别、无编号 H2 降级与缺失 H1 补齐。

## EPUB

EPUB 适配器执行：

1. 校验 ZIP、`META-INF/container.xml` 和包文档。
2. 从包元数据读取书名，缺失时回退到文件名。
3. Pandoc 转为 GFM，关闭硬换行并把媒体提取到 `images/`。
4. 删除空标题；自动判定并应用唯一书名 H1 或并列章节 H1，同时保持相对层级和代码块内容。
5. agent 抽查自动判断是否符合书籍语义；必要时自行覆盖策略并重新转换。
6. 校验全部本地图片链接、最终标题策略和最终文件，再移动源 EPUB。

损坏、截断、缺少容器信息或带有 Pandoc 无法处理的保护机制时，明确报错并保留源文件。此 skill 不移除 DRM。

## DOCX 与 DOC

DOCX 适配器校验文件结构，读取核心属性中的标题（缺失时使用文件名），用 Pandoc 转为 GFM 并提取媒体到 `images/`。随后由 agent 审查实际 Markdown：

- Pandoc 提取出的 EMF/WMF 自动栅格化为 PNG，并同步更新引用；转换失败时停止发布。
- HTML `<img>` 统一改为 Markdown 图片语法 `![](...)`；简单的 figure/caption 结构转为图片加引用说明。

1. 统计 H1-H6，查看正文开头、中部和结尾。
2. 长文只有 H1、H2-H6 全为零时，视为大纲识别失败；在 `single-title` 下不得仅因唯一 H1 就判定成功，在 `chapter-h1` 下也不得只数 H1 而不审查章节语义。
3. 检查 Pandoc 是否把标题转成了普通段落，例如独占一行的粗体文本、中文序号、阿拉伯数字编号、下划线标题或短标签。
4. 结合具体文档的编号体系、语义和上下文确定层级。不要为所有 DOCX 套用同一组固定正则；同一文档内保持层级一致即可。
5. 修复后重新统计标题，并抽查标题前后的正文归属。若候选标题存在歧义，向用户汇报，不要猜测后静默发布。

所选标题策略、图片链接和文件存在性是硬校验；`single-title` 要求恰好一个 H1，`chapter-h1` 要求存在经语义确认的并列章级 H1。正文是否形成可导航大纲必须由 agent 结合文档内容验收。

旧版 `.doc` 不允许直接转换，也不调用 LibreOffice。检测到 DOC 时保留源文件并提示：先使用 WPS 或其他办公软件将文件另存为 `.docx`，再重新运行统一入口。

## 大纲复用边界

共享模块 `scripts/document_to_markdown/outline.py` 只提供格式无关能力：代码块识别、标题解析、H1-H6 计数、缺失 H1 补齐、唯一书名 H1 归一化、章级 H1 保留和空标题删除。它会拒绝把超过 H6 的层级静默压平。这些函数不会理解粗体、编号或自定义 Word 样式的语义，不能替代 agent 审查。

PDF 专用启发式仍保留在 PDF 流程；EPUB 和 DOCX 不调用这些规则。

## 验证

```bash
python -m unittest discover -s "<skill_dir>/tests" -v
python "<skill_creator_dir>/scripts/quick_validate.py" "<skill_dir>"
```

`parallel-repair` 还必须运行：

```bash
python "<skill_dir>/scripts/repair.py" merge --manifest "<work_dir>/manifest.json"
python "<skill_dir>/scripts/repair.py" verify --manifest "<work_dir>/manifest.json"
python "<skill_dir>/scripts/repair.py" publish --manifest "<work_dir>/manifest.json" --report "<work_dir>/verification-report.json"
```

只有报告中的 `passed: true` 才允许发布。协调 agent 是最终成品的唯一写入者；worker 只写各自候选单元，审查者只写各自审查 JSON。

真实文件验收至少检查：

- Markdown、原文件和图片目录均位于最终 `<book>/`。
- Markdown 符合已选标题策略且无空 `#` 标题：`single-title` 恰好一个有效 H1；`chapter-h1` 的多个 H1 必须是并列章节，而不是转换误判。
- 检查整体下移是否会超过 H6 或合并原本不同的层级；出现这种情况时不得使用 `single-title` 强行压平。
- 对非短篇文档统计 H2-H6；全部为零时必须检查粗体、编号和短段落候选，不得直接交付。
- 标题层级符合当前文档自身的编号与语义结构，抽查开头、中部和结尾。
- Markdown 中的本地图片链接全部存在。
- 图片使用 Markdown 图片语法；不得残留本地 `<img>`、EMF/WMF 引用或浏览器不可显示的图片。
- 复杂表格已按表格策略改写为管道表（语义重组或机械展开）；成品不得残留 `<table>`、`rowspan`、`colspan`（按表格策略保留并在交付说明中写明原因的除外）。
- 原始测试样本未被移动；实际转换应在副本上执行。

## 已知限制

- PDF 质量取决于 MinerU 与扫描/OCR 质量，并受其文件大小、页数和联网限制。
- EPUB 的复杂 CSS、固定版式、交互内容和 DRM 不保证保真。
- DOCX 的复杂排版、文本框、修订标记和嵌入对象不保证保真。
- DOC 必须先由用户使用 WPS 或其他办公软件另存为 DOCX。
- 复杂表格按表格策略改写为管道表；除此之外表格内容、公式编号和图片 caption 不做额外语义改写。
- 当前注册 PDF、EPUB、DOCX，并为 DOC 提供拒绝提示；新增格式时添加适配器并在统一注册表中登记。
- `parallel-repair` 的翻译与表达质量仍取决于宿主是否真的支持用户指定模型；能力不可用时必须在写入前停止，脚本不会替宿主调用外部模型。
