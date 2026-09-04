"""Test: capture mark-verify CLI + API."""
import subprocess
import sys


def test_cli_capture_mark_verify_registered():
    """capture-mark-verify should appear in --help."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert "capture-mark-verify" in result.stdout, (
        f"capture-mark-verify not in CLI; stdout={result.stdout!r}"
    )


def test_api_route_imports_cleanly():
    """Routes module must import without errors."""
    from src.server.routes import capture as capture_route
    assert hasattr(capture_route, "router")
    # Verify the verify endpoint is registered
    paths = [r.path for r in capture_route.router.routes]
    assert any("verify" in p for p in paths), (
        f"verify route not found; paths={paths}"
    )
