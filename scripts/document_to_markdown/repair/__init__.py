"""Deterministic support for explicitly requested parallel document repair."""

from document_to_markdown.repair.routing import (
    PARALLEL_REPAIR_MARKERS,
    parallel_repair_requested,
    require_parallel_repair,
)

__all__ = [
    "PARALLEL_REPAIR_MARKERS",
    "parallel_repair_requested",
    "require_parallel_repair",
]
