"""Format-neutral Markdown outline utilities."""

import re
from pathlib import Path


HEADING_POLICIES = ("auto", "single-title", "chapter-h1")


def is_fence(line):
    return line.lstrip().startswith("```")


def heading_parts(line):
    match = re.match(r"^(#{1,6}) (.+)$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2)


def count_heading_levels(md_path):
    """Count H1-H6 while ignoring fenced code blocks."""
    counts = {level: 0 for level in range(1, 7)}
    in_block = False
    for line in Path(md_path).read_text(encoding="utf-8").split("\n"):
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts:
            counts[parts[0]] += 1
    return counts


def ensure_h1(md_path, title):
    """Prepend a document title when no real H1 exists."""
    md_path = Path(md_path)
    if count_heading_levels(md_path)[1] != 0:
        return
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(
        "# {}\n\n{}".format(title, text.lstrip("\ufeff\n")),
        encoding="utf-8",
    )


def _normalized_title(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def normalize_under_title(md_path, title):
    """Put every real heading below one metadata-derived H1."""
    md_path = Path(md_path)
    lines = md_path.read_text(encoding="utf-8").split("\n")

    body = []
    in_block = False
    first_heading_seen = False
    for line in lines:
        if is_fence(line):
            in_block = not in_block
            body.append(line)
            continue
        if not in_block and re.match(r"^#{1,6}\s*$", line):
            continue
        parts = None if in_block else heading_parts(line)
        if parts and not first_heading_seen:
            first_heading_seen = True
            if _normalized_title(parts[1]) == _normalized_title(title):
                continue
        body.append(line)

    levels = []
    in_block = False
    for line in body:
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts:
            levels.append(parts[0])

    shift = 0 if not levels else 2 - min(levels)
    if levels and max(levels) + shift > 6:
        raise ValueError(
            "添加唯一书名 H1 会使正文标题超过 H6；"
            "请改用 chapter-h1 策略，不能把不同层级静默压平到 H6"
        )
    normalized = []
    in_block = False
    for line in body:
        if is_fence(line):
            in_block = not in_block
            normalized.append(line)
            continue
        parts = None if in_block else heading_parts(line)
        if parts:
            level, heading = parts
            level = max(level + shift, 2)
            line = "{} {}".format("#" * level, heading)
        normalized.append(line)

    body_text = "\n".join(normalized).lstrip("\ufeff\n")
    md_path.write_text("# {}\n\n{}".format(title, body_text), encoding="utf-8")


def preserve_chapter_h1(md_path, title):
    """Preserve peer chapters as H1 and remove a redundant metadata title H1."""
    md_path = Path(md_path)
    lines = md_path.read_text(encoding="utf-8").split("\n")

    headings = []
    in_block = False
    for index, line in enumerate(lines):
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts:
            headings.append((index, parts[0], parts[1]))

    redundant_title_index = None
    h1_count = sum(level == 1 for _, level, _ in headings)
    if headings and h1_count > 1:
        index, level, heading = headings[0]
        if level == 1 and _normalized_title(heading) == _normalized_title(title):
            redundant_title_index = index

    preserved = []
    in_block = False
    for index, line in enumerate(lines):
        if is_fence(line):
            in_block = not in_block
            preserved.append(line)
            continue
        if not in_block and re.match(r"^#{1,6}\s*$", line):
            continue
        if index == redundant_title_index:
            continue
        preserved.append(line)

    md_path.write_text("\n".join(preserved).lstrip("\ufeff\n"), encoding="utf-8")


def apply_heading_policy(md_path, title, policy):
    """Apply an explicit, non-lossy document heading policy."""
    if policy == "single-title":
        normalize_under_title(md_path, title)
    elif policy == "chapter-h1":
        preserve_chapter_h1(md_path, title)
    else:
        raise ValueError(
            "未知标题策略: {}（可选: {}）".format(policy, ", ".join(HEADING_POLICIES))
        )


def resolve_heading_policy(md_path, source_format, requested="auto"):
    """Resolve auto from source type and outline shape; explicit values are agent overrides."""
    if requested != "auto":
        if requested not in HEADING_POLICIES:
            raise ValueError(
                "未知标题策略: {}（可选: {}）".format(
                    requested, ", ".join(HEADING_POLICIES)
                )
            )
        return requested

    counts = count_heading_levels(md_path)
    deepest = max((level for level, count in counts.items() if count), default=0)
    multiple_top_sections = counts[1] >= 2
    would_overflow = multiple_top_sections and deepest >= 6

    if would_overflow:
        return "chapter-h1"
    if source_format.casefold() == "epub" and multiple_top_sections:
        return "chapter-h1"
    return "single-title"


def validate_heading_policy(md_path, policy):
    """Validate the H1 invariant selected for this document."""
    counts = count_heading_levels(md_path)
    if policy == "single-title":
        return counts[1] == 1
    if policy == "chapter-h1":
        return counts[1] >= 1
    return False
