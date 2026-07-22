"""Tests for vision CLI subcommands."""
from src.cli_ext.vision_cmd import cmd_vision_list, cmd_vision_extract
from src.vision.storage import MediaPage
from src.vision.captioner import ImageCaption


def test_vision_list_empty(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = type("A", (), {"project_root": str(tmp_path)})()
    cmd_vision_list(args)
    out = capsys.readouterr().out
    assert "No media pages" in out


def test_vision_list_with_pages(capsys, tmp_path):
    from src.vision.extractor import ExtractedImage
    img = ExtractedImage(
        task_id="t", index=0, bytes=b"\x89PNG",
        mime_type="image/png", source_page="x", context="c",
    )
    cap = ImageCaption("t", 0, "alt", "short", [], 0.5, "model", 1)
    MediaPage.write(tmp_path, img, cap)

    args = type("A", (), {"project_root": str(tmp_path)})()
    cmd_vision_list(args)
    out = capsys.readouterr().out
    assert "t_0.md" in out
    assert "Total:" in out


def test_vision_extract_file_not_found(capsys, tmp_path):
    import pytest
    args = type("A", (), {
        "path": str(tmp_path / "nope.pdf"),
        "task_id": "t1",
        "project_root": str(tmp_path),
        "provider": None,
        "model": None,
    })()
    with pytest.raises(SystemExit) as exc:
        cmd_vision_extract(args)
    assert exc.value.code == 2
