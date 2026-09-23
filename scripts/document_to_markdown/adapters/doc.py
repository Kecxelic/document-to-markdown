"""Reject legacy Word documents with an actionable conversion instruction."""

from pathlib import Path

from document_to_markdown.core import ConversionResult


def convert(source, options):
    source = Path(source)
    return ConversionResult(
        source=source,
        format="doc",
        ok=False,
        diagnostic="不支持旧版 .doc 格式。请先使用 WPS 或其他办公软件将文件另存为 .docx，再重新转换。",
    )
