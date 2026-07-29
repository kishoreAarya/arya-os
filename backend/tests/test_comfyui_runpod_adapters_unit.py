"""
Unit tests for the ComfyUI and RunPod media adapters
(app/providers/comfyui.py, app/providers/runpod.py).

HTTP is mocked (monkeypatching httpx.AsyncClient), no real network,
no real GPU, no real RunPod/ComfyUI server.
"""
import httpx
import pytest

from app.providers import comfyui, runpod


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

        async def get(self, *args, **kwargs):
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)


# ---------------------------------------------------------------------
# ComfyUI
# ---------------------------------------------------------------------
class TestComfyUIGenerateImage:
    async def test_missing_base_url_raises_runtime_error(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", None, raising=False)

        with pytest.raises(RuntimeError, match="base URL is not configured"):
            await comfyui.generate_image(prompt="a cat", api_key=None, model="m.safetensors")

    async def test_success(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", "http://runpod-tunnel:8188", raising=False)

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json):
                return FakeResponse(200, {"prompt_id": "abc123"})

            async def get(self, url):
                return FakeResponse(
                    200,
                    {
                        "abc123": {
                            "outputs": {
                                "9": {"images": [{"filename": "output_00001.png"}]}
                            }
                        }
                    },
                )

        monkeypatch.setattr(comfyui.httpx, "AsyncClient", FakeAsyncClient)

        result, cost_usd = await comfyui.generate_image(
            prompt="a cat", api_key=None, model="flux1-dev.safetensors"
        )
        assert result["storage_path"] == (
            "http://runpod-tunnel:8188/view?filename=output_00001.png"
        )
        assert cost_usd == 0.0

    async def test_polling_exhausted_raises_runtime_error(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", "http://runpod-tunnel:8188", raising=False)
        monkeypatch.setattr(comfyui, "_MAX_POLL_ATTEMPTS", 2)
        monkeypatch.setattr(comfyui, "_POLL_INTERVAL_SECONDS", 0)

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json):
                return FakeResponse(200, {"prompt_id": "abc123"})

            async def get(self, url):
                return FakeResponse(200, {})  # never has "abc123" -> keeps polling

        monkeypatch.setattr(comfyui.httpx, "AsyncClient", FakeAsyncClient)

        with pytest.raises(RuntimeError, match="did not complete within"):
            await comfyui.generate_image(prompt="x", api_key=None, model="m.safetensors")

    async def test_submit_error_response_raises_runtime_error(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", "http://runpod-tunnel:8188", raising=False)
        _patch_client(monkeypatch, comfyui, FakeResponse(500, {}, "server error"))

        with pytest.raises(RuntimeError, match="500"):
            await comfyui.generate_image(prompt="x", api_key=None, model="m.safetensors")

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", "http://runpod-tunnel:8188", raising=False)
        _patch_client(monkeypatch, comfyui, httpx.ConnectError("unreachable"))

        with pytest.raises(RuntimeError, match="network error"):
            await comfyui.generate_image(prompt="x", api_key=None, model="m.safetensors")


class TestComfyUIGenerateVideo:
    async def test_success_parses_video_output(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "comfyui_base_url", "http://runpod-tunnel:8188", raising=False)

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json):
                return FakeResponse(200, {"prompt_id": "vid1"})

            async def get(self, url):
                return FakeResponse(
                    200,
                    {"vid1": {"outputs": {"9": {"videos": [{"filename": "clip_001.mp4"}]}}}},
                )

        monkeypatch.setattr(comfyui.httpx, "AsyncClient", FakeAsyncClient)

        result, cost_usd = await comfyui.generate_video(
            prompt="a cat running", api_key=None, model="flux1-dev.safetensors"
        )
        assert result["storage_path"] == "http://runpod-tunnel:8188/view?filename=clip_001.mp4"
        assert cost_usd == 0.0


# ---------------------------------------------------------------------
# RunPod
# ---------------------------------------------------------------------
class TestRunPodRunGpuJob:
    async def test_success(self, monkeypatch):
        _patch_client(
            monkeypatch,
            runpod,
            FakeResponse(
                200,
                {"status": "COMPLETED", "output": {"result": "ok"}, "executionTime": 2000},
            ),
        )
        result, cost_usd = await runpod.run_gpu_job(
            payload={"endpoint_id": "ep-123", "input": {"foo": "bar"}}, api_key="rp-key"
        )
        assert result["output"] == {"result": "ok"}
        assert cost_usd > 0

    async def test_model_used_as_endpoint_id_fallback(self, monkeypatch):
        captured = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json, headers):
                captured["url"] = url
                return FakeResponse(200, {"status": "COMPLETED", "output": {}, "executionTime": 0})

        monkeypatch.setattr(runpod.httpx, "AsyncClient", FakeAsyncClient)

        await runpod.run_gpu_job(payload={"input": {}}, api_key="rp-key", model="ep-from-model")
        assert "ep-from-model" in captured["url"]

    async def test_missing_endpoint_id_raises_runtime_error(self, monkeypatch):
        from app.core import config as config_module

        settings = config_module.get_settings()
        monkeypatch.setattr(settings, "runpod_endpoint_id", None, raising=False)

        with pytest.raises(RuntimeError, match="endpoint_id"):
            await runpod.run_gpu_job(payload={}, api_key="rp-key", model=None)

    async def test_non_completed_status_raises_runtime_error(self, monkeypatch):
        _patch_client(
            monkeypatch,
            runpod,
            FakeResponse(200, {"status": "FAILED", "error": "boom"}),
        )
        with pytest.raises(RuntimeError, match="did not complete"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="rp-key")

    async def test_auth_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, runpod, FakeResponse(401, {}, "unauthorized"))
        with pytest.raises(RuntimeError, match="401"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="bad")

    async def test_rate_limited_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, runpod, FakeResponse(429, {}, "rate limited"))
        with pytest.raises(RuntimeError, match="429"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="rp-key")

    async def test_malformed_response_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, runpod, FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(RuntimeError, match="missing expected fields"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="rp-key")

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, runpod, httpx.ConnectError("unreachable"))
        with pytest.raises(RuntimeError, match="network error"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="rp-key")

    async def test_timeout_raises_runtime_error(self, monkeypatch):
        _patch_client(monkeypatch, runpod, httpx.TimeoutException("too slow"))
        with pytest.raises(RuntimeError, match="timed out"):
            await runpod.run_gpu_job(payload={"endpoint_id": "ep-123"}, api_key="rp-key")
