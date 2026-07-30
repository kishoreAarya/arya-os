"""YouTube PlatformAdapter — full YouTube Data API v3 integration.

Implements the PlatformAdapter ABC for YouTube using:
- google-api-python-client for API calls
- google-auth for OAuth2 credential management
- Resumable upload protocol for video uploads

Authentication requires OAuth2 credentials stored in SecretsManager:
  - youtube_client_id
  - youtube_client_secret
  - youtube_refresh_token

Optional:
  - youtube_api_key (for read-only operations if OAuth unavailable)

The adapter follows the standard YouTube upload flow:
  1. Upload video as "private" (via upload_content)
  2. Upload thumbnail (via upload_thumbnail)
  3. Publish by changing privacyStatus to "public" (via publish)
  4. Poll processing status (via check_processing)
  5. Get public URL (via fetch_url)
  6. Fetch analytics (via fetch_analytics)

All methods return structured results (never raise raw exceptions).
"""
import asyncio
import datetime
import json
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.secrets import SecretsManager
from app.platforms.base import (
    AuthResult,
    PlatformAdapter,
    ProcessingStatus,
    PublishResult,
    UploadResult,
)

logger = get_logger(__name__)

# YouTube Data API v3 constants
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_URL_FORMAT = "https://www.youtube.com/watch?v={video_id}"

# Maximum chunk size for resumable upload (256MB)
MAX_RESUMABLE_CHUNK_SIZE = 256 * 1024 * 1024


class YouTubeAdapter(PlatformAdapter):
    """YouTube PlatformAdapter using Data API v3."""

    name = "youtube"

    def __init__(self, db: AsyncSession, secrets: SecretsManager):
        self._db = db
        self._secrets = secrets
        self._credentials: Any | None = None  # google.oauth2.credentials.Credentials
        self._youtube_client: Any | None = None  # googleapiclient.discovery.Resource

    # ------------------------------------------------------------------
    # Internal: build authenticated API client
    # ------------------------------------------------------------------

    def _build_credentials(self) -> Any:
        """Build or refresh OAuth2 credentials from SecretsManager.

        Reads youtube_client_id, youtube_client_secret, youtube_refresh_token.
        Falls back to API key (read-only) if OAuth credentials are incomplete.
        """
        try:
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError(
                "google-auth is not installed. Add 'google-auth' to dependencies."
            ) from exc

        client_id = self._secrets.get("youtube_client_id", required=False)
        client_secret = self._secrets.get("youtube_client_secret", required=False)
        refresh_token = self._secrets.get("youtube_refresh_token", required=False)

        if not all([client_id, client_secret, refresh_token]):
            # OAuth incomplete — try API key for read-only
            api_key = self._secrets.get("youtube_api_key", required=False)
            if api_key:
                logger.warning(
                    "youtube_adapter_oauth_incomplete",
                    reason="OAuth credentials incomplete; API key available for read-only",
                )
                return None  # API key path
            raise RuntimeError(
                "YouTube OAuth credentials incomplete. Need: youtube_client_id, "
                "youtube_client_secret, youtube_refresh_token (or youtube_api_key for read-only)"
            )

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READ_SCOPE],
        )

        # Refresh to get a valid access token
        try:
            from google.auth.transport.requests import Request
            credentials.refresh(Request())
        except Exception as exc:
            raise RuntimeError(f"Failed to refresh YouTube OAuth token: {exc}") from exc

        return credentials

    def _build_api_client(self, credentials: Any | None = None) -> Any:
        """Build the YouTube API client."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client is not installed. "
                "Add 'google-api-python-client' to dependencies."
            ) from exc

        if credentials:
            return build(
                YOUTUBE_API_SERVICE_NAME,
                YOUTUBE_API_VERSION,
                credentials=credentials,
                cache_discovery=False,
            )

        # API key path (read-only)
        api_key = self._secrets.get("youtube_api_key", required=False)
        if not api_key:
            raise RuntimeError("No YouTube credentials available (OAuth or API key)")

        return build(
            YOUTUBE_API_SERVICE_NAME,
            YOUTUBE_API_VERSION,
            developerKey=api_key,
            cache_discovery=False,
        )

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> AuthResult:
        """Authenticate with YouTube via OAuth2 or API key."""
        try:
            self._credentials = self._build_credentials()
            self._youtube_client = self._build_api_client(self._credentials)

            logger.info(
                "youtube_adapter_authenticated",
                auth_type="oauth2" if self._credentials else "api_key",
            )
            return AuthResult(
                success=True,
                credentials=self._credentials,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_authentication_failed",
                error=str(exc),
            )
            return AuthResult(
                success=False,
                error=f"YouTube authentication failed: {exc}",
            )

    async def upload_content(
        self,
        *,
        file_path: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        credentials: Any | None = None,
    ) -> UploadResult:
        """Upload a video to YouTube via resumable upload.

        Uploads as "private" by default. Call publish() to make public.
        """
        if not os.path.exists(file_path):
            return UploadResult(
                success=False,
                error=f"Video file not found: {file_path}",
            )

        # Ensure we have an authenticated client
        if self._youtube_client is None:
            auth_result = await self.authenticate()
            if not auth_result.success:
                return UploadResult(success=False, error=auth_result.error)

        body = {
            "snippet": {
                "title": title or "Untitled Video",
                "description": description or "",
                "tags": tags or [],
                "categoryId": "22",  # People & Blogs (default)
            },
            "status": {
                "privacyStatus": "private",  # Upload private, publish later
                "embeddable": True,
                "license": "youtube",
            },
        }

        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(
                file_path,
                chunksize=MAX_RESUMABLE_CHUNK_SIZE,
                resumable=True,
            )

            insert_request = self._youtube_client.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media,
            )

            # Execute resumable upload with progress tracking
            response = None
            while response is None:
                status, response = insert_request.next_chunk()
                if status:
                    logger.info(
                        "youtube_adapter_upload_progress",
                        progress_percent=int(status.progress() * 100),
                    )

            video_id = response.get("id")
            logger.info(
                "youtube_adapter_upload_complete",
                video_id=video_id,
                title=title,
            )

            return UploadResult(
                success=True,
                content_id=video_id,
                storage_path=file_path,
                url=YOUTUBE_URL_FORMAT.format(video_id=video_id),
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_upload_failed",
                file_path=file_path,
                error=str(exc),
            )
            return UploadResult(
                success=False,
                error=f"YouTube upload failed: {exc}",
            )

    async def upload_thumbnail(
        self,
        *,
        video_content_id: str,
        thumbnail_path: str,
        credentials: Any | None = None,
    ) -> UploadResult:
        """Upload a thumbnail for an existing YouTube video."""
        if not os.path.exists(thumbnail_path):
            return UploadResult(
                success=False,
                error=f"Thumbnail file not found: {thumbnail_path}",
            )

        if self._youtube_client is None:
            auth_result = await self.authenticate()
            if not auth_result.success:
                return UploadResult(success=False, error=auth_result.error)

        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")

            self._youtube_client.thumbnails().set(
                videoId=video_content_id,
                media_body=media,
            ).execute()

            logger.info(
                "youtube_adapter_thumbnail_upload_complete",
                video_id=video_content_id,
                thumbnail_path=thumbnail_path,
            )

            return UploadResult(
                success=True,
                content_id=video_content_id,
                storage_path=thumbnail_path,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_thumbnail_upload_failed",
                video_id=video_content_id,
                error=str(exc),
            )
            return UploadResult(
                success=False,
                error=f"YouTube thumbnail upload failed: {exc}",
            )

    async def publish(
        self,
        *,
        content_id: str,
        credentials: Any | None = None,
    ) -> PublishResult:
        """Publish a YouTube video by changing privacyStatus to 'public'."""
        if self._youtube_client is None:
            auth_result = await self.authenticate()
            if not auth_result.success:
                return PublishResult(success=False, error=auth_result.error)

        try:
            self._youtube_client.videos().update(
                part="status",
                body={
                    "id": content_id,
                    "status": {
                        "privacyStatus": "public",
                        "embeddable": True,
                    },
                },
            ).execute()

            logger.info(
                "youtube_adapter_publish_complete",
                video_id=content_id,
            )

            return PublishResult(
                success=True,
                published_content_id=content_id,
                publish_status="published",
                url=YOUTUBE_URL_FORMAT.format(video_id=content_id),
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_publish_failed",
                video_id=content_id,
                error=str(exc),
            )
            return PublishResult(
                success=False,
                error=f"YouTube publish failed: {exc}",
            )

    async def check_processing(
        self,
        *,
        content_id: str,
        credentials: Any | None = None,
    ) -> ProcessingStatus:
        """Check whether a YouTube video has finished processing."""
        if self._youtube_client is None:
            auth_result = await self.authenticate()
            if not auth_result.success:
                return ProcessingStatus(status="failed", error=auth_result.error)

        try:
            response = (
                self._youtube_client.videos()
                .list(part="processingDetails", id=content_id)
                .execute()
            )

            items = response.get("items", [])
            if not items:
                return ProcessingStatus(
                    status="failed",
                    error=f"Video {content_id} not found",
                )

            processing = items[0].get("processingDetails", {})
            processing_status = processing.get("processingStatus", "unknown")

            # Map YouTube status to our status
            status_map = {
                "processing": "processing",
                "succeeded": "ready",
                "failed": "failed",
                "terminated": "failed",
            }
            mapped_status = status_map.get(processing_status, "unknown")

            logger.info(
                "youtube_adapter_processing_status",
                video_id=content_id,
                status=mapped_status,
            )

            return ProcessingStatus(
                status=mapped_status,
                progress_percent=processing.get("processingProgress", {}).get(
                    "partsProcessed", 0
                )
                / max(
                    processing.get("processingProgress", {}).get("partsTotal", 1),
                    1,
                )
                * 100
                if mapped_status == "processing"
                else None,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_check_processing_failed",
                video_id=content_id,
                error=str(exc),
            )
            return ProcessingStatus(
                status="failed",
                error=f"YouTube processing check failed: {exc}",
            )

    async def fetch_url(
        self,
        *,
        published_content_id: str,
        credentials: Any | None = None,
    ) -> str | None:
        """Get the public URL for a published YouTube video."""
        return YOUTUBE_URL_FORMAT.format(video_id=published_content_id)

    async def fetch_analytics(
        self,
        *,
        published_content_id: str,
        credentials: Any | None = None,
    ) -> dict:
        """Fetch analytics for a YouTube video.

        Uses YouTube Data API videos.list with statistics part.
        Returns a flat dict matching the Analytics model fields.

        Note: YouTube Data API provides basic stats (views, likes, comments).
        For advanced metrics (CTR, average view duration), YouTube Analytics
        API v2 would be needed. This implementation returns what's available.
        """
        if self._youtube_client is None:
            auth_result = await self.authenticate()
            if not auth_result.success:
                return {"error": auth_result.error}

        try:
            response = (
                self._youtube_client.videos()
                .list(part="statistics", id=published_content_id)
                .execute()
            )

            items = response.get("items", [])
            if not items:
                return {"error": f"Video {published_content_id} not found"}

            stats = items[0].get("statistics", {})

            result = {
                "snapshot_at": datetime.datetime.utcnow().isoformat(),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "shares": 0,  # Not available via Data API
                "subscribers_gained": 0,  # Not available via Data API
            }

            logger.info(
                "youtube_adapter_analytics_fetched",
                video_id=published_content_id,
                views=result["views"],
                likes=result["likes"],
            )

            return result

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "youtube_adapter_fetch_analytics_failed",
                video_id=published_content_id,
                error=str(exc),
            )
            return {"error": f"YouTube analytics fetch failed: {exc}"}
