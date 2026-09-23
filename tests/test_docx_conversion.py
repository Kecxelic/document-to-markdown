import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class DocxConversionTests(unittest.TestCase):
    def test_normalizes_html_and_markdown_metafile_images_to_png(self):
        from document_to_markdown.adapters import docx

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "images" / "media"
            images.mkdir(parents=True)
            (images / "figure.emf").write_bytes(b"emf")
            (images / "symbol.wmf").write_bytes(b"wmf")
            markdown = root / "Book.md"
            markdown.write_text(
                '<img src="images/media/figure.emf" style="width:2in" />\n\n'
                'Value ![Symbol](images/media/symbol.wmf) and '
                'again ![Symbol](images/media/symbol.wmf)\n',
                encoding="utf-8",
            )

            def fake_convert(source, target):
                target.write_bytes(b"png")

            with patch.object(docx, "_convert_metafile", side_effect=fake_convert):
                docx._normalize_images(markdown, root)

            text = markdown.read_text(encoding="utf-8")
            self.assertIn("![](images/media/figure.png)", text)
            self.assertIn("![Symbol](images/media/symbol.png)", text)
            self.assertNotIn("<img", text)
            self.assertNotRegex(text, r"\.(?:emf|wmf)\b")
            self.assertTrue((images / "figure.png").exists())
            self.assertTrue((images / "symbol.png").exists())
            self.assertFalse((images / "figure.emf").exists())
            self.assertFalse((images / "symbol.wmf").exists())

    def test_doc_adapter_rejects_with_wps_instruction_without_moving_source(self):
        from document_to_markdown.adapters import doc
        from document_to_markdown.core import ConversionOptions

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Legacy.doc"
            source.write_bytes(b"legacy")

            result = doc.convert(source, ConversionOptions())

            self.assertFalse(result.ok)
            self.assertEqual(result.format, "doc")
            self.assertIn("WPS", result.diagnostic)
            self.assertIn(".docx", result.diagnostic)
            self.assertTrue(source.exists())

    def test_docx_adapter_publishes_markdown_images_and_original(self):
        from document_to_markdown.adapters import docx
        from document_to_markdown.core import ConversionOptions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Report.docx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", "<document/>")
                archive.writestr("docProps/core.xml", """<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Quarterly Report</dc:title></cp:coreProperties>""")

            def fake_pandoc(source_path, staging, markdown_name):
                (staging / "images").mkdir()
                (staging / "images" / "chart.png").write_bytes(b"png")
                (staging / markdown_name).write_text(
                    "## Findings\n\n![Chart](images/chart.png)\n", encoding="utf-8"
                )

            with patch.object(docx, "_run_pandoc", side_effect=fake_pandoc):
                result = docx.convert(source, ConversionOptions())

            self.assertTrue(result.ok, result.diagnostic)
            self.assertEqual(result.format, "docx")
            self.assertTrue((result.output_dir / "Report.docx").exists())
            self.assertTrue((result.output_dir / "images" / "chart.png").exists())
            text = result.markdown.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Quarterly Report\n\n"))

    def test_invalid_docx_fails_without_moving_source(self):
        from document_to_markdown.adapters import docx
        from document_to_markdown.core import ConversionOptions

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Broken.docx"
            source.write_bytes(b"not-a-zip")

            result = docx.convert(source, ConversionOptions())

            self.assertFalse(result.ok)
            self.assertIn("DOCX", result.diagnostic)
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
