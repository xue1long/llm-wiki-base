"""R10 — heat restore/archive write ops routed through a service.

Audit: server routes (heat.py) called wiki.storage write_page / shutil.move
directly, bypassing the service layer — replacing storage later would
touch routes, and route logic duplicated CLI logic. R10 extracts the
write operations into src/services/heat.py so routes are thin adapters.

Coverage:
- services.heat.restore_zombies updates heat/immutability and persists.
- services.heat.archive_zombies moves pages to _archive/.
- The HTTP routes delegate to the service (behavior preserved).
"""
import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.services import heat as heat_service
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage

app = create_app()
client = TestClient(app)


def _paths(tmp_path) -> WikiPaths:
    root = tmp_path / "kb"
    root.mkdir(exist_ok=True)
    for sub in ("sources", "entities", "concepts", "synthesis"):
        (root / "wiki" / sub).mkdir(parents=True, exist_ok=True)
    return WikiPaths(root)


def _write(paths: WikiPaths, page: WikiPage) -> None:
    from src.wiki.storage.page_writer import write_page
    write_page(paths, page)


def _zombie_page(pid: str, heat: int = 0, zombie_since: int = 1) -> WikiPage:
    return WikiPage(
        id=pid, title=pid, type=PageType.CONCEPT, body="x",
        heat=heat, zombie_since=zombie_since,
    )


def _patch_resolve(monkeypatch, tmp_path):
    from src.project.context import ProjectContext
    paths = _paths(tmp_path)  # creates kb + wiki subdirs
    monkeypatch.setattr(
        "src.services.heat.resolve_project",
        lambda pid, by_id_only=True: (
            ProjectContext(identity=type("I", (), {"id": "u"})(),
                           path=tmp_path / "kb", name="p", schema_version="v2.0"),
            paths,
        ),
    )
    return paths


# ---------------------------------------------------------------------------
# 1. service restore
# ---------------------------------------------------------------------------

def test_restore_zombies_updates_and_persists(monkeypatch, tmp_path):
    """V4 (ADR-002): heat/is_immutable/zombie_since are NOT serialized.

    restore_zombies() still runs (returns the right count) and updates
    the in-memory page, but on disk the V4 8-key whitelist excludes
    these fields. After re-read, heat/is_immutable/zombie_since are the
    defaults (50 / False / None).
    """
    paths = _paths(tmp_path)
    p = _zombie_page("z1")
    _write(paths, p)
    _patch_resolve(monkeypatch, tmp_path)

    result = heat_service.restore_zombies("proj", ["z1"])
    assert result == {"restored": 1}

    from src.wiki.storage.page_writer import read_page
    from src.wiki.features.heat import _infer_type
    from src.wiki.storage.page_writer import page_path_for
    f = page_path_for(paths, _infer_type(paths, "z1"), "z1")
    restored = read_page(f)
    # V4: heat/is_immutable/zombie_since are in-memory only.
    assert restored.heat == 50  # default (was 100 in V2)
    assert restored.is_immutable is False  # default (was True in V2)
    assert restored.zombie_since is None  # default (cleared correctly)


def test_restore_missing_page_noop(monkeypatch, tmp_path):
    _patch_resolve(monkeypatch, tmp_path)
    result = heat_service.restore_zombies("proj", ["ghost"])
    assert result == {"restored": 0}


# ---------------------------------------------------------------------------
# 2. service archive
# ---------------------------------------------------------------------------

def test_archive_zombies_moves_page(monkeypatch, tmp_path):
    paths = _paths(tmp_path)
    p = _zombie_page("z2")
    _write(paths, p)
    _patch_resolve(monkeypatch, tmp_path)

    result = heat_service.archive_zombies("proj", ["z2"])
    assert result == {"archived": 1}
    archive_dir = paths.wiki / "_archive"
    assert (archive_dir / "z2.md").exists()
    assert not (paths.wiki / "concepts" / "z2.md").exists()


def test_archive_missing_page_noop(monkeypatch, tmp_path):
    _patch_resolve(monkeypatch, tmp_path)
    result = heat_service.archive_zombies("proj", ["ghost"])
    assert result == {"archived": 0}


# ---------------------------------------------------------------------------
# 3. HTTP routes delegate to the service
# ---------------------------------------------------------------------------

def test_route_restore_delegates(monkeypatch, tmp_path):
    from src.server.routes import heat as heat_route
    monkeypatch.setattr(
        heat_route, "resolve_project",
        lambda pid, by_id_only=True: (None, None),
    )
    monkeypatch.setattr(
        heat_service, "restore_zombies", lambda pid, ids: {"restored": 3},
    )
    r = client.post("/api/v1/projects/x/heat/zombies/restore",
                    json={"page_ids": ["a", "b", "c"]})
    assert r.status_code == 200
    assert r.json() == {"restored": 3}


def test_route_archive_delegates(monkeypatch, tmp_path):
    from src.server.routes import heat as heat_route
    monkeypatch.setattr(
        heat_route, "resolve_project",
        lambda pid, by_id_only=True: (None, None),
    )
    monkeypatch.setattr(
        heat_service, "archive_zombies", lambda pid, ids: {"archived": 2},
    )
    r = client.post("/api/v1/projects/x/heat/zombies/archive",
                    json={"page_ids": ["a", "b"]})
    assert r.status_code == 200
    assert r.json() == {"archived": 2}
