"""Unit tests for Aspect Ratio support across Arya OS pipeline.

Covers:
1. Canonical aspect ratio validation and configuration (core/aspect_ratio.py).
2. WorkflowInput model validation and default fallback.
3. Provider payload generation (fal.py image and video).
4. Media dispatch aspect_ratio forwarding.
5. Agent prompt adaptation and propagation (Storyboard, Prompt, Image, Video, Thumbnail, Publishing).
6. VideoAssembler FFmpeg scaling filter commands for 9:16 vs 16:9.
7. ThumbnailValidator and VideoValidator aspect ratio verification.
8. Orchestrator validation gating on invalid aspect ratios.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.aspect_ratio import (
    AspectRatio,
    AspectRatioConfig,
    get_aspect_ratio_config,
    validate_aspect_ratio,
)
from app.workflows.models import WorkflowInput
from app.providers import fal
from app.providers.capabilities import Capability, ProviderCapability, PROVIDER_CAPABILITIES
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionResult
from app.platforms.base import AuthResult, PublishResult, UploadResult
from app.agents.storyboard import StoryboardAgent, _build_storyboard_prompt
from app.agents.prompt import PromptAgent, _build_prompt_prompt
from app.agents.image import ImageAgent
from app.agents.video import VideoAgent
from app.agents.thumbnail import ThumbnailAgent, _build_thumbnail_prompt
from app.agents.publishing import PublishingAgent
from app.workflows.video_assembler import VideoAssembler
from app.validators.thumbnail_validator import ThumbnailValidator
from app.validators.video_validator import VideoValidator
from app.workflows.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# 1. Core Validation & Config Tests
# ---------------------------------------------------------------------------

def test_validate_aspect_ratio_canonical():
    assert validate_aspect_ratio("16:9") == "16:9"
    assert validate_aspect_ratio("9:16") == "9:16"
    assert validate_aspect_ratio(" 16:9 ") == "16:9"
    assert validate_aspect_ratio(" 9:16 ") == "9:16"
    assert validate_aspect_ratio(None) == "16:9"
    assert validate_aspect_ratio("") == "16:9"


def test_validate_aspect_ratio_unsupported():
    with pytest.raises(ValueError, match="Unsupported aspect_ratio"):
        validate_aspect_ratio("4:3")
    with pytest.raises(ValueError, match="Unsupported aspect_ratio"):
        validate_aspect_ratio("1:1")
    with pytest.raises(ValueError, match="Unsupported aspect_ratio"):
        validate_aspect_ratio("21:9")


def test_get_aspect_ratio_config():
    config_16_9 = get_aspect_ratio_config("16:9")
    assert config_16_9.ratio == AspectRatio.LANDSCAPE_16_9
    assert config_16_9.aspect_ratio == "16:9"
    assert config_16_9.width == 1920
    assert config_16_9.height == 1080
    assert config_16_9.thumbnail_width == 1280
    assert config_16_9.thumbnail_height == 720
    assert config_16_9.fal_image_size == "landscape_16_9"
    assert config_16_9.is_vertical is False

    config_9_16 = get_aspect_ratio_config("9:16")
    assert config_9_16.ratio == AspectRatio.PORTRAIT_9_16
    assert config_9_16.aspect_ratio == "9:16"
    assert config_9_16.width == 1080
    assert config_9_16.height == 1920
    assert config_9_16.thumbnail_width == 1080
    assert config_9_16.thumbnail_height == 1920
    assert config_9_16.fal_image_size == "portrait_16_9"
    assert config_9_16.is_vertical is True


# ---------------------------------------------------------------------------
# 2. WorkflowInput Model Tests
# ---------------------------------------------------------------------------

def test_workflow_input_default_aspect_ratio():
    inp = WorkflowInput(
        topic="AI Revolution",
        language="en",
        style="cinematic",
        duration=60,
        platform="youtube",
    )
    assert inp.aspect_ratio == "16:9"


def test_workflow_input_valid_9_16():
    inp = WorkflowInput(
        topic="AI Revolution",
        language="en",
        style="cinematic",
        duration=60,
        platform="youtube",
        aspect_ratio="9:16",
    )
    assert inp.aspect_ratio == "9:16"


def test_workflow_input_invalid_aspect_ratio():
    with pytest.raises(ValidationError):
        WorkflowInput(
            topic="AI Revolution",
            language="en",
            style="cinematic",
            duration=60,
            platform="youtube",
            aspect_ratio="4:3",
        )


# ---------------------------------------------------------------------------
# 3. Provider Payload Tests (fal.py)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fal_generate_image_payload_9_16():
    with patch("app.providers.fal._submit_and_poll", new_callable=AsyncMock) as mock_poll:
        mock_poll.return_value = {
            "images": [{"url": "https://fal.media/files/sample.png", "width": 1080, "height": 1920}]
        }
        res, cost = await fal.generate_image(
            prompt="Cyberpunk portrait",
            api_key="test-fal-key",
            model="flux-schnell",
            aspect_ratio="9:16",
        )
        assert res["storage_path"] == "https://fal.media/files/sample.png"
        payload = mock_poll.call_args.kwargs["payload"]
        assert payload["aspect_ratio"] == "9:16"
        assert payload["image_size"] == "portrait_16_9"


@pytest.mark.asyncio
async def test_fal_generate_video_payload_9_16():
    with patch("app.providers.fal._submit_and_poll", new_callable=AsyncMock) as mock_poll:
        mock_poll.return_value = {
            "video": {"url": "https://fal.media/files/sample.mp4", "duration": 5.0}
        }
        res, cost = await fal.generate_video(
            prompt="Drone flying through futuristic city",
            api_key="test-fal-key",
            model="kling-v3-standard",
            aspect_ratio="9:16",
        )
        assert res["storage_path"] == "https://fal.media/files/sample.mp4"
        payload = mock_poll.call_args.kwargs["payload"]
        assert payload["aspect_ratio"] == "9:16"


# ---------------------------------------------------------------------------
# 4. Media Dispatch Aspect Ratio Forwarding Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_dispatch_passes_aspect_ratio_to_image_provider():
    call = build_media_generation_call(
        capability=Capability.IMAGE_GENERATION,
        prompt="A neon city",
        aspect_ratio="9:16",
    )
    prov = PROVIDER_CAPABILITIES["fal"]
    with patch("app.providers.media_dispatch.get_secrets_manager") as mock_sec, \
         patch("app.providers.fal.generate_image", autospec=True) as mock_gen:
        mock_sec.return_value.get.return_value = "fake-key"
        mock_gen.return_value = ({"storage_path": "https://fal.media/img.jpg"}, 0.02)

        res, cost = await call(prov)
        assert mock_gen.call_args.kwargs["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_media_dispatch_passes_aspect_ratio_to_video_provider():
    call = build_media_generation_call(
        capability=Capability.VIDEO_GENERATION,
        prompt="Drone movement",
        aspect_ratio="9:16",
    )
    prov = PROVIDER_CAPABILITIES["fal"]
    with patch("app.providers.media_dispatch.get_secrets_manager") as mock_sec, \
         patch("app.providers.fal.generate_video", autospec=True) as mock_gen:
        mock_sec.return_value.get.return_value = "fake-key"
        mock_gen.return_value = ({"storage_path": "https://fal.media/vid.mp4"}, 0.35)

        res, cost = await call(prov)
        assert mock_gen.call_args.kwargs["aspect_ratio"] == "9:16"


# ---------------------------------------------------------------------------
# 5. Agent Framing & Propagation Tests
# ---------------------------------------------------------------------------

def test_storyboard_prompt_builder_aspect_ratio_instructions():
    prompt_9_16 = _build_storyboard_prompt(
        script_content="A brave astronaut reaches Mars.",
        aspect_ratio="9:16",
    )
    assert "9:16" in prompt_9_16
    assert "vertical 9:16" in prompt_9_16

    prompt_16_9 = _build_storyboard_prompt(
        script_content="A brave astronaut reaches Mars.",
        aspect_ratio="16:9",
    )
    assert "16:9" in prompt_16_9
    assert "widescreen" in prompt_16_9.lower()


@pytest.mark.asyncio
async def test_storyboard_agent_propagates_aspect_ratio():
    mock_db = AsyncMock()
    agent = StoryboardAgent(db=mock_db)
    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=True,
        output='{"shots":[{"shot_number":1,"description":"Shot 1","shot_type":"Wide"}]}',
        provider="openai",
    ))

    context = {
        "script_content": "Quick vertical short about artificial intelligence.",
        "aspect_ratio": "9:16",
    }
    result = await agent.run(context)
    assert result.success is True
    assert result.output["aspect_ratio"] == "9:16"


def test_prompt_prompt_builder_aspect_ratio_instructions():
    prompt_9_16 = _build_prompt_prompt(
        script="A hacker in the rain",
        aspect_ratio="9:16",
    )
    assert "9:16" in prompt_9_16
    assert "vertical 9:16 shorts" in prompt_9_16.lower()

    prompt_16_9 = _build_prompt_prompt(
        script="A hacker in the rain",
        aspect_ratio="16:9",
    )
    assert "16:9" in prompt_16_9
    assert "horizontal 16:9 widescreen" in prompt_16_9.lower()


@pytest.mark.asyncio
async def test_image_agent_propagates_aspect_ratio():
    mock_db = AsyncMock()
    agent = ImageAgent(db=mock_db)
    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=True,
        output={"storage_path": "https://fal.media/sample.jpg"},
        provider="fal",
    ))

    context = {
        "shot_description": "Futuristic skyline",
        "aspect_ratio": "9:16",
    }
    result = await agent.run(context)
    assert result.success is True
    assert result.output["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_video_agent_propagates_aspect_ratio():
    mock_db = AsyncMock()
    agent = VideoAgent(db=mock_db)
    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=True,
        output={"storage_path": "https://fal.media/sample.mp4"},
        provider="fal",
    ))

    context = {
        "source_image_path": "https://fal.media/sample.jpg",
        "shot_description": "Futuristic skyline drone flight",
        "aspect_ratio": "9:16",
    }
    result = await agent.run(context)
    assert result.success is True
    assert result.output["aspect_ratio"] == "9:16"


def test_thumbnail_prompt_builder_aspect_ratio_instructions():
    prompt_9_16 = _build_thumbnail_prompt(topic="Space Robots", style_guide=None, aspect_ratio="9:16")
    assert "vertical 9:16 YouTube Shorts" in prompt_9_16

    prompt_16_9 = _build_thumbnail_prompt(topic="Space Robots", style_guide=None, aspect_ratio="16:9")
    assert "16:9 widescreen YouTube" in prompt_16_9


@pytest.mark.asyncio
async def test_thumbnail_agent_customizes_for_9_16():
    mock_db = AsyncMock()
    agent = ThumbnailAgent(db=mock_db)
    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=True,
        output={"storage_path": "https://fal.media/thumb.jpg"},
        provider="fal",
    ))

    context = {
        "topic": "Amazing robot revolution",
        "aspect_ratio": "9:16",
    }
    result = await agent.run(context)
    assert result.success is True
    assert result.output["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_publishing_agent_adds_shorts_tag_for_9_16():
    mock_db = AsyncMock()
    agent = PublishingAgent(db=mock_db)

    mock_adapter = MagicMock()
    mock_adapter.authenticate = AsyncMock(return_value=AuthResult(success=True, credentials={"token": "t"}))
    mock_adapter.upload_content = AsyncMock(return_value=UploadResult(success=True, content_id="yt_short_123"))
    mock_adapter.upload_thumbnail = AsyncMock(return_value=UploadResult(success=True))
    mock_adapter.publish = AsyncMock(return_value=PublishResult(success=True, published_content_id="yt_short_123", publish_status="published"))
    mock_adapter.fetch_url = AsyncMock(return_value="https://youtube.com/shorts/yt_short_123")

    async def fake_ensure_local(p):
        return f"/local/{p}" if p else None

    with patch("app.agents.publishing.get_platform_adapter", return_value=mock_adapter), \
         patch("app.agents.publishing.ensure_local_asset", side_effect=fake_ensure_local):
        context = {
            "platform": "youtube",
            "video_id": str(uuid.uuid4()),
            "video_storage_path": "video.mp4",
            "title": "Crazy Robot Fact",
            "description": "Watch this mind blowing AI trick!",
            "tags": "AI, Technology",
            "aspect_ratio": "9:16",
        }

        result = await agent.run(context)
        assert result.success is True
        assert result.output["aspect_ratio"] == "9:16"

        pub_kwargs = mock_adapter.upload_content.call_args.kwargs
        assert "#Shorts" in pub_kwargs["description"]
        assert "Shorts" in pub_kwargs["tags"]


@pytest.mark.asyncio
async def test_publishing_agent_leaves_16_9_untouched():
    mock_db = AsyncMock()
    agent = PublishingAgent(db=mock_db)

    mock_adapter = MagicMock()
    mock_adapter.authenticate = AsyncMock(return_value=AuthResult(success=True, credentials={"token": "t"}))
    mock_adapter.upload_content = AsyncMock(return_value=UploadResult(success=True, content_id="yt_video_123"))
    mock_adapter.upload_thumbnail = AsyncMock(return_value=UploadResult(success=True))
    mock_adapter.publish = AsyncMock(return_value=PublishResult(success=True, published_content_id="yt_video_123", publish_status="published"))
    mock_adapter.fetch_url = AsyncMock(return_value="https://youtube.com/watch?v=yt_video_123")

    async def fake_ensure_local(p):
        return f"/local/{p}" if p else None

    with patch("app.agents.publishing.get_platform_adapter", return_value=mock_adapter), \
         patch("app.agents.publishing.ensure_local_asset", side_effect=fake_ensure_local):
        context = {
            "platform": "youtube",
            "video_id": str(uuid.uuid4()),
            "video_storage_path": "video.mp4",
            "title": "Long Form Documentary",
            "description": "A detailed 16:9 documentary.",
            "tags": "Documentary",
            "aspect_ratio": "16:9",
        }

        result = await agent.run(context)
        assert result.success is True
        assert result.output["aspect_ratio"] == "16:9"

        pub_kwargs = mock_adapter.upload_content.call_args.kwargs
        assert "#Shorts" not in pub_kwargs["description"]
        assert "Shorts" not in pub_kwargs["tags"]


# ---------------------------------------------------------------------------
# 6. FFmpeg Scale Filter in VideoAssembler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_video_assembler_normalize_clip_scale_filter_9_16(tmp_path):
    mock_db = AsyncMock()
    assembler = VideoAssembler(db=mock_db)
    fake_video = tmp_path / "shot.mp4"
    fake_video.write_bytes(b"dummy")

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value.st_size = 1000

        result = await assembler._normalize_video_clip(
            str(fake_video), tmp_path, 0, aspect_ratio="9:16"
        )
        assert result is not None

        cmd = mock_run.call_args[0][0]
        vf_index = cmd.index("-vf")
        filter_str = cmd[vf_index + 1]
        assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filter_str
        assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black" in filter_str
        assert "setsar=1" in filter_str


@pytest.mark.asyncio
async def test_video_assembler_normalize_clip_scale_filter_16_9(tmp_path):
    mock_db = AsyncMock()
    assembler = VideoAssembler(db=mock_db)
    fake_video = tmp_path / "shot.mp4"
    fake_video.write_bytes(b"dummy")

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value.st_size = 1000

        result = await assembler._normalize_video_clip(
            str(fake_video), tmp_path, 0, aspect_ratio="16:9"
        )
        assert result is not None

        cmd = mock_run.call_args[0][0]
        vf_index = cmd.index("-vf")
        filter_str = cmd[vf_index + 1]
        assert "scale=1920:1080:force_original_aspect_ratio=decrease" in filter_str
        assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" in filter_str
        assert "setsar=1" in filter_str


# ---------------------------------------------------------------------------
# 7. Validator Aspect Ratio Verification
# ---------------------------------------------------------------------------

def test_thumbnail_validator_aspect_ratio_checks():
    validator = ThumbnailValidator()

    # Valid 16:9 thumbnail
    res = validator.validate({
        "storage_path": "/tmp/thumb.jpg",
        "aspect_ratio": "16:9",
        "mock_image_data": {
            "width": 1280,
            "height": 720,
            "format": "JPEG",
            "file_size": 500_000,
            "stddev": 35.0,
        },
    })
    assert res.passed is True
    assert res.dimension_scores["aspect_ratio"] == 25.0

    # Valid 9:16 thumbnail
    res = validator.validate({
        "storage_path": "/tmp/thumb.jpg",
        "aspect_ratio": "9:16",
        "mock_image_data": {
            "width": 1080,
            "height": 1920,
            "format": "JPEG",
            "file_size": 500_000,
            "stddev": 35.0,
        },
    })
    assert res.passed is True
    assert res.dimension_scores["aspect_ratio"] == 25.0

    # Mismatched thumbnail: requested 9:16 but provided 1280x720 (landscape)
    res = validator.validate({
        "storage_path": "/tmp/thumb.jpg",
        "aspect_ratio": "9:16",
        "mock_image_data": {
            "width": 1280,
            "height": 720,
            "format": "JPEG",
            "file_size": 500_000,
            "stddev": 35.0,
        },
    })
    assert any("Aspect ratio" in issue for issue in res.issues)


def test_video_validator_aspect_ratio_checks():
    probe_9_16 = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "duration": "10.0",
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "duration": "10.0",
            },
        ],
        "format": {"duration": "10.0", "size": "15000000"},
    }

    validator = VideoValidator(probe_fn=lambda p: probe_9_16)

    # Validate matching 9:16 video
    with patch("os.path.exists", return_value=True):
        mock_run = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_run):
            res = validator.validate({
                "storage_path": "/tmp/video.mp4",
                "aspect_ratio": "9:16",
            })
            assert res.passed is True
            assert not any("Aspect ratio" in issue for issue in res.issues)

    # Validate mismatch: video is 1080x1920 (9:16) but target is 16:9
    with patch("os.path.exists", return_value=True):
        mock_run = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_run):
            res = validator.validate({
                "storage_path": "/tmp/video.mp4",
                "aspect_ratio": "16:9",
            })
            assert any("Aspect ratio" in issue for issue in res.issues)


# ---------------------------------------------------------------------------
# 8. Orchestrator Aspect Ratio Validation Gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrator_rejects_unsupported_aspect_ratio():
    mock_db = AsyncMock()
    orchestrator = Orchestrator(db=mock_db)

    # Pass invalid aspect ratio to Orchestrator.run()
    result = await orchestrator.run(
        workflow_run_id=uuid.uuid4(),
        workflow_input={
            "topic": "Quantum Computing",
            "aspect_ratio": "4:3",
        },
    )
    assert result.success is False
    assert result.failed_stage == "validation"
    assert "Unsupported aspect_ratio" in result.error
