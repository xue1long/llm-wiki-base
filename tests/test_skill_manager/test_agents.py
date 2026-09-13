from __future__ import annotations

from pathlib import Path

import pytest

from src.skill_manager.agents import (
    AgentTargetError,
    DeploymentMarker,
    discover_targets,
    resolve_custom_target,
)


def test_default_agent_discovery_uses_user_skill_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.skill_manager.agents.Path.home", lambda: tmp_path)

    targets = {target.id: target for target in discover_targets()}

    assert targets["codex"].path == tmp_path / ".codex" / "skills"
    assert targets["claude_code"].path == tmp_path / ".claude" / "skills"


def test_custom_target_must_stay_inside_allowed_root_and_exist(tmp_path: Path):
    allowed = tmp_path / "agents"
    custom = allowed / "skills"
    custom.mkdir(parents=True)

    target = resolve_custom_target("project", custom, allowed_root=allowed)

    assert target.id == "project"
    assert target.path == custom.resolve()

    with pytest.raises(AgentTargetError) as exc_info:
        resolve_custom_target("escape", allowed / ".." / "outside", allowed_root=allowed)
    assert exc_info.value.code == "TARGET_OUTSIDE_ALLOWED_ROOT"


def test_deployment_marker_round_trips():
    marker = DeploymentMarker(
        artifact_id="skill-a",
        content_hash="b" * 64,
        installed_at=123,
        manager_version="1",
        files=("SKILL.md", "references/guide.md"),
    )

    assert DeploymentMarker.from_dict(marker.to_dict()) == marker
