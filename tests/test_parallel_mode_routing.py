import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class ParallelModeRoutingTests(unittest.TestCase):
    def test_exact_chinese_marker_enables_mode(self):
        from document_to_markdown.repair.routing import parallel_repair_requested

        self.assertTrue(parallel_repair_requested("请并行多智能体修复这本书"))

    def test_bracket_marker_is_case_insensitive(self):
        from document_to_markdown.repair.routing import parallel_repair_requested

        self.assertTrue(parallel_repair_requested("[PARALLEL-REPAIR] repair this book"))

    def test_vague_repair_language_never_enables_mode(self):
        from document_to_markdown.repair.routing import parallel_repair_requested

        prompts = (
            "修复文档格式和内容",
            "把繁体中文转换成简体中文",
            "用多个 agent 提高质量",
            "优化 Obsidian 阅读体验",
            "parallel repair this document",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(parallel_repair_requested(prompt))

    def test_explicitly_negated_chinese_marker_does_not_enable_mode(self):
        from document_to_markdown.repair.routing import parallel_repair_requested

        self.assertFalse(parallel_repair_requested("不要并行多智能体修复，只做普通检查"))

    def test_skill_documents_exact_opt_in_and_no_silent_fallback(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("并行多智能体修复", text)
        self.assertIn("[parallel-repair]", text)
        self.assertIn("不得静默换模型", text)
        self.assertIn("不得直接调用任何模型厂商 API", text)


if __name__ == "__main__":
    unittest.main()
