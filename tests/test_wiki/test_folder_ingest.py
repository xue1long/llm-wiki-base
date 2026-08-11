from src.wiki.features.folder_ingest import collect_files, folder_context_for
from src.wiki.storage.ensure import ensure_knowledge_base


def test_collect_files_recursive(tmp_path):
    ensure_knowledge_base(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("y")
    (tmp_path / "sub" / "deeper").mkdir()
    (tmp_path / "sub" / "deeper" / "c.md").write_text("z")

    files = collect_files(tmp_path)
    names = sorted(f.name for f in files)
    assert "a.txt" in names
    assert "b.txt" in names
    assert "c.md" in names


def test_collect_files_nonexistent_dir(tmp_path):
    """Non-existent directory → empty list (not error)."""
    fake = tmp_path / "does_not_exist"
    assert collect_files(fake) == []


def test_folder_context_for(tmp_path):
    (tmp_path / "papers").mkdir()
    (tmp_path / "papers" / "energy").mkdir()
    target = tmp_path / "papers" / "energy" / "solar.pdf"
    target.touch()

    ctx = folder_context_for(tmp_path, target)
    assert ctx == "papers > energy"


def test_folder_context_for_top_level(tmp_path):
    (tmp_path / "papers").mkdir()
    target = tmp_path / "papers" / "solar.pdf"
    target.touch()

    ctx = folder_context_for(tmp_path, target)
    assert ctx == "papers"


def test_folder_context_for_outside(tmp_path):
    """File outside folder → empty string."""
    other = tmp_path / "elsewhere" / "x.pdf"
    other.parent.mkdir(parents=True)
    other.touch()
    ctx = folder_context_for(tmp_path / "papers", other)
    assert ctx == ""
