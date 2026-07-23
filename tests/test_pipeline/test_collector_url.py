import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.events.events import SourceType
from src.permissions import AgentType, Permission, PermissionDenied
from src.pipeline.collector import collect


@pytest.mark.asyncio
async def test_collect_url_does_not_move_to_processing(tmp_path, monkeypatch):
    """URL sources are fetched directly into processing storage."""
    inbox = MagicMock()
    inbox.processing_path = tmp_path
    response = MagicMock(text="<html>hi</html>", is_redirect=False, headers={})
    response.raise_for_status = MagicMock()

    with (
        patch("src.pipeline.collector.get_inbox_manager", return_value=inbox),
        patch("src.pipeline.collector.enforce_permission") as permission,
        patch("src.pipeline.collector.socket.gethostbyname", return_value="93.184.216.34"),
        patch("src.pipeline.collector.httpx.get", return_value=response) as get,
        patch("src.pipeline.collector.event_bus.emit") as emit,
    ):
        payload = await collect("t1", "https://example.com/a", SourceType.URL)

    permission.assert_any_call(AgentType.COLLECTOR, "https://example.com/a", Permission.READ)
    get.assert_called_once_with("https://example.com/a", timeout=30, follow_redirects=False)
    inbox.move_to_processing.assert_not_called()
    assert (tmp_path / "t1.html").read_text(encoding="utf-8")
    assert payload.raw_path == str(tmp_path / "t1.html")
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
async def test_url_redirect_to_loopback_blocked(tmp_path, monkeypatch):
    """Redirect targets must be re-validated against the SSRF ACL."""
    inbox = MagicMock()
    inbox.processing_path = tmp_path

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
        return orig_gethostbyname(host)

    with (
        patch("src.pipeline.collector.get_inbox_manager", return_value=inbox),
        patch("src.pipeline.collector.enforce_permission") as permission,
        patch("src.pipeline.collector.socket.gethostbyname", side_effect=stub_gethostbyname),
        patch("src.pipeline.collector.httpx.get", side_effect=fake_get) as get,
    ):
        with pytest.raises(PermissionDenied):
            await collect("t1", "https://example.com/a", SourceType.URL)

    # The follow-up GET to the loopback target must not have been performed
    assert get.call_count == 1
    inbox.move_to_processing.assert_not_called()
    assert not (tmp_path / "t1.html").exists()


@pytest.mark.asyncio
async def test_collect_file_source_still_works(tmp_path, monkeypatch):
    """FILE source path: move_to_processing is called and payload is emitted with source_type=file."""
    src_path = tmp_path / "Inbox"
    src_path.mkdir()
    foo = src_path / "foo.md"
    foo.write_text("# Hello\nworld\n", encoding="utf-8")

    inbox = MagicMock()
    inbox.processing_path = tmp_path / "Processing"
    inbox.processing_path.mkdir()

    # Move semantics: pretend the inbox renames to processing dir
    def fake_move(path):
        target = inbox.processing_path / Path(path).name
        return target
    inbox.move_to_processing.side_effect = fake_move

    monkeypatch.setattr("src.pipeline.collector.Path", Path)  # real Path

    with (
        patch("src.pipeline.collector.get_inbox_manager", return_value=inbox),
        patch("src.pipeline.collector.enforce_permission"),
        patch("src.pipeline.collector.event_bus.emit") as emit,
    ):
        payload = await collect("t1", str(foo), SourceType.FILE)

    inbox.move_to_processing.assert_called_once_with(str(foo))
    assert (inbox.processing_path / "t1.md").exists()
    assert payload.raw_path == str(inbox.processing_path / "t1.md")
    emit.assert_called_once()
    # emit was called with CollectorDonePayload; check via public attributes
    args, _ = emit.call_args
    assert args[1].task_id == "t1"
