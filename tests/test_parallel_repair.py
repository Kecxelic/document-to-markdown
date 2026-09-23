import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def _make_documents(root):
    primary = root / "The Book (English)"
    reference = root / "The Book (繁體中文)"
    primary.mkdir()
    reference.mkdir()
    (primary / "images").mkdir()
    (primary / "images" / "diagram.png").write_bytes(b"fake-png-for-link-test")
    (primary / "The Book (English).epub").write_bytes(b"source-epub")
    (reference / "The Book (繁體中文).epub").write_bytes(b"reference-epub")
    (primary / "The Book (English).md").write_text(
        """# The Book

<span class="publisher">A practical guide.</span>

## 1 First

Keep the trusted [source](https://example.com/source).

![Diagram](images/diagram.png)

```python
print("immutable")
```

## 2 Second

Finish the system.
""",
        encoding="utf-8",
    )
    (reference / "The Book (繁體中文).md").write_text(
        """# 這本書

## 推薦序

這是出版社新增內容。

## 第1章 開始

保留可信來源。

## 第2章 完成

完成這套系統。
""",
        encoding="utf-8",
    )
    return primary, reference


def _approve_all(manifest_path):
    from document_to_markdown.repair.markdown import sha256_file

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    work_dir = Path(manifest["work_dir"])
    for unit in manifest["primary_units"]:
        unit_id = unit["unit_id"]
        candidate = work_dir / "candidates" / (unit_id + ".md")
        for role in manifest["required_review_roles"]:
            path = work_dir / "reviews" / role / (unit_id + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "unit_id": unit_id,
                        "role": role,
                        "base_sha256": unit["sha256"],
                        "candidate_sha256": sha256_file(candidate),
                        "approved": True,
                        "unresolved": [],
                        "notes": ["fixture approval"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


class ParallelRepairTests(unittest.TestCase):
    def test_unit_level_prefers_shallow_chapters_over_numbered_appendix_items(self):
        from document_to_markdown.repair.markdown import detect_unit_level

        text = """# Book

## 第1章 One

## 第2章 Two

## 附录

###### 1. Question

###### 2. Question

###### 3. Question
"""
        self.assertEqual(detect_unit_level(text), 2)

    def test_prepare_without_exact_opt_in_makes_no_workspace(self):
        from document_to_markdown.repair.prepare import prepare_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            work_dir = root / "temp" / "forbidden"
            with self.assertRaises(ValueError):
                prepare_workspace(
                    prompt="请修复文档",
                    primary=primary,
                    reference=reference,
                    output=root / "The Book (简体中文)",
                    worker_model="zcode/glm-5.3-flash",
                    target_language="zh-CN",
                    work_dir=work_dir,
                    host_capability_confirmed=True,
                )
            self.assertFalse(work_dir.exists())

    def test_prepare_requires_confirmed_host_capability_before_writes(self):
        from document_to_markdown.repair.prepare import prepare_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            work_dir = root / "temp" / "unconfirmed"
            with self.assertRaises(ValueError):
                prepare_workspace(
                    prompt="并行多智能体修复这本书",
                    primary=primary,
                    reference=reference,
                    output=root / "The Book (简体中文)",
                    worker_model="zcode/glm-5.3-flash",
                    target_language="zh-CN",
                    work_dir=work_dir,
                    host_capability_confirmed=False,
                )
            self.assertFalse(work_dir.exists())

    def test_prepare_aligns_chapters_and_excludes_reference_only_preface(self):
        from document_to_markdown.repair.prepare import prepare_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            manifest_path = prepare_workspace(
                prompt="[parallel-repair] make zh-CN",
                primary=primary,
                reference=reference,
                output=root / "The Book (简体中文)",
                worker_model="zcode/glm-5.3-flash",
                target_language="zh-CN",
                host_capability_confirmed=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            aligned = [item for item in manifest["alignment"] if item["state"] == "aligned"]
            reference_only = [
                item for item in manifest["alignment"] if item["state"] == "reference-only"
            ]
            self.assertGreaterEqual(len(aligned), 3)
            self.assertTrue(reference_only)
            self.assertTrue(manifest["source_policy"]["reference_only_content_is_excluded"])
            self.assertFalse((root / "The Book (简体中文)").exists())

    def test_merge_rejects_changed_code_even_if_reviews_would_approve(self):
        from document_to_markdown.repair.merge import merge_candidates
        from document_to_markdown.repair.prepare import prepare_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            manifest_path = prepare_workspace(
                prompt="并行多智能体修复",
                primary=primary,
                reference=reference,
                output=root / "The Book (简体中文)",
                worker_model="zcode/glm-5.3-flash",
                target_language="zh-CN",
                host_capability_confirmed=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            work_dir = Path(manifest["work_dir"])
            code_unit = next(
                item for item in manifest["primary_units"] if item["signature"]["code_hashes"]
            )
            candidate = work_dir / "candidates" / (code_unit["unit_id"] + ".md")
            candidate.write_text(
                candidate.read_text(encoding="utf-8").replace("immutable", "changed"),
                encoding="utf-8",
            )
            _approve_all(manifest_path)
            with self.assertRaisesRegex(ValueError, "code-blocks"):
                merge_candidates(manifest_path)

    def test_merge_rejects_any_source_asset_change(self):
        from document_to_markdown.repair.merge import merge_candidates
        from document_to_markdown.repair.prepare import prepare_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            manifest_path = prepare_workspace(
                prompt="并行多智能体修复",
                primary=primary,
                reference=reference,
                output=root / "The Book (简体中文)",
                worker_model="zcode/glm-5.3-flash",
                target_language="zh-CN",
                host_capability_confirmed=True,
            )
            (primary / "The Book (English).epub").write_bytes(b"unexpected-change")
            with self.assertRaisesRegex(ValueError, "primary 源目录"):
                merge_candidates(manifest_path)

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required")
    def test_reviewed_content_and_format_repair_verifies_and_publishes(self):
        from document_to_markdown.repair.merge import merge_candidates, publish_output
        from document_to_markdown.repair.prepare import prepare_workspace
        from document_to_markdown.repair.verify import verify_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, reference = _make_documents(root)
            primary_md = primary / "The Book (English).md"
            reference_md = reference / "The Book (繁體中文).md"
            source_before = primary_md.read_bytes()
            reference_before = reference_md.read_bytes()
            output = root / "The Book (简体中文)"
            manifest_path = prepare_workspace(
                prompt="并行多智能体修复这本书",
                primary=primary,
                reference=reference,
                output=output,
                worker_model="zcode/glm-5.3-flash",
                target_language="zh-CN",
                host_capability_confirmed=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            work_dir = Path(manifest["work_dir"])
            replacements = {
                "000-preamble": "# 这本书\n\n一本实用指南。\n",
                "001": """## 1 开始

保留可信的[来源](https://example.com/source)。

![示意图](images/diagram.png)

```python
print("immutable")
```
""",
                "002": "## 2 完成\n\n完成这套系统。\n",
            }
            for unit_id, text in replacements.items():
                (work_dir / "candidates" / (unit_id + ".md")).write_text(
                    text, encoding="utf-8"
                )
            _approve_all(manifest_path)
            merge_candidates(manifest_path)
            report_path = verify_manifest(manifest_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"], report["failures"])
            published = publish_output(manifest_path, report_path)

            self.assertEqual(published.resolve(), output.resolve())
            self.assertTrue((output / "The Book (简体中文).md").is_file())
            self.assertTrue((output / "images" / "diagram.png").is_file())
            self.assertEqual(primary_md.read_bytes(), source_before)
            self.assertEqual(reference_md.read_bytes(), reference_before)

    def test_traditional_residue_lint_is_conservative_and_actionable(self):
        from document_to_markdown.repair.zh_cn_lint import find_traditional_residue

        findings = find_traditional_residue("这是简体。這是繁體。")
        self.assertEqual([item["traditional"] for item in findings], ["這", "體"])
        self.assertEqual(find_traditional_residue("這", whitelist=["這"]), [])


if __name__ == "__main__":
    unittest.main()
