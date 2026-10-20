"""Focused unit and regression tests for asset download SSRF protection and redirect validation.

Validates remediation of asset-download-ssrf-filter-bypass:
- Rejection of canonical loopback (127.0.0.1)
- Rejection of non-canonical shorthand IPv4 loopback (127.1, 0x7f000001, 2130706433)
- Rejection of private IPv4 addresses (10.x, 172.16.x, 192.168.x)
- Rejection of IPv6 loopback ([::1])
- Rejection of hostnames resolving to private/loopback addresses
- Rejection of HTTP 3xx redirects targeting loopback destinations
- Rejection of HTTP 3xx redirects targeting private destinations
- Acceptance of legitimate safe redirects
- Rejection of non-HTTP schemes (file://, ftp://)
- Regression test for legitimate remote downloads
"""

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.utils.asset_manager import ensure_local_asset, is_safe_asset_url


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("ARYA_API_KEY", "test-secret-key")
    with patch("app.core.secrets.SecretsManager.get", return_value="test-secret-key"):
        client = TestClient(app)
        client.headers.update({"Authorization": "Bearer test-secret-key"})
        yield client


# ---------------------------------------------------------------------------
# Test A: Canonical Loopback
# ---------------------------------------------------------------------------
def test_canonical_loopback_rejected(auth_client):
    """Test A: Canonical loopback address 127.0.0.1 is rejected."""
    url = "http://127.0.0.1:8000/internal-metrics"
    assert is_safe_asset_url(url) is False

    res = auth_client.get(f"/creator/assets/download?url={url}")
    assert res.status_code == 400
    assert "Insecure or disallowed remote URL" in res.text


# ---------------------------------------------------------------------------
# Test B: Shorthand / Non-Canonical Loopback
# ---------------------------------------------------------------------------
def test_shorthand_loopback_rejected(auth_client):
    """Test B: Shorthand / non-canonical loopback representations are rejected."""
    shorthand_urls = [
        "http://127.1:8000/secret",
        "http://0x7f000001:8000/secret",
        "http://2130706433:8000/secret",
        "http://0177.0.0.1:8000/secret",
    ]
    for url in shorthand_urls:
        assert is_safe_asset_url(url) is False, f"Expected {url} to be unsafe"
        res = auth_client.get(f"/creator/assets/download?url={url}")
        assert res.status_code == 400
        assert "Insecure or disallowed remote URL" in res.text


# ---------------------------------------------------------------------------
# Test C: IPv4 Private Addresses
# ---------------------------------------------------------------------------
def test_ipv4_private_addresses_rejected(auth_client):
    """Test C: RFC 1918 private IPv4 addresses are rejected."""
    private_urls = [
        "http://10.0.0.1/admin",
        "http://10.254.254.1/secret",
        "http://172.16.0.1/config",
        "http://172.31.255.255/db",
        "http://192.168.1.1/router",
        "http://192.168.0.100/status",
        "http://169.254.169.254/latest/meta-data",
    ]
    for url in private_urls:
        assert is_safe_asset_url(url) is False, f"Expected {url} to be unsafe"
        res = auth_client.get(f"/creator/assets/download?url={url}")
        assert res.status_code == 400
        assert "Insecure or disallowed remote URL" in res.text


# ---------------------------------------------------------------------------
# Test D: IPv6 Loopback
# ---------------------------------------------------------------------------
def test_ipv6_loopback_rejected(auth_client):
    """Test D: IPv6 loopback address [::1] is rejected."""
    url = "http://[::1]:8000/secret"
    assert is_safe_asset_url(url) is False

    res = auth_client.get(f"/creator/assets/download?url={url}")
    assert res.status_code == 400
    assert "Insecure or disallowed remote URL" in res.text


# ---------------------------------------------------------------------------
# Test E: Hostname Resolving to Loopback / Private Address
# ---------------------------------------------------------------------------
def test_hostname_resolving_to_private_rejected(auth_client):
    """Test E: Hostnames resolving to loopback or private IPs are rejected locally."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "intranet-rebinding.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        if host == "corp-internal.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.10.10.10", 80))]
        return socket.getaddrinfo(host, port, *args, **kwargs)

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        assert is_safe_asset_url("http://intranet-rebinding.test/asset.png") is False
        assert is_safe_asset_url("http://corp-internal.test/asset.png") is False

        res1 = auth_client.get("/creator/assets/download?url=http://intranet-rebinding.test/asset.png")
        assert res1.status_code == 400
        assert "Insecure or disallowed remote URL" in res1.text

        res2 = auth_client.get("/creator/assets/download?url=http://corp-internal.test/asset.png")
        assert res2.status_code == 400
        assert "Insecure or disallowed remote URL" in res2.text


# ---------------------------------------------------------------------------
# Test F: Redirect to Loopback Destination
# ---------------------------------------------------------------------------
def test_redirect_to_loopback_blocked(auth_client):
    """Test F: Redirect from an allowed initial URL to a loopback address is blocked before connection."""
    res_redirect = httpx.Response(
        status_code=302,
        headers={"Location": "http://127.0.0.1:8000/internal-data"},
    )
    with patch("app.utils.asset_manager.is_safe_asset_url") as mock_safe:
        mock_safe.side_effect = lambda u: False if "127.0.0.1" in u else True
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = res_redirect

            res = auth_client.get("/creator/assets/download?url=https://allowed-cdn.example/video.mp4")
            assert res.status_code == 400
            assert "Insecure or disallowed remote URL" in res.text
            assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Test G: Redirect to Private Address
# ---------------------------------------------------------------------------
def test_redirect_to_private_blocked(auth_client):
    """Test G: Redirect targeting a private address (10.0.0.5) is blocked before connection."""
    res_redirect = httpx.Response(
        status_code=302,
        headers={"Location": "http://10.0.0.5:8080/private-asset.png"},
    )
    with patch("app.utils.asset_manager.is_safe_asset_url") as mock_safe:
        mock_safe.side_effect = lambda u: False if "10.0.0.5" in u else True
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = res_redirect

            res = auth_client.get("/creator/assets/download?url=https://allowed-cdn.example/video.mp4")
            assert res.status_code == 400
            assert "Insecure or disallowed remote URL" in res.text
            assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Test H: Safe Redirect
# ---------------------------------------------------------------------------
def test_safe_redirect_followed(auth_client):
    """Test H: Redirect between two safe destinations is followed successfully."""
    res_redirect = httpx.Response(
        status_code=302,
        headers={"Location": "https://allowed-cdn.example/final-target.mp4"},
    )
    res_final = httpx.Response(
        status_code=200,
        content=b"LEGITIMATE_MEDIA_BYTES",
        headers={"Content-Type": "video/mp4"},
    )

    with patch("app.utils.asset_manager.is_safe_asset_url", return_value=True):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [res_redirect, res_final]

            res = auth_client.get(
                "/creator/assets/download?url=https://allowed-cdn.example/initial.mp4&filename=video.mp4"
            )
            assert res.status_code == 200
            assert res.content == b"LEGITIMATE_MEDIA_BYTES"
            assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Test I: Non-HTTP Scheme
# ---------------------------------------------------------------------------
def test_non_http_schemes_rejected(auth_client):
    """Test I: Non-HTTP(S) schemes like file:// and ftp:// are rejected."""
    assert is_safe_asset_url("file:///etc/passwd") is False
    assert is_safe_asset_url("ftp://example.com/asset.png") is False
    assert is_safe_asset_url("gopher://example.com/item") is False

    res_ftp = auth_client.get("/creator/assets/download?url=ftp://example.com/asset.png")
    assert res_ftp.status_code in (400, 403, 404)


# ---------------------------------------------------------------------------
# Test J: Legitimate Remote Download
# ---------------------------------------------------------------------------
def test_legitimate_remote_download_success(auth_client):
    """Test J: Legitimate remote download from a safe destination passes."""
    res_ok = httpx.Response(
        status_code=200,
        content=b"VALID_GENERATED_IMAGE_CONTENT",
        headers={"Content-Type": "image/png"},
    )
    with patch("app.utils.asset_manager.is_safe_asset_url", return_value=True):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = res_ok

            res = auth_client.get(
                "/creator/assets/download?url=https://replicate.delivery/pbxt/sample.png&filename=my_art.png"
            )
            assert res.status_code == 200
            assert res.content == b"VALID_GENERATED_IMAGE_CONTENT"
            assert 'attachment; filename="my_art.png"' in res.headers.get("Content-Disposition", "")
            assert res.headers.get("Content-Length") == str(len(b"VALID_GENERATED_IMAGE_CONTENT"))
