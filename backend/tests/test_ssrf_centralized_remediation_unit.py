"""Regression tests for centralized SSRF remediation across Validators, AssetDownloader, Video Assembler, and VoiceFirstAgent.

Covers:
1. Validator SSRF rejection & size bounds (Image, Video, Audio, Thumbnail, KeyframeSelector)
2. AssetDownloader redirect SSRF prevention (follow_redirects=False, loop detection, hop limit, per-hop SSRF validation)
3. Video Assembler & VoiceFirst centralized asset routing through ensure_local_asset
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.voice_first import VoiceFirstAgent
from app.services.execution_engine import ExecutionEngine
from app.services.keyframe_selector import evaluate_candidate
from app.utils.asset_downloader import (
    AssetDownloadError,
    SSRFSecurityError,
    download_media_asset,
    download_remote_asset,
    is_safe_remote_url,
)
from app.utils.asset_manager import ensure_local_asset, ensure_local_asset_sync, is_safe_asset_url
from app.validators.audio_validator import AudioValidator
from app.validators.image_validator import ImageValidator
from app.validators.thumbnail_validator import ThumbnailValidator
from app.validators.video_validator import VideoValidator
from app.workflows.video_assembler import VideoAssembler


# ===========================================================================
# 1. Validator Paths — SSRF Rejection & Safe Processing
# ===========================================================================


def test_image_validator_rejects_loopback():
    """Verify ImageValidator rejects 127.0.0.1 loopback target."""
    validator = ImageValidator()
    result = validator.validate({"storage_path": "http://127.0.0.1:8000/internal.png"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_image_validator_rejects_rfc1918_private():
    """Verify ImageValidator rejects RFC1918 private address."""
    validator = ImageValidator()
    result = validator.validate({"storage_path": "http://192.168.1.100/secret.jpg"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_image_validator_rejects_cloud_metadata():
    """Verify ImageValidator rejects 169.254.169.254 cloud metadata."""
    validator = ImageValidator()
    result = validator.validate({"storage_path": "http://169.254.169.254/latest/meta-data"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_video_validator_rejects_ssrf():
    """Verify VideoValidator rejects private network URL."""
    validator = VideoValidator()
    result = validator.validate({"video_storage_path": "http://10.0.0.5/private.mp4"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_audio_validator_rejects_ssrf():
    """Verify AudioValidator rejects loopback URL."""
    validator = AudioValidator()
    result = validator.validate({"storage_path": "http://localhost:9000/audio.wav"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_thumbnail_validator_rejects_ssrf():
    """Verify ThumbnailValidator rejects loopback URL."""
    validator = ThumbnailValidator()
    result = validator.validate({"storage_path": "http://127.1:8080/thumb.jpg"})
    assert result.passed is False
    assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_keyframe_selector_rejects_ssrf():
    """Verify evaluate_candidate rejects SSRF target with penalty."""
    score = evaluate_candidate(
        candidate_index=0,
        image_path_or_url="http://169.254.169.254/latest/meta-data",
    )
    assert score.total_score == 2.0
    assert any("Insecure or invalid remote asset URL" in p for p in score.penalties_applied)


def test_validator_rejects_redirect_to_private():
    """Verify ImageValidator rejects public URL that redirects to private IP."""
    validator = ImageValidator()

    # Mock response delivering a 302 to 127.0.0.1
    redirect_resp = MagicMock(spec=httpx.Response)
    redirect_resp.is_redirect = True
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": "http://127.0.0.1:8000/stolen.png"}
    redirect_resp.aclose = AsyncMock()

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def build_request(self, method, url):
            return httpx.Request(method, url)

        async def send(self, req, stream=False):
            return redirect_resp

    with patch("app.utils.asset_manager.is_safe_asset_url", side_effect=lambda u: "safe.com" in u), \
         patch("httpx.AsyncClient", return_value=MockAsyncClient()):
        result = validator.validate({"storage_path": "https://safe.com/image.png"})
        assert result.passed is False
        assert any("Insecure or invalid remote asset URL" in issue for issue in result.issues)


def test_validator_rejects_oversized_response():
    """Verify ImageValidator rejects remote response exceeding max_bytes."""
    validator = ImageValidator()

    with patch("app.utils.asset_manager.ensure_local_asset", side_effect=RuntimeError("Asset exceeds maximum allowed size of 52428800 bytes")):
        result = validator.validate({"storage_path": "https://safe-domain.com/huge.png"})
        assert result.passed is False
        assert any("Asset exceeds maximum allowed size" in issue for issue in result.issues)


def test_validator_local_file_behavior_preserved(tmp_path):
    """Verify local file validation behavior remains functional and unmodified."""
    from PIL import Image

    img_path = tmp_path / "valid.png"
    img = Image.new("RGB", (1024, 1024))
    pixels = img.load()
    for x in range(1024):
        for y in range(1024):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    img.save(img_path)

    validator = ImageValidator(passing_threshold=50.0)
    result = validator.validate({"storage_path": str(img_path)})
    assert result.passed is True
    assert result.score > 50.0


# ===========================================================================
# 2. AssetDownloader — Redirect SSRF & Bounds Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_asset_downloader_safe_url_success(tmp_path):
    """Verify download_media_asset succeeds for a safe URL with follow_redirects=False."""
    dest = tmp_path
    content = b"TEST_IMAGE_BYTES" * 10

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.is_redirect = False
    mock_resp.headers = {"Content-Type": "image/png"}

    async def mock_aiter_bytes(chunk_size=None):
        yield content

    mock_resp.aiter_bytes = mock_aiter_bytes

    client_instances = []

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            client_instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            class StreamCtx:
                async def __aenter__(self):
                    return mock_resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", side_effect=MockAsyncClient), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        local_path, telemetry = await download_media_asset("https://safe-cdn.example.com/asset.png", dest_dir=dest)
        assert os.path.exists(local_path)
        assert Path(local_path).read_bytes() == content
        assert telemetry["bytes"] == len(content)

    # Verify follow_redirects=False was enforced
    assert len(client_instances) > 0
    assert client_instances[0].kwargs.get("follow_redirects") is False


@pytest.mark.asyncio
async def test_asset_downloader_allows_safe_redirect(tmp_path):
    """Verify download_media_asset follows safe public -> public redirect."""
    content = b"SAFE_REDIRECT_DATA"
    step = 0

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            nonlocal step
            resp = MagicMock(spec=httpx.Response)
            if step == 0:
                resp.status_code = 302
                resp.is_redirect = True
                resp.headers = {"Location": "https://cdn-subdomain.safe.com/final.png"}
                step += 1
            else:
                resp.status_code = 200
                resp.is_redirect = False
                resp.headers = {"Content-Type": "image/png"}

                async def mock_aiter(chunk_size=None):
                    yield content

                resp.aiter_bytes = mock_aiter

            class StreamCtx:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        local_path, telemetry = await download_media_asset("https://safe.com/initial.png", dest_dir=tmp_path)
        assert os.path.exists(local_path)
        assert Path(local_path).read_bytes() == content


@pytest.mark.asyncio
async def test_asset_downloader_blocks_redirect_to_loopback(tmp_path):
    """Verify download_media_asset rejects public -> 127.0.0.1 redirect."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 302
    resp.is_redirect = True
    resp.headers = {"Location": "http://127.0.0.1:8000/private-key"}

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            class StreamCtx:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", side_effect=lambda u: "safe.com" in u):
        with pytest.raises(SSRFSecurityError) as exc_info:
            await download_media_asset("https://safe.com/initial.png", dest_dir=tmp_path)
        assert "Insecure or internal redirect URL blocked by SSRF guard" in str(exc_info.value)


@pytest.mark.asyncio
async def test_asset_downloader_blocks_redirect_to_metadata(tmp_path):
    """Verify download_media_asset rejects public -> 169.254.169.254 redirect."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 301
    resp.is_redirect = True
    resp.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            class StreamCtx:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", side_effect=lambda u: "safe.com" in u):
        with pytest.raises(SSRFSecurityError) as exc_info:
            await download_remote_asset("https://safe.com/initial.png", tmp_path / "out.png")
        assert "Insecure or internal redirect URL blocked by SSRF guard" in str(exc_info.value)


@pytest.mark.asyncio
async def test_asset_downloader_blocks_redirect_loop(tmp_path):
    """Verify download_media_asset rejects a redirect loop (A -> B -> A)."""
    step = 0

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            nonlocal step
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 302
            resp.is_redirect = True
            # Alternating between loop-a and loop-b
            if "loop-a" in url or step == 0:
                resp.headers = {"Location": "https://safe.com/loop-b"}
            else:
                resp.headers = {"Location": "https://safe.com/loop-a"}
            step += 1

            class StreamCtx:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        with pytest.raises(SSRFSecurityError) as exc_info:
            await download_media_asset("https://safe.com/loop-a", dest_dir=tmp_path)
        assert "Redirect loop detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_asset_downloader_exceeds_max_redirects(tmp_path):
    """Verify download_media_asset enforces max 3 redirects limit."""
    redirect_count = 0

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            nonlocal redirect_count
            redirect_count += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 302
            resp.is_redirect = True
            resp.headers = {"Location": f"https://safe.com/step-{redirect_count}"}

            class StreamCtx:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        with pytest.raises(SSRFSecurityError) as exc_info:
            await download_media_asset("https://safe.com/start", dest_dir=tmp_path)
        assert "Too many redirects" in str(exc_info.value)


# ===========================================================================
# 3. Video Assembler & VoiceFirst — Centralized Asset Boundary Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_video_assembler_routes_remote_via_ensure_local_asset(tmp_path):
    """Verify VideoAssembler._resolve_local_path uses ensure_local_asset."""
    node = VideoAssembler(db=AsyncMock())
    test_media = tmp_path / "downloaded.mp4"
    test_media.write_bytes(b"VIDEO_DATA")

    with patch("app.utils.asset_manager.ensure_local_asset", new_callable=AsyncMock) as mock_ensure:
        mock_ensure.return_value = str(test_media)
        res = await node._resolve_local_path("https://remote-storage.example.com/video.mp4", tmp_path, ".mp4")
        assert res is not None
        assert os.path.exists(res)
        assert Path(res).suffix == ".mp4"
        mock_ensure.assert_called_once()
        args, kwargs = mock_ensure.call_args
        assert args[0] == "https://remote-storage.example.com/video.mp4"


@pytest.mark.asyncio
async def test_video_assembler_rejects_ssrf_via_ensure_local_asset(tmp_path):
    """Verify VideoAssembler._resolve_local_path fails safely when SSRF is blocked."""
    node = VideoAssembler(db=AsyncMock())

    with patch("app.utils.asset_manager.ensure_local_asset", side_effect=ValueError("Insecure or invalid remote asset URL")):
        res = await node._resolve_local_path("http://169.254.169.254/secret.mp4", tmp_path, ".mp4")
        assert res is None


@pytest.mark.asyncio
async def test_voice_first_agent_routes_remote_via_ensure_local_asset(tmp_path):
    """Verify VoiceFirstAgent routes remote voice URL through ensure_local_asset."""
    agent = VoiceFirstAgent(db=AsyncMock())
    temp_voice = tmp_path / "voice.wav"
    temp_voice.write_bytes(b"WAV_AUDIO_DATA")

    mock_exec = MagicMock()
    mock_exec.success = True
    mock_exec.output = {"storage_path": "https://remote-voice.example.com/audio.wav", "duration_seconds": 10.0}

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock, return_value=mock_exec), \
         patch("app.utils.asset_manager.ensure_local_asset", new_callable=AsyncMock) as mock_ensure:
        mock_ensure.return_value = str(temp_voice)
        res = await agent.run({"script_content": "Hello world", "platform": "tiktok"})
        assert res.success is True
        voice_res = res.output["voice_first_result"]
        assert voice_res.voice_path == str(temp_voice)
        mock_ensure.assert_called_once()
        args, kwargs = mock_ensure.call_args
        assert args[0] == "https://remote-voice.example.com/audio.wav"


@pytest.mark.asyncio
async def test_voice_first_agent_handles_ssrf_rejection(tmp_path):
    """Verify VoiceFirstAgent handles SSRF failure gracefully without unhandled exception."""
    agent = VoiceFirstAgent(db=AsyncMock())

    mock_exec = MagicMock()
    mock_exec.success = True
    mock_exec.output = {"storage_path": "http://127.0.0.1:8000/internal.wav", "duration_seconds": 5.0}

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock, return_value=mock_exec), \
         patch("app.utils.asset_manager.ensure_local_asset", side_effect=ValueError("Insecure or invalid remote asset URL")):
        res = await agent.run({"script_content": "Hello world", "platform": "tiktok"})
        assert res.success is True
        # Falls back gracefully rather than crashing
        voice_res = res.output["voice_first_result"]
        assert voice_res.voice_path == "http://127.0.0.1:8000/internal.wav"
