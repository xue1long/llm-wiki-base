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
    # PR-3: collector now passes the DNS-pinned transport to httpx.get;
    # assert the call happened once with the right URL + the transport
    # kwarg present, regardless of the transport identity.
    assert get.call_count == 1
    call = get.call_args
    assert call.args[0] == "https://example.com/a"
    assert call.kwargs.get("timeout") == 30
    assert call.kwargs.get("follow_redirects") is False
    assert "transport" in call.kwargs
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
        with pytest.raises(PermissionDenied, match="private.*loopback.*link-local"):
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
    """Redirect targets must be re-validated against the SSRF ACL.

    PR-3: the SSRF guard now sits inside ``_PinnedDnsTransport`` (one
    DNS resolve + IP allowlist per transport). The collector's redirect
    loop joins relative ``Location:`` headers with the current URL, but
    the transport still inspects every hop's hostname. We exercise the
    transport directly here to assert the per-hop guard.

    ``socket.gethostbyname`` is patched so the test does not depend on
    the host's actual DNS resolution (which on some CI networks points
    at a benchmarking-only reserved IP that we, rightly, also reject).
    """
    from src.pipeline.collector import _PinnedDnsTransport

    def _fake_resolve(host):
        # First hop: a stable public IP literal the allowlist must accept.
        if host == "example.com":
            return "93.184.216.34"
        # The redirect target is a literal loopback / private IP;
        # gethostbyname on a literal IP is identity on most platforms,
        # but be explicit so the test is portable.
        if host == "127.0.0.1" or host == "10.0.0.5":
            return host
        return "0.0.0.0"  # force the allowlist to fail loudly

    transport = _PinnedDnsTransport()
    with patch("src.pipeline.collector.socket.gethostbyname", side_effect=_fake_resolve):
        # First hop (public) gets pinned to a public IP — must not raise.
        transport._resolve_and_pin("https://example.com/v1")
        # A redirect to an absolute loopback URL must be rejected.
        with pytest.raises(PermissionDenied):
            transport._resolve_and_pin("http://127.0.0.1/secret")

        # Sanity: a private IP literal cannot be passed even by an
        # attacker who controls DNS — the IP allowlist fires before
        # the DNS result is even consulted.
        with pytest.raises(PermissionDenied):
            transport._resolve_and_pin("http://10.0.0.5/secret")


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
