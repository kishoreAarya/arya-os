"""Phase 44A security remediation unit tests.

Focused, deterministic coverage for the eight approved application fixes:

- M-1a: asset URL validator convergence (DNS-aware delegation)
- M-1b: bounded, validated redirects in /creator/assets/download
- L-4:  bounded, validated redirects in the pipeline asset downloader
- M-2:  CORS tightened to explicit origins, credentials disabled
- L-2:  public health endpoints never echo exception details
- L-10: API docs/OpenAPI disabled in production only
- L-3:  Gemini API key sent via x-goog-api-key header, never in the URL

L-6 (get_refresh_token.py) is a utility script whose module body executes a
live OAuth flow on import; testing it deterministically would require
refactoring the script, which is out of Phase 44A scope. Its change is
verified by diff review only.

All HTTP interactions use httpx.MockTransport and all DNS resolution is
monkeypatched — no real network calls, no real credentials.
"""

import importlib
from pathlib import Path

import app.api.routers.health as health_module
import app.utils.asset_downloader as asset_downloader_module
import httpx
import pytest
from app.core.config import get_settings
from app.main import app
from app.providers import gemini
from app.utils.asset_downloader import (
    AssetDownloadError,
    SSRFSecurityError,
    download_media_asset,
    download_remote_asset,
    is_safe_remote_url,
)
from app.utils.asset_manager import is_safe_asset_url
from fastapi.testclient import TestClient

TEST_KEY = "phase44a-synthetic-bearer-key"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fake_dns(ip: str):
    """Deterministic getaddrinfo replacement: every hostname resolves to ip."""

    def _getaddrinfo(host, *args, **kwargs):
        import socket

        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _getaddrinfo


def _install_http_mock(monkeypatch, handler):
    """Force every httpx.AsyncClient constructed during the test to use a
    MockTransport with the given handler (captures requests, no network)."""
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _auth_headers():
    return {"Authorization": f"Bearer {TEST_KEY}"}


@pytest.fixture
def auth_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "arya_api_key", TEST_KEY, raising=False)
    return settings


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        asset_downloader_module.socket, "getaddrinfo", _fake_dns("93.184.216.34")
    )


# ---------------------------------------------------------------------------
# M-1a — asset URL validator convergence
# ---------------------------------------------------------------------------


def test_m1a_dns_name_resolving_to_private_ip_rejected(monkeypatch):
    monkeypatch.setattr(asset_downloader_module.socket, "getaddrinfo", _fake_dns("10.1.2.3"))
    assert is_safe_asset_url("https://cdn.assets-provider.example/img.png") is False


def test_m1a_metadata_hostname_rejected():
    assert is_safe_asset_url("https://metadata.google.internal/latest/meta-data/") is False


def test_m1a_dns_name_resolving_to_public_ip_allowed(monkeypatch):
    monkeypatch.setattr(asset_downloader_module.socket, "getaddrinfo", _fake_dns("93.184.216.34"))
    assert is_safe_asset_url("https://cdn.assets-provider.example/img.png") is True


def test_m1a_literal_private_ip_rejected():
    assert is_safe_asset_url("http://192.168.0.10/internal.png") is False


def test_m1a_delegates_to_dns_aware_validator(monkeypatch):
    """is_safe_asset_url must be the same guard as is_safe_remote_url."""
    monkeypatch.setattr(asset_downloader_module.socket, "getaddrinfo", _fake_dns("172.16.0.9"))
    url = "https://any-host.example/x.png"
    assert is_safe_asset_url(url) == is_safe_remote_url(url) is False


# ---------------------------------------------------------------------------
# M-1b — bounded redirect validation in /creator/assets/download
# ---------------------------------------------------------------------------


def _redirect_handler(chain: dict, final_content: bytes = b"PNGDATA"):
    """chain maps host -> next Location; hosts not in chain serve the asset."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in chain:
            return httpx.Response(302, headers={"Location": chain[host]})
        return httpx.Response(
            200, content=final_content, headers={"Content-Type": "image/png"}
        )

    return handler


def _proxy_download(monkeypatch, target_url: str, chain: dict):
    _install_http_mock(monkeypatch, _redirect_handler(chain))
    client = TestClient(app)
    return client.get(
        "/creator/assets/download",
        params={"url": target_url, "filename": "a.png"},
        headers=_auth_headers(),
    )


def test_m1b_direct_public_url_succeeds(monkeypatch, auth_settings, public_dns):
    resp = _proxy_download(
        monkeypatch, "https://final.example/a.png", {"unused.example": "https://x.example/"}
    )
    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"].startswith("image/png")
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_m1b_public_to_public_redirect_succeeds(monkeypatch, auth_settings, public_dns):
    resp = _proxy_download(
        monkeypatch,
        "https://origin.example/a.png",
        {"origin.example": "https://final.example/a.png"},
    )
    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"


def test_m1b_three_hop_redirect_succeeds(monkeypatch, auth_settings, public_dns):
    resp = _proxy_download(
        monkeypatch,
        "https://origin.example/a.png",
        {
            "origin.example": "https://hop1.example/a.png",
            "hop1.example": "https://hop2.example/a.png",
            "hop2.example": "https://final.example/a.png",
        },
    )
    assert resp.status_code == 200


def test_m1b_redirect_to_private_ip_rejected(monkeypatch, auth_settings, public_dns):
    _install_http_mock(
        monkeypatch,
        _redirect_handler({"origin.example": "http://10.9.8.7/secret.png"}),
    )
    client = TestClient(app)
    resp = client.get(
        "/creator/assets/download",
        params={"url": "https://origin.example/a.png", "filename": "a.png"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_m1b_redirect_to_localhost_rejected(monkeypatch, auth_settings, public_dns):
    _install_http_mock(
        monkeypatch,
        _redirect_handler({"origin.example": "http://localhost:8000/secret"}),
    )
    client = TestClient(app)
    resp = client.get(
        "/creator/assets/download",
        params={"url": "https://origin.example/a.png", "filename": "a.png"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_m1b_redirect_to_metadata_rejected(monkeypatch, auth_settings, public_dns):
    _install_http_mock(
        monkeypatch,
        _redirect_handler(
            {"origin.example": "https://metadata.google.internal/latest/meta-data/"}
        ),
    )
    client = TestClient(app)
    resp = client.get(
        "/creator/assets/download",
        params={"url": "https://origin.example/a.png", "filename": "a.png"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_m1b_redirect_chain_over_three_hops_rejected(monkeypatch, auth_settings, public_dns):
    # origin -> hop1 -> hop2 -> hop3 -> final  (4 redirects: one too many)
    resp = _proxy_download(
        monkeypatch,
        "https://origin.example/a.png",
        {
            "origin.example": "https://hop1.example/a.png",
            "hop1.example": "https://hop2.example/a.png",
            "hop2.example": "https://hop3.example/a.png",
            "hop3.example": "https://final.example/a.png",
        },
    )
    assert resp.status_code == 502


def test_m1b_redirect_loop_rejected(monkeypatch, auth_settings, public_dns):
    _install_http_mock(
        monkeypatch,
        _redirect_handler({"loop-a.example": "https://loop-b.example/x", "loop-b.example": "https://loop-a.example/x"}),
    )
    client = TestClient(app)
    resp = client.get(
        "/creator/assets/download",
        params={"url": "https://loop-a.example/a.png", "filename": "a.png"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 502


def test_m1b_malformed_or_missing_location_rejected(monkeypatch, auth_settings, public_dns):
    def bad_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "noloc.example":
            return httpx.Response(302)  # missing Location
        if request.url.host == "badloc.example":
            return httpx.Response(302, headers={"Location": "::::not-a-url"})
        return httpx.Response(200, content=b"x")

    _install_http_mock(monkeypatch, bad_handler)
    client = TestClient(app)
    for host in ("noloc.example", "badloc.example"):
        resp = client.get(
            "/creator/assets/download",
            params={"url": f"https://{host}/a.png", "filename": "a.png"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 502, host


def test_m1b_authentication_still_required(monkeypatch, auth_settings, public_dns):
    _install_http_mock(monkeypatch, _redirect_handler({}))
    client = TestClient(app)
    resp = client.get(
        "/creator/assets/download",
        params={"url": "https://final.example/a.png", "filename": "a.png"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# L-4 — bounded redirect validation in the pipeline asset downloader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l4_download_media_asset_validated_redirect_succeeds(
    monkeypatch, public_dns, tmp_path
):
    _install_http_mock(
        monkeypatch, _redirect_handler({"origin.example": "https://final.example/v.mp4"})
    )
    path, telemetry = await download_media_asset(
        "https://origin.example/v.mp4", dest_dir=str(tmp_path), max_bytes=1024
    )
    assert telemetry["bytes"] == len(b"PNGDATA")
    assert Path(path).read_bytes() == b"PNGDATA"


@pytest.mark.asyncio
async def test_l4_download_media_asset_private_redirect_rejected(
    monkeypatch, public_dns, tmp_path
):
    _install_http_mock(
        monkeypatch, _redirect_handler({"origin.example": "http://169.254.169.254/latest"})
    )
    with pytest.raises(SSRFSecurityError):
        await download_media_asset(
            "https://origin.example/v.mp4", dest_dir=str(tmp_path), max_bytes=1024
        )


@pytest.mark.asyncio
async def test_l4_download_media_asset_loop_rejected(monkeypatch, public_dns, tmp_path):
    _install_http_mock(
        monkeypatch,
        _redirect_handler({"loop-a.example": "https://loop-b.example/x", "loop-b.example": "https://loop-a.example/x"}),
    )
    with pytest.raises(AssetDownloadError):
        await download_media_asset(
            "https://loop-a.example/v.mp4", dest_dir=str(tmp_path), max_bytes=1024
        )


@pytest.mark.asyncio
async def test_l4_download_media_asset_too_many_hops_rejected(
    monkeypatch, public_dns, tmp_path
):
    _install_http_mock(
        monkeypatch,
        _redirect_handler(
            {
                "origin.example": "https://hop1.example/a",
                "hop1.example": "https://hop2.example/a",
                "hop2.example": "https://hop3.example/a",
                "hop3.example": "https://final.example/a",
            }
        ),
    )
    with pytest.raises(AssetDownloadError):
        await download_media_asset(
            "https://origin.example/v.mp4", dest_dir=str(tmp_path), max_bytes=1024
        )


@pytest.mark.asyncio
async def test_l4_download_remote_asset_private_redirect_rejected(
    monkeypatch, public_dns, tmp_path
):
    _install_http_mock(
        monkeypatch, _redirect_handler({"origin.example": "http://10.0.0.5/internal.png"})
    )
    with pytest.raises(SSRFSecurityError):
        await download_remote_asset(
            "https://origin.example/x.png", dest_path=tmp_path / "out.png"
        )


# ---------------------------------------------------------------------------
# M-2 — CORS tightening
# ---------------------------------------------------------------------------


def test_m2_allowed_origin_receives_acao_header():
    client = TestClient(app)
    resp = client.get("/", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_m2_allowed_origin_127_receives_acao_header():
    client = TestClient(app)
    resp = client.get("/", headers={"Origin": "http://127.0.0.1:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_m2_disallowed_origin_receives_no_acao_header():
    client = TestClient(app)
    resp = client.get("/", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_m2_no_wildcard_origin_and_credentials_disabled():
    cors = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
    assert cors, "CORSMiddleware must be installed"
    kwargs = cors[0].kwargs
    assert "*" not in kwargs["allow_origins"]
    assert kwargs["allow_credentials"] is False
    assert "http://localhost:5173" in kwargs["allow_origins"]
    assert "http://127.0.0.1:5173" in kwargs["allow_origins"]


# ---------------------------------------------------------------------------
# L-2 — public health error sanitization
# ---------------------------------------------------------------------------


class _ExplodingDB:
    async def execute(self, *args, **kwargs):
        raise RuntimeError(
            "postgresql+asyncpg://arya:TOPSECRETPW@secret-db-host.internal:5432/arya_os"
        )


def test_l2_health_does_not_leak_exception_details():
    async def _override_db():
        return _ExplodingDB()

    app.dependency_overrides[health_module.get_db] = _override_db
    try:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.text
        assert "TOPSECRETPW" not in body
        assert "secret-db-host" not in body
        assert "postgresql" not in body
        assert "error:" not in body
        assert resp.json()["checks"]["postgres"] == "error"
    finally:
        app.dependency_overrides.pop(health_module.get_db, None)


def test_l2_ready_does_not_leak_storage_exception_details(monkeypatch):
    def _boom():
        raise RuntimeError("SECRET storage failure at /srv/secret-path")

    monkeypatch.setattr(health_module, "get_storage_provider", _boom)

    async def _override_db():
        return _ExplodingDB()

    app.dependency_overrides[health_module.get_db] = _override_db
    try:
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.text
        assert "SECRET" not in body
        assert "/srv/secret-path" not in body
        assert "TOPSECRETPW" not in body
        assert resp.json()["storage"] == "error"
    finally:
        app.dependency_overrides.pop(health_module.get_db, None)


# ---------------------------------------------------------------------------
# L-10 — production-only API docs disabling
# ---------------------------------------------------------------------------


def _reload_app_with_env(monkeypatch, app_env: str | None):
    """Reload app.main under a forced APP_ENV and return its app object.

    Never asserts on the Settings object itself (its repr contains live
    configuration values that must not appear in test output).
    """
    import app.main as main_module

    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    get_settings.cache_clear()
    importlib.reload(main_module)
    return main_module.app


def test_l10_docs_available_outside_production(monkeypatch):
    prod_app = _reload_app_with_env(monkeypatch, "development")
    client = TestClient(prod_app)
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_l10_docs_disabled_in_production(monkeypatch):
    prod_app = _reload_app_with_env(monkeypatch, "production")
    client = TestClient(prod_app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---------------------------------------------------------------------------
# L-3 — Gemini API key in header, never in URL
# ---------------------------------------------------------------------------

GEMINI_TEST_KEY = "phase44a-synthetic-gemini-key-000"


def _gemini_ok_handler(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "generated text"}]}}],
                "usageMetadata": {"totalTokenCount": 10},
            },
        )

    return handler


@pytest.mark.asyncio
async def test_l3_gemini_key_in_header_not_url(monkeypatch):
    captured: list = []
    _install_http_mock(monkeypatch, _gemini_ok_handler(captured))
    text, cost = await gemini.generate_text(
        prompt="hello", api_key=GEMINI_TEST_KEY, model="gemini-2.0-flash"
    )
    assert text == "generated text"
    assert cost == round((10 / 1000) * 0.0003, 6)
    assert len(captured) == 1
    request = captured[0]
    assert request.headers.get("x-goog-api-key") == GEMINI_TEST_KEY
    assert GEMINI_TEST_KEY not in str(request.url)
    assert request.url.params.get("key") is None
    assert (
        str(request.url).startswith(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        )
    )


@pytest.mark.asyncio
async def test_l3_gemini_error_handling_unchanged(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "API key not valid"}})

    _install_http_mock(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="Gemini rejected the API key \\(401\\)"):
        await gemini.generate_text(
            prompt="hello", api_key=GEMINI_TEST_KEY, model="gemini-2.0-flash"
        )
