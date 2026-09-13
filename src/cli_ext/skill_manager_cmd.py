"""JSON CLI adapter for Skill Manager."""

from __future__ import annotations

import argparse
import json
import sys

from ..services import skill_manager as service


def _run(fn, args: argparse.Namespace) -> None:
    try:
        print(json.dumps(fn(args), ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"code": getattr(exc, "code", "INVALID_ARGUMENT"), "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_skill_manager_list(args):
    _run(lambda _: service.list_library(), args)


def cmd_skill_manager_inspect(args):
    _run(lambda _: service.inspect_artifact(args.source), args)


def cmd_skill_manager_import(args):
    _run(lambda _: service.import_artifact(args.source, args.plan_hash, args.confirm), args)


def cmd_skill_manager_deploy(args):
    _run(lambda _: service.apply_artifact(args.artifact_id, args.agent, args.plan_hash, args.confirm), args)


def cmd_skill_manager_status(args):
    _run(lambda _: service.get_operation(args.operation_id) if args.operation_id else service.list_operations(), args)


def add_skill_manager_parser(subparsers) -> None:
    parser = subparsers.add_parser("skill-manager", help="Manage static Agent Skills")
    commands = parser.add_subparsers(dest="skill_manager_command", required=True)
    for name, handler in (("list", cmd_skill_manager_list), ("status", cmd_skill_manager_status)):
        child = commands.add_parser(name)
        if name == "status":
            child.add_argument("operation_id", nargs="?")
        child.add_argument("--json", action="store_true")
        child.set_defaults(func=handler)
    child = commands.add_parser("inspect")
    child.add_argument("source")
    child.add_argument("--json", action="store_true")
    child.set_defaults(func=cmd_skill_manager_inspect)
    child = commands.add_parser("import")
    child.add_argument("source")
    child.add_argument("--plan-hash", required=True)
    child.add_argument("--confirm", action="store_true")
    child.add_argument("--json", action="store_true")
    child.set_defaults(func=cmd_skill_manager_import)
    child = commands.add_parser("deploy")
    child.add_argument("artifact_id")
    child.add_argument("--agent", action="append", required=True)
    child.add_argument("--plan-hash", required=True)
    child.add_argument("--confirm", action="store_true")
    child.add_argument("--json", action="store_true")
    child.set_defaults(func=cmd_skill_manager_deploy)
