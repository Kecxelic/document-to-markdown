# document-to-markdown 转换产物

`document-to-markdown` 把 PDF 或 EPUB 发布为同名书籍目录：

```text
<source_parent>/
  temp/
    minerU_trans/            # PDF 原始/分块结果
    清理冗余/                # PDF 清理后结果
    epub_trans/              # EPUB Pandoc 阶段结果
  <book>/
    <book>.md                # 首选阅读文件
    images/                  # 有图片时存在
    <book>.pdf | <book>.epub # 原文件
```

AI 和人阅读时优先打开 `<book>/<book>.md`；需要核对版面、公式、扫描内容或 EPUB 原结构时，再打开同目录原文件。`temp/` 只用于审计、排错和重跑。

转换成功前不移动源文件。最终目录或中间阶段目录已存在时拒绝覆盖。
