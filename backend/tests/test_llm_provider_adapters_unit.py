"""
Unit tests for the Gemini, OpenAI, and Anthropic text-generation
adapters (app/providers/gemini.py, openai_provider.py,
anthropic_provider.py) — same structure as
test_openrouter_provider_unit.py, one test class per provider.

HTTP is mocked (monkeypatching httpx.AsyncClient), no real network.
"""
import httpx
import pytest

from app.providers import anthropic_provider, gemini, openai_provider


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


def _patch_client(monkeypatch, module, response):
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

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)


# ---------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------
class TestGeminiGenerateText:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            gemini,
            FakeResponse(
                200,
                {
                    "candidates": [{"content": {"parts": [{"text": "Bonjour"}]}}],
                    "usageMetadata": {
                        "promptTokenCount": 6,
                        "candidatesTokenCount": 3,
                        "totalTokenCount": 9,
                    },
                },
            ),
        )
        text, cost_usd = await gemini.generate_text(
            prompt="say hi in french", api_key="g-key", model="gemini-2.0-flash"
        )
        assert text == "Bonjour"
        assert cost_usd > 0

    async def test_forbidden_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, FakeResponse(403, {}, "forbidden"))
        with pytest.raises(RuntimeError, match="403"):
            await gemini.generate_text(prompt="say hi", api_key="bad", model="gemini-2.0-flash")

    async def test_unauthorized_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await gemini.generate_text(prompt="say hi", api_key="bad", model="gemini-2.0-flash")

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await gemini.generate_text(prompt="say hi", api_key="g-key", model="gemini-2.0-flash")

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await gemini.generate_text(prompt="say hi", api_key="g-key", model="gemini-2.0-flash")

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, httpx.ConnectError("unreachable"))
        with pytest.raises(RuntimeError, match="network error"):
            await gemini.generate_text(prompt="say hi", api_key="g-key", model="gemini-2.0-flash")

    async def test_timeout_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, gemini, httpx.TimeoutException("too slow"))
        with pytest.raises(RuntimeError, match="timed out"):
            await gemini.generate_text(prompt="say hi", api_key="g-key", model="gemini-2.0-flash")


# ---------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------
class TestOpenAIGenerateText:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            openai_provider,
            FakeResponse(
                200,
                {
                    "choices": [{"message": {"content": "Hi there"}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
                },
            ),
        )
        text, cost_usd = await openai_provider.generate_text(
            prompt="hello", api_key="oa-key", model="gpt-4o-mini"
        )
        assert text == "Hi there"
        assert cost_usd > 0

    async def test_auth_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, openai_provider, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await openai_provider.generate_text(prompt="hello", api_key="bad", model="gpt-4o-mini")

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, openai_provider, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await openai_provider.generate_text(prompt="hello", api_key="oa-key", model="gpt-4o-mini")

    async def test_server_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, openai_provider, FakeResponse(500, {}, "server error"))
        with pytest.raises(RuntimeError, match="500"):
            await openai_provider.generate_text(prompt="hello", api_key="oa-key", model="gpt-4o-mini")

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, openai_provider, FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await openai_provider.generate_text(prompt="hello", api_key="oa-key", model="gpt-4o-mini")

    async def test_timeout_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, openai_provider, httpx.TimeoutException("too slow"))
        with pytest.raises(RuntimeError, match="timed out"):
            await openai_provider.generate_text(prompt="hello", api_key="oa-key", model="gpt-4o-mini")


# ---------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------
class TestAnthropicGenerateText:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            anthropic_provider,
            FakeResponse(
                200,
                {
                    "content": [{"type": "text", "text": "Hello there"}],
                    "usage": {"input_tokens": 10, "output_tokens": 6},
                },
            ),
        )
        text, cost_usd = await anthropic_provider.generate_text(
            prompt="say hi", api_key="a-key", model="claude-sonnet-4-6"
        )
        assert text == "Hello there"
        assert cost_usd > 0

    async def test_auth_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, anthropic_provider, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await anthropic_provider.generate_text(
                prompt="say hi", api_key="bad", model="claude-sonnet-4-6"
            )

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, anthropic_provider, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await anthropic_provider.generate_text(
                prompt="say hi", api_key="a-key", model="claude-sonnet-4-6"
            )

    async def test_server_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, anthropic_provider, FakeResponse(500, {}, "server error"))
        with pytest.raises(RuntimeError, match="500"):
            await anthropic_provider.generate_text(
                prompt="say hi", api_key="a-key", model="claude-sonnet-4-6"
            )

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(
            monkeypatch, anthropic_provider, FakeResponse(200, {"unexpected": "shape"})
        )
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await anthropic_provider.generate_text(
                prompt="say hi", api_key="a-key", model="claude-sonnet-4-6"
            )

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, anthropic_provider, httpx.ConnectError("unreachable"))
        with pytest.raises(RuntimeError, match="network error"):
            await anthropic_provider.generate_text(
                prompt="say hi", api_key="a-key", model="claude-sonnet-4-6"
            )
