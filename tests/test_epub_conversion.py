import sys
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class EpubConversionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required")
    def test_long_filename_uses_metadata_title_for_safe_output_path(self):
        from document_to_markdown.adapters.epub import convert
        from document_to_markdown.core import ConversionOptions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "source.md"
            short_epub = root / "short.epub"
            markdown.write_text(
                "---\ntitle: Short Safe Title\n---\n\n# Chapter\n\nText.\n",
                encoding="utf-8",
            )
            subprocess.run(
                [shutil.which("pandoc"), str(markdown), "-o", str(short_epub)],
                check=True,
                capture_output=True,
                text=True,
            )
            source = root / (("A" * 180) + ".epub")
            short_epub.replace(source)

            result = convert(source, ConversionOptions(heading_policy="single-title"))

            self.assertTrue(result.ok, result.diagnostic)
            self.assertEqual(result.output_dir.name, "Short Safe Title")
            self.assertTrue((result.output_dir / "Short Safe Title.md").exists())
            self.assertTrue((result.output_dir / "Short Safe Title.epub").exists())

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required")
    def test_converts_valid_epub_with_title_headings_media_and_footnote(self):
        from document_to_markdown.adapters.epub import convert
        from document_to_markdown.core import ConversionOptions
        from document_to_markdown.outline import count_heading_levels

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "source.md"
            image = root / "diagram.svg"
            source = root / "Fixture.epub"
            image.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
                '<rect width="40" height="20" fill="navy"/></svg>',
                encoding="utf-8",
            )
            markdown.write_text(
                "\n".join(
                    [
                        "---",
                        "title: EPUB Test Book",
                        "---",
                        "",
                        "# EPUB Test Book",
                        "",
                        "# Chapter One",
                        "",
                        "## Topic",
                        "",
                        "Unicode text: 第二大脑。",
                        "",
                        "![Diagram](diagram.svg)",
                        "",
                        "```python",
                        "# not a heading",
                        "```",
                        "",
                        "Footnote reference.[^1]",
                        "",
                        "[^1]: Footnote body.",
                    ]
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [shutil.which("pandoc"), str(markdown), "-o", str(source)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            result = convert(source, ConversionOptions())

            output = root / "Fixture"
            output_md = output / "Fixture.md"
            self.assertTrue(result.ok, result.diagnostic)
            self.assertFalse(source.exists())
            self.assertTrue((output / "Fixture.epub").exists())
            self.assertTrue(output_md.exists())
            self.assertEqual(count_heading_levels(output_md)[1], 1)
            text = output_md.read_text(encoding="utf-8")
            self.assertNotIn("# EPUB Test Book", text)
            self.assertIn("# Chapter One", text)
            self.assertIn("## Topic", text)
            self.assertIn("# not a heading", text)
            self.assertIn("Footnote body", text)
            media_files = [path for path in (output / "images").rglob("*") if path.is_file()]
            self.assertTrue(media_files)
            for target in re.findall(r"!\[[^]]*\]\(([^)]+)\)", text):
                self.assertTrue((output / target).resolve().is_file(), target)

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required")
    def test_reads_title_from_epub_package_metadata(self):
        from document_to_markdown.adapters.epub import read_epub_title

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "source.md"
            epub = root / "Different Filename.epub"
            markdown.write_text(
                "---\ntitle: Metadata Book\n---\n\n# Chapter One\n\nText.\n",
                encoding="utf-8",
            )
            subprocess.run(
                [shutil.which("pandoc"), str(markdown), "-o", str(epub)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(read_epub_title(epub), "Metadata Book")

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required")
    def test_auto_policy_preserves_single_file_book_chapters(self):
        from document_to_markdown.adapters.epub import convert
        from document_to_markdown.core import ConversionOptions
        from document_to_markdown.outline import count_heading_levels

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "source.md"
            source = root / "Book.epub"
            markdown.write_text(
                "---\ntitle: Book Title\n---\n\n"
                "# Book Title\n\n# Chapter One\n\n## Topic\n\n# Chapter Two\n",
                encoding="utf-8",
            )
            subprocess.run(
                [shutil.which("pandoc"), str(markdown), "-o", str(source)],
                check=True,
                capture_output=True,
                text=True,
            )

            result = convert(source, ConversionOptions())

            self.assertTrue(result.ok, result.diagnostic)
            text = result.markdown.read_text(encoding="utf-8")
            self.assertNotIn("# Book Title\n", text)
            self.assertIn("# Chapter One", text)
            self.assertIn("## Topic", text)
            self.assertIn("# Chapter Two", text)
            self.assertEqual(count_heading_levels(result.markdown)[1], 2)

    def test_corrupt_epub_fails_without_moving_source_or_creating_output(self):
        from document_to_markdown.adapters.epub import convert
        from document_to_markdown.core import ConversionOptions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Broken.epub"
            source.write_bytes(b"PK\x03\x04truncated")

            result = convert(source, ConversionOptions())

            self.assertFalse(result.ok)
            self.assertIn("EPUB", result.diagnostic)
            self.assertIn("ZIP", result.diagnostic)
            self.assertTrue(source.exists())
            self.assertFalse((root / "Broken").exists())


if __name__ == "__main__":
    unittest.main()
