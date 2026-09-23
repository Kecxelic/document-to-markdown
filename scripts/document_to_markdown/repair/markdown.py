"""Fence-aware Markdown slicing and invariant signatures."""

from __future__ import annotations

import hashlib
import html
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


FENCE_RE = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MD_IMAGE_RE = re.compile(r"!\[([^]]*)\]\((?:<([^>]+)>|([^)\s]+))\)")
HTML_IMAGE_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*>', re.IGNORECASE)
LINK_RE = re.compile(r"(?<!!)\[([^]]+)\]\((?:<([^>]+)>|([^)]+))\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_heading(value):
    value = HTML_TAG_RE.sub("", value)
    value = html.unescape(value)
    value = re.sub(r"[*_~`]", "", value)
    value = re.sub(r"\\([#\[\]])", r"\1", value)
    return " ".join(value.split()).strip()


def chapter_number(value):
    value = clean_heading(value)
    match = re.search(r"第\s*(\d{1,3})\s*章", value)
    if match:
        return int(match.group(1))
    if re.match(r"(?i)^part\b", value):
        return None
    match = re.match(r"(?i)^(?:chapter\s+)?(\d{1,3})(?:\b|\s)", value)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class Heading:
    line_index: int
    char_offset: int
    level: int
    raw: str
    clean: str
    number: int | None


@dataclass(frozen=True)
class Unit:
    unit_id: str
    order: int
    title: str
    level: int
    number: int | None
    text: str


@dataclass(frozen=True)
class Signature:
    heading_levels: tuple
    code_hashes: tuple
    image_names: tuple
    external_links: tuple
    internal_link_count: int
    raw_html_counts: dict

    def to_dict(self):
        data = asdict(self)
        data["heading_levels"] = list(self.heading_levels)
        data["code_hashes"] = list(self.code_hashes)
        data["image_names"] = list(self.image_names)
        data["external_links"] = list(self.external_links)
        return data


def headings(text):
    found = []
    active = None
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.rstrip("\r\n")
        fence = FENCE_RE.match(stripped)
        if active is None and fence:
            active = (fence.group(1)[0], len(fence.group(1)))
        elif active is not None:
            if fence and fence.group(1)[0] == active[0] and len(fence.group(1)) >= active[1]:
                active = None
        else:
            match = HEADING_RE.match(stripped)
            if match:
                raw = match.group(2)
                cleaned = clean_heading(raw)
                found.append(
                    Heading(
                        line_index=index,
                        char_offset=offset,
                        level=len(match.group(1)),
                        raw=raw,
                        clean=cleaned,
                        number=chapter_number(cleaned),
                    )
                )
        offset += len(line)
    return found


def detect_unit_level(text):
    found = headings(text)
    numbered = Counter(item.level for item in found if item.number is not None)
    if numbered:
        # Prefer the shallowest repeated numbered level. A translated EPUB may
        # contain a longer numbered FAQ beneath the actual chapter level.
        eligible = [level for level, count in numbered.items() if count >= 2]
        if eligible:
            return min(eligible)
    counts = Counter(item.level for item in found)
    if counts[1] >= 2:
        return 1
    if counts[2] >= 2:
        return 2
    return min(counts) if counts else 1


def split_units(text, level=None):
    level = level or detect_unit_level(text)
    boundaries = [item for item in headings(text) if item.level == level]
    if not boundaries:
        return [Unit("000-document", 0, "document", 0, None, text)]
    units = []
    if boundaries[0].char_offset:
        units.append(Unit("000-preamble", 0, "preamble", 0, None, text[: boundaries[0].char_offset]))
    for position, item in enumerate(boundaries, 1):
        end = boundaries[position].char_offset if position < len(boundaries) else len(text)
        units.append(
            Unit(
                unit_id="{:03d}".format(position),
                order=len(units),
                title=item.clean,
                level=item.level,
                number=item.number,
                text=text[item.char_offset : end],
            )
        )
    return units


def _code_blocks(text):
    active = None
    content = []
    blocks = []
    for line in text.splitlines():
        fence = FENCE_RE.match(line)
        if active is None and fence:
            active = (fence.group(1)[0], len(fence.group(1)))
            content = []
            continue
        if active is not None:
            if fence and fence.group(1)[0] == active[0] and len(fence.group(1)) >= active[1]:
                blocks.append("\n".join(content))
                active = None
            else:
                content.append(line)
    if active is not None:
        raise ValueError("Markdown 中存在未闭合代码围栏")
    return blocks


def _prose_lines(text):
    active = None
    output = []
    for line in text.splitlines():
        fence = FENCE_RE.match(line)
        if active is None and fence:
            active = (fence.group(1)[0], len(fence.group(1)))
            continue
        if active is not None:
            if fence and fence.group(1)[0] == active[0] and len(fence.group(1)) >= active[1]:
                active = None
            continue
        output.append(line)
    return output


def markdown_signature(text):
    found_headings = headings(text)
    prose = "\n".join(_prose_lines(text))
    image_targets = []
    for _, angle, plain in MD_IMAGE_RE.findall(prose):
        image_targets.append(angle or plain)
    image_targets.extend(HTML_IMAGE_RE.findall(prose))
    image_names = tuple(Path(target.replace("\\", "/")).name.casefold() for target in image_targets)
    external = []
    internal_count = 0
    for _, angle, plain in LINK_RE.findall(prose):
        target = (angle or plain).strip()
        parsed = urlparse(target)
        if parsed.scheme in {"http", "https", "mailto"}:
            external.append(target)
        else:
            internal_count += 1
    raw_counts = {
        tag: len(re.findall(r"</?{}\b".format(tag), prose, re.IGNORECASE))
        for tag in ("div", "span", "svg", "figure", "figcaption", "img")
    }
    return Signature(
        heading_levels=tuple(item.level for item in found_headings),
        code_hashes=tuple(sha256_text(block) for block in _code_blocks(text)),
        image_names=image_names,
        external_links=tuple(sorted(external)),
        internal_link_count=internal_count,
        raw_html_counts=raw_counts,
    )


def invariant_failures(base_text, candidate_text, allow_heading_level_changes=False):
    base = markdown_signature(base_text)
    candidate = markdown_signature(candidate_text)
    failures = []
    if allow_heading_level_changes:
        if len(base.heading_levels) != len(candidate.heading_levels):
            failures.append("heading-count")
    elif base.heading_levels != candidate.heading_levels:
        failures.append("heading-levels")
    if base.code_hashes != candidate.code_hashes:
        failures.append("code-blocks")
    if Counter(base.image_names) != Counter(candidate.image_names):
        failures.append("images")
    if Counter(base.external_links) != Counter(candidate.external_links):
        failures.append("external-links")
    if base.internal_link_count != candidate.internal_link_count:
        failures.append("internal-link-count")
    return failures


def heading_structure_failures(text):
    """Return structural heading errors without imposing a single-H1 policy."""
    found = headings(text)
    if not found:
        return ["文档没有可导航标题"]
    failures = []
    if found[0].level != 1:
        failures.append("首个标题不是 H1")
    previous = found[0]
    for current in found[1:]:
        if current.level > previous.level + 1:
            failures.append(
                "标题层级跳跃: {} -> {} ({})".format(
                    previous.level, current.level, current.clean
                )
            )
        previous = current
    return failures
