import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class DispatchTests(unittest.TestCase):
    def test_skill_metadata_describes_all_supported_formats(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("name: document-to-markdown", text)
        self.assertRegex(text, r"description: (>?-?\s*)?Use when")
        self.assertIn("PDF", text)
        self.assertIn("EPUB", text)
        self.assertIn("DOCX", text)
        self.assertIn("WPS", text)
        self.assertIn("scripts/convert.py", text)
        self.assertIn("MinerU", text)
        self.assertIn("Pandoc", text)

    def test_skill_requires_adaptive_outline_review_and_user_reporting(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("工具初转", text)
        self.assertIn("H2-H6", text)
        self.assertIn("粗体", text)
        self.assertIn("具体文档", text)
        self.assertIn("向用户汇报", text)
        self.assertIn("不得仅因唯一 H1", text)
        self.assertIn("EMF/WMF", text)
        self.assertIn("PNG", text)
        self.assertIn("Markdown 图片语法", text)

    def test_unified_cli_help_exposes_supported_formats_and_pdf_options(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "convert.py"), "--help"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PDF", completed.stdout)
        self.assertIn("EPUB", completed.stdout)
        self.assertIn("DOCX", completed.stdout)
        self.assertIn("WPS", completed.stdout)
        self.assertIn("--model", completed.stdout)
        self.assertIn("--ocr", completed.stdout)
        self.assertIn("--demote", completed.stdout)

    def test_pdf_adapter_composes_existing_stages_and_reports_output(self):
        from document_to_markdown.adapters import pdf
        from document_to_markdown.core import ConversionOptions

        calls = []

        def stage1(source, **kwargs):
            calls.append(("stage1", source.name, kwargs))
            return [{"stem": source.stem, "pdf": str(source), "parts": 1}]

        def stage2(source, **kwargs):
            calls.append(("stage2", source.name, kwargs))
            out = source.parent / source.stem
            out.mkdir()
            (out / (source.stem + ".md")).write_text("# Book", encoding="utf-8")
            source.replace(out / (source.stem + ".pdf"))
            return 1

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Book.pdf"
            source.write_bytes(b"pdf")
            options = ConversionOptions(ocr=True, demote=("Series",))

            with patch.object(pdf, "run_stage1", side_effect=stage1), patch.object(
                pdf, "run_stage2", side_effect=stage2
            ):
                result = pdf.convert(source, options)

            self.assertEqual([call[0] for call in calls], ["stage1", "stage2"])
            self.assertTrue(result.ok)
            self.assertEqual(result.format, "pdf")
            self.assertTrue(result.markdown.exists())
            self.assertEqual(calls[1][2]["demote_substrings"], ("Series",))

    def test_discovery_routes_supported_files_and_skips_internal_outputs(self):
        from document_to_markdown.core import discover_sources

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Book.PDF").write_bytes(b"pdf")
            (root / "sub").mkdir()
            (root / "sub" / "Novel.EPUB").write_bytes(b"epub")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")
            (root / "temp").mkdir()
            (root / "temp" / "Hidden.pdf").write_bytes(b"pdf")
            published = root / "Published"
            published.mkdir()
            (published / "Published.pdf").write_bytes(b"pdf")
            (published / "Published.md").write_text("# Published", encoding="utf-8")

            (root / "Report.DOCX").write_bytes(b"docx")
            (root / "Legacy.doc").write_bytes(b"doc")

            found = discover_sources(root, {".pdf", ".epub", ".docx", ".doc"})

            self.assertEqual(
                [path.name for path in found],
                ["Book.PDF", "Legacy.doc", "Report.DOCX", "Novel.EPUB"],
            )

    def test_discovery_rejects_one_unsupported_file(self):
        from document_to_markdown.core import discover_sources

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.txt"
            source.write_text("text", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "不支持的文档格式"):
                discover_sources(source, {".pdf", ".epub"})

    def test_batch_records_failure_and_continues_with_later_source(self):
        from document_to_markdown.core import (
            ConversionOptions,
            ConversionResult,
            run_batch,
        )

        calls = []

        def fail_pdf(source, options):
            calls.append(source.name)
            raise RuntimeError("boom")

        def convert_epub(source, options):
            calls.append(source.name)
            return ConversionResult(
                source=source,
                format="epub",
                ok=True,
                output_dir=source.parent / source.stem,
                markdown=source.parent / source.stem / (source.stem + ".md"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.pdf").write_bytes(b"pdf")
            (root / "b.epub").write_bytes(b"epub")

            results = run_batch(
                root,
                ConversionOptions(),
                {".pdf": fail_pdf, ".epub": convert_epub},
            )

            self.assertEqual(calls, ["a.pdf", "b.epub"])
            self.assertEqual(len(results), 2)
            self.assertFalse(results[0].ok)
            self.assertIn("boom", results[0].diagnostic)
            self.assertTrue(results[1].ok)


if __name__ == "__main__":
    unittest.main()
