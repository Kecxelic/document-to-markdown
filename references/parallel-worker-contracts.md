# Parallel repair worker contracts

本文件定义廉价 worker 与独立审查者的最小合同。路径都相对于 manifest 所在工作区；worker 只读取自己的任务包及其列出的输入。

## 生成 worker

读取 `tasks/<unit>.json`，严格按以下顺序工作：

1. 读取 `primary_path`，列出本单元的事实、章节目的和段落顺序。
2. 读取 `reference_paths`。只吸收更自然或更准确的术语表达，不复制参考独有内容。
3. 把自然、准确、完整的目标文本写入 `candidate_path`。不得修改其他文件。
4. 自查 `immutable_invariants`。代码块内部逐字不变；图片和外部链接目标不变；不得增加或删除标题与内部链接。
5. 不生成审查 JSON，不宣称自己已经通过独立审查。

标题文字可以翻译，标题层级可以为修复全书大纲而调整。不得用把多个层级全部压到 H6 的方式规避 Markdown 的 H1-H6 限制。

## 审查者输入与输出

每个角色独立读取主源、候选和必要的参考译本。审查者不得直接改候选，只写：

```text
reviews/<role>/<unit_id>.json
```

JSON 必须包含且精确指向当前文件哈希：

```json
{
  "unit_id": "001",
  "role": "fidelity",
  "base_sha256": "<primary unit sha256>",
  "candidate_sha256": "<candidate sha256>",
  "approved": true,
  "unresolved": [],
  "notes": ["可选的简短审查证据"]
}
```

候选修改后旧审查自动失效，必须重新审查。`approved` 只有在 `unresolved` 为空时才能为 `true`。

## 三个角色的判定边界

### fidelity

- 逐段对应主源，检查遗漏、无依据新增、意义反转、数字、专名、逻辑关系与术语漂移。
- 参考译本与主源冲突时服从主源，并在 `notes` 记录冲突。
- 不把“读起来顺”当作忠实性通过的证据。

### zh-cn-editor

- 检查大陆简体中文字符、标点、搭配、指代、衔接和自然语序。
- 删除英译中或繁译简造成的生硬直译，但不得改变事实和作者语气强度。
- 专名确需保留繁体字符时，在最终 `verify` 使用最小字符白名单并记录理由。

### format

- 检查标题数量与层级语义、围栏代码、列表、引用、图片、链接和脚注。
- 所有可表达为 Markdown 的 `<div>`、`<span>`、`<figure>`、`<figcaption>`、`<img>` 等 HTML 必须清理。
- 标题层级改变必须服务于全书一致的大纲；不能跳级，不能产生 H7，也不能把不同层级静默合并。

## 协调 agent

协调 agent 负责分配互不重叠的单元、等待当前波次结束、处理冲突、触发重审、运行确定性合并与最终验收。协调 agent 不把“多数 worker 认为正确”当作证据；任何硬门禁失败都必须回到对应单元修复。
