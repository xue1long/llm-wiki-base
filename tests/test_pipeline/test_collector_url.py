import socket
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
    response = MagicMock(text="<html>hi</html>")

    with (
        patch("src.pipeline.collector.get_inbox_manager", return_value=inbox),
        patch("src.pipeline.collector.enforce_permission") as permission,
        patch("src.pipeline.collector.socket.gethostbyname", return_value="93.184.216.34"),
        patch("src.pipeline.collector.httpx.get", return_value=response) as get,
        patch("src.pipeline.collector.event_bus.emit") as emit,
    ):
        payload = await collect("t1", "https://example.com/a", SourceType.URL)

    permission.assert_any_call(AgentType.COLLECTOR, "https://example.com/a", Permission.READ)
    get.assert_called_once_with("https://example.com/a", timeout=30, follow_redirects=True)
    inbox.move_to_processing.assert_not_called()
    assert (tmp_path / "t1.html.txt").read_text(encoding="utf-8")
    assert payload.raw_path == str(tmp_path / "t1.html.txt")
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
