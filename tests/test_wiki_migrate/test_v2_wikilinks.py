from src.wiki.migrate.v2_wikilinks import extract_link_ledger, extract_relations


def test_bvid_and_numeric_wikilinks_become_references():
    relations = extract_relations(
        "参考 [[BV1AtwLzTEtB]] 与 [[7512800963258797321]]",
        current_page_id="BVcur",
    )

    assert {"target": "BV1AtwLzTEtB", "type": "references"} in relations
    assert {"target": "7512800963258797321", "type": "references"} in relations


def test_text_targets_are_deterministically_normalized():
    relations = extract_relations(
        "相关 [[Claude Code]] [[ClaudeCode]] [[Obsidian]]",
        current_page_id="x",
    )
    targets = [item["target"] for item in relations]

    assert targets == ["claude-code", "claudecode", "obsidian"]


def test_aliased_wikilink_uses_target_not_display_alias():
    relations = extract_relations("见 [[ClaudeCode|claude code]]", current_page_id="x")

    assert relations == [{"target": "claudecode", "type": "references"}]


def test_self_reference_is_skipped_after_normalization():
    relations = extract_relations(
        "指向 [[self_page]] 又被 [[self-page]] 引用",
        current_page_id="self_page",
    )

    assert relations == []


def test_markdown_link_is_not_a_wikilink():
    relations = extract_relations(
        "看 [B站](https://bilibili.com) 和 [[BV1xxx]]", current_page_id="x"
    )

    assert relations == [{"target": "BV1xxx", "type": "references"}]


def test_ledger_preserves_raw_text_and_separates_resolution_without_fabrication():
    ledger = extract_link_ledger(
        "见 [[Claude Code|显示名]]、[[missing]]、[[page]]",
        current_page_id="page",
        known_targets={"claude-code"},
    )

    assert ledger["total"] == 3
    assert ledger["resolved"] == 1
    assert ledger["unresolved"] == 1
    assert ledger["self_references"] == 1
    assert ledger["parse_errors"] == 0
    assert ledger["links"][0]["raw"] == "[[Claude Code|显示名]]"
    assert ledger["links"][0]["target"] == "claude-code"
    assert ledger["links"][0]["status"] == "resolved"
    assert ledger["links"][1]["raw"] == "[[missing]]"
    assert ledger["links"][1]["status"] == "unresolved"
