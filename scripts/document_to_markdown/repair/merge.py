"""Hash-gated merge and publication for reviewed repair candidates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from document_to_markdown.repair.markdown import invariant_failures, sha256_file
from document_to_markdown.repair.prepare import assert_sources_unchanged, load_manifest


def _load_review(path, unit_id, role, base_sha256, candidate_sha256):
    if not path.is_file():
        raise ValueError("缺少 {} 审查: unit={} path={}".format(role, unit_id, path))
    review = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "unit_id": unit_id,
        "role": role,
        "base_sha256": base_sha256,
        "candidate_sha256": candidate_sha256,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise ValueError("审查记录过期或对象不匹配: {} {}".format(path, key))
    if review.get("approved") is not True:
        raise ValueError("审查未批准: {}".format(path))
    if review.get("unresolved"):
        raise ValueError("审查仍有未解决问题: {}".format(path))
    return review


def merge_candidates(manifest_path):
    _, manifest = load_manifest(manifest_path)
    work_dir = Path(manifest["work_dir"])
    assert_sources_unchanged(manifest)
    snapshot = work_dir / "snapshots" / "primary.md"
    if sha256_file(snapshot) != manifest["snapshot_hashes"]["primary"]:
        raise ValueError("主源快照哈希已变化，停止合并")

    chunks = []
    candidate_hashes = {}
    for record in sorted(manifest["primary_units"], key=lambda item: item["order"]):
        unit_id = record["unit_id"]
        base_path = work_dir / record["path"]
        candidate_path = work_dir / "candidates" / (unit_id + ".md")
        if not candidate_path.is_file():
            raise ValueError("缺少候选单元: {}".format(candidate_path))
        if sha256_file(base_path) != record["sha256"]:
            raise ValueError("主源单元哈希已变化: {}".format(unit_id))
        base_text = base_path.read_text(encoding="utf-8")
        candidate_text = candidate_path.read_text(encoding="utf-8")
        failures = invariant_failures(
            base_text, candidate_text, allow_heading_level_changes=True
        )
        if failures:
            raise ValueError(
                "候选单元破坏硬约束: {} {}".format(unit_id, ", ".join(failures))
            )
        candidate_sha256 = sha256_file(candidate_path)
        candidate_hashes[unit_id] = candidate_sha256
        for role in manifest["required_review_roles"]:
            _load_review(
                work_dir / "reviews" / role / (unit_id + ".json"),
                unit_id,
                role,
                record["sha256"],
                candidate_sha256,
            )
        chunks.append(candidate_text.rstrip())

    target = Path(manifest["staging_output"]) / (manifest["target_name"] + ".md")
    target.write_text("\n\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    receipt = {
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "target_sha256": sha256_file(target),
        "candidate_hashes": candidate_hashes,
    }
    receipt_path = work_dir / "merge-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt_path


def publish_output(manifest_path, report_path):
    _, manifest = load_manifest(manifest_path)
    work_dir = Path(manifest["work_dir"])
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("验收报告未通过，拒绝发布")
    if Path(report.get("manifest", "")).resolve() != Path(manifest_path).resolve():
        raise ValueError("验收报告不属于当前 manifest")
    merge_receipt = json.loads((work_dir / "merge-receipt.json").read_text(encoding="utf-8"))
    merged = Path(merge_receipt["target"])
    if report.get("target_sha256") != merge_receipt["target_sha256"]:
        raise ValueError("验收报告已过期，拒绝发布")
    if sha256_file(merged) != merge_receipt["target_sha256"]:
        raise ValueError("验收后成品发生变化，拒绝发布")
    assert_sources_unchanged(manifest)

    staging = Path(manifest["staging_output"])
    output = Path(manifest["output"])
    if output.exists():
        raise FileExistsError("目标目录已存在，拒绝覆盖: {}".format(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, output)
    publication = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output),
        "markdown_sha256": merge_receipt["target_sha256"],
        "report": str(report_path),
    }
    publication_path = work_dir / "publication.json"
    publication_path.write_text(
        json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output
