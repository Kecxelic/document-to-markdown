"""Unified PDF/EPUB/DOCX to Markdown command-line entry point."""

import argparse
import sys
from pathlib import Path

from document_to_markdown.adapters import doc, docx, epub, pdf
from document_to_markdown.core import ConversionOptions, run_batch


REGISTRY = {
    ".pdf": pdf.convert,
    ".epub": epub.convert,
    ".docx": docx.convert,
    ".doc": doc.convert,
}


def build_parser():
    parser = argparse.ArgumentParser(
        description="统一文档转 Markdown：支持 PDF、EPUB、DOCX；旧版 DOC 请先用 WPS 或其他办公软件另存为 DOCX。"
    )
    parser.add_argument("path", help="PDF/EPUB/DOCX/DOC 文件，或递归扫描的目录")
    parser.add_argument("--model", default="vlm", help="PDF: MinerU 模型（默认 vlm）")
    parser.add_argument("--language", default="en", help="PDF: 文档语言（默认 en）")
    parser.add_argument("--chunk-size", type=int, default=180, help="PDF: 分块页数（默认 180）")
    parser.add_argument("--no-upload", action="store_true", help="PDF: 使用已下载的 MinerU 结果")
    parser.add_argument("--work-dir", help="PDF: MinerU 工作目录")
    parser.add_argument("--ocr", action="store_true", help="PDF: 启用 OCR 标题预处理")
    parser.add_argument("--demote", action="append", default=[], metavar="TXT", help="PDF: 将包含 TXT 的 H1 降级，可重复")
    parser.add_argument(
        "--heading-policy",
        choices=("auto", "single-title", "chapter-h1"),
        default="auto",
        help="EPUB/DOCX: 默认 auto 由文档类型和大纲决定；其余值供 agent 审查后覆盖",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    options = ConversionOptions(
        model=args.model,
        language=args.language,
        chunk_size=args.chunk_size,
        no_upload=args.no_upload,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        ocr=args.ocr,
        demote=tuple(args.demote),
        heading_policy=args.heading_policy,
    )

    try:
        results = run_batch(args.path, options, REGISTRY)
    except ValueError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1

    succeeded = 0
    for result in results:
        if result.ok:
            succeeded += 1
            print("OK [{}] {} -> {}".format(result.format.upper(), result.source, result.markdown))
        else:
            print("FAIL [{}] {}: {}".format(result.format.upper(), result.source, result.diagnostic), file=sys.stderr)

    failed = len(results) - succeeded
    print("\nConverted: {}  Succeeded: {}  Failed: {}".format(len(results), succeeded, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
