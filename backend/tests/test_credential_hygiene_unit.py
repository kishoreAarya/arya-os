"""Phase 48B — test credential hygiene regression tests.

Proves, without reading .env or contacting any external service:

1. The shared ``synthetic_api_key`` fixture pins the cached Settings
   object to the synthetic credential, so ambient environment values
   (including a live ARYA_API_KEY in .env) cannot determine the token
   tests authenticate with.
2. The application's own ``verify_api_key`` dependency validates against
   the synthetic value (accept) and rejects a wrong token (401) while
   the fixture is active — i.e. the real auth path is exercised, not
   bypassed.
3. Static trip-wire: none of the audited test files interpolate
   ``arya_api_key`` from settings into Authorization headers anymore.
"""

import re
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.security import verify_api_key
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

_TESTS_DIR = Path(__file__).resolve().parent

# Files audited in Phase 48A (conftest excluded — it DEFINES the fixture).
_AUDITED_FILES = (
    "test_reddit_research_unit.py",
    "test_creator_loop_integration.py",
    "test_storage_hardening_unit.py",
    "test_analytics_ingestion_unit.py",
    "test_postiz_publishing_unit.py",
    "test_creator_provenance.py",
    "test_publication_attempt_reconciliation.py",
)


def test_synthetic_fixture_overrides_ambient_environment(synthetic_api_key):
    """While the fixture is active, the cached Settings object — the exact
    instance the app's auth dependency reads — holds the synthetic value."""
    assert synthetic_api_key == "synthetic-test-bearer-key"
    assert get_settings().arya_api_key == synthetic_api_key
    # The real auth path is forced on, deterministically.
    assert get_settings().api_auth_enabled is True


def test_app_validates_against_synthetic_not_ambient(synthetic_api_key):
    """The application's own auth dependency accepts the synthetic token
    and rejects a wrong one while the fixture is active."""
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=synthetic_api_key)
    assert (
        verify_api_key(credentials=creds, settings=get_settings()) == synthetic_api_key
    )

    bad = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="definitely-not-the-token"
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=bad, settings=get_settings())
    assert exc_info.value.status_code == 401
    # 401 detail must never echo the presented token.
    assert "definitely-not-the-token" not in str(exc_info.value.detail)


def test_no_live_key_interpolation_remains():
    """Static trip-wire (supplementary, not the only evidence): the audited
    files must not build Authorization headers from settings lookups."""
    pattern = re.compile(r"Bearer\s*\{[^}]*arya_api_key")
    offenders = []
    for name in _AUDITED_FILES:
        source = (_TESTS_DIR / name).read_text(encoding="utf-8")
        if pattern.search(source):
            offenders.append(name)
    assert offenders == [], f"live arya_api_key interpolation found in: {offenders}"


def test_conftest_defines_the_shared_synthetic_credential():
    source = (_TESTS_DIR / "conftest.py").read_text(encoding="utf-8")
    assert 'TEST_API_KEY = "synthetic-test-bearer-key"' in source
