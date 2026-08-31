from __future__ import annotations

import argparse
import json

from src.cli_ext.readiness_cmd import cmd_readiness_compare, cmd_readiness_inventory
from src.pipeline.readiness_audit import write_readiness_record


def _record(policy_version: str = "content-policy-v1") -> dict:
    return {
        "assessment_version": "content-readiness-v1",
        "policy_version": policy_version,
        "source_id": "raw/sources/example.md",
        "decision": "skip_no_content",
        "reason_codes": ["metadata_only"],
        "input_text_sha256": "a" * 64,
        "evidence_capacity": {"blocks": 0, "chars": 0, "units": 0},
    }


def test_readiness_inventory_is_read_only_and_json(tmp_path, capsys) -> None:
    write_readiness_record(tmp_path, _record())

    cmd_readiness_inventory(argparse.Namespace(project=str(tmp_path), json=True))

    report = json.loads(capsys.readouterr().out)
    assert report["count"] == 1
    assert report["decisions"] == {"skip_no_content": 1}


def test_readiness_compare_is_read_only(tmp_path, capsys) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps(_record()), encoding="utf-8")
    new.write_text(json.dumps(_record(policy_version="content-policy-v0")), encoding="utf-8")

    cmd_readiness_compare(argparse.Namespace(old=str(old), new=str(new), json=True))

    report = json.loads(capsys.readouterr().out)
    assert report["policy_version"]["old"] == "content-policy-v1"
