"""Postiz PlatformAdapter — integration with Postiz social media publishing.

Implements PlatformAdapter for multi-platform scheduling and distribution via Postiz
(public v1 REST API). Handles:
- Authentication via POSTIZ_API_KEY
- Media upload to Postiz storage (/public/v1/upload)
- Post creation, drafting, and scheduling (/public/v1/posts)
- Connected integrations retrieval (/public/v1/integrations)
- Post status synchronization (/public/v1/posts/{id})
- Safe dry-run mode for pre-flight validation without public publishing
"""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import SecretsManager
from app.platforms.base import (
    AuthResult,
    PlatformAdapter,
    ProcessingStatus,
    PublishResult,
    UploadResult,
)

logger = get_logger("arya.platforms.postiz")


class PostizAdapter(PlatformAdapter):
    """Postiz PlatformAdapter using the official Postiz Public API v1."""

    name = "postiz"

    def __init__(self, db: AsyncSession, secrets: SecretsManager):
        self._db = db
        self._secrets = secrets
        settings = get_settings()
        self._base_url = (settings.postiz_base_url or "http://localhost:4007").rstrip("/")
        self._timeout_seconds = float(settings.postiz_timeout_seconds)
        self._default_integration_id = settings.postiz_default_integration_id

    # ------------------------------------------------------------------
    # Authentication & Connectivity Check
    # ------------------------------------------------------------------

    async def authenticate(self) -> AuthResult:
        """Verify Postiz credentials and connectivity."""
        api_key = self._secrets.get("postiz_api_key", required=False)
        if not api_key:
            return AuthResult(
                success=False,
                error="Postiz API key is not configured. Set POSTIZ_API_KEY in .env.",
            )

        # Test live connectivity against integrations endpoint
        try:
            async with httpx.AsyncClient(timeout=min(self._timeout_seconds, 5.0)) as client:
                resp = await client.get(
                    f"{self._base_url}/public/v1/integrations",
                    headers={"Authorization": api_key},
                )
                if resp.status_code in (401, 403):
                    return AuthResult(
                        success=False,
                        error=f"Postiz authentication rejected (HTTP {resp.status_code}): invalid API key",
                    )
                if resp.status_code >= 400:
                    return AuthResult(
                        success=False,
                        error=f"Postiz server returned HTTP {resp.status_code} at {self._base_url}",
                    )

                data = resp.json()
                integrations = data if isinstance(data, list) else []
                return AuthResult(
                    success=True,
                    credentials={
                        "api_key": api_key,
                        "base_url": self._base_url,
                        "integrations": integrations,
                    },
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            logger.warning("postiz_server_unreachable", url=self._base_url, error=str(exc))
            return AuthResult(
                success=False,
                error=f"Postiz server unreachable at {self._base_url}: {exc}",
            )
        except Exception as exc:
            logger.warning("postiz_auth_unexpected_error", error=str(exc))
            return AuthResult(
                success=False,
                error=f"Postiz connectivity error: {exc}",
            )

    # ------------------------------------------------------------------
    # Content & Media Upload
    # ------------------------------------------------------------------

    async def upload_content(
        self,
        *,
        file_path: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        credentials: object | None = None,
        **kwargs: Any,
    ) -> UploadResult:
        """Upload media file to Postiz storage."""
        is_dry_run = kwargs.get("is_dry_run", False)

        if not os.path.isfile(file_path):
            return UploadResult(
                success=False,
                error=f"File not found on filesystem: {file_path}",
            )

        if is_dry_run:
            file_name = Path(file_path).name
            simulated_id = f"dry_run_upload_{uuid.uuid4().hex[:8]}"
            return UploadResult(
                success=True,
                content_id=simulated_id,
                storage_path=file_path,
                url=f"{self._base_url}/uploads/{simulated_id}_{file_name}",
            )

        api_key = self._extract_api_key(credentials)
        if not api_key:
            return UploadResult(success=False, error="Missing Postiz API key for upload")

        mime_type, _ = mimetypes.guess_type(file_path)
        content_type = mime_type or "application/octet-stream"
        file_name = Path(file_path).name

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                files = {"file": (file_name, file_bytes, content_type)}
                resp = await client.post(
                    f"{self._base_url}/public/v1/upload",
                    headers={"Authorization": api_key},
                    files=files,
                )

                if resp.status_code >= 400:
                    return UploadResult(
                        success=False,
                        error=f"Postiz media upload failed with HTTP {resp.status_code}: {resp.text}",
                    )

                data = resp.json()
                content_id = data.get("id") or data.get("path") or file_name
                url = data.get("path") or data.get("url")
                return UploadResult(
                    success=True,
                    content_id=str(content_id),
                    storage_path=file_path,
                    url=url,
                )
        except Exception as exc:
            logger.error("postiz_upload_exception", error=str(exc))
            return UploadResult(
                success=False,
                error=f"Postiz upload exception: {exc}",
            )

    async def upload_thumbnail(
        self,
        *,
        video_content_id: str,
        thumbnail_path: str,
        credentials: object | None = None,
        **kwargs: Any,
    ) -> UploadResult:
        """Upload thumbnail for video post."""
        return await self.upload_content(
            file_path=thumbnail_path,
            credentials=credentials,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Post Creation / Scheduling
    # ------------------------------------------------------------------

    async def publish(
        self,
        *,
        content_id: str,
        credentials: object | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        """Create, draft, or schedule a post in Postiz.

        Supported kwargs:
        - title: Post title
        - description / caption: Text content of the post
        - integration_id: Target connected social account ID
        - platform_type: Social platform type ("youtube", "tiktok", "instagram", "x", etc.)
        - publish_type: "now" | "schedule" | "draft" (default: "draft")
        - scheduled_at: ISO 8601 string for scheduled release
        - tags: list of hashtags / topic tags
        - is_dry_run: bool (if True, executes validation without external API call)
        """
        is_dry_run = kwargs.get("is_dry_run", False)
        caption = kwargs.get("description") or kwargs.get("caption") or kwargs.get("title") or ""
        integration_id = kwargs.get("integration_id") or self._default_integration_id
        platform_type = kwargs.get("platform_type", "youtube")
        publish_type = kwargs.get("publish_type", "draft")
        scheduled_at = kwargs.get("scheduled_at")
        tags = kwargs.get("tags") or []

        # Enforce minimal validation
        if not content_id and publish_type != "draft":
            return PublishResult(success=False, error="content_id is required to publish media")

        if is_dry_run:
            dry_post_id = f"dry_run_post_{uuid.uuid4().hex[:12]}"
            logger.info(
                "postiz_dry_run_validated",
                content_id=content_id,
                publish_type=publish_type,
                integration_id=integration_id,
                platform_type=platform_type,
            )
            return PublishResult(
                success=True,
                published_content_id=dry_post_id,
                publish_status="draft" if publish_type == "draft" else "scheduled",
                url=f"{self._base_url}/posts/{dry_post_id}",
            )

        api_key = self._extract_api_key(credentials)
        if not api_key:
            return PublishResult(success=False, error="Missing Postiz API key for publishing")

        if not integration_id:
            return PublishResult(
                success=False,
                error="No Postiz integration_id specified and POSTIZ_INTEGRATION_ID is not configured",
            )

        post_date = scheduled_at or datetime.now(timezone.utc).isoformat()

        platform_settings: dict[str, Any] = {"__type": platform_type}
        if platform_type == "instagram":
            platform_settings["post_type"] = "post"
        if isinstance(kwargs.get("settings"), dict):
            platform_settings.update(kwargs["settings"])

        image_list: list[dict[str, Any]] = []
        if content_id and content_id not in ("none", "empty", "no_media"):
            media_item: dict[str, Any] = {"id": content_id}
            if kwargs.get("media_path") or kwargs.get("path"):
                media_item["path"] = kwargs.get("media_path") or kwargs.get("path")
            image_list.append(media_item)

        payload = {
            "type": publish_type,
            "date": post_date,
            "shortLink": False,
            "tags": tags if isinstance(tags, list) else [],
            "posts": [
                {
                    "integration": {"id": integration_id},
                    "value": [
                        {
                            "content": caption,
                            "image": image_list,
                        }
                    ],
                    "settings": platform_settings,
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                resp = await client.post(
                    f"{self._base_url}/public/v1/posts",
                    headers={
                        "Authorization": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if resp.status_code >= 400:
                    return PublishResult(
                        success=False,
                        error=f"Postiz post creation failed with HTTP {resp.status_code}: {resp.text}",
                    )

                data = resp.json()
                post_id = None
                if isinstance(data, dict):
                    post_id = data.get("id") or data.get("postId")
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    post_id = data[0].get("id") or data[0].get("postId")

                pub_status = "published" if publish_type == "now" else "scheduled"
                if publish_type == "draft":
                    pub_status = "draft"

                return PublishResult(
                    success=True,
                    published_content_id=str(post_id or uuid.uuid4()),
                    publish_status=pub_status,
                    url=f"{self._base_url}/posts/{post_id}" if post_id else None,
                )
        except Exception as exc:
            logger.error("postiz_publish_exception", error=str(exc))
            return PublishResult(
                success=False,
                error=f"Postiz publish network error: {exc}",
            )

    # ------------------------------------------------------------------
    # Status Synchronization & URLs
    # ------------------------------------------------------------------

    async def check_processing(
        self,
        *,
        content_id: str,
        credentials: object | None = None,
    ) -> ProcessingStatus:
        """Check status of a Postiz post."""
        if content_id.startswith("dry_run_"):
            return ProcessingStatus(status="ready", progress_percent=100.0)

        api_key = self._extract_api_key(credentials)
        if not api_key:
            return ProcessingStatus(status="unknown", error="Missing Postiz API key")

        try:
            async with httpx.AsyncClient(timeout=min(self._timeout_seconds, 10.0)) as client:
                resp = await client.get(
                    f"{self._base_url}/public/v1/posts/{content_id}",
                    headers={"Authorization": api_key},
                )
                if resp.status_code == 404:
                    now = datetime.now(timezone.utc)
                    posts_resp = await client.get(
                        f"{self._base_url}/public/v1/posts",
                        headers={"Authorization": api_key},
                        params={
                            "startDate": (now - timedelta(days=30)).isoformat(),
                            "endDate": (now + timedelta(days=30)).isoformat(),
                        },
                    )
                    if posts_resp.status_code == 200:
                        posts_data = posts_resp.json()
                        posts_list = posts_data.get("posts", []) if isinstance(posts_data, dict) else posts_data
                        matching = next((p for p in posts_list if p.get("id") == content_id), None)
                        if matching:
                            state = (matching.get("state") or matching.get("status") or "ready").lower()
                            normalized_status = "ready" if state in ("published", "draft", "ready") else "processing"
                            return ProcessingStatus(
                                status=normalized_status,
                                progress_percent=100.0 if normalized_status == "ready" else 50.0,
                            )
                    return ProcessingStatus(status="failed", error="Postiz post not found")
                if resp.status_code >= 400:
                    return ProcessingStatus(
                        status="unknown",
                        error=f"HTTP {resp.status_code}: {resp.text}",
                    )

                data = resp.json()
                state = (data.get("status") or "ready").lower()
                normalized_status = "ready" if state in ("published", "ready") else "processing"
                return ProcessingStatus(
                    status=normalized_status,
                    progress_percent=100.0 if normalized_status == "ready" else 50.0,
                )
        except Exception as exc:
            return ProcessingStatus(status="unknown", error=str(exc))

    async def fetch_url(
        self,
        *,
        published_content_id: str,
        credentials: object | None = None,
    ) -> str | None:
        """Get post URL."""
        return f"{self._base_url}/posts/{published_content_id}"

    async def fetch_analytics(
        self,
        *,
        published_content_id: str,
        credentials: object | None = None,
    ) -> dict:
        """Fetch post analytics from Postiz API v1 if available."""
        if published_content_id.startswith("dry_run_"):
            return {
                "source": "postiz_dry_run",
                "platform": "postiz",
                "views": 100,
                "likes": 10,
                "comments": 2,
                "shares": 1,
            }

        api_key = self._extract_api_key(credentials)
        if not api_key:
            return {"error": "Missing Postiz API key for analytics"}

        try:
            async with httpx.AsyncClient(timeout=min(self._timeout_seconds, 10.0)) as client:
                resp = await client.get(
                    f"{self._base_url}/public/v1/analytics/post/{published_content_id}?date=30",
                    headers={"Authorization": api_key},
                )
                if resp.status_code == 404:
                    return {"error": f"Postiz analytics not found for post {published_content_id}"}
                if resp.status_code >= 400:
                    return {"error": f"Postiz analytics error ({resp.status_code}): {resp.text}"}

                raw_data = resp.json()
                if isinstance(raw_data, dict) and raw_data.get("error"):
                    return raw_data

                normalized = self.parse_postiz_analytics(raw_data)
                return {
                    "source": "postiz",
                    "platform": "postiz",
                    "data": raw_data,
                    **normalized,
                }
        except Exception as exc:
            return {"error": f"Postiz analytics server unreachable: {exc}"}

    @staticmethod
    def parse_postiz_analytics(raw_data: Any) -> dict[str, Any]:
        """Normalize Postiz analytics response into a flat canonical metrics dictionary.

        Maps Postiz's labeled time-series array into flat canonical fields:
        views, likes, comments, shares, saves, subscribers_gained,
        engagement_rate, watch_time_seconds, click_through_rate, etc.

        Guarantees:
        - Safe handling of empty array / unreleased drafts (returns zero metrics)
        - Sums count metrics across multiple dated entries
        - Handles numeric strings, integers, floats, zero values, and commas
        - Robust against missing labels, empty data, or malformed entries without crashing
        - Preserves backward compatibility with legacy dict payloads
        """
        result: dict[str, Any] = {
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
        }

        if not raw_data:
            return result

        items_to_process: list[Any] = []
        if isinstance(raw_data, list):
            items_to_process = raw_data
        elif isinstance(raw_data, dict):
            if isinstance(raw_data.get("analytics"), list):
                items_to_process = raw_data["analytics"]
            elif isinstance(raw_data.get("data"), list):
                items_to_process = raw_data["data"]
            elif isinstance(raw_data.get("analytics"), dict):
                nested = raw_data["analytics"]
                for k, v in nested.items():
                    try:
                        num = int(v) if str(v).isdigit() else float(v)
                        result[k] = num
                    except (ValueError, TypeError):
                        pass
                return result
            else:
                for k in ("views", "likes", "comments", "shares", "saves", "subscribers_gained"):
                    if k in raw_data and raw_data[k] is not None:
                        try:
                            result[k] = int(raw_data[k])
                        except (ValueError, TypeError):
                            pass
                for k in ("click_through_rate", "engagement_rate", "watch_time_seconds"):
                    if k in raw_data and raw_data[k] is not None:
                        try:
                            result[k] = float(raw_data[k])
                        except (ValueError, TypeError):
                            pass
                return result

        label_map: dict[str, str] = {
            # Views
            "views": "views",
            "view": "views",
            "view count": "views",
            "view_count": "views",
            "impressions": "impressions",
            "impression": "impressions",
            "reach": "reach",
            # Likes
            "likes": "likes",
            "like": "likes",
            "like count": "likes",
            "like_count": "likes",
            "total likes": "likes",
            "recent likes": "likes",
            "favorites": "favorites",
            # Comments
            "comments": "comments",
            "comment": "comments",
            "comment count": "comments",
            "comment_count": "comments",
            "recent comments": "comments",
            "replies": "replies",
            # Shares
            "shares": "shares",
            "share": "shares",
            "share count": "shares",
            "share_count": "shares",
            "recent shares": "shares",
            "retweets": "shares",
            "reposts": "shares",
            "quotes": "shares",
            # Saves
            "saves": "saves",
            "save": "saves",
            "bookmarks": "saves",
            # Subscribers
            "subscribers gained": "subscribers_gained",
            "subscribers_gained": "subscribers_gained",
            "new subscribers": "subscribers_gained",
            "followers gained": "subscribers_gained",
            "followers_gained": "subscribers_gained",
            "subscribers": "subscribers_gained",
            "followers": "subscribers_gained",
            "follower count": "subscribers_gained",
            # Rates
            "engagement rate": "engagement_rate",
            "engagement_rate": "engagement_rate",
            "engagement": "engagement_rate",
            "click through rate": "click_through_rate",
            "click_through_rate": "click_through_rate",
            "ctr": "click_through_rate",
            "pin click rate": "click_through_rate",
            # Durations & percentages
            "watch time": "watch_time_seconds",
            "watch_time": "watch_time_seconds",
            "watch time seconds": "watch_time_seconds",
            "watch_time_seconds": "watch_time_seconds",
            "estimated minutes watched": "estimated_minutes_watched",
            "average view duration": "average_view_duration_seconds",
            "average view duration seconds": "average_view_duration_seconds",
            "average view percentage": "average_view_percentage",
            "completion rate": "completion_rate",
            "retention rate": "completion_rate",
            # Clicks
            "clicks": "clicks",
            "link clicks": "clicks",
            "pin clicks": "clicks",
            "outbound clicks": "clicks",
        }

        def _to_number(val: Any) -> int | float | None:
            if val is None or val == "":
                return None
            if isinstance(val, bool):
                return None
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                try:
                    if "." in cleaned:
                        return float(cleaned)
                    return int(cleaned)
                except ValueError:
                    return None
            return None

        collected_values: dict[str, list[int | float]] = {}

        for item in items_to_process:
            if not isinstance(item, dict):
                continue
            raw_label = item.get("label") or item.get("name")
            if not raw_label or not isinstance(raw_label, str):
                continue

            norm_label = raw_label.strip().lower().replace("-", " ").replace("_", " ")
            category = label_map.get(norm_label)
            if not category:
                continue

            data_field = item.get("data")
            entries: list[Any] = []
            if isinstance(data_field, list):
                entries = data_field
            elif isinstance(data_field, dict):
                entries = [data_field]
            elif "total" in item or "value" in item:
                entries = [item]

            for entry in entries:
                val = None
                if isinstance(entry, dict):
                    val = entry.get("total")
                    if val is None:
                        val = entry.get("value")
                    if val is None:
                        val = entry.get("count")
                else:
                    val = entry

                num = _to_number(val)
                if num is not None:
                    collected_values.setdefault(category, []).append(num)

        # 1. Views
        views_vals = collected_values.get("views") or collected_values.get("impressions") or collected_values.get("reach")
        if views_vals:
            result["views"] = max(0, sum(int(v) for v in views_vals if v >= 0))

        # 2. Likes
        likes_vals = collected_values.get("likes") or collected_values.get("favorites")
        if likes_vals:
            result["likes"] = max(0, sum(int(v) for v in likes_vals if v >= 0))

        # 3. Comments
        comments_vals = collected_values.get("comments") or collected_values.get("replies")
        if comments_vals:
            result["comments"] = max(0, sum(int(v) for v in comments_vals if v >= 0))

        # 4. Shares
        shares_vals = collected_values.get("shares")
        if shares_vals:
            result["shares"] = max(0, sum(int(v) for v in shares_vals if v >= 0))

        # 5. Saves
        if "saves" in collected_values:
            result["saves"] = max(0, sum(int(v) for v in collected_values["saves"] if v >= 0))

        # 6. Subscribers gained
        if "subscribers_gained" in collected_values:
            result["subscribers_gained"] = max(0, sum(int(v) for v in collected_values["subscribers_gained"] if v >= 0))

        # 7. Clicks
        if "clicks" in collected_values:
            result["clicks"] = max(0, sum(int(v) for v in collected_values["clicks"] if v >= 0))

        # 8. Watch time (seconds)
        if "watch_time_seconds" in collected_values:
            result["watch_time_seconds"] = float(sum(v for v in collected_values["watch_time_seconds"] if v >= 0))
        elif "estimated_minutes_watched" in collected_values:
            minutes = sum(v for v in collected_values["estimated_minutes_watched"] if v >= 0)
            result["watch_time_seconds"] = round(float(minutes * 60), 2)

        # 9. Click-through rate
        if "click_through_rate" in collected_values:
            ctr_vals = [v for v in collected_values["click_through_rate"] if v >= 0]
            if ctr_vals:
                avg_ctr = sum(ctr_vals) / len(ctr_vals)
                if 1.0 < avg_ctr <= 100.0:
                    avg_ctr = avg_ctr / 100.0
                result["click_through_rate"] = round(avg_ctr, 4)

        # 10. Engagement rate
        if "engagement_rate" in collected_values:
            eng_vals = [v for v in collected_values["engagement_rate"] if v >= 0]
            if eng_vals:
                avg_eng = sum(eng_vals) / len(eng_vals)
                if 1.0 < avg_eng <= 100.0:
                    avg_eng = avg_eng / 100.0
                result["engagement_rate"] = round(avg_eng, 4)

        # 11. Average view duration seconds
        if "average_view_duration_seconds" in collected_values:
            dur_vals = [v for v in collected_values["average_view_duration_seconds"] if v >= 0]
            if dur_vals:
                result["average_view_duration_seconds"] = round(sum(dur_vals) / len(dur_vals), 2)

        # 12. Average view percentage / completion rate
        if "average_view_percentage" in collected_values:
            pct_vals = [v for v in collected_values["average_view_percentage"] if v >= 0]
            if pct_vals:
                avg_pct = sum(pct_vals) / len(pct_vals)
                if 1.0 < avg_pct <= 100.0:
                    avg_pct = avg_pct / 100.0
                result["average_view_percentage"] = round(avg_pct, 4)

        if "completion_rate" in collected_values:
            comp_vals = [v for v in collected_values["completion_rate"] if v >= 0]
            if comp_vals:
                avg_comp = sum(comp_vals) / len(comp_vals)
                if 1.0 < avg_comp <= 100.0:
                    avg_comp = avg_comp / 100.0
                result["completion_rate"] = round(avg_comp, 4)

        return result

    # ------------------------------------------------------------------
    # Helper Utilities
    # ------------------------------------------------------------------

    def _extract_api_key(self, credentials: object | None) -> str | None:
        if isinstance(credentials, dict) and credentials.get("api_key"):
            return credentials["api_key"]
        return self._secrets.get("postiz_api_key", required=False)
