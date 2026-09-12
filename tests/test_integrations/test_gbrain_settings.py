from __future__ import annotations

import json
import subprocess

import pytest

from src.integrations.gbrain.settings import (
    GBrainSettingsError,
    apply_search_mode,
    read_search_mode,
)


def test_read_search_mode_parses_gbrain_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.gbrain.settings._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, json.dumps({"active_mode": "balanced"}), ""
        ),
    )

    assert read_search_mode(tmp_path) == "balanced"


def test_apply_search_mode_reads_back_effective_value(monkeypatch, tmp_path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[1:])
        return subprocess.CompletedProcess([], 0, json.dumps({"active_mode": "tokenmax"}), "")

    monkeypatch.setattr("src.integrations.gbrain.settings._run", fake_run)

    assert apply_search_mode(tmp_path, "tokenmax") == {"gbrain_mode": "tokenmax"}
    assert calls[0] == ("config", "set", "search.mode", "tokenmax")


def test_read_search_mode_rejects_unparseable_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.gbrain.settings._run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "not-json", ""),
    )

    with pytest.raises(GBrainSettingsError, match="search_modes_invalid"):
        read_search_mode(tmp_path)


def test_run_uses_utf8_for_gbrain_diagnostics(monkeypatch, tmp_path):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0, json.dumps({"active_mode": "balanced"}), "")

    monkeypatch.setattr("src.integrations.gbrain.settings.subprocess.run", fake_run)
    monkeypatch.setattr("src.integrations.gbrain.settings.shutil.which", lambda name: "bun")

    assert read_search_mode(tmp_path) == "balanced"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_read_search_mode_fails_closed_when_runtime_path_is_stale(monkeypatch, tmp_path):
    monkeypatch.setattr("src.integrations.gbrain.settings.shutil.which", lambda name: "bun")
    def fail_run(*args, **kwargs):
        raise FileNotFoundError("stale runtime")

    monkeypatch.setattr("src.integrations.gbrain.settings.subprocess.run", fail_run)

    with pytest.raises(GBrainSettingsError, match="search_command_failed"):
        read_search_mode(tmp_path)
