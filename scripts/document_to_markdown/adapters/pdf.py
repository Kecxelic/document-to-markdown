"""PDF adapter that composes the established MinerU and outline stages."""

from pathlib import Path

from fix_outline import book_stem_for_pdf, run as run_stage2
from mineru_convert import run as run_stage1

from document_to_markdown.core import ConversionResult


def convert(source, options):
    source = Path(source)
    book = book_stem_for_pdf(source)
    output_dir = source.parent / book
    markdown = output_dir / (book + ".md")

    try:
        converted = run_stage1(
            source,
            model=options.model,
            language=options.language,
            chunk_size=options.chunk_size,
            no_upload=options.no_upload,
            work_dir=options.work_dir,
        )
        if not converted:
            return ConversionResult(
                source=source,
                format="pdf",
                ok=False,
                diagnostic="MinerU 未生成可发布结果",
            )

        fixed = run_stage2(
            source,
            ocr=options.ocr,
            demote_substrings=options.demote,
            heading_policy=options.heading_policy,
        )
        if not fixed or not markdown.exists():
            return ConversionResult(
                source=source,
                format="pdf",
                ok=False,
                output_dir=output_dir,
                diagnostic="PDF 大纲修复或发布未完成",
            )

        return ConversionResult(
            source=source,
            format="pdf",
            ok=True,
            output_dir=output_dir,
            markdown=markdown,
        )
    except Exception as exc:
        return ConversionResult(
            source=source,
            format="pdf",
            ok=False,
            output_dir=output_dir if output_dir.exists() else None,
            diagnostic=str(exc),
        )
