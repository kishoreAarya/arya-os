"""L-7 Redis authentication — static configuration-contract tests.

Read-only validation of the authenticated Redis contract WITHOUT Docker:
- Settings and the redis-py client accept credential-bearing REDIS_URLs.
- Both compose files require Redis authentication (requirepass via
  REDIS_PASSWORD with fail-fast interpolation), construct the backend's
  REDIS_URL from the same secret, and keep the audited exposure posture
  (dev loopback-only, prod unpublished).
- The CI workflow starts Redis with --requirepass and hands tests an
  authenticated REDIS_URL.
- .env.example no longer advertises the dead REDIS_HOST/REDIS_PORT
  application contract.
- /health still degrades (never crashes) when Redis is unavailable.

Secret safety: every credential used here is synthetic; no test prints a
password, a credential-bearing URL, or an environment dump (assertions are
name/shape/boolean checks only).
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from app.api.routers.health import health
from app.core.config import Settings
from fastapi import Request

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SYNTHETIC_PASSWORD = "synthetic-redis-password-do-not-print"


# ---------------------------------------------------------------------------
# A. Configuration: credential-bearing REDIS_URL parsing
# ---------------------------------------------------------------------------


def test_settings_accept_password_only_redis_url():
    settings = Settings(redis_url=f"redis://:{_SYNTHETIC_PASSWORD}@localhost:6379/0")
    assert settings.redis_url.startswith("redis://:")


def test_settings_accept_user_password_redis_url():
    settings = Settings(
        redis_url=f"redis://arya-redis-user:{_SYNTHETIC_PASSWORD}@localhost:6379/0"
    )
    assert settings.redis_url.startswith("redis://arya-redis-user:")


@pytest.mark.asyncio
async def test_redis_client_parses_embedded_credentials():
    """redis.from_url (the exact call backend/app/main.py makes) must carry
    the URL-embedded password into the connection pool — proving the client
    needs no code change for L-7. from_url is lazy: no connection is made,
    so this test performs no network I/O."""
    import redis.asyncio as redis

    client = redis.from_url(
        f"redis://:{_SYNTHETIC_PASSWORD}@localhost:6379/0",
        decode_responses=True,
    )
    try:
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs.get("password") == _SYNTHETIC_PASSWORD
        assert kwargs.get("host") == "localhost"
        assert kwargs.get("port") == 6379
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# B. Compose configuration contract (static, no Docker)
# ---------------------------------------------------------------------------


def _load_compose(name: str) -> dict:
    with open(_REPO_ROOT / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_DEV = _load_compose("docker-compose.yml")
_PROD = _load_compose("docker-compose.prod.yml")


def _redis_service(compose: dict) -> dict:
    return compose["services"]["redis"]


def _backend_env(compose: dict) -> dict:
    return compose["services"]["backend"]["environment"]


def _assert_requirepass(redis_service: dict) -> None:
    command = redis_service["command"]
    assert "redis-server" in command
    assert "--requirepass" in command
    # The password slot must be compose interpolation with the M1-style
    # fail-fast guard — never a literal secret and never a bare default.
    password_slot = command[command.index("--requirepass") + 1]
    assert password_slot.startswith(
        "${REDIS_PASSWORD:?"
    ), "requirepass value must be fail-fast REDIS_PASSWORD interpolation"
    assert "must be set" in password_slot


def test_dev_redis_requires_authentication():
    _assert_requirepass(_redis_service(_DEV))


def test_prod_redis_requires_authentication():
    _assert_requirepass(_redis_service(_PROD))


def test_dev_redis_remains_loopback_only():
    assert _redis_service(_DEV)["ports"] == ["127.0.0.1:6379:6379"]


def test_prod_redis_remains_unpublished():
    assert "ports" not in _redis_service(_PROD)


def test_dev_backend_redis_url_is_constructed_authenticated():
    url = _backend_env(_DEV)["REDIS_URL"]
    assert url.startswith("redis://:${REDIS_PASSWORD:?")
    assert url.endswith("@redis:6379/0")


def test_prod_backend_redis_url_is_constructed_authenticated():
    url = _backend_env(_PROD)["REDIS_URL"]
    assert url.startswith("redis://:${REDIS_PASSWORD:?")
    assert url.endswith("@redis:6379/0")
    # The old unauthenticated prod URL shape must not return.
    assert url != "redis://redis:6379/0"


def _assert_authenticated_healthcheck(redis_service: dict) -> None:
    test_cmd = redis_service["healthcheck"]["test"]
    assert test_cmd[0] == "CMD-SHELL"
    script = test_cmd[1]
    assert "redis-cli" in script and "ping" in script
    # Authentication must come from the container-local environment
    # ($$-escaped compose reference), never a literal password in the file.
    assert '"$$REDIS_PASSWORD"' in script
    assert "--no-auth-warning" in script
    # The redis container must actually define that variable (fail-fast
    # interpolation, same contract as requirepass).
    env = redis_service["environment"]
    assert env["REDIS_PASSWORD"].startswith("${REDIS_PASSWORD:?")


def test_dev_healthcheck_authenticates_without_literal_secret():
    _assert_authenticated_healthcheck(_redis_service(_DEV))


def test_prod_healthcheck_authenticates_without_literal_secret():
    _assert_authenticated_healthcheck(_redis_service(_PROD))


def test_compose_files_contain_no_literal_redis_password():
    """No real or placeholder password may be hardcoded where compose
    expects interpolation — every non-comment line that mentions
    REDIS_PASSWORD must carry an interpolated reference (the
    ${REDIS_PASSWORD:?...} value form or the $$REDIS_PASSWORD
    healthcheck form). Fail-fast value forms are asserted separately."""
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        text = (_REPO_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "REDIS_PASSWORD" not in line or line.lstrip().startswith("#"):
                continue
            assert (
                "${REDIS_PASSWORD:?" in line or "$$REDIS_PASSWORD" in line
            ), f"non-interpolated REDIS_PASSWORD spelling in {name}"


# ---------------------------------------------------------------------------
# C. Environment-contract (.env.example) and CI workflow
# ---------------------------------------------------------------------------


def test_env_example_has_no_dead_redis_host_port_contract():
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    active = (ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    for line in active:
        assert not re.match(
            r"^\s*REDIS_(HOST|PORT)\s*=", line
        ), "REDIS_HOST/REDIS_PORT are not application configuration"


def test_env_example_documents_password_and_authenticated_url():
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    active = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert any(re.match(r"^\s*REDIS_PASSWORD=", ln) for ln in active)
    # The documented REDIS_URL example must carry the credential slot.
    url_lines = [ln for ln in active if re.match(r"^\s*REDIS_URL=", ln)]
    assert url_lines, "REDIS_URL example entry missing"
    assert all(":change_me@" in ln for ln in url_lines)


def test_ci_redis_requires_authentication_and_matches_url():
    with open(
        _REPO_ROOT / ".github" / "workflows" / "test.yml", encoding="utf-8"
    ) as fh:
        workflow = yaml.safe_load(fh)

    job = workflow["jobs"]["pytest"]
    # No unauthenticated redis service container may remain.
    assert "redis" not in job.get("services", {})
    # Tests receive a credential-bearing REDIS_URL.
    url = job["env"]["REDIS_URL"]
    assert url.startswith("redis://:") and ":arya-ci-synthetic-redis-password@" in url
    # Redis itself is started with requirepass.
    scripts = [step.get("run", "") for step in job["steps"]]
    start_script = next(s for s in scripts if "--requirepass" in s)
    assert "redis:7-alpine" in start_script
    assert "-e REDIS_PASSWORD=" in start_script


# ---------------------------------------------------------------------------
# D. Health regression: Redis unavailable ⇒ degraded, never a crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_reports_degraded_when_redis_unavailable():
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis.ping = AsyncMock(
        side_effect=ConnectionRefusedError("Redis down")
    )

    res = await health(request=mock_request, db=mock_db)

    assert res["checks"]["postgres"] == "ok"
    assert res["checks"]["redis"] == "error"
    assert res["status"] == "degraded"
