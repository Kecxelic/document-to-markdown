"""Final deterministic acceptance checks for repaired Markdown."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from document_to_markdown.repair.markdown import (
    LINK_RE,
    MD_IMAGE_RE,
    HTML_IMAGE_RE,
    heading_structure_failures,
    headings,
    markdown_signature,
    sha256_file,
)
from document_to_markdown.repair.prepare import load_manifest
from document_to_markdown.repair.zh_cn_lint import find_traditional_residue


def _pandoc_metrics(path):
    executable = shutil.which("pandoc")
    if not executable:
        raise RuntimeError("parallel-repair 最终验收需要 Pandoc")
    process = subprocess.run(
        [executable, str(path), "--from", "gfm", "--to", "json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if process.returncode:
        raise RuntimeError("Pandoc 解析失败: {}".format(process.stderr.strip()))
    ast = json.loads(process.stdout)
    counts = Counter()

    def visit(value):
        if isinstance(value, dict):
            kind = value.get("t")
            if kind in {
                "Header", "CodeBlock", "Image", "Link", "RawBlock", "RawInline", "Table"
            }:
                counts[kind] += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(ast)
    return dict(counts)


def _slug(value):
    value = re.sub(r"<[^>]+>", "", value).strip().casefold()
    value = re.sub(r"[^\w\-\s\u4e00-\u9fff]", "", value)
    return re.sub(r"[\s_]+", "-", value).strip("-")


def _image_targets(text):
    targets = [angle or plain for _, angle, plain in MD_IMAGE_RE.findall(text)]
    targets.extend(HTML_IMAGE_RE.findall(text))
    return targets


def _is_zh_cn(value):
    folded = str(value or "").strip().casefold().replace("_", "-")
    return folded in {"zh-cn", "zh-hans", "简体中文", "simplified-chinese"}


def _link_failures(text, root):
    anchors = {_slug(item.clean) for item in headings(text)}
    failures = []
    for label, angle, plain in LINK_RE.findall(text):
        target = unquote((angle or plain).strip())
        parsed = urlparse(target)
        if parsed.scheme in {"http", "https", "mailto"}:
            continue
        if target.startswith("#"):
            if _slug(target[1:]) not in anchors:
                failures.append("未解析的内部锚点: {} -> {}".format(label, target))
            continue
        local = target.split("#", 1)[0]
        if local and not (root / local).resolve().is_file():
            failures.append("未解析的本地链接: {} -> {}".format(label, target))
    return failures


def verify_manifest(manifest_path, traditional_whitelist=None):
    manifest_path, manifest = load_manifest(manifest_path)
    work_dir = Path(manifest["work_dir"])
    receipt_path = work_dir / "merge-receipt.json"
    if not receipt_path.is_file():
        raise ValueError("必须先执行 merge")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    target = Path(receipt["target"])
    if not target.is_file():
        raise ValueError("合并成品不存在: {}".format(target))
    if sha256_file(target) != receipt["target_sha256"]:
        raise ValueError("合并成品哈希与 receipt 不一致")

    text = target.read_text(encoding="utf-8")
    failures = []
    try:
        signature = markdown_signature(text)
    except ValueError as error:
        signature = None
        failures.append(str(error))
    failures.extend(heading_structure_failures(text))
    if signature:
        raw = {key: value for key, value in signature.raw_html_counts.items() if value}
        if raw:
            failures.append("仍有应清理的原始 HTML: {}".format(raw))

    root = target.parent
    referenced = []
    primary_image_hashes = defaultdict(set)
    for record in manifest["primary"]["images"]:
        primary_image_hashes[Path(record["path"]).name.casefold()].add(record["sha256"])
    for raw_target in _image_targets(text):
        parsed = urlparse(unquote(raw_target))
        if parsed.scheme in {"http", "https", "data"}:
            continue
        local = Path(*[part for part in parsed.path.split("/") if part])
        image_path = (root / local).resolve()
        if root.resolve() not in image_path.parents:
            failures.append("图片必须随成品发布，不能指向目录外: {}".format(raw_target))
        elif not image_path.is_file():
            failures.append("图片不存在: {}".format(raw_target))
        else:
            referenced.append(image_path)
            allowed_hashes = primary_image_hashes.get(image_path.name.casefold(), set())
            if sha256_file(image_path) not in allowed_hashes:
                failures.append("图片内容不属于主源或已被修改: {}".format(raw_target))
    image_root = root / "images"
    actual_images = {
        item.resolve() for item in image_root.rglob("*") if item.is_file()
    } if image_root.is_dir() else set()
    orphaned = sorted(str(item.relative_to(root)) for item in actual_images - set(referenced))
    if orphaned:
        failures.append("存在未引用图片: {}".format(", ".join(orphaned)))

    failures.extend(_link_failures(text, root))
    traditional = find_traditional_residue(
        text, whitelist=traditional_whitelist
    ) if _is_zh_cn(manifest.get("target_language")) else []
    if traditional:
        sample = traditional[:20]
        failures.append("仍有繁体字残留 {} 处，示例: {}".format(len(traditional), sample))

    try:
        pandoc = _pandoc_metrics(target)
    except (RuntimeError, json.JSONDecodeError) as error:
        pandoc = {}
        failures.append(str(error))
    raw_nodes = pandoc.get("RawBlock", 0) + pandoc.get("RawInline", 0)
    if raw_nodes:
        failures.append("Pandoc 仍识别到 {} 个原始 HTML/Raw 节点".format(raw_nodes))

    report = {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "target": str(target),
        "target_sha256": sha256_file(target),
        "passed": not failures,
        "failures": failures,
        "markdown_signature": signature.to_dict() if signature else None,
        "pandoc_metrics": pandoc,
        "traditional_residue_count": len(traditional),
        "target_language": manifest.get("target_language"),
        "referenced_image_count": len(referenced),
        "actual_image_count": len(actual_images),
    }
    report_path = work_dir / "verification-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report_path
