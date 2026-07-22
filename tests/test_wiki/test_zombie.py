"""Tests for src/wiki/zombie.py."""
from src.wiki.zombie import ZombieDetector
from src.wiki.types import PageType, WikiPage
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page


def test_zombie_detected_at_zero_heat(tmp_path):
    """ZombieDetector lists pages with zombie_since set."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="z1", title="Z", type=PageType.ENTITY, body="", zombie_since=12345))
    write_page(paths, WikiPage(id="alive", title="A", type=PageType.ENTITY, body="", zombie_since=None))

    zombies = ZombieDetector.list_zombies(paths)
    assert len(zombies) == 1
    assert zombies[0]["id"] == "z1"
    assert zombies[0]["zombie_since"] == 12345


def test_generate_staging_draft(tmp_path):
    """generate_staging_draft creates a .index/staging/ file."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(id="z1", title="Zombie", type=PageType.ENTITY, body="...", heat=0, last_used_at=0)

    draft_path = ZombieDetector.generate_staging_draft(paths, page)
    assert draft_path.exists()
    assert "z1" in draft_path.name
    content = draft_path.read_text(encoding="utf-8")
    assert "Staging: Zombie" in content
    assert "heat: 0" in content