"""GBrain runtime control-plane commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..integrations.gbrain.runtime import (
    RuntimeConfigError,
    load_runtime_config,
    resolve_runtime,
    validate_runtime,
)
from ..integrations.gbrain.setup import setup_runtime
from ..integrations.gbrain.state import save_runtime_state


def cmd_gbrain_runtime_status(args: argparse.Namespace) -> None:
    root = Path(args.project_root or Path.cwd()).resolve()
    try:
        config = load_runtime_config(root)
        resolution = resolve_runtime(root, config)
        validation = validate_runtime(
            resolution,
            config=config,
            expected_version=args.version,
            timeout=args.timeout,
        )
        report = validation.to_dict()
    except RuntimeConfigError as exc:
        report = {
            "status": "failed",
            "path": None,
            "origin": "",
            "version": "",
            "checks": {},
            "error_code": "invalid_runtime_config",
            "error": str(exc),
        }

    save_runtime_state(root, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"GBrain: {report['status']}")
    if report.get("path"):
        print(f"Path: {report['path']}")
    if report.get("version"):
        print(f"Version: {report['version']}")
    if report.get("error_code"):
        print(f"Error: {report['error_code']}")


def add_gbrain_parser(subparsers) -> None:
    parser = subparsers.add_parser("gbrain", help="Manage the optional GBrain runtime")
    commands = parser.add_subparsers(dest="gbrain_command", required=True)
    status = commands.add_parser("runtime-status", help="Discover and validate GBrain")
    status.add_argument("--project-root", default=None, help="Project root directory")
    status.add_argument("--version", default=None, help="Expected GBrain version")
    status.add_argument("--timeout", type=float, default=5.0, help="Probe timeout in seconds")
    status.add_argument("--json", action="store_true", help="Print JSON")
    status.set_defaults(func=cmd_gbrain_runtime_status)
    setup = commands.add_parser("setup", help="Validate or explicitly install GBrain")
    setup.add_argument("--project-root", default=None, help="Project root directory")
    setup.add_argument("--install", action="store_true", help="Confirm download and dependency installation")
    setup.add_argument("--json", action="store_true", help="Print JSON")
    setup.set_defaults(func=cmd_gbrain_setup)


def cmd_gbrain_setup(args: argparse.Namespace) -> None:
    root = Path(args.project_root or Path.cwd()).resolve()
    try:
        config = load_runtime_config(root)
        result = setup_runtime(root, config, install=args.install)
        report = result.to_dict()
    except RuntimeConfigError as exc:
        report = {"status": "failed", "error_code": "invalid_runtime_config", "error": str(exc)}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"GBrain setup: {report['status']}")
    if report.get("error_code"):
        print(f"Error: {report['error_code']}")
