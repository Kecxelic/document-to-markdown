import sys
import tempfile
import unittest
from inspect import signature
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import mineru_convert
import fix_outline


class PipelineLayoutTests(unittest.TestCase):
    def test_mineru_data_ids_are_short_stable_and_unique_for_long_names(self):
        long_name = ("Very Long Book Name " * 12) + ".pdf"
        first = {"name": long_name, "part": 1, "total_parts": 2}
        second = {"name": long_name, "part": 2, "total_parts": 2}

        first_id = mineru_convert.data_id_for_job(first)
        second_id = mineru_convert.data_id_for_job(second)

        self.assertLessEqual(len(first_id), 128)
        self.assertEqual(first_id, mineru_convert.data_id_for_job(first))
        self.assertNotEqual(first_id, second_id)

    def test_stage2_normalizes_multiple_h1_below_first_document_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Book.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            clean_dir = root / "temp" / "清理冗余" / "Book"
            clean_dir.mkdir(parents=True)
            (clean_dir / "Book.md").write_text(
                "# Actual Book Title\n\n# Main Section\n\n## Topic\n",
                encoding="utf-8",
            )

            self.assertTrue(fix_outline.process_one(pdf, ocr=False, demote_substrings=[]))

            output = root / "Book" / "Book.md"
            text = output.read_text(encoding="utf-8")
            self.assertEqual(fix_outline.count_heading_levels(output)[1], 1)
            self.assertTrue(text.startswith("# Actual Book Title\n\n"))
            self.assertIn("## Main Section", text)
            self.assertIn("### Topic", text)

    def test_pdf_stages_expose_callable_runners_with_cli_defaults(self):
        stage1 = signature(mineru_convert.run).parameters
        stage2 = signature(fix_outline.run).parameters

        self.assertEqual(stage1["model"].default, "vlm")
        self.assertEqual(stage1["language"].default, "en")
        self.assertEqual(stage1["chunk_size"].default, 180)
        self.assertFalse(stage1["no_upload"].default)
        self.assertIsNone(stage1["work_dir"].default)
        self.assertFalse(stage2["ocr"].default)
        self.assertEqual(stage2["demote_substrings"].default, ())

    def test_shared_outline_normalizes_headings_below_document_title(self):
        from document_to_markdown.outline import count_heading_levels, normalize_under_title

        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "book.md"
            md.write_text(
                "\n".join(
                    [
                        "# Book Title",
                        "",
                        "# Chapter One",
                        "",
                        "## Topic",
                        "",
                        "# ",
                        "",
                        "```python",
                        "# not a heading",
                        "```",
                    ]
                ),
                encoding="utf-8",
            )

            normalize_under_title(md, "Book Title")

            text = md.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Book Title\n\n"))
            self.assertEqual(count_heading_levels(md)[1], 1)
            self.assertIn("## Chapter One", text)
            self.assertIn("### Topic", text)
            self.assertNotIn("\n# \n", text)
            self.assertIn("```python\n# not a heading\n```", text)

    def test_shared_outline_preserves_chapter_h1_when_explicitly_selected(self):
        from document_to_markdown.outline import count_heading_levels, preserve_chapter_h1

        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "book.md"
            md.write_text(
                "# Book Title\n\n# Chapter One\n\n##### Deep Topic\n",
                encoding="utf-8",
            )

            preserve_chapter_h1(md, "Book Title")

            text = md.read_text(encoding="utf-8")
            self.assertFalse(text.startswith("# Book Title"))
            self.assertIn("# Chapter One", text)
            self.assertIn("##### Deep Topic", text)
            self.assertEqual(count_heading_levels(md)[1], 1)
            self.assertEqual(count_heading_levels(md)[5], 1)

    def test_single_title_policy_rejects_heading_depth_overflow(self):
        from document_to_markdown.outline import normalize_under_title

        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "book.md"
            md.write_text("# Chapter One\n\n###### Deep Topic\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "chapter-h1"):
                normalize_under_title(md, "Book Title")

    def test_auto_heading_policy_uses_document_type_and_outline_shape(self):
        from document_to_markdown.outline import resolve_heading_policy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.md"
            report = root / "report.md"
            deep_docx_book = root / "deep-docx-book.md"
            book.write_text("# Chapter One\n\n# Chapter Two\n", encoding="utf-8")
            report.write_text("# Report\n\n## Findings\n", encoding="utf-8")
            deep_docx_book.write_text(
                "# Chapter One\n\n# Chapter Two\n\n###### Deep Topic\n",
                encoding="utf-8",
            )

            self.assertEqual(resolve_heading_policy(book, "epub"), "chapter-h1")
            self.assertEqual(resolve_heading_policy(report, "docx"), "single-title")
            self.assertEqual(
                resolve_heading_policy(deep_docx_book, "docx"), "chapter-h1"
            )

    def test_stage1_clean_output_renames_full_md_and_removes_redundant_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Book.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")

            raw_dir = root / "raw"
            (raw_dir / "images").mkdir(parents=True)
            (raw_dir / "full.md").write_text("# Book\n\n## 1. Intro\n", encoding="utf-8")
            (raw_dir / "images" / "page.png").write_bytes(b"png")
            (raw_dir / "layout.json").write_text("{}", encoding="utf-8")
            (raw_dir / "origin.pdf").write_bytes(b"pdf")

            clean_dir = mineru_convert.create_clean_output(raw_dir, pdf)

            self.assertEqual(clean_dir, root / "temp" / "清理冗余" / "Book")
            self.assertTrue((clean_dir / "Book.md").exists())
            self.assertTrue((clean_dir / "images" / "page.png").exists())
            self.assertFalse(list(clean_dir.rglob("*.json")))
            self.assertFalse(list(clean_dir.rglob("*.pdf")))

    def test_stage2_writes_final_book_folder_and_moves_source_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Book.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")

            clean_dir = root / "temp" / "清理冗余" / "Book"
            (clean_dir / "images").mkdir(parents=True)
            (clean_dir / "Book.md").write_text(
                "# Book\n\n# 1. Intro\n\n## 1.1 Method\n",
                encoding="utf-8",
            )
            (clean_dir / "images" / "page.png").write_bytes(b"png")

            self.assertTrue(fix_outline.process_one(pdf, ocr=False, demote_substrings=[]))

            final_dir = root / "Book"
            self.assertTrue((final_dir / "Book.md").exists())
            self.assertTrue((final_dir / "images" / "page.png").exists())
            self.assertTrue((final_dir / "Book.pdf").exists())
            self.assertFalse(pdf.exists())
            fixed_text = (final_dir / "Book.md").read_text(encoding="utf-8")
            self.assertIn("## 1. Intro", fixed_text)
            self.assertIn("### 1.1 Method", fixed_text)

    def test_stage2_adds_book_title_when_clean_markdown_has_no_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "NoTitle.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")

            clean_dir = root / "temp" / "清理冗余" / "NoTitle"
            clean_dir.mkdir(parents=True)
            (clean_dir / "NoTitle.md").write_text("## 摘要\n\n正文\n", encoding="utf-8")

            self.assertTrue(fix_outline.process_one(pdf, ocr=False, demote_substrings=[]))

            fixed_text = (root / "NoTitle" / "NoTitle.md").read_text(encoding="utf-8")
            self.assertTrue(fixed_text.startswith("# NoTitle\n\n## 摘要"))

    def test_outline_demotes_local_numbered_and_appendix_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.md"
            dest = root / "dest.md"
            src.write_text(
                "\n".join(
                    [
                        "# Book",
                        "## 2.1 Data Types",
                        "## 1. Under section",
                        "## 2.1.1 Attributes",
                        "## 1. Under subsection",
                        "## A.1 Vectors",
                        "## A.1.1 Definition",
                    ]
                ),
                encoding="utf-8",
            )

            fix_outline.fix_outline(src, dest)

            fixed = dest.read_text(encoding="utf-8")
            self.assertIn("### 2.1 Data Types", fixed)
            self.assertIn("#### 1. Under section", fixed)
            self.assertIn("#### 2.1.1 Attributes", fixed)
            self.assertIn("##### 1. Under subsection", fixed)
            self.assertIn("### A.1 Vectors", fixed)
            self.assertIn("#### A.1.1 Definition", fixed)

    def test_outline_demotes_unnumbered_h2_inside_book_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.md"
            dest = root / "dest.md"
            src.write_text(
                "\n".join(
                    [
                        "# Book",
                        "## Preface",
                        "## Data",
                        "## 2.1 Data Types",
                        "## Side Note",
                        "## 2.2 Quality",
                        "## 参考文献",
                        "## Clustering",
                        "## 3.1 Overview",
                    ]
                ),
                encoding="utf-8",
            )

            fix_outline.fix_outline(src, dest)

            fixed = dest.read_text(encoding="utf-8")
            self.assertIn("## Preface", fixed)
            self.assertIn("## Data", fixed)
            self.assertIn("### 2.1 Data Types", fixed)
            self.assertIn("#### Side Note", fixed)
            self.assertIn("### 参考文献", fixed)
            self.assertIn("## Clustering", fixed)
            self.assertIn("### 3.1 Overview", fixed)

    def test_outline_demotes_front_matter_metadata_h2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.md"
            dest = root / "dest.md"
            src.write_text(
                "\n".join(
                    [
                        "# Book",
                        "## PEARSON",
                        "## 内容提要",
                        "## 版权声明",
                        "## 图灵计算机科学丛书",
                        "## 本书特色",
                        "## Book Title（完整版）",
                        "## 前言",
                        "## 概述",
                        "## 支持材料",
                        "## 致谢",
                        "## 1.1 Start",
                    ]
                ),
                encoding="utf-8",
            )

            fix_outline.fix_outline(src, dest)

            fixed = dest.read_text(encoding="utf-8")
            self.assertIn("## 图书信息", fixed)
            self.assertIn("### PEARSON", fixed)
            self.assertIn("### 内容提要", fixed)
            self.assertIn("### 版权声明", fixed)
            self.assertIn("### 图灵计算机科学丛书", fixed)
            self.assertIn("### 本书特色", fixed)
            self.assertIn("### Book Title（完整版）", fixed)
            self.assertIn("## 前言", fixed)
            self.assertIn("### 概述", fixed)
            self.assertIn("### 支持材料", fixed)
            self.assertIn("## 致谢", fixed)
            self.assertIn("### 1.1 Start", fixed)
            self.assertLess(fixed.index("## 图书信息"), fixed.index("### PEARSON"))
            self.assertLess(fixed.index("## 图书信息"), fixed.index("## 前言"))


if __name__ == "__main__":
    unittest.main()
