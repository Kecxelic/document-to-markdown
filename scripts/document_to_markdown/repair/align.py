"""Conservative unit alignment for bilingual converted documents."""

from __future__ import annotations

from collections import defaultdict


def _kind(title):
    folded = title.casefold()
    compact = "".join(folded.split())
    if any(
        value in compact
        for value in ("appendix", "bonus", "frequentlyasked", "附錄", "附录")
    ):
        return "appendix"
    if any(value in compact for value in ("introduction", "引言")):
        return "introduction"
    if any(value in compact for value in ("推薦序", "推荐序", "foreword")):
        return "recommendation-preface"
    if any(value in compact for value in ("alsoby", "作者其他作品")):
        return "also-by"
    if compact.startswith("part") or compact.startswith("第") and "部" in compact[:6]:
        return "part"
    if title == "preamble":
        return "preamble"
    return "other"


def align_units(primary_units, reference_units):
    """Return deterministic mappings and leave unsafe guesses explicit."""
    by_number = defaultdict(list)
    by_kind = defaultdict(list)
    for unit in reference_units:
        if unit.number is not None:
            by_number[unit.number].append(unit)
        else:
            by_kind[_kind(unit.title)].append(unit)
    used = set()
    mentioned = set()
    mappings = []
    for primary in primary_units:
        candidates = []
        reason = ""
        if primary.number is not None:
            candidates = [item for item in by_number.get(primary.number, []) if item.unit_id not in used]
            reason = "chapter-number"
        else:
            category = _kind(primary.title)
            candidates = [] if category == "other" else [
                item for item in by_kind.get(category, []) if item.unit_id not in used
            ]
            reason = category
        if len(candidates) == 1:
            reference = candidates[0]
            used.add(reference.unit_id)
            state = "aligned"
            reference_ids = [reference.unit_id]
        elif not candidates:
            state = "primary-only"
            reference_ids = []
        else:
            state = "ambiguous"
            reference_ids = [item.unit_id for item in candidates]
            mentioned.update(reference_ids)
        mappings.append(
            {
                "primary_unit": primary.unit_id,
                "reference_units": reference_ids,
                "state": state,
                "reason": reason,
            }
        )
    for reference in reference_units:
        if reference.unit_id not in used and reference.unit_id not in mentioned:
            mappings.append(
                {
                    "primary_unit": None,
                    "reference_units": [reference.unit_id],
                    "state": "reference-only",
                    "reason": _kind(reference.title),
                }
            )
    return mappings
