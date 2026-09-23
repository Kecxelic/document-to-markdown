# 显式并行多智能体修复

本模式面向**已经转换为 Markdown 的文档或书籍目录**，同时修复翻译/表达、标题层级、HTML 残留、图片与链接等问题。它会消耗大量 token，只有用户的当前请求把 `并行多智能体修复` 或 `[parallel-repair]` 用作立即执行文档修复的动作指令时才启用。诸如“修一下”“润色”“把繁体变简体”“提高阅读体验”都不构成授权；讨论规则、引用示例或明确否定也不触发。

## 路由与写入前门禁

1. 默认始终走普通转换或单 agent 审查，不创建并行任务。
2. 检查显式触发词；没有触发词就停止读取本参考，不得启动子 agent。
3. 解析主源、参考译本、目标语言、目标目录、宿主和 worker 模型。主源决定内容与结构，译本仅作为用语参考。
4. 使用当前宿主的原生能力确认：能够并行启动 agent、能够为 worker 选择用户指定的模型、协调 agent 能继续使用当前模型。无法确认指定模型时，必须在任何写入前停止并报告；不得静默换成当前模型或其他模型。
5. 不得在脚本里直接调用智谱、OpenAI 或其他厂商 API。`scripts/repair.py` 只负责确定性切片、哈希、合并和验收；agent 调度由 zcode、Codex 等当前宿主负责。
6. 只有上述条件都满足，才执行 `prepare` 并传入 `--host-capability-confirmed`。

## 输入权威与输出规则

- 主源是内容、章节顺序、代码、图片和外部链接的权威来源。
- 参考译本只帮助理解术语与语义。参考译本独有的序言、广告、附录或出版信息默认排除；存在歧义时标记为 `reference-only` 或 `ambiguous`，不得偷偷并入正文。
- 主源和参考译本全程只读。工作只发生在 `temp/parallel-repair/<target>/`；最终验收通过前不得创建或覆盖目标目录。
- 目标目录已存在时拒绝覆盖。验收通过后用原子移动发布一个新目录；不删除主源、参考译本或旧成品。
- 以英文和繁体译本生成简体中文版时，英文版通常是主源，繁体中文版是参考，简体中文版是新目标。除非用户明确另行指定，不把繁体版当作待删除对象。

## 执行波次

### 波次 0：只读盘点

分别统计 Markdown、原始 EPUB/PDF/DOCX、图片、H1-H6、代码块、图片引用、链接和原始 HTML。抽查开头、中部、结尾。确认两份文档不必拥有相同的物理章节数；对齐必须保守。

### 波次 1：准备隔离工作区

```bash
python "<skill_dir>/scripts/repair.py" prepare \
  --prompt "<包含显式触发词的原始请求>" \
  --primary "<主源目录或 Markdown>" \
  --reference "<参考目录或 Markdown>" \
  --output "<新目标目录>" \
  --worker-model "<宿主/模型 ID，由用户指定>" \
  --target-language "<目标语言，例如 zh-CN>" \
  --host-capability-confirmed
```

准备脚本生成不可变快照、章节单元、保守对齐、候选副本和任务 JSON。任何 worker 都不得直接改主源、参考译本、manifest 或最终目录。

### 波次 2：并行生成候选单元

- 每个 worker 只处理一个 `tasks/<unit>.json` 指定的单元，写入唯一的 `candidates/<unit>.md`。
- 先忠实理解主源，再参考译本，最后写自然的目标语言；不得逐字硬译，不得增删事实。
- 必须保持标题数量、代码块内容、图片引用、外部链接和内部链接数量。标题文本与层级可以修复，但必须经过格式审查。
- 清理 EPUB 转换遗留的 `<span>`、`<div>`、`<figure>`、`<img>` 等原始 HTML，并转成 Obsidian 友好的 Markdown。
- 不嵌套启动子 agent，不互相写同一个文件，不写最终成品。

### 波次 3：并行独立审查

对每个候选单元分别运行三个独立角色；审查者不改候选，只写自己的 JSON：

- `fidelity`：对照主源检查遗漏、增译、误译、术语和事实。
- `zh-cn-editor`：检查简体中文、可读性、书面表达、段落衔接和机器翻译腔。
- `format`：检查标题层级、代码、图片、链接、列表、引用和 HTML 清理。

三个角色全部批准且哈希指向当前候选，单元才可合并。具体 JSON 合同见 [parallel-worker-contracts.md](parallel-worker-contracts.md)。廉价模型只有在任务包足够小、边界足够硬、审查彼此独立时才可靠。

### 波次 4：协调合并与全书复核

协调 agent 是唯一的最终写入者：

```bash
python "<skill_dir>/scripts/repair.py" merge --manifest "<work_dir>/manifest.json"
```

合并脚本重新计算主源、候选和审查哈希，拒绝过期审查、未解决项、代码变化、图片变化、外链变化、链接数量变化或标题数量变化。随后协调 agent 通读章节衔接、全书术语和标题体系；如需改候选，所有相关审查必须基于新哈希重做。

### 波次 5：硬验收与发布

```bash
python "<skill_dir>/scripts/repair.py" verify --manifest "<work_dir>/manifest.json"
python "<skill_dir>/scripts/repair.py" publish \
  --manifest "<work_dir>/manifest.json" \
  --report "<work_dir>/verification-report.json"
```

最终验收至少包括：Pandoc 可解析、代码围栏闭合、标题不跳级、图片全存在且无孤儿、内部链接可解析、原始 HTML 清零、简体目标中无未豁免的繁体残留。`verification-report.json` 的 `passed` 不为 `true` 时不得发布。

## 一句话调用示例

```text
$document-to-markdown 并行多智能体修复《The PARA Method (English)》：参考《The PARA Method (繁體中文)》，用用户指定的 worker 模型生成简体中文版。
```

这句话同时给出高成本授权、主源、参考译本、宿主/模型和目标语言。若目标目录可从同级命名规则唯一推断，agent 直接使用 `<书名> (简体中文)`；无法唯一推断时才询问。
