"""Deterministic control plane for the explicit parallel-repair mode."""

import argparse
import json
import sys

from document_to_markdown.repair.inventory import inventory_document
from document_to_markdown.repair.merge import merge_candidates, publish_output
from document_to_markdown.repair.prepare import prepare_workspace
from document_to_markdown.repair.routing import parallel_repair_requested
from document_to_markdown.repair.verify import verify_manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="已转换 Markdown 的显式并行多智能体内容与格式修复控制面"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route", help="判断一句请求是否显式启用高成本模式")
    route.add_argument("--prompt", required=True)

    inventory = subparsers.add_parser("inventory", help="只读统计已转换目录")
    inventory.add_argument("path")

    prepare = subparsers.add_parser("prepare", help="生成隔离工作区与 worker 任务包")
    prepare.add_argument("--prompt", required=True)
    prepare.add_argument("--primary", required=True)
    prepare.add_argument("--reference", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--worker-model", required=True)
    prepare.add_argument("--target-language", required=True, help="例如 zh-CN 或 en")
    prepare.add_argument("--work-dir")
    prepare.add_argument(
        "--host-capability-confirmed",
        action="store_true",
        help="调用者已在写入前确认宿主支持原生并行 agent 与指定模型",
    )

    merge = subparsers.add_parser("merge", help="校验三类审查记录并合并候选单元")
    merge.add_argument("--manifest", required=True)

    verify = subparsers.add_parser("verify", help="对暂存成品执行最终硬验收")
    verify.add_argument("--manifest", required=True)
    verify.add_argument(
        "--allow-traditional-char",
        action="append",
        default=[],
        help="允许保留的单个繁体字符；可重复",
    )

    publish = subparsers.add_parser("publish", help="验收通过后原子发布新目录")
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--report", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "route":
            enabled = parallel_repair_requested(args.prompt)
            print(json.dumps({"parallel_repair": enabled}, ensure_ascii=False))
            return 0 if enabled else 2
        if args.command == "inventory":
            print(json.dumps(inventory_document(args.path).to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "prepare":
            path = prepare_workspace(
                prompt=args.prompt,
                primary=args.primary,
                reference=args.reference,
                output=args.output,
                worker_model=args.worker_model,
                target_language=args.target_language,
                work_dir=args.work_dir,
                host_capability_confirmed=args.host_capability_confirmed,
            )
        elif args.command == "merge":
            path = merge_candidates(args.manifest)
        elif args.command == "verify":
            path = verify_manifest(
                args.manifest, traditional_whitelist=args.allow_traditional_char
            )
        else:
            path = publish_output(args.manifest, args.report)
        print(path)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
