"""
Unit tests for app/providers/openrouter.py — the module that was
missing entirely, breaking agents/trend.py and agents/storyboard.py's
imports (Issue: broken `from app.providers import openrouter`).

HTTP is mocked (monkeypatching httpx.AsyncClient), no real network,
matching the pattern already used elsewhere in this test suite.
"""
import httpx
import pytest

from app.providers import openrouter


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


def _patch_client(monkeypatch, response):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", FakeAsyncClient)


async def test_generate_text_success(monkeypatch):
    fake = FakeResponse(
        200,
        {
            "choices": [{"message": {"content": "Hello world"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )
    _patch_client(monkeypatch, fake)

    text, cost_usd = await openrouter.generate_text(
        prompt="say hi", api_key="test-key", model="deepseek/deepseek-chat"
    )

    assert text == "Hello world"
    assert cost_usd > 0


async def test_generate_text_auth_error_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, FakeResponse(401, {}, "unauthorized"))

    with pytest.raises(RuntimeError, match="401"):
        await openrouter.generate_text(prompt="say hi", api_key="bad-key", model="x")


async def test_generate_text_rate_limited_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, FakeResponse(429, {}, "rate limited"))

    with pytest.raises(RuntimeError, match="429"):
        await openrouter.generate_text(prompt="say hi", api_key="test-key", model="x")


async def test_generate_text_server_error_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, FakeResponse(500, {}, "boom"))

    with pytest.raises(RuntimeError, match="500"):
        await openrouter.generate_text(prompt="say hi", api_key="test-key", model="x")


async def test_generate_text_malformed_response_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, FakeResponse(200, {"unexpected": "shape"}))

    with pytest.raises(RuntimeError, match="missing expected fields"):
        await openrouter.generate_text(prompt="say hi", api_key="test-key", model="x")


async def test_generate_text_timeout_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, httpx.TimeoutException("too slow"))

    with pytest.raises(RuntimeError, match="timed out"):
        await openrouter.generate_text(prompt="say hi", api_key="test-key", model="x")


async def test_generate_text_network_error_raises_runtime_error(monkeypatch):
    _patch_client(monkeypatch, httpx.ConnectError("unreachable"))

    with pytest.raises(RuntimeError, match="network error"):
        await openrouter.generate_text(prompt="say hi", api_key="test-key", model="x")
