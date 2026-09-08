from __future__ import annotations

from src.kc.views.book.wiki.tutorial_path import validate_tutorial_paths


def _outline():
    return {
        "volumes": [{
            "volume_id": "v1",
            "chapters": [{
                "chapter_id": "c1",
                "sections": [{"section_id": "s1"}],
            }, {
                "chapter_id": "c2",
                "sections": [{"section_id": "s2"}],
            }],
        }],
    }


def test_valid_path_references_existing_chapter_and_section():
    paths = {"paths": [{
        "path_id": "path-1",
        "title": "入门",
        "steps": [{"chapter_id": "c1", "section_id": "s1", "task": "阅读"}],
        "status": "active",
    }]}

    assert validate_tutorial_paths(paths, _outline()) == ()


def test_path_rejects_unknown_chapter_and_cross_chapter_section():
    paths = {"paths": [{
        "path_id": "path-1",
        "steps": [
            {"chapter_id": "missing"},
            {"chapter_id": "c1", "section_id": "s2"},
        ],
    }]}

    errors = validate_tutorial_paths(paths, _outline())

    assert "unknown-chapter:path-1:0" in errors
    assert "section-chapter-mismatch:path-1:1" in errors


def test_path_rejects_duplicate_ids_and_embedded_body():
    paths = {"paths": [{
        "path_id": "path-1",
        "body": "不得复制正文",
        "steps": [{"chapter_id": "c1"}],
    }, {
        "path_id": "path-1",
        "steps": [{"chapter_id": "c1"}],
    }]}

    errors = validate_tutorial_paths(paths, _outline())

    assert "duplicate-path-id:path-1" in errors
    assert "path-body-forbidden:path-1" in errors


def test_path_validation_does_not_change_outline():
    outline = _outline()
    paths = {"paths": [{"path_id": "path-1", "steps": [{"chapter_id": "c1"}]}]}

    validate_tutorial_paths(paths, outline)

    assert outline["volumes"][0]["chapters"][0]["chapter_id"] == "c1"
