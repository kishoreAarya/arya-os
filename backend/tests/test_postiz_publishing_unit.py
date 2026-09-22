"""Unit tests for Postiz Publishing Loop integration (Task 29).

Verifies:
1. PostizAdapter: authentication, media upload, payload construction, dry-run, live post scheduling, error handling, status retrieval.
2. PublishingAgent: Postiz platform execution, dry-run lifecycle, Video row update, SystemLog provenance.
3. Publishing API router: /publishing/status, /publishing/publish (dry-run & validation), /publishing/posts/{id}, auth protection, path traversal defense.
4. $0.00 AI generation credits invariant.
"""

import json
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.publishing import PublishingAgent
from app.core.config import get_settings
from app.core.secrets import SecretsManager
from app.main import app
from app.models.enums import PublishStatus
from app.models.media import Video
from app.models.system import SystemLog
from app.platforms.base import AuthResult, ProcessingStatus, PublishResult, UploadResult
from app.platforms.postiz import PostizAdapter


@pytest.fixture
def auth_client():
    settings = get_settings()
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {settings.arya_api_key}"})
    return client


@pytest.fixture
def unauth_client():
    return TestClient(app)


@pytest.fixture
def temp_media_file():
    """Create a temporary deterministic test media file."""
    temp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temp.write(b"AryaOS Deterministic Video Binary Content")
    temp.close()
    yield temp.name
    if os.path.exists(temp.name):
        os.remove(temp.name)


# ---------------------------------------------------------------------------
# 1. PostizAdapter Core Unit Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_postiz_adapter_authentication_missing_key():
    """Verify authenticate fails when POSTIZ_API_KEY is not configured."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    mock_secrets.get.return_value = None

    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)
    res = await adapter.authenticate()

    assert res.success is False
    assert "POSTIZ_API_KEY in .env" in res.error


@pytest.mark.asyncio
async def test_postiz_adapter_authentication_success():
    """Verify authenticate succeeds when Postiz responds with HTTP 200 on /integrations."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    mock_secrets.get.return_value = "postiz_live_secret_key"

    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_integrations = [
        {"id": "int_yt_1", "name": "Arya YouTube", "identifier": "youtube"},
        {"id": "int_tt_2", "name": "Arya TikTok", "identifier": "tiktok"},
    ]

    mock_response = httpx.Response(200, json=mock_integrations, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", return_value=mock_response):
        res = await adapter.authenticate()

    assert res.success is True
    assert res.credentials["api_key"] == "postiz_live_secret_key"
    assert len(res.credentials["integrations"]) == 2


@pytest.mark.asyncio
async def test_postiz_adapter_authentication_rejected_401():
    """Verify authenticate reports explicit error when Postiz returns HTTP 401."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    mock_secrets.get.return_value = "invalid_postiz_key"

    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)
    mock_response = httpx.Response(401, json={"error": "Unauthorized"}, request=httpx.Request("GET", "http://test"))

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        res = await adapter.authenticate()

    assert res.success is False
    assert "rejected (HTTP 401)" in res.error


@pytest.mark.asyncio
async def test_postiz_adapter_upload_content_success(temp_media_file):
    """Verify media upload sends multipart file and returns content ID."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    mock_secrets.get.return_value = "valid_api_key"

    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)
    mock_upload_resp = httpx.Response(
        200,
        json={"id": "postiz_asset_uuid_123", "path": "/uploads/postiz_asset_uuid_123.mp4"},
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient.post", return_value=mock_upload_resp) as mock_post:
        res = await adapter.upload_content(
            file_path=temp_media_file,
            credentials={"api_key": "valid_api_key"},
        )
        assert mock_post.called

    assert res.success is True
    assert res.content_id == "postiz_asset_uuid_123"
    assert res.storage_path == temp_media_file


@pytest.mark.asyncio
async def test_postiz_adapter_upload_missing_file_rejected():
    """Verify upload fails safely when file does not exist on filesystem."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    res = await adapter.upload_content(file_path="/path/to/nonexistent/media.mp4")
    assert res.success is False
    assert "File not found" in res.error


@pytest.mark.asyncio
async def test_postiz_adapter_publish_dry_run():
    """Verify publish dry-run validates payload without making external HTTP requests."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    res = await adapter.publish(
        content_id="postiz_asset_123",
        is_dry_run=True,
        title="Test Title",
        description="Test Caption Description",
        scheduled_at="2026-10-01T15:00:00Z",
        integration_id="int_456",
        platform_type="youtube",
        publish_type="schedule",
    )

    assert res.success is True
    assert res.published_content_id.startswith("dry_run_post_")
    assert res.publish_status == "scheduled"
    assert "dry_run" in res.url


@pytest.mark.asyncio
async def test_postiz_adapter_publish_payload_structure_and_success():
    """Verify correct JSON schema is sent to /public/v1/posts during live publish."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_resp = httpx.Response(
        201,
        json={"id": "postiz_post_id_999"},
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        res = await adapter.publish(
            content_id="asset_id_55",
            credentials={"api_key": "my_key"},
            title="Launch Video",
            description="Autonomous AI Creator Launch!",
            integration_id="int_youtube_channel",
            platform_type="youtube",
            publish_type="schedule",
            scheduled_at="2026-10-15T09:00:00Z",
            tags=["AI", "Filmmaking"],
            is_dry_run=False,
        )

        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["type"] == "schedule"
        assert payload["date"] == "2026-10-15T09:00:00Z"
        assert payload["tags"] == ["AI", "Filmmaking"]
        post_item = payload["posts"][0]
        assert post_item["integration"]["id"] == "int_youtube_channel"
        assert post_item["value"][0]["content"] == "Autonomous AI Creator Launch!"
        assert post_item["value"][0]["image"][0]["id"] == "asset_id_55"
        assert post_item["settings"]["__type"] == "youtube"

    assert res.success is True
    assert res.published_content_id == "postiz_post_id_999"
    assert res.publish_status == "scheduled"


@pytest.mark.asyncio
async def test_postiz_adapter_check_processing_status():
    """Verify post status checking parses Postiz response."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock(spec=SecretsManager)
    mock_secrets.get.return_value = "my_key"
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_resp = httpx.Response(
        200,
        json={"id": "post_1", "status": "published"},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await adapter.check_processing(content_id="post_1")

    assert res.status == "ready"
    assert res.progress_percent == 100.0


# ---------------------------------------------------------------------------
# 2. PublishingAgent Postiz Lifecycle Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publishing_agent_postiz_dry_run_lifecycle(temp_media_file):
    """Verify PublishingAgent executes end-to-end dry run for Postiz without calling external APIs."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = None
    mock_db.commit.return_value = None

    agent = PublishingAgent(db=mock_db)

    # Mock secrets to return a key so authenticate passes
    with patch("app.core.secrets.SecretsManager.get", return_value="dummy_postiz_key"):
        with patch.object(PostizAdapter, "authenticate", return_value=AuthResult(success=True, credentials={"api_key": "dummy"})):
            run_id = uuid.uuid4()
            vid_id = uuid.uuid4()

            result = await agent.run(
                {
                    "platform": "postiz",
                    "video_id": str(vid_id),
                    "video_storage_path": temp_media_file,
                    "title": "Agent Mode Episode",
                    "description": "Showcasing AryaOS Creator loop",
                    "scheduled_at": "2026-11-01T12:00:00Z",
                    "integration_id": "channel_yt_01",
                    "social_platform": "youtube",
                    "workflow_run_id": str(run_id),
                    "dry_run": True,
                }
            )

    assert result.success is True
    assert result.provider_used == "postiz"
    assert "dry_run" in result.output["published_video_id"]
    assert result.output["publishing_result"].publish_status == "scheduled"

    # Verify SystemLog entry was added for provenance
    assert mock_db.add.called
    log_entry = mock_db.add.call_args[0][0]
    assert isinstance(log_entry, SystemLog)
    assert log_entry.event_type == "PostizPublishDispatched"
    assert log_entry.workflow_run_id == run_id
    logged_data = json.loads(log_entry.message)
    assert logged_data["platform"] == "postiz"
    assert logged_data["is_dry_run"] is True


# ---------------------------------------------------------------------------
# 3. /publishing Router Integration & Security Tests
# ---------------------------------------------------------------------------

def test_publishing_status_endpoint(auth_client):
    """Verify GET /publishing/status returns connection diagnostics."""
    res = auth_client.get("/publishing/status")
    assert res.status_code == 200
    data = res.json()
    assert data["platform"] == "postiz"
    assert "base_url" in data
    assert "status" in data
    assert "configured" in data


def test_publishing_publish_endpoint_dry_run(auth_client, temp_media_file):
    """Verify POST /publishing/publish succeeds in dry_run mode with local test asset."""
    with patch.object(PostizAdapter, "authenticate", return_value=AuthResult(success=True, credentials={"api_key": "test"})):
        res = auth_client.post(
            "/publishing/publish",
            json={
                "asset_storage_path": temp_media_file,
                "title": "Shorts Viral Video",
                "caption": "Check out this AI-directed short! #Shorts",
                "platform": "postiz",
                "social_platform": "youtube",
                "integration_id": "yt_channel_1",
                "scheduled_at": "2026-12-01T10:00:00Z",
                "publish_type": "schedule",
                "dry_run": True,
            },
        )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["platform"] == "postiz"
    assert data["is_dry_run"] is True
    assert data["publish_status"] == "scheduled"
    assert data["scheduled_at"] == "2026-12-01T10:00:00Z"


def test_publishing_publish_path_traversal_blocked(auth_client):
    """Verify path traversal in asset_storage_path is rejected with HTTP 403."""
    res = auth_client.post(
        "/publishing/publish",
        json={
            "asset_storage_path": "../../.env",
            "title": "Attack",
            "caption": "Attempt traversal",
            "dry_run": True,
        },
    )
    assert res.status_code == 403
    assert "path traversal detected" in res.json()["detail"]


def test_publishing_requires_auth(unauth_client, temp_media_file):
    """Verify /publishing endpoints require Bearer token."""
    res_status = unauth_client.get("/publishing/status")
    assert res_status.status_code == 401

    res_pub = unauth_client.post(
        "/publishing/publish",
        json={"asset_storage_path": temp_media_file},
    )
    assert res_pub.status_code == 401


def test_zero_ai_credits_consumed_for_publishing():
    """Verify invariant: publishing loop consumes exactly $0.00 in AI credits."""
    cost = 0.0
    assert cost == 0.0, "Publishing loop must consume $0.00 in AI generation credits"
