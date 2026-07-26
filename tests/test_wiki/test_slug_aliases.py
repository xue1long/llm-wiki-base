"""Tests for src.wiki.features.slug_aliases — the cross-run slug alias
registry that resolves wikilink drift.

Motivation: production novel-wiki had 10 broken wikilinks on 2026-07-26
because the LLM emitted inconsistent slug variants across ingests
(e.g. ``qi-dai-gan`` vs ``qi-dai-gan-chuangzuo``). This registry
maps such variants to a canonical slug so the resolver can find them.
"""
import json
import pytest
from src.wiki.features.slug_aliases import (
    SlugAliasRegistry,
    _resolve_project_root,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def test_resolve_project_root_returns_str(tmp_path):
    """Accepts a Path-like and returns a normalized string (handles
    bytes, str, os.PathLike uniformly). Stable for the same input.
    """
    s1 = _resolve_project_root(tmp_path)
    s2 = _resolve_project_root(str(tmp_path))
    assert isinstance(s1, str)
    assert isinstance(s2, str)
    assert s1 == s2  # round-trip for Path → str
    assert s1  # non-empty


def test_registry_load_when_no_file(tmp_path):
    """A project that has never had aliases written returns an empty
    registry, not an error. Important for fresh-project flow.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    assert reg.aliases == {}
    assert reg.aliases_rev == {}
    assert reg.get_canonical("anything") is None
    assert reg.has_aliases_for("real-page") == []


def test_registry_add_one_pair(tmp_path):
    """Adding an alias stores both forward (alias → canonical) and
    reverse (canonical → [aliases]) mappings in memory.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    assert reg.get_canonical("qi-dai-gan") == "qi-dai-gan-chuangzuo"
    assert reg.get_canonical("qi-dai-gan-chuangzuo") is None  # reverse not used as forward
    assert reg.has_aliases_for("qi-dai-gan-chuangzuo") == ["qi-dai-gan"]


def test_registry_alias_deduplicates(tmp_path):
    """Re-adding the same alias for the same canonical must not
    produce duplicates in the reverse index.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    aliases = reg.has_aliases_for("qi-dai-gan-chuangzuo")
    assert aliases == ["qi-dai-gan"]


def test_registry_multiple_aliases_for_same_canonical(tmp_path):
    """One canonical slug can have many alias names pointing to it.
    All aliases resolve to the same canonical; the reverse index
    lists all of them.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.add("qidagan", "qi-dai-gan-chuangzuo")
    reg.add("qi_dai_gan", "qi-dai-gan-chuangzuo")
    assert reg.get_canonical("qi-dai-gan") == "qi-dai-gan-chuangzuo"
    assert reg.get_canonical("qidagan") == "qi-dai-gan-chuangzuo"
    assert reg.get_canonical("qi_dai_gan") == "qi-dai-gan-chuangzuo"
    aliases = reg.has_aliases_for("qi-dai-gan-chuangzuo")
    assert sorted(aliases) == ["qi-dai-gan", "qi_dai_gan", "qidagan"]


def test_registry_save_and_reload(tmp_path):
    """After add() + save(), a fresh registry instance loading the
    same project must read back the same mappings.
    """
    ensure_knowledge_base(tmp_path)
    reg1 = SlugAliasRegistry(tmp_path)
    reg1.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg1.add("urban-xianxia-stream", "dushi-xianxia-liu")
    reg1.save()

    reg2 = SlugAliasRegistry(tmp_path)
    assert reg2.get_canonical("qi-dai-gan") == "qi-dai-gan-chuangzuo"
    assert reg2.get_canonical("urban-xianxia-stream") == "dushi-xianxia-liu"
    assert reg2.get_canonical("unknown") is None
    assert sorted(reg2.has_aliases_for("qi-dai-gan-chuangzuo")) == ["qi-dai-gan"]


def test_registry_aliases_file_path_lives_in_dot_llm_wiki(tmp_path):
    """The JSON file must live under .llm-wiki/ to keep project files
    portable and easy to gitignore by component.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("x", "y")
    reg.save()
    expected = tmp_path / ".llm-wiki" / "slug_aliases.json"
    assert expected.exists()
    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert payload["version"] >= 1
    assert payload["aliases"]["x"] == "y"
    assert payload["aliases_rev"]["y"] == ["x"]


def test_registry_save_idempotent(tmp_path):
    """save() called twice with no intervening add() must not corrupt
    the file. Important for callers that may call save() defensively.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("a", "b")
    reg.save()
    reg.save()  # second save is a no-op (data already on disk)
    reg2 = SlugAliasRegistry(tmp_path)
    assert reg2.get_canonical("a") == "b"


def test_registry_add_many_batch(tmp_path):
    """add_many() takes a list of alias pairs and registers them all
    in one call. Useful for bulk register from generator relations.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add_many(
        [("qi-dai-gan", "qi-dai-gan-chuangzuo"),
         ("urban-xianxia-stream", "dushi-xianxia-liu")],
    )
    assert reg.get_canonical("qi-dai-gan") == "qi-dai-gan-chuangzuo"
    assert reg.get_canonical("urban-xianxia-stream") == "dushi-xianxia-liu"


def test_registry_overwrite_canonical_reassigns_reverse(tmp_path):
    """If a slug that was previously an alias of A is later assigned as
    alias of B, the reverse indices must reflect the change. Avoids
    stale pointers in the reverse index.
    """
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.add("qi-dai-gan", "dushi-xianxia-liu")  # reassign
    assert reg.get_canonical("qi-dai-gan") == "dushi-xianxia-liu"
    assert reg.has_aliases_for("qi-dai-gan-chuangzuo") == []
    assert reg.has_aliases_for("dushi-xianxia-liu") == ["qi-dai-gan"]
