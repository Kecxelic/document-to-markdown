"""Explicit-only routing for the high-cost parallel repair mode."""

import re

PARALLEL_REPAIR_MARKERS = ("并行多智能体修复", "[parallel-repair]")
NEGATED_CHINESE_MARKER_RE = re.compile(
    r"(?:不要|不得|禁止|无需|无须|不用|别|不需要)\s*"
    r"(?:使用|启用|进行)?\s*并行多智能体修复"
)


def parallel_repair_requested(prompt):
    """Return True only when the user supplied an explicit opt-in marker."""
    value = str(prompt or "")
    folded = value.casefold()
    if PARALLEL_REPAIR_MARKERS[1] in folded:
        return True
    return (
        PARALLEL_REPAIR_MARKERS[0] in value
        and not NEGATED_CHINESE_MARKER_RE.search(value)
    )


def require_parallel_repair(prompt):
    """Reject expensive preparation before it writes any run artifacts."""
    if not parallel_repair_requested(prompt):
        raise ValueError(
            "高成本修复模式必须由用户显式写出“并行多智能体修复”"
            "或“[parallel-repair]”；普通修复请求不得启动此模式"
        )
