import json

from src.kc.mainline import quarantine_incomplete_v2_bundles


def test_rollback_quarantines_unpublished_v2_only(tmp_path):
    bundles = tmp_path / ".index" / "kc" / "bundles"
    pending = bundles / "v2-pending"
    published = bundles / "v2-published"
    legacy = bundles / "v1-pending"
    for directory, status, version in (
        (pending, "staged", "v2"),
        (published, "published", "v2"),
        (legacy, "staged", "v1"),
    ):
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(
            json.dumps({"contract_version": version, "status": status}),
            encoding="utf-8",
        )

    moved = quarantine_incomplete_v2_bundles(tmp_path)

    assert moved == [tmp_path / ".index" / "quarantine" / "v2-pending"]
    assert not pending.exists()
    assert published.exists()
    assert legacy.exists()
