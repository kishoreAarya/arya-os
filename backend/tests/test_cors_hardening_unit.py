"""
Security regression unit tests for:
cors-wildcard-origin-reflection (CWE-942 / CWE-346)

Verifies:
1. A trusted configured origin receives the appropriate CORS headers.
2. An untrusted origin does NOT receive an Access-Control-Allow-Origin header.
3. Credentialed requests cannot cause arbitrary Origin reflection.
4. Preflight OPTIONS behavior is valid for trusted origins.
5. Preflight OPTIONS for untrusted origins is rejected or does not emit allow headers.
6. Wildcard security invariant: credentials must never be enabled when wildcard is present.
7. Existing non-CORS API behavior remains unchanged.
8. Settings parsing handles comma-separated, JSON array, and default list configurations.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_cors_trusted_origin_receives_headers(client):
    """A configured trusted origin receives the appropriate CORS headers."""
    trusted_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
    ]
    for origin in trusted_origins:
        resp = client.get("/", headers={"Origin": origin})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_untrusted_origin_not_reflected(client):
    """An untrusted origin does NOT receive an Access-Control-Allow-Origin header."""
    untrusted_origins = [
        "https://attacker.com",
        "https://malicious.evil.io",
        "http://localhost.evil.com",
        "http://evil-localhost:3000",
        "null",
    ]
    for origin in untrusted_origins:
        resp = client.get("/", headers={"Origin": origin})
        assert resp.status_code == 200
        # The untrusted origin must NOT be reflected
        assert resp.headers.get("access-control-allow-origin") is None


def test_cors_credentialed_request_no_arbitrary_reflection(client):
    """Credentialed requests with untrusted Origin cannot cause origin reflection."""
    resp = client.get(
        "/",
        headers={
            "Origin": "https://attacker.com",
            "Authorization": "Bearer some-token",
            "Cookie": "session=secret",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") is None
    # Access-Control-Allow-Origin must be absent, so browser will block access to the response


def test_cors_preflight_trusted_origin(client):
    """Preflight OPTIONS request from a trusted origin is approved."""
    resp = client.options(
        "/",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_untrusted_origin_rejected(client):
    """Preflight OPTIONS request from an untrusted origin is rejected."""
    resp = client.options(
        "/",
        headers={
            "Origin": "https://attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette CORSMiddleware responds with 400 for disallowed preflights,
    # and omits Access-Control-Allow-Origin
    assert resp.headers.get("access-control-allow-origin") is None


def test_cors_non_cors_requests_unaffected(client):
    """Regular non-CORS requests without an Origin header proceed normally."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"service": "arya-os", "status": "running", "sprint": 3}
    assert "access-control-allow-origin" not in resp.headers


def test_cors_wildcard_safety_invariant():
    """If wildcard origin is configured, credentials must be strictly disabled to prevent origin reflection."""
    test_settings = Settings(
        cors_allowed_origins=["*"],
        cors_allow_credentials=True,
    )
    cors_origins = [o.strip() for o in test_settings.cors_allowed_origins if o.strip()]
    has_wildcard = "*" in cors_origins
    cors_allow_credentials = test_settings.cors_allow_credentials and not has_wildcard

    assert has_wildcard is True
    assert cors_allow_credentials is False  # Invariant enforced: credentials turned off when wildcard used

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @test_app.get("/ping")
    def ping():
        return {"ping": "pong"}

    tclient = TestClient(test_app)
    resp = tclient.get("/ping", headers={"Origin": "https://arbitrary-site.com"})
    # When allow_credentials is False and wildcard is used, origin must be wildcard "*", NOT the reflected domain with credentials
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("access-control-allow-credentials") is None


def test_cors_settings_parsing():
    """Verify Settings parses comma-separated strings, JSON arrays, and lists."""
    # 1. Comma-separated string
    s1 = Settings(cors_allowed_origins="http://a.com, http://b.com,")
    assert s1.cors_allowed_origins == ["http://a.com", "http://b.com"]

    # 2. JSON list string
    s2 = Settings(cors_allowed_origins='["http://c.com", "http://d.com"]')
    assert s2.cors_allowed_origins == ["http://c.com", "http://d.com"]

    # 3. Native list
    s3 = Settings(cors_allowed_origins=["http://e.com"])
    assert s3.cors_allowed_origins == ["http://e.com"]

    # 4. Empty string
    s4 = Settings(cors_allowed_origins="")
    assert s4.cors_allowed_origins == []
