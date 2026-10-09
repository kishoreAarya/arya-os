"""Phase 47A — SSRF / asset-redirect hardening unit tests.

Covers the two Phase 46C findings fixed in this phase:

1. ``ensure_local_asset`` previously followed redirects automatically
   (``follow_redirects=True``) with no per-hop revalidation. It now reuses
   the shared bounded redirect walker (``open_validated_stream``), so every
   redirect Location is revalidated with the DNS-aware SSRF guard BEFORE it
   is requested, redirect chains are hop-limited, and loops are rejected.

2. ``is_safe_remote_url`` previously failed OPEN when DNS resolution
   failed (dotted, public-looking hostnames passed). It now fails CLOSED.

All HTTP is mocked via ``httpx.MockTransport`` and all DNS via a
deterministic ``getaddrinfo`` monkeypatch — no network access, no real
internal/metadata endpoints are ever contacted.
"""

import httpx
import pytest
from app.utils.asset_downloader import (
    AssetDownloadError,
    SSRFSecurityError,
    is_safe_remote_url,
)
from app.utils.asset_manager import ensure_local_asset, is_safe_asset_url


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_phase44a_security_remediation_unit.py)
# ---------------------------------------------------------------------------

PUBLIC_IP = "93.184.216.34"


def _fake_dns(ip: str):
    """Deterministic getaddrinfo replacement: every hostname resolves to ip."""

    def _getaddrinfo(host, *args, **kwargs):
        import socket

        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _getaddrinfo


def _failing_dns():
    """getaddrinfo replacement that always raises gaierror."""

    def _getaddrinfo(host, *args, **kwargs):
        import socket

        raise socket.gaierror("resolution failed (mocked)")

    return _getaddrinfo


def _install_http_mock(monkeypatch, handler):
    """Force every httpx.AsyncClient constructed during the test to use a
    MockTransport with the given handler (captures requests, no network)."""
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


class _Recorder:
    """Handler wrapper that records the sequence of requested URLs."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def _chain_handler(chain: dict, final_content: bytes = b"PNGDATA"):
    """chain maps exact URL -> next Location; unmapped URLs serve the asset."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in chain:
            return httpx.Response(302, headers={"Location": chain[url]})
        return httpx.Response(
            200, content=final_content, headers={"Content-Type": "image/png"}
        )

    return handler


@pytest.fixture
def public_dns(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _fake_dns(PUBLIC_IP))


# ---------------------------------------------------------------------------
# 1. DNS validation fails closed
# ---------------------------------------------------------------------------


def test_dns_resolution_failure_rejected(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _failing_dns())
    assert is_safe_remote_url("https://public-looking.example/img.png") is False


def test_dns_failure_rejected_through_asset_manager_guard(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _failing_dns())
    assert is_safe_asset_url("https://public-looking.example/img.png") is False


def test_offline_dotted_hostname_no_longer_passes(monkeypatch):
    """The exact pre-47A fail-open case: dotted non-local hostname with DNS
    down used to be accepted; it must now be rejected."""
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _failing_dns())
    assert is_safe_remote_url("https://cdn.assets-provider.example/img.png") is False


def test_malformed_resolved_address_rejected(monkeypatch):
    import socket

    import app.utils.asset_downloader as adm

    def _bad(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0))]

    monkeypatch.setattr(adm.socket, "getaddrinfo", _bad)
    assert is_safe_remote_url("https://some.example/img.png") is False


def test_public_hostname_still_allowed(public_dns):
    assert is_safe_remote_url("https://cdn.assets-provider.example/img.png") is True


def test_hostname_resolving_to_forbidden_address_rejected(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _fake_dns("10.1.2.3"))
    assert is_safe_remote_url("https://cdn.assets-provider.example/img.png") is False


# ---------------------------------------------------------------------------
# 2. ensure_local_asset — redirect hardening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_public_url_download_succeeds(monkeypatch, public_dns):
    rec = _Recorder(_chain_handler({}))
    _install_http_mock(monkeypatch, rec)
    path = await ensure_local_asset("https://cdn.example/a.png")
    assert path is not None and path.endswith(".png")
    assert _read_bytes(path) == b"PNGDATA"
    assert rec.urls == ["https://cdn.example/a.png"]


@pytest.mark.asyncio
async def test_initial_url_rejected_before_any_request(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _fake_dns("10.1.2.3"))
    rec = _Recorder(_chain_handler({}))
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(ValueError):
        await ensure_local_asset("https://internal.example/a.png")
    assert rec.urls == []  # nothing requested


@pytest.mark.asyncio
async def test_redirect_to_private_ip_rejected_before_connecting(
    monkeypatch, public_dns
):
    rec = _Recorder(
        _chain_handler({"https://cdn.example/a.png": "http://192.168.1.5/x.png"})
    )
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(SSRFSecurityError):
        await ensure_local_asset("https://cdn.example/a.png")
    # The redirect target itself must never have been requested.
    assert rec.urls == ["https://cdn.example/a.png"]


@pytest.mark.asyncio
async def test_redirect_to_metadata_host_rejected_before_connecting(
    monkeypatch, public_dns
):
    rec = _Recorder(
        _chain_handler(
            {"https://cdn.example/a.png": "http://metadata.google.internal/latest/"}
        )
    )
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(SSRFSecurityError):
        await ensure_local_asset("https://cdn.example/a.png")
    assert rec.urls == ["https://cdn.example/a.png"]


@pytest.mark.asyncio
async def test_redirect_to_loopback_name_rejected(monkeypatch, public_dns):
    # "localhost" is blocked by name regardless of DNS mocking.
    rec = _Recorder(
        _chain_handler({"https://cdn.example/a.png": "http://localhost/x.png"})
    )
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(SSRFSecurityError):
        await ensure_local_asset("https://cdn.example/a.png")
    assert rec.urls == ["https://cdn.example/a.png"]


@pytest.mark.asyncio
async def test_every_redirect_hop_revalidated_and_public_chain_succeeds(
    monkeypatch, public_dns
):
    chain = {
        "https://hop1.example/a.png": "https://hop2.example/b.png",
        "https://hop2.example/b.png": "https://final.example/c.png",
    }
    rec = _Recorder(_chain_handler(chain))
    _install_http_mock(monkeypatch, rec)
    path = await ensure_local_asset("https://hop1.example/a.png")
    assert _read_bytes(path) == b"PNGDATA"
    assert rec.urls == [
        "https://hop1.example/a.png",
        "https://hop2.example/b.png",
        "https://final.example/c.png",
    ]


@pytest.mark.asyncio
async def test_redirect_chain_exceeding_hop_limit_rejected(monkeypatch, public_dns):
    chain = {
        "https://h1.example/a.png": "https://h2.example/b.png",
        "https://h2.example/b.png": "https://h3.example/c.png",
        "https://h3.example/c.png": "https://h4.example/d.png",
        "https://h4.example/d.png": "https://final.example/e.png",
    }
    rec = _Recorder(_chain_handler(chain))
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(AssetDownloadError, match="redirect hops"):
        await ensure_local_asset("https://h1.example/a.png")
    # Walker default limit is 3 hops -> 4 redirect requests never issued.
    assert len(rec.urls) == 4


@pytest.mark.asyncio
async def test_redirect_loop_detected(monkeypatch, public_dns):
    chain = {
        "https://a.example/x.png": "https://b.example/y.png",
        "https://b.example/y.png": "https://a.example/x.png",
    }
    _install_http_mock(monkeypatch, _chain_handler(chain))
    with pytest.raises(AssetDownloadError, match="loop"):
        await ensure_local_asset("https://a.example/x.png")


@pytest.mark.asyncio
async def test_relative_location_resolved_against_current_url(monkeypatch, public_dns):
    chain = {"https://cdn.example/dir/page": "img.png"}
    rec = _Recorder(_chain_handler(chain))
    _install_http_mock(monkeypatch, rec)
    path = await ensure_local_asset("https://cdn.example/dir/page")
    assert _read_bytes(path) == b"PNGDATA"
    assert rec.urls == [
        "https://cdn.example/dir/page",
        "https://cdn.example/dir/img.png",
    ]


@pytest.mark.asyncio
async def test_unsupported_redirect_scheme_rejected(monkeypatch, public_dns):
    rec = _Recorder(
        _chain_handler({"https://cdn.example/a.png": "ftp://evil.example/x"})
    )
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(SSRFSecurityError):
        await ensure_local_asset("https://cdn.example/a.png")
    assert rec.urls == ["https://cdn.example/a.png"]


@pytest.mark.asyncio
async def test_dns_failure_on_redirect_target_rejected(monkeypatch, public_dns):
    """A redirect to a hostname whose DNS fails must be rejected (fail-closed
    applies to revalidation too)."""
    import app.utils.asset_downloader as adm

    real = adm.socket.getaddrinfo

    def _flaky(host, *args, **kwargs):
        if host == "unresolvable.example":
            import socket

            raise socket.gaierror("mocked failure")
        return real(host, *args, **kwargs)

    monkeypatch.setattr(adm.socket, "getaddrinfo", _flaky)
    rec = _Recorder(
        _chain_handler(
            {"https://cdn.example/a.png": "https://unresolvable.example/x.png"}
        )
    )
    _install_http_mock(monkeypatch, rec)
    with pytest.raises(SSRFSecurityError):
        await ensure_local_asset("https://cdn.example/a.png")
    assert rec.urls == ["https://cdn.example/a.png"]


# ---------------------------------------------------------------------------
# 3. ensure_local_asset — preserved download safeguards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_size_cap_enforced(monkeypatch, public_dns):
    _install_http_mock(monkeypatch, _chain_handler({}, final_content=b"X" * 64))
    with pytest.raises(RuntimeError, match="maximum allowed size"):
        await ensure_local_asset("https://cdn.example/big.png", max_bytes=16)


@pytest.mark.asyncio
async def test_zero_byte_download_rejected(monkeypatch, public_dns):
    _install_http_mock(monkeypatch, _chain_handler({}, final_content=b""))
    with pytest.raises(RuntimeError, match="zero bytes"):
        await ensure_local_asset("https://cdn.example/empty.png")


@pytest.mark.asyncio
async def test_http_error_status_wrapped(monkeypatch, public_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _install_http_mock(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="status 404"):
        await ensure_local_asset("https://cdn.example/missing.png")


@pytest.mark.asyncio
async def test_timeout_preserved(monkeypatch, public_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("mocked timeout")

    _install_http_mock(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="timed out"):
        await ensure_local_asset("https://cdn.example/slow.png")
