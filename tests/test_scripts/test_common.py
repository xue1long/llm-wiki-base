import builtins
import os
import subprocess
import sys
from pathlib import Path

from scripts._common import log_message


def test_log_message_formats_appends_and_flushes(tmp_path, monkeypatch):
    report = tmp_path / "report.txt"
    monkeypatch.setattr("scripts._common.time.strftime", lambda fmt: "12:34:56")
    printed = []

    def fake_print(*args, **kwargs):
        printed.append((args, kwargs))

    monkeypatch.setattr(builtins, "print", fake_print)

    log_message("中文消息", report)
    log_message("second", report)

    assert printed == [
        (("[12:34:56] 中文消息",), {"flush": True}),
        (("[12:34:56] second",), {"flush": True}),
    ]
    assert report.read_text(encoding="utf-8") == "[12:34:56] 中文消息\n[12:34:56] second\n"


def test_scripts_support_direct_help_execution():
    root = Path(__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(root), "PYTHONIOENCODING": "utf-8"}
    for script in ("phase4_batch.py", "pilot_ingest.py"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / script), "--help"],
            cwd=root,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
