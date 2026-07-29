"""
Unit tests for the fal.ai and Replicate media adapters
(app/providers/fal.py, app/providers/replicate.py) — same structure
and mocking style as test_llm_provider_adapters_unit.py.

HTTP is mocked (monkeypatching httpx.AsyncClient), no real network.
"""
import httpx
import pytest

from app.providers import fal, replicate


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
# fal.ai
# ---------------------------------------------------------------------
class TestFalGenerateImage:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            fal,
            FakeResponse(200, {"images": [{"url": "https://fal.example/img.png"}]}),
        )
        result, cost_usd = await fal.generate_image(
            prompt="a cat", api_key="fal-key", model="fal-ai/flux/schnell"
        )
        assert result["storage_path"] == "https://fal.example/img.png"
        assert cost_usd > 0

    async def test_unauthorized_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await fal.generate_image(prompt="a cat", api_key="bad", model="m")

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await fal.generate_image(prompt="a cat", api_key="fal-key", model="m")

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await fal.generate_image(prompt="a cat", api_key="fal-key", model="m")

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, httpx.ConnectError("unreachable"))
        with pytest.raises(RuntimeError, match="network error"):
            await fal.generate_image(prompt="a cat", api_key="fal-key", model="m")

    async def test_timeout_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, httpx.TimeoutException("too slow"))
        with pytest.raises(RuntimeError, match="timed out"):
            await fal.generate_image(prompt="a cat", api_key="fal-key", model="m")


class TestFalGenerateVideo:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            fal,
            FakeResponse(
                200, {"video": {"url": "https://fal.example/clip.mp4", "duration": 4.0}}
            ),
        )
        result, cost_usd = await fal.generate_video(
            prompt="a cat running", api_key="fal-key", model="fal-ai/ltx-video"
        )
        assert result["storage_path"] == "https://fal.example/clip.mp4"
        assert result["duration_seconds"] == 4.0
        assert cost_usd > 0

    async def test_with_image_url_included_in_payload(self, monkeypatch):
        captured = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json, headers):
                captured["json"] = json
                return FakeResponse(200, {"video": {"url": "https://fal.example/clip.mp4"}})

        monkeypatch.setattr(fal.httpx, "AsyncClient", FakeAsyncClient)

        await fal.generate_video(
            prompt="animate this",
            api_key="fal-key",
            model="fal-ai/ltx-video",
            image_url="https://example.com/source.png",
        )
        assert captured["json"]["image_url"] == "https://example.com/source.png"

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, fal, FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await fal.generate_video(prompt="x", api_key="fal-key", model="m")


# ---------------------------------------------------------------------
# Replicate
# ---------------------------------------------------------------------
class TestReplicateGenerateImage:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            replicate,
            FakeResponse(
                200, {"status": "succeeded", "output": ["https://replicate.example/img.png"]}
            ),
        )
        result, cost_usd = await replicate.generate_image(
            prompt="a dog", api_key="r-key", model="owner/model:version"
        )
        assert result["storage_path"] == "https://replicate.example/img.png"
        assert cost_usd > 0

    async def test_string_output_supported(self, monkeypatch):
        _patch_client(
            monkeypatch,
            replicate,
            FakeResponse(200, {"status": "succeeded", "output": "https://replicate.example/x.png"}),
        )
        result, _ = await replicate.generate_image(
            prompt="a dog", api_key="r-key", model="owner/model:version"
        )
        assert result["storage_path"] == "https://replicate.example/x.png"

    async def test_failed_status_raises_runtime_error(self, monkeypatch):
        _patch_client(
            monkeypatch,
            replicate,
            FakeResponse(200, {"status": "failed", "error": "model exploded"}),
        )
        with pytest.raises(RuntimeError, match="failed"):
            await replicate.generate_image(prompt="x", api_key="r-key", model="m:v")

    async def test_incomplete_status_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, replicate, FakeResponse(200, {"status": "processing"}))
        with pytest.raises(RuntimeError, match="did not complete"):
            await replicate.generate_image(prompt="x", api_key="r-key", model="m:v")

    async def test_auth_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, replicate, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await replicate.generate_image(prompt="x", api_key="bad", model="m:v")

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, replicate, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await replicate.generate_image(prompt="x", api_key="r-key", model="m:v")

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, replicate, httpx.ConnectError("unreachable"))
        with pytest.raises(RuntimeError, match="network error"):
            await replicate.generate_image(prompt="x", api_key="r-key", model="m:v")

    async def test_timeout_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, replicate, httpx.TimeoutException("too slow"))
        with pytest.raises(RuntimeError, match="timed out"):
            await replicate.generate_image(prompt="x", api_key="r-key", model="m:v")


class TestReplicateGenerateVideo:
    async def test_success_with_image_input(self, monkeypatch):
        captured = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json, headers):
                captured["json"] = json
                return FakeResponse(
                    200,
                    {"status": "succeeded", "output": ["https://replicate.example/clip.mp4"]},
                )

        monkeypatch.setattr(replicate.httpx, "AsyncClient", FakeAsyncClient)

        result, cost_usd = await replicate.generate_video(
            prompt="animate",
            api_key="r-key",
            model="owner/model:version",
            image_url="https://example.com/source.png",
        )
        assert result["storage_path"] == "https://replicate.example/clip.mp4"
        assert captured["json"]["input"]["image"] == "https://example.com/source.png"
        assert cost_usd > 0


class TestReplicateGenerateSpeech:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            replicate,
            FakeResponse(200, {"status": "succeeded", "output": "https://replicate.example/a.mp3"}),
        )
        result, cost_usd = await replicate.generate_speech(
            text="hello world", api_key="r-key", model="owner/tts:version"
        )
        assert result["storage_path"] == "https://replicate.example/a.mp3"
        assert cost_usd > 0
