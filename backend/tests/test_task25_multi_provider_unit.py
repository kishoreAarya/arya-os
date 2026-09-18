"""Task 25 Unit & Integration Tests — Multi-Provider Visual Migration.

Verifies:
1. Together AI provider adapter (image gen, resolutions, auth, errors, video constraints).
2. fal.ai provider adapter (aliases, queue submit/poll, candidates, errors).
3. SSRF-safe Asset Downloader (loopback, private subnets, metadata, size limits).
4. Capabilities registration & media dispatch routing for together, fal, and replicate.
5. Strict preservation of production defaults (current_legacy, replicate, kling).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import get_settings
from app.providers import fal, replicate, together
from app.providers.capabilities import Capability, get_capability, providers_for
from app.providers.media_dispatch import get_media_adapter
from app.services.visual_profiles import (
    ProviderAvailabilityStatus,
    VisualProfileType,
    check_provider_status,
    classify_provider_error,
    resolve_visual_profile,
    sanitize_prompt_v2,
)
from app.utils.asset_downloader import (
    AssetDownloadError,
    SSRFSecurityError,
    download_remote_asset,
    is_safe_remote_url,
)


# ===========================================================================
# 1. Together AI Provider Adapter Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_together_generate_image_success_mock():
    """Verify Together AI generate_image parses response, calculates cost, and tracks latency."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"url": "https://api.together.xyz/images/img_test_123.jpg", "b64_json": None}
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result, cost = await together.generate_image(
            prompt="Cinematic dark crypt, 35mm lens, f/2.0",
            model="black-forest-labs/FLUX.1.1-pro",
            api_key="test-together-key-123",
            aspect_ratio="9:16",
        )

        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-together-key-123"
        json_body = call_args.kwargs["json"]
        assert json_body["model"] == "black-forest-labs/FLUX.1.1-pro"
        assert json_body["prompt"] == "Cinematic dark crypt, 35mm lens, f/2.0"
        assert json_body["width"] == 768
        assert json_body["height"] == 1344

        assert result["image_url"] == "https://api.together.xyz/images/img_test_123.jpg"
        assert result["provider"] == "together"
        assert result["model"] == "black-forest-labs/FLUX.1.1-pro"
        assert cost == 0.040


@pytest.mark.asyncio
async def test_together_aspect_ratio_resolution_mapping():
    """Verify aspect ratios map to valid Together AI pixel dimensions."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"url": "https://test.com/out.jpg"}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        # 9:16 portrait
        await together.generate_image("test", api_key="k", aspect_ratio="9:16")
        assert mock_post.call_args.kwargs["json"]["width"] == 768
        assert mock_post.call_args.kwargs["json"]["height"] == 1344

        # 16:9 landscape
        await together.generate_image("test", api_key="k", aspect_ratio="16:9")
        assert mock_post.call_args.kwargs["json"]["width"] == 1344
        assert mock_post.call_args.kwargs["json"]["height"] == 768

        # 1:1 square
        await together.generate_image("test", api_key="k", aspect_ratio="1:1")
        assert mock_post.call_args.kwargs["json"]["width"] == 1024
        assert mock_post.call_args.kwargs["json"]["height"] == 1024


@pytest.mark.asyncio
async def test_together_error_401_credential():
    """Verify HTTP 401 raises RuntimeError classified as CREDENTIAL_ERROR."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.text = '{"error": "Invalid API key"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(RuntimeError) as exc_info:
            await together.generate_image("test", api_key="bad-key")
        assert "401" in str(exc_info.value)
        assert classify_provider_error(str(exc_info.value)) == ProviderAvailabilityStatus.CREDENTIAL_ERROR


@pytest.mark.asyncio
async def test_together_error_402_payment_required():
    """Verify HTTP 402 raises RuntimeError classified as CREDIT_EXHAUSTED."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 402
    mock_response.text = '{"error": "Payment required / credit balance depleted"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(RuntimeError) as exc_info:
            await together.generate_image("test", api_key="unpaid-key")
        assert "402" in str(exc_info.value)
        assert classify_provider_error(str(exc_info.value)) == ProviderAvailabilityStatus.CREDIT_EXHAUSTED


@pytest.mark.asyncio
async def test_together_error_429_rate_limit():
    """Verify HTTP 429 raises RuntimeError classified as RATE_LIMITED."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = '{"error": "Rate limit exceeded"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(RuntimeError) as exc_info:
            await together.generate_image("test", api_key="rate-limited-key")
        assert "429" in str(exc_info.value)
        assert classify_provider_error(str(exc_info.value)) == ProviderAvailabilityStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_together_video_generation_constraints():
    """Verify generate_video raises descriptive error regarding lack of serverless Kling catalog."""
    with pytest.raises(RuntimeError) as exc_info:
        await together.generate_video("test prompt", api_key="k", model="kling")
    assert "does not offer" in str(exc_info.value).lower() or "serverless" in str(exc_info.value).lower()


# ===========================================================================
# 2. fal.ai Provider Adapter Tests
# ===========================================================================

def test_fal_model_aliases():
    """Verify shorthand model names resolve to canonical fal.ai queue paths."""
    assert fal.normalize_fal_model("flux-1.1-pro") == "fal-ai/flux-pro/v1.1"
    assert fal.normalize_fal_model("flux-dev") == "fal-ai/flux/dev"
    assert fal.normalize_fal_model("kling") == "fal-ai/kling-video/v1.6/standard/image-to-video"
    assert fal.normalize_fal_model("wan-i2v") == "fal-ai/wan-i2v"


@pytest.mark.asyncio
async def test_fal_generate_image_queue_success():
    """Verify fal.ai queue submit and poll flow returns valid asset dict and cost."""
    mock_submit_resp = MagicMock(spec=httpx.Response)
    mock_submit_resp.status_code = 200
    mock_submit_resp.json.return_value = {
        "request_id": "req-fal-test-999",
        "status_url": "https://queue.fal.run/fal-ai/flux-pro/v1.1/requests/req-fal-test-999/status",
        "response_url": "https://queue.fal.run/fal-ai/flux-pro/v1.1/requests/req-fal-test-999",
    }

    mock_status_resp = MagicMock(spec=httpx.Response)
    mock_status_resp.status_code = 200
    mock_status_resp.json.return_value = {"status": "COMPLETED"}

    mock_result_resp = MagicMock(spec=httpx.Response)
    mock_result_resp.status_code = 200
    mock_result_resp.json.return_value = {
        "images": [
            {"url": "https://fal.media/files/img_fal_1.jpg", "content_type": "image/jpeg"}
        ],
        "timings": {"inference": 3.1},
    }

    async def mock_get(url, **kwargs):
        if "status" in url:
            return mock_status_resp
        return mock_result_resp

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", side_effect=mock_get):
        mock_post.return_value = mock_submit_resp

        result, cost = await fal.generate_image(
            prompt="Ancient weeping sarcophagus, 50mm macro",
            model="fal-ai/flux-pro/v1.1",
            api_key="fal-test-key",
            aspect_ratio="9:16",
        )

        assert mock_post.called
        assert result["image_url"] == "https://fal.media/files/img_fal_1.jpg"
        assert result["provider"] == "fal"
        assert cost == 0.050


@pytest.mark.asyncio
async def test_fal_candidates_handling():
    """Verify fal.ai correctly extracts multiple candidates when num_outputs > 1."""
    mock_submit_resp = MagicMock(spec=httpx.Response)
    mock_submit_resp.status_code = 200
    mock_submit_resp.json.return_value = {
        "request_id": "req-fal-multi",
        "status_url": "https://queue.fal.run/status/req-fal-multi",
        "response_url": "https://queue.fal.run/res/req-fal-multi",
    }

    mock_status_resp = MagicMock(spec=httpx.Response)
    mock_status_resp.status_code = 200
    mock_status_resp.json.return_value = {"status": "COMPLETED"}

    mock_result_resp = MagicMock(spec=httpx.Response)
    mock_result_resp.status_code = 200
    mock_result_resp.json.return_value = {
        "images": [
            {"url": "https://fal.media/files/c1.jpg"},
            {"url": "https://fal.media/files/c2.jpg"},
            {"url": "https://fal.media/files/c3.jpg"},
        ]
    }

    async def mock_get(url, **kwargs):
        if "status" in url:
            return mock_status_resp
        return mock_result_resp

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", side_effect=mock_get):
        mock_post.return_value = mock_submit_resp

        result, cost = await fal.generate_image(
            prompt="Descend test",
            model="fal-ai/flux-pro/v1.1",
            api_key="fal-key",
            num_outputs=3,
        )

        assert len(result["candidates"]) == 3
        assert result["image_url"] == "https://fal.media/files/c1.jpg"
        assert cost == pytest.approx(0.150, 0.001)


@pytest.mark.asyncio
async def test_fal_error_401_handling():
    """Verify fal HTTP 401 returns descriptive message classified as CREDENTIAL_ERROR."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 401
    mock_resp.text = '{"detail": "invalid key credentials"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(RuntimeError) as exc_info:
            await fal.generate_image("test", api_key="bad-fal-key", model="fal-ai/flux-pro/v1.1")
        assert "401" in str(exc_info.value)
        assert classify_provider_error(str(exc_info.value)) == ProviderAvailabilityStatus.CREDENTIAL_ERROR


# ===========================================================================
# 3. SSRF-Safe Asset Downloader Tests
# ===========================================================================

def test_is_safe_remote_url_blocks_ssrf():
    """Verify SSRF protection rejects loopback, private subnets, and metadata endpoints."""
    # Loopback
    assert not is_safe_remote_url("http://127.0.0.1/test.png")
    assert not is_safe_remote_url("http://localhost/test.png")
    assert not is_safe_remote_url("https://127.0.0.1:8000/image.jpg")

    # Cloud metadata
    assert not is_safe_remote_url("http://169.254.169.254/latest/meta-data/")

    # Private IP spaces
    assert not is_safe_remote_url("http://10.0.1.50/asset.png")
    assert not is_safe_remote_url("http://192.168.1.1/cam.jpg")
    assert not is_safe_remote_url("http://172.16.0.1/intranet.png")

    # Non-HTTP/HTTPS schemes
    assert not is_safe_remote_url("file:///etc/passwd")
    assert not is_safe_remote_url("ftp://server/file.png")

    # Valid public HTTPS URLs
    assert is_safe_remote_url("https://api.together.xyz/images/123.jpg")
    assert is_safe_remote_url("https://v3.fal.media/files/elephant.jpg")
    assert is_safe_remote_url("https://replicate.delivery/pbxt/xyz.mp4")


@pytest.mark.asyncio
async def test_download_remote_asset_rejects_ssrf(tmp_path):
    """Verify download_remote_asset raises SSRFSecurityError for malicious target."""
    dest = tmp_path / "bad.jpg"
    with pytest.raises(SSRFSecurityError):
        await download_remote_asset("http://169.254.169.254/secret.json", dest)
    assert not dest.exists()


@pytest.mark.asyncio
async def test_download_remote_asset_enforces_size_limit(tmp_path):
    """Verify download_remote_asset aborts and cleans up when size exceeds limit."""
    dest = tmp_path / "oversize.jpg"

    # Mock response delivering chunks exceeding 100 bytes limit
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": "1000"}

    async def mock_aiter_bytes(chunk_size=None):
        yield b"A" * 200

    mock_resp.aiter_bytes = mock_aiter_bytes

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            class StreamContext:
                async def __aenter__(self):
                    return mock_resp
                async def __aexit__(self, *args):
                    pass
            return StreamContext()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        with pytest.raises(AssetDownloadError) as exc_info:
            await download_remote_asset("https://safe-domain.com/big.jpg", dest, max_bytes=100)
        assert "exceeds maximum allowed size" in str(exc_info.value)
        assert not dest.exists()


@pytest.mark.asyncio
async def test_download_remote_asset_success(tmp_path):
    """Verify successful asset download writes complete bytes to disk."""
    dest = tmp_path / "image.jpg"
    test_content = b"\xFF\xD8\xFF\xE0" + b"TEST_JPEG_DATA" * 10

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(test_content))}

    async def mock_aiter_bytes(chunk_size=None):
        yield test_content

    mock_resp.aiter_bytes = mock_aiter_bytes

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            class StreamContext:
                async def __aenter__(self):
                    return mock_resp
                async def __aexit__(self, *args):
                    pass
            return StreamContext()

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()), \
         patch("app.utils.asset_downloader.is_safe_remote_url", return_value=True):
        saved_path = await download_remote_asset("https://safe.com/test.jpg", dest)
        assert saved_path.exists()
        assert saved_path.read_bytes() == test_content


# ===========================================================================
# 4. Capabilities Registry & Media Dispatch Tests
# ===========================================================================

def test_capabilities_registry_contains_together_and_fal():
    """Verify Together AI and fal.ai are registered with correct capabilities."""
    together_cap = get_capability("together")
    assert together_cap is not None
    assert Capability.IMAGE_GENERATION in together_cap.capabilities
    assert "black-forest-labs/FLUX.1.1-pro" in together_cap.supported_models
    assert together_cap.cost_tier == 2

    fal_cap = get_capability("fal")
    assert fal_cap is not None
    assert Capability.IMAGE_GENERATION in fal_cap.capabilities
    assert Capability.VIDEO_GENERATION in fal_cap.capabilities
    assert "fal-ai/flux-pro/v1.1" in fal_cap.supported_models
    assert "fal-ai/kling-video/v1.6/standard/image-to-video" in fal_cap.supported_models


def test_media_dispatch_adapters_registered():
    """Verify get_media_adapter resolves registered adapters."""
    assert get_media_adapter("together") is together
    assert get_media_adapter("fal") is fal
    assert get_media_adapter("replicate") is replicate
    assert get_media_adapter("kling") is replicate


# ===========================================================================
# 5. Production Defaults & Profile Invariants
# ===========================================================================

def test_production_defaults_strictly_preserved():
    """Verify production defaults are unchanged: current_legacy, replicate, kling."""
    default_profile = resolve_visual_profile()
    assert default_profile.name == "current_legacy"
    assert default_profile.image_provider == "replicate"
    assert default_profile.video_provider == "kling"

    # Verify candidate count for legacy is fixed at 1
    assert default_profile.get_candidate_count("A", is_key_beat=True) == 1
    assert default_profile.get_candidate_count("B", is_key_beat=False) == 1


def test_provider_status_diagnostics_live_contract():
    """Verify check_provider_status handles configured and unconfigured providers."""
    # Together unconfigured
    with patch.object(get_settings(), "together_api_key", None):
        status, detail = check_provider_status("together")
        assert status == ProviderAvailabilityStatus.CREDENTIAL_ERROR
        assert "CREDENTIAL_NOT_CONFIGURED" in detail

    # fal unconfigured
    with patch.object(get_settings(), "fal_key", None), \
         patch.object(get_settings(), "fal_api_key", None):
        status, detail = check_provider_status("fal")
        assert status == ProviderAvailabilityStatus.CREDENTIAL_ERROR
        assert "CREDENTIAL_NOT_CONFIGURED" in detail

    # Replicate credit exhausted
    status, detail = check_provider_status("replicate", override_credits_exhausted=True)
    assert status == ProviderAvailabilityStatus.CREDIT_EXHAUSTED
    assert "0 active credits" in detail
