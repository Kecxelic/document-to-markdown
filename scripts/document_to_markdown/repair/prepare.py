"""Prepare an isolated, auditable workspace for parallel document repair."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from document_to_markdown.repair.align import align_units
from document_to_markdown.repair.inventory import inventory_document
from document_to_markdown.repair.markdown import markdown_signature, sha256_file, split_units
from document_to_markdown.repair.routing import require_parallel_repair


REQUIRED_REVIEW_ROLES = ("fidelity", "zh-cn-editor", "format")


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_within(path, parent):
    path = Path(path).resolve()
    parent = Path(parent).resolve()
    return path == parent or parent in path.parents


def _unit_record(unit, relative_path):
    return {
        "unit_id": unit.unit_id,
        "order": unit.order,
        "title": unit.title,
        "level": unit.level,
        "number": unit.number,
        "path": relative_path.as_posix(),
        "sha256": sha256_file(relative_path),
        "signature": markdown_signature(unit.text).to_dict(),
    }


def _absolute_record(unit, path, work_dir):
    record = _unit_record(unit, path)
    record["path"] = path.relative_to(work_dir).as_posix()
    return record


def prepare_workspace(
    prompt,
    primary,
    reference,
    output,
    worker_model,
    target_language,
    work_dir=None,
    host_capability_confirmed=False,
):
    """Create work packets only after explicit opt-in and host/model confirmation."""
    require_parallel_repair(prompt)
    if not host_capability_confirmed:
        raise ValueError("写入前必须确认当前宿主支持并行多智能体及指定模型")
    if not str(worker_model).strip():
        raise ValueError("必须显式记录并行 worker 使用的模型")
    if not str(target_language).strip():
        raise ValueError("必须显式记录目标语言")

    primary_inventory = inventory_document(primary)
    reference_inventory = inventory_document(reference)
    if Path(primary_inventory.markdown) == Path(reference_inventory.markdown):
        raise ValueError("主源与参考译本不能是同一个 Markdown 文件")

    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("目标目录已存在，拒绝覆盖: {}".format(output))
    for source_root in (primary_inventory.root, reference_inventory.root):
        if _is_within(output, source_root):
            raise ValueError("目标目录不能位于源目录内部: {}".format(output))

    primary_root = Path(primary_inventory.root)
    work_dir = Path(work_dir).resolve() if work_dir else (
        primary_root.parent / "temp" / "parallel-repair" / output.name
    ).resolve()
    if work_dir.exists():
        raise FileExistsError("并行修复工作区已存在，拒绝复用: {}".format(work_dir))
    for source_root in (primary_inventory.root, reference_inventory.root):
        if _is_within(work_dir, source_root):
            raise ValueError("工作区不能位于源目录内部: {}".format(work_dir))
    if _is_within(work_dir, output) or _is_within(output, work_dir):
        raise ValueError("工作区与最终目标目录不能互相嵌套")
    if work_dir.anchor.casefold() != output.anchor.casefold():
        raise ValueError("为保证原子发布，工作区与目标目录必须位于同一卷")

    primary_text = Path(primary_inventory.markdown).read_text(encoding="utf-8")
    reference_text = Path(reference_inventory.markdown).read_text(encoding="utf-8")
    primary_units = split_units(primary_text)
    reference_units = split_units(reference_text)
    mappings = align_units(primary_units, reference_units)

    # All checks above are read-only. This is the first mutation.
    (work_dir / "snapshots").mkdir(parents=True)
    (work_dir / "units" / "primary").mkdir(parents=True)
    (work_dir / "units" / "reference").mkdir(parents=True)
    (work_dir / "candidates").mkdir(parents=True)
    (work_dir / "reviews").mkdir(parents=True)
    staging_output = work_dir / "staging_output"
    staging_output.mkdir(parents=True)

    primary_snapshot = work_dir / "snapshots" / "primary.md"
    reference_snapshot = work_dir / "snapshots" / "reference.md"
    shutil.copy2(primary_inventory.markdown, primary_snapshot)
    shutil.copy2(reference_inventory.markdown, reference_snapshot)

    image_source = primary_root / "images"
    if image_source.is_dir():
        shutil.copytree(image_source, staging_output / "images")

    primary_records = []
    reference_records = []
    for unit in primary_units:
        unit_path = work_dir / "units" / "primary" / (unit.unit_id + ".md")
        unit_path.write_text(unit.text, encoding="utf-8")
        candidate_path = work_dir / "candidates" / (unit.unit_id + ".md")
        candidate_path.write_text(unit.text, encoding="utf-8")
        primary_records.append(_absolute_record(unit, unit_path, work_dir))
    for unit in reference_units:
        unit_path = work_dir / "units" / "reference" / (unit.unit_id + ".md")
        unit_path.write_text(unit.text, encoding="utf-8")
        reference_records.append(_absolute_record(unit, unit_path, work_dir))

    mapping_by_primary = {
        item["primary_unit"]: item for item in mappings if item["primary_unit"] is not None
    }
    tasks = []
    for record in primary_records:
        mapping = mapping_by_primary[record["unit_id"]]
        task = {
            "unit_id": record["unit_id"],
            "worker_model": str(worker_model),
            "target_language": str(target_language),
            "primary_path": record["path"],
            "reference_paths": [
                "units/reference/{}.md".format(unit_id)
                for unit_id in mapping["reference_units"]
            ],
            "candidate_path": "candidates/{}.md".format(record["unit_id"]),
            "alignment": mapping,
            "authority": {
                "content_and_structure": "primary",
                "translation_reference": "advisory-only",
                "reference_only_content": "excluded-unless-explicitly-approved",
            },
            "immutable_invariants": [
                "heading-count",
                "code-blocks",
                "images",
                "external-links",
                "internal-link-count",
            ],
            "mutable_with-review": ["prose", "heading-text", "heading-levels", "markdown-format"],
            "required_reviews": list(REQUIRED_REVIEW_ROLES),
            "primary_character_count": len(
                (work_dir / record["path"]).read_text(encoding="utf-8")
            ),
        }
        task_path = work_dir / "tasks" / (record["unit_id"] + ".json")
        _write_json(task_path, task)
        tasks.append(task_path.relative_to(work_dir).as_posix())

    manifest = {
        "schema_version": 1,
        "mode": "parallel-repair",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "explicit_prompt": str(prompt),
        "worker_model": str(worker_model),
        "target_language": str(target_language),
        "host_capability_confirmed": True,
        "work_dir": str(work_dir),
        "output": str(output),
        "target_name": output.name,
        "staging_output": str(staging_output),
        "required_review_roles": list(REQUIRED_REVIEW_ROLES),
        "source_policy": {
            "primary_is_authoritative": True,
            "reference_is_advisory": True,
            "sources_are_immutable": True,
            "reference_only_content_is_excluded": True,
        },
        "primary": primary_inventory.to_dict(),
        "reference": reference_inventory.to_dict(),
        "snapshot_hashes": {
            "primary": sha256_file(primary_snapshot),
            "reference": sha256_file(reference_snapshot),
        },
        "primary_units": primary_records,
        "reference_units": reference_records,
        "alignment": mappings,
        "tasks": tasks,
    }
    manifest_path = work_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def load_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("mode") != "parallel-repair":
        raise ValueError("不是 parallel-repair manifest: {}".format(path))
    return path, data


def assert_sources_unchanged(manifest):
    for label in ("primary", "reference"):
        expected = manifest[label]
        current = inventory_document(expected["markdown"]).to_dict()
        if current != expected:
            raise ValueError("{} 源目录在任务期间发生变化，停止操作".format(label))
