import socket
from unittest.mock import MagicMock, patch

import pytest

from src.events.events import SourceType
from src.permissions import AgentType, Permission, PermissionDenied
from src.pipeline.collector import collect


@pytest.mark.asyncio
async def test_collect_url_returns_content_in_payload(monkeypatch):
    """URL sources: collector fetches and returns content in the payload.
    No Inbox/Processing/<task_id>.html copy is written after the
    2026-07 cleanup — the URL itself is recorded in ``raw_path``.
    """
    response = MagicMock(text="<html>hi</html>", is_redirect=False, headers={})
    response.raise_for_status = MagicMock()

    with (
        patch("src.pipeline.collector.enforce_permission") as permission,
        patch("src.pipeline.collector.socket.gethostbyname", return_value="93.184.216.34"),
        patch("src.pipeline.collector.httpx.get", return_value=response) as get,
        patch("src.pipeline.collector.event_bus.emit") as emit,
    ):
        payload = await collect("t1", "https://example.com/a", SourceType.URL)

    permission.assert_any_call(AgentType.COLLECTOR, "https://example.com/a", Permission.READ)
    get.assert_called_once_with("https://example.com/a", timeout=30, follow_redirects=False)
    # raw_path is the URL itself (not a staged file path)
    assert payload.raw_path == "https://example.com/a"
    assert payload.content == "<html>hi</html>"
    emit.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.1"])
async def test_collect_url_blocks_non_public_addresses(address):
    with (
        patch("src.pipeline.collector.enforce_permission"),
        patch("src.pipeline.collector.socket.gethostbyname", return_value=address),
        patch("src.pipeline.collector.httpx.get") as get,
    ):
        with pytest.raises(PermissionDenied, match="private/loopback/link-local"):
            await collect("t1", f"http://{address}/secret", SourceType.URL)

    get.assert_not_called()


@pytest.mark.asyncio
async def test_collect_url_rejects_dns_failure():
    with (
        patch("src.pipeline.collector.enforce_permission"),
        patch("src.pipeline.collector.socket.gethostbyname", side_effect=socket.gaierror),
        patch("src.pipeline.collector.httpx.get") as get,
    ):
        with pytest.raises(PermissionDenied, match="DNS resolution failed for missing.example"):
            await collect("t1", "https://missing.example/a", SourceType.URL)

    get.assert_not_called()


@pytest.mark.asyncio
async def test_url_redirect_to_loopback_blocked():
    """Redirect targets must be re-validated against the SSRF ACL."""
    # First request is to a public host and returns 302 -> 127.0.0.1
    redirect_headers = {"Location": "http://127.0.0.1/secret"}
    redirect_resp = MagicMock(is_redirect=True, headers=redirect_headers)
    redirect_resp.raise_for_status = MagicMock()

    # Second request (after redirect-following code re-issues) — should never happen because ACL rejects
    final_resp = MagicMock(text="should-not-fetch")

    responses = iter([redirect_resp, final_resp])

    def fake_get(url, **kwargs):
        try:
            return next(responses)
        except StopIteration:
            return final_resp

    # The ACL performs socket.gethostbyname on the redirect Location too —
    # we map 127.0.0.1 to itself so the ACL detects the loopback.
    orig_gethostbyname = socket.gethostbyname

    def stub_gethostbyname(host):
        if host == "127.0.0.1":
            return "127.0.0.1"
        if host == "example.com":
            return "93.184.216.34"
        return orig_gethostbyname(host)

    with (
        patch("src.pipeline.collector.enforce_permission") as permission,
        patch("src.pipeline.collector.socket.gethostbyname", side_effect=stub_gethostbyname),
        patch("src.pipeline.collector.httpx.get", side_effect=fake_get) as get,
    ):
        with pytest.raises(PermissionDenied):
            await collect("t1", "https://example.com/a", SourceType.URL)

    # The follow-up GET to the loopback target must not have been performed
    assert get.call_count == 1
    permission.assert_any_call(AgentType.COLLECTOR, "https://example.com/a", Permission.READ)


@pytest.mark.asyncio
async def test_collect_file_source_returns_source_path_as_raw_path(tmp_path, monkeypatch):
    """FILE source: collector reads content and returns the source path
    itself as ``raw_path``. No staged copy is written. (2026-07 cleanup.)
    """
    source = tmp_path / "doc.md"
    source.write_text("# Hello\nworld\n", encoding="utf-8")

    with (
        patch("src.pipeline.collector.enforce_permission"),
        patch("src.pipeline.collector.event_bus.emit") as emit,
    ):
        payload = await collect("t1", str(source), SourceType.FILE)

    # raw_path is the source itself, not a staged copy
    assert payload.raw_path == str(source)
    assert payload.content == "# Hello\nworld\n"

    # The source must remain at its original location — collect() does
    # not move/delete the file.
    assert source.exists(), "source must remain at original path after collect()"

    # No Inbox/Processing/<task_id>.md should exist
    assert not (tmp_path / "Inbox").exists(), (
        "No Inbox/ directory should be created by the collector after the "
        "2026-07 cleanup."
    )

    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[1].task_id == "t1"
    assert args[1].source == str(source)
