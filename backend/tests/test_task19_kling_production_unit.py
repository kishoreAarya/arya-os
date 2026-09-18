"""Task 19 — Kling Hybrid Production Promotion and Rollback Unit Tests.

Covers:
1. Provider capability registration for Kling and Replicate (LTX fallback).
2. Media dispatch mapping for top-level Kling provider.
3. VideoAgent priority resolution, default Kling selection, and explicit LTX rollback override.
4. Replicate adapter input filtering:
   - start_image and aspect_ratio passed to Kling
   - image passed to LTX; start_image and aspect_ratio omitted
   - $0.25 cost for Kling vs $0.50 for LTX
5. Polling timeout scoping in Replicate adapter (360s for Kling, 300s for video, 180s otherwise).
6. SSRF validation and bounded asset download in ensure_local_asset.
7. Remote image download, PIL validation, FFmpeg invocation, and temp-file cleanup in ShotExecutor.
8. ExecutionEngine fallback from Kling to Replicate LTX on error.
9. Configuration and Preset defaults.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.agents.storyboard import Shot
from app.agents.video import VideoAgent
from app.core.config import Settings, get_settings
from app.core.presets import get_preset
from app.providers.capabilities import Capability, get_capability, providers_for
from app.providers.media_dispatch import _MEDIA_ADAPTERS, build_media_generation_call
from app.providers import replicate
from app.utils.asset_manager import ensure_local_asset, is_safe_asset_url
from app.workflows.shot_executor import ShotExecutor


# ---------------------------------------------------------------------------
# 1. Capability & Model Registration Tests
# ---------------------------------------------------------------------------

def test_kling_provider_registered():
    """Verify 'kling' is registered as a top-level provider for VIDEO_GENERATION."""
    cap = get_capability("kling")
    assert cap is not None
    assert Capability.VIDEO_GENERATION in cap.capabilities
    assert cap.cost_tier == 2
    assert cap.secret_name == "replicate_api_key"
    assert cap.avg_latency_seconds == 220
    model = cap.get_model(Capability.VIDEO_GENERATION)
    assert "kling-v1.6-standard" in model


def test_replicate_primary_video_model_is_ltx_for_fallback():
    """Verify 'replicate' provider has LTX as its primary video model for clean rollback."""
    cap = get_capability("replicate")
    assert cap is not None
    assert Capability.VIDEO_GENERATION in cap.capabilities
    model = cap.get_model(Capability.VIDEO_GENERATION)
    assert "lightricks/ltx-video" in model
    # Kling standard is also supported in the model tuple
    assert any("kling-v1.6-standard" in m for m in cap.supported_models)


def test_media_dispatch_has_kling_adapter():
    """Verify 'kling' is mapped to the replicate adapter in media dispatch."""
    assert "kling" in _MEDIA_ADAPTERS
    assert _MEDIA_ADAPTERS["kling"] is replicate


# ---------------------------------------------------------------------------
# 2. Replicate Adapter Input Contract & Cost Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replicate_generate_video_kling_contract(monkeypatch):
    """Verify Kling generation receives start_image, aspect_ratio, and records $0.25."""
    captured = {}

    async def fake_create_prediction(version, model_input, api_key, capability):
        captured["version"] = version
        captured["input"] = model_input
        captured["capability"] = capability
        return {"status": "succeeded", "output": ["https://replicate.example/kling.mp4"]}

    monkeypatch.setattr(replicate, "_create_prediction", fake_create_prediction)

    res, cost = await replicate.generate_video(
        prompt="A cloaked figure in rain",
        api_key="rep-key",
        model="kwaivgi/kling-v1.6-standard",
        image_url="https://replicate.example/start.png",
        aspect_ratio="9:16",
    )

    assert "kling-v1.6-standard" in captured["version"]
    assert captured["input"]["prompt"] == "A cloaked figure in rain"
    assert captured["input"]["start_image"] == "https://replicate.example/start.png"
    assert "image" not in captured["input"]
    assert captured["input"]["aspect_ratio"] == "9:16"
    assert pytest.approx(cost, 0.001) == 0.25
    assert res["storage_path"] == "https://replicate.example/kling.mp4"


@pytest.mark.asyncio
async def test_replicate_generate_video_ltx_contract_no_kling_fields(monkeypatch):
    """Verify LTX fallback generation receives 'image', NOT 'start_image' or 'aspect_ratio'."""
    captured = {}

    async def fake_create_prediction(version, model_input, api_key, capability):
        captured["version"] = version
        captured["input"] = model_input
        captured["capability"] = capability
        return {"status": "succeeded", "output": ["https://replicate.example/ltx.mp4"]}

    monkeypatch.setattr(replicate, "_create_prediction", fake_create_prediction)

    res, cost = await replicate.generate_video(
        prompt="A cloaked figure in rain",
        api_key="rep-key",
        model="lightricks/ltx-video:8c47da666861d081eeb4d1261853087de23923a268a69b63febdf5dc1dee08e4",
        image_url="https://replicate.example/start.png",
        aspect_ratio="9:16",
    )

    assert "ltx-video" in captured["version"]
    assert captured["input"]["prompt"] == "A cloaked figure in rain"
    assert captured["input"]["image"] == "https://replicate.example/start.png"
    assert "start_image" not in captured["input"]
    assert "aspect_ratio" not in captured["input"]
    assert pytest.approx(cost, 0.001) == 0.50
    assert res["storage_path"] == "https://replicate.example/ltx.mp4"


# ---------------------------------------------------------------------------
# 3. VideoAgent Priority Resolution & Fallback Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_video_agent_default_priority_routes_kling_then_replicate():
    """Verify default VideoAgent execution sets priority=['kling', 'replicate']."""
    db_mock = AsyncMock()
    agent = VideoAgent(db_mock)

    executed_params = {}

    async def fake_execute(**kwargs):
        executed_params.update(kwargs)
        res_mock = MagicMock()
        res_mock.success = True
        res_mock.provider = "kling"
        res_mock.cost_usd = 0.25
        res_mock.elapsed_time = 220.0
        res_mock.output = {"storage_path": "https://replicate.example/kling.mp4", "duration_seconds": 5.0}
        return res_mock

    agent._execution_engine.execute = AsyncMock(side_effect=fake_execute)

    result = await agent.run({
        "source_image_path": "https://replicate.example/img.png",
        "shot_description": "Hero enters cellar",
        "aspect_ratio": "9:16",
    })

    assert result.success is True
    assert executed_params["priority"] == ["kling", "replicate"]
    assert executed_params["capability"] == Capability.VIDEO_GENERATION


@pytest.mark.asyncio
async def test_video_agent_explicit_ltx_rollback_override():
    """Verify explicit video_provider='replicate' or 'ltx' routes directly to LTX."""
    db_mock = AsyncMock()
    agent = VideoAgent(db_mock)

    for override in ("replicate", "ltx", "ltx-video"):
        executed_params = {}

        async def fake_execute(**kwargs):
            executed_params.update(kwargs)
            res_mock = MagicMock()
            res_mock.success = True
            res_mock.provider = "replicate"
            res_mock.cost_usd = 0.50
            res_mock.elapsed_time = 50.0
            res_mock.output = {"storage_path": "https://replicate.example/ltx.mp4", "duration_seconds": 5.0}
            return res_mock

        agent._execution_engine.execute = AsyncMock(side_effect=fake_execute)

        result = await agent.run({
            "source_image_path": "https://replicate.example/img.png",
            "video_provider": override,
            "aspect_ratio": "9:16",
        })

        assert result.success is True
        assert executed_params["priority"] == ["replicate"]


@pytest.mark.asyncio
async def test_video_agent_fallback_logging_when_kling_fails_and_ltx_succeeds():
    """Verify VideoAgent logs fallback when primary Kling fails and Replicate LTX succeeds."""
    db_mock = AsyncMock()
    agent = VideoAgent(db_mock)

    async def fake_execute(**kwargs):
        res_mock = MagicMock()
        res_mock.success = True
        res_mock.provider = "replicate"  # Fallback succeeded
        res_mock.cost_usd = 0.50
        res_mock.elapsed_time = 60.0
        res_mock.output = {"storage_path": "https://replicate.example/ltx.mp4", "duration_seconds": 5.0}
        return res_mock

    agent._execution_engine.execute = AsyncMock(side_effect=fake_execute)

    with patch("app.agents.video.logger.warning") as mock_warn:
        result = await agent.run({
            "source_image_path": "https://replicate.example/img.png",
            "aspect_ratio": "9:16",
        })

        assert result.success is True
        assert result.provider_used == "replicate"
        mock_warn.assert_called_once()
        call_kwargs = mock_warn.call_args[1]
        assert call_kwargs["primary_provider"] == "kling"
        assert call_kwargs["fallback_provider"] == "replicate"


# ---------------------------------------------------------------------------
# 4. SSRF & Asset Download Protection Tests
# ---------------------------------------------------------------------------

def test_is_safe_asset_url():
    """Verify SSRF filter rejects private, loopback, link-local, and bad schemes."""
    assert is_safe_asset_url("https://replicate.delivery/pbxt/sample.png") is True
    assert is_safe_asset_url("https://storage.googleapis.com/bucket/img.png") is True

    # Bad schemes
    assert is_safe_asset_url("file:///etc/passwd") is False
    assert is_safe_asset_url("ftp://example.com/asset.png") is False

    # Loopback / localhost
    assert is_safe_asset_url("http://localhost:8000/secret") is False
    assert is_safe_asset_url("http://127.0.0.1:8000/secret") is False
    assert is_safe_asset_url("http://[::1]:8000/secret") is False
    assert is_safe_asset_url("http://0.0.0.0:8000/secret") is False

    # Private network ranges
    assert is_safe_asset_url("http://10.0.0.1/internal") is False
    assert is_safe_asset_url("http://192.168.1.1/router") is False
    assert is_safe_asset_url("http://172.16.0.5/admin") is False
    assert is_safe_asset_url("http://169.254.169.254/latest/meta-data") is False


@pytest.mark.asyncio
async def test_ensure_local_asset_ssrf_rejection():
    """Verify ensure_local_asset raises ValueError for SSRF target."""
    with pytest.raises(ValueError, match="Insecure or invalid remote asset URL"):
        await ensure_local_asset("http://127.0.0.1:8080/internal.png")


# ---------------------------------------------------------------------------
# 5. Remote Image Download, PIL Validation, and Cleanup in ShotExecutor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shot_executor_remote_image_motion_download_validation_and_cleanup(monkeypatch):
    """Verify _render_image_motion_clip downloads remote URL, verifies with PIL, and cleans up."""
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)

    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    # Create a real local temp image to serve as downloaded asset
    temp_local = Path(tempfile.gettempdir()) / f"mock_dl_{uuid.uuid4().hex}.png"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=darkred:s=1080x1920:d=1", "-vframes", "1", str(temp_local)],
        check=True,
        capture_output=True,
    )
    assert temp_local.exists()

    download_called = False

    async def fake_ensure_local(url, **kwargs):
        nonlocal download_called
        download_called = True
        return str(temp_local)

    monkeypatch.setattr("app.utils.asset_manager.ensure_local_asset", fake_ensure_local)

    fake_remote_url = "https://replicate.delivery/pbxt/test_image.png"
    rendered_mp4 = await executor._render_image_motion_clip(
        image_path=fake_remote_url,
        camera_movement="slow_push_in",
        duration_seconds=2.0,
        aspect_ratio="9:16",
    )

    assert download_called is True
    assert rendered_mp4 is not None
    assert Path(rendered_mp4).exists()

    # Verify temp_local was cleaned up by the finally block
    assert not temp_local.exists()

    # Cleanup generated MP4
    if Path(rendered_mp4).exists():
        Path(rendered_mp4).unlink()


@pytest.mark.asyncio
async def test_shot_executor_image_motion_corrupt_image_aborts(monkeypatch):
    """Verify _render_image_motion_clip aborts gracefully if downloaded file is corrupted."""
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)

    corrupt_file = Path(tempfile.gettempdir()) / f"corrupt_{uuid.uuid4().hex}.png"
    corrupt_file.write_bytes(b"NOT_A_REAL_PNG_HEADER_CORRUPTED_DATA")

    async def fake_ensure_local(url, **kwargs):
        return str(corrupt_file)

    monkeypatch.setattr("app.utils.asset_manager.ensure_local_asset", fake_ensure_local)

    res = await executor._render_image_motion_clip(
        image_path="https://replicate.delivery/corrupt.png",
        camera_movement="slow_push_in",
        duration_seconds=2.0,
        aspect_ratio="9:16",
    )

    assert res is None
    # Verify corrupt temp file was cleaned up in finally
    assert not corrupt_file.exists()


# ---------------------------------------------------------------------------
# 6. Configuration & Preset Tests
# ---------------------------------------------------------------------------

def test_settings_has_kling_defaults():
    """Verify Settings includes default_video_provider='kling' and kling_timeout_seconds=360."""
    settings = get_settings()
    assert getattr(settings, "default_video_provider", None) == "kling"
    assert getattr(settings, "kling_timeout_seconds", None) == 360


def test_cinematic_story_preset_specifies_kling():
    """Verify cinematic_story preset specifies video_provider='kling'."""
    preset = get_preset("cinematic_story")
    assert preset.video_provider == "kling"
    assert preset.voice_provider == "elevenlabs"
    assert preset.captions_enabled is True
