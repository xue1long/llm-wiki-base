"""Tests for src/wiki/zombie.py.

V4 (ADR-002, 2026-08-31): zombie_since is NOT serialized to disk.
Therefore list_zombies() (which reads pages from disk and filters by
zombie_since) will always return empty in a V4 wiki, because zombie
state lives only in memory.

generate_staging_draft() still works on an in-memory WikiPage and writes
a staging draft to .index/staging/.
"""
import tempfile
import pathlib

from src.wiki.features.zombie import ZombieDetector
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page, read_page, page_path_for


def test_zombie_state_lost_on_v4_write():
    """V4 contract: zombie_since is dropped on write. Reading back yields None."""
    with tempfile.TemporaryDirectory() as td:
        tmp_path = pathlib.Path(td)
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        write_page(
            paths,
            WikiPage(id="z1", title="Z", type=PageType.ENTITY, body="", zombie_since=12345),
        )

        # V4: zombie_since is in-memory only — page read back has zombie_since=None.
        p = read_page(page_path_for(paths, PageType.ENTITY, "z1"))
        assert p.zombie_since is None, "V4: zombie_since is not persisted"

        # list_zombies (which reads from disk) finds no zombies.
        zombies = ZombieDetector.list_zombies(paths)
        assert zombies == [], "V4: zombie_since never persisted → no zombies found"


def test_generate_staging_draft(tmp_path):
    """generate_staging_draft creates a .index/staging/ file (in-memory only)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(id="z1", title="Zombie", type=PageType.ENTITY, body="...",
                    heat=0, last_used_at=0)

    draft_path = ZombieDetector.generate_staging_draft(paths, page)
    assert draft_path.exists()
    assert "z1" in draft_path.name
    content = draft_path.read_text(encoding="utf-8")
    assert "Staging: Zombie" in content
    assert "heat: 0" in content
