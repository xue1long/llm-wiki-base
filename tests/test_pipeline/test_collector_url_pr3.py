"""PR-3 regression: SSRF DNS TOCTOU + relative redirect chain.

Pre-PR-3 bugs:
1. The collector resolved the hostname twice per URL — once in
   ``_check_url_allowlisted`` and once inside ``httpx``. An attacker
   controlling DNS could return a public IP on the first resolve and
   a private IP on the second, silently bypassing the SSRF guard.

2. The redirect loop used ``current_url = location`` for every
   ``Location:`` header. Relative redirects (``Location: /v2/article``)
   dropped the scheme + host, and the next request was issued against
   a path-only URL — relative to ``$CWD``, not the original domain.
   The very common ``302 Found`` pattern crashed.

After PR-3: ``_PinnedDnsTransport`` resolves the hostname exactly once
per transport and replaces the request URL with an IP-anchored form
(the IP becomes the netloc, the original hostname rides on the
``Host:`` header for vhost routing). ``_safe_redirect_join`` uses
``urllib.parse.urljoin`` to handle absolute, root-relative, and
relative redirects correctly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from src.permissions import PermissionDenied
from src.pipeline.collector import (
    _PinnedDnsTransport,
    _safe_redirect_join,
    _check_ip_public,
    _check_url_allowlisted,
)


# ── _safe_redirect_join ──────────────────────────────────────────────


def test_safe_redirect_join_absolute_redirect_takes_priority():
    """``Location: https://other.example/v2`` follows the absolute URL."""
    base = "https://example.com/v1"
    out = _safe_redirect_join(base, "https://other.example/v2")
    assert out == "https://other.example/v2"


def test_safe_redirect_join_root_relative_uses_base_scheme_and_host():
    """``Location: /v2/article`` resolves to ``https://example.com/v2/article``."""
    base = "https://example.com/v1/page"
    out = _safe_redirect_join(base, "/v2/article")
    assert out == "https://example.com/v2/article"


def test_safe_redirect_join_relative_uses_base_directory():
    """``Location: v2`` resolves to ``https://example.com/v1/v2``."""
    base = "https://example.com/v1/"
    out = _safe_redirect_join(base, "v2")
    assert out == "https://example.com/v1/v2"


def test_safe_redirect_join_empty_location_returns_base():
    """An empty ``Location:`` header is a protocol error per RFC; surface
    it instead of looping forever by returning the base URL untouched."""
    base = "https://example.com/v1"
    assert _safe_redirect_join(base, "") == base


def test_safe_redirect_join_protocol_relative_url():
    """``Location: //cdn.example.com/article`` keeps current scheme but
    swaps host."""
    base = "https://example.com/v1"
    out = _safe_redirect_join(base, "//cdn.example.com/article")
    assert out == "https://cdn.example.com/article"


# ── _check_ip_public ──────────────────────────────────────────────


def test_check_ip_public_rejects_loopback_ipv4():
    with pytest.raises(PermissionDenied, match="127"):
        _check_ip_public(__import__("ipaddress").ip_address("127.0.0.1"),
                         "http://127.0.0.1/secret")


def test_check_ip_public_rejects_private_10_dot():
    import ipaddress
    with pytest.raises(PermissionDenied, match="10"):
        _check_ip_public(
            ipaddress.ip_address("10.0.0.1"), "http://10.0.0.1/secret"
        )


def test_check_ip_public_rejects_link_local_169_dot():
    import ipaddress
    with pytest.raises(PermissionDenied, match="169"):
        _check_ip_public(
            ipaddress.ip_address("169.254.169.254"),
            "http://169.254.169.254/latest/meta-data/",
        )


def test_check_ip_public_rejects_multicast():
    import ipaddress
    with pytest.raises(PermissionDenied, match="multicast"):
        _check_ip_public(
            ipaddress.ip_address("224.0.0.1"), "http://224.0.0.1/secret"
        )


def test_check_ip_public_accepts_public_ip():
    """Normal public IPv4 — must NOT raise."""
    import ipaddress
    _check_ip_public(
        ipaddress.ip_address("93.184.216.34"),
        "https://example.com/",
    )


# ── _check_url_allowlisted (entry-level helper retained) ────────────


def test_check_url_allowlisted_rejects_missing_scheme():
    with pytest.raises(PermissionDenied, match="missing a scheme"):
        _check_url_allowlisted("example.com/x")


def test_check_url_allowlisted_rejects_ftp_scheme():
    with pytest.raises(PermissionDenied, match="disallowed scheme"):
        _check_url_allowlisted("ftp://example.com/x")


def test_check_url_allowlisted_rejects_dns_failure(monkeypatch):
    import socket

    def boom(_host):
        raise socket.gaierror("no DNS")
    monkeypatch.setattr(
        "src.pipeline.collector.socket.gethostbyname", boom
    )
    with pytest.raises(PermissionDenied, match="DNS resolution failed"):
        _check_url_allowlisted("https://missing.example/x")


def test_check_url_allowlisted_rejects_unresolvable_ip(monkeypatch):
    """DNS returns a non-IP string — must surface as PermissionDenied,
    not silently allow the connect."""
    monkeypatch.setattr(
        "src.pipeline.collector.socket.gethostbyname",
        lambda _host: "not-an-ip",
    )
    # ``socket.gethostbyname`` returning an unparseable string passes
    # ipaddress.ip_address which raises ValueError; surface it.
    with pytest.raises(Exception):
        _check_url_allowlisted("https://example.com/x")


# ── _PinnedDnsTransport ──────────────────────────────────────────


def test_transport_resolves_public_ip_and_rewrites_url():
    """A public IP literal IP-anchors the URL."""
    from unittest.mock import MagicMock, patch

    def fake_resolve(host):
        return "93.184.216.34" if host == "example.com" else "0.0.0.0"

    transport = _PinnedDnsTransport()
    with patch("src.pipeline.collector.socket.gethostbyname", side_effect=fake_resolve):
        pinned = transport._resolve_and_pin("https://example.com/v1")
    # URL is now IP-anchored; the original hostname is preserved via
    # the ``Host:`` header at handle_request time.
    assert pinned.startswith("https://93.184.216.34/")
    assert "example.com" not in pinned


def test_transport_rejects_loopback_redirect_target():
    """A redirect to ``127.0.0.1`` must be rejected at the transport."""
    transport = _PinnedDnsTransport()
    with patch(
        "src.pipeline.collector.socket.gethostbyname",
        lambda host: host if host == "127.0.0.1" else "93.184.216.34",
    ):
        # First hop is fine.
        transport._resolve_and_pin("https://example.com/v1")
        # Now an attacker redirects us to a loopback literal — blocked.
        with pytest.raises(PermissionDenied):
            transport._resolve_and_pin("http://127.0.0.1/secret")


def test_transport_rejects_private_ip_literal():
    """Even without DNS — an IP literal in the URL must be allowlisted."""
    transport = _PinnedDnsTransport()
    # ``socket.gethostbyname`` on an IP literal is identity on most
    # platforms; mirror that so the transport sees the private IP.
    with patch(
        "src.pipeline.collector.socket.gethostbyname",
        lambda host: host,
    ):
        with pytest.raises(PermissionDenied, match="disallowed address"):
            transport._resolve_and_pin("http://10.0.0.5/private")


def test_transport_pin_cache_keeps_stable_ip_across_calls():
    """The cache pins the IP for repeated calls within one transport —
    a TOCTOU attacker DNS-rebinding the same hostname to a different
    IP cannot bypass."""
    transport = _PinnedDnsTransport()
    resolve_calls: list[str] = []

    def fake_resolve(host):
        resolve_calls.append(host)
        return "93.184.216.34"  # public, stable

    with patch("src.pipeline.collector.socket.gethostbyname", side_effect=fake_resolve):
        transport._resolve_and_pin("https://example.com/v1")
        transport._resolve_and_pin("https://example.com/v2")
        transport._resolve_and_pin("https://example.com/v3")

    assert resolve_calls == ["example.com"], (
        "transport must cache the resolved IP for the lifetime of "
        "this transport; subsequent hits return the cached IP"
    )


def test_transport_rejects_nonnumeric_dns_result():
    """If DNS returns garbage (an attacker-controlled resolver), the
    transport must surface the failure as PermissionDenied, not pass
    the bogus string to ipaddress and crash."""
    transport = _PinnedDnsTransport()
    with patch(
        "src.pipeline.collector.socket.gethostbyname",
        lambda _host: "not-an-ip",
    ):
        with pytest.raises(PermissionDenied, match="not a parseable IP"):
            transport._resolve_and_pin("https://example.com/")


def test_transport_rejects_dns_failure():
    import socket

    transport = _PinnedDnsTransport()
    with patch(
        "src.pipeline.collector.socket.gethostbyname",
        side_effect=socket.gaierror("no DNS"),
    ):
        with pytest.raises(PermissionDenied, match="DNS resolution failed"):
            transport._resolve_and_pin("https://missing.example/")


def test_transport_rejects_non_http_scheme():
    """``file:``, ``ftp:``, ``data:`` schemes must be blocked outright.
    URL collectors must not honour them, and the IP-allowlist alone
    would happily approve them."""
    import re

    transport = _PinnedDnsTransport()

    # ``file:///etc/passwd`` parses as scheme='file', hostname='',
    # so the URL guard fires its "missing hostname" path. Both
    # remaining entries have a real hostname — that's where the
    # scheme check kicks in.
    with pytest.raises(PermissionDenied):
        transport._resolve_and_pin("file:///etc/passwd")
    with patch(
        "src.pipeline.collector.socket.gethostbyname",
        return_value="93.184.216.34",
    ):
        with pytest.raises(PermissionDenied, match=re.compile(
            r"(missing|disallowed scheme)", re.I
        )):
            transport._resolve_and_pin("ftp://example.com/x")
        with pytest.raises(PermissionDenied, match=re.compile(
            r"(missing|disallowed scheme)", re.I
        )):
            transport._resolve_and_pin("data:text/plain,hello")


def test_transport_rejects_missing_scheme():
    transport = _PinnedDnsTransport()
    with pytest.raises(PermissionDenied, match="missing a scheme"):
        transport._resolve_and_pin("example.com/x")


# ── DNS TOCTOU defence ────────────────────────────────────────────


def test_transport_resolves_only_once_per_transport_instance():
    """The whole point of the pin transport: one DNS resolve per
    hostname, no matter how many redirects follow. This is what
    closes the SSRF TOCTOU window: even if the resolver returns a
    different IP on a subsequent call, the cache wins.
    """
    transport = _PinnedDnsTransport()
    resolve_calls: list[str] = []

    resolver_state = {"calls": 0}

    def flaky_resolve(host):
        resolver_state["calls"] += 1
        resolve_calls.append(host)
        # First call returns public IP, subsequent call returns a
        # private IP — the classic TOCTOU exploit shape.
        if resolver_state["calls"] == 1:
            return "93.184.216.34"
        return "10.0.0.5"

    with patch("src.pipeline.collector.socket.gethostbyname", side_effect=flaky_resolve):
        pinned = transport._resolve_and_pin("https://example.com/v1")
        # Second call would return a private IP, but the cache wins.
        pinned2 = transport._resolve_and_pin("https://example.com/v2")

    # Both URLs anchor to the cached public IP — no private IP leaked.
    assert resolve_calls == ["example.com"], (
        f"transport must cache the resolved IP; resolver was called "
        f"{len(resolve_calls)} times: {resolve_calls}"
    )
    assert "10.0.0.5" not in pinned
    assert "10.0.0.5" not in pinned2
    assert "93.184.216.34" in pinned
    assert "93.184.216.34" in pinned2
    # Different paths is fine; what matters is the host IP.
    assert "/v1" in pinned and "/v2" in pinned2
