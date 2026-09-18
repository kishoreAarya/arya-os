"""YouTube Data API v3 trend research source."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import SimpleRateLimiter

logger = get_logger("arya.trend_sources.youtube")


class YouTubeTrendSource(BaseTrendSource):
    """Fetches live trend and search signals from YouTube Data API v3."""

    name = "youtube_data_api"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key or get_settings().youtube_api_key
        self._client = client
        self._rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_seconds=0.2)
        self._timeout = timeout

    def _compute_relevance(self, topic_hint: str, text: str) -> float:
        """Compute normalized keyword relevance score between 0.5 and 1.0."""
        if not topic_hint.strip():
            return 0.7
        words = set(re.findall(r"\w+", topic_hint.lower()))
        if not words:
            return 0.7
        text_lower = text.lower()
        matched = sum(1 for w in words if w in text_lower)
        ratio = matched / len(words)
        return round(0.5 + (0.5 * ratio), 3)

    def _estimate_competition(self, view_count: int) -> str:
        """Categorize competition based on top video view volume."""
        if view_count >= 1_000_000:
            return "high"
        elif view_count >= 100_000:
            return "medium"
        return "low"

    async def fetch_trends(
        self, topic_hint: str, limit: int = 10
    ) -> list[TrendSignal]:
        """Fetch trending videos or top search results for the given topic."""
        if not self._api_key:
            logger.info("youtube_trend_skipped_no_api_key")
            return []

        clean_topic = topic_hint.strip()
        max_results = min(max(1, limit), 25)

        own_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            own_client = True

        try:
            await self._rate_limiter.acquire()

            # 1. Search or most popular video query
            if clean_topic:
                search_url = "https://www.googleapis.com/youtube/v3/search"
                params: dict[str, Any] = {
                    "part": "snippet",
                    "q": clean_topic,
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": max_results,
                    "key": self._api_key,
                }
            else:
                search_url = "https://www.googleapis.com/youtube/v3/videos"
                params = {
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "maxResults": max_results,
                    "key": self._api_key,
                }

            res = await client.get(search_url, params=params)
            res.raise_for_status()
            data = res.json()
            items = data.get("items", [])

            if not items:
                return []

            # 2. If search returned video IDs, fetch statistics
            video_ids = []
            for item in items:
                v_id = item.get("id")
                if isinstance(v_id, dict) and "videoId" in v_id:
                    video_ids.append(v_id["videoId"])
                elif isinstance(v_id, str):
                    video_ids.append(v_id)

            detailed_items = items
            if video_ids and clean_topic:
                await self._rate_limiter.acquire()
                videos_url = "https://www.googleapis.com/youtube/v3/videos"
                v_params = {
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids),
                    "key": self._api_key,
                }
                v_res = await client.get(videos_url, params=v_params)
                if v_res.is_success:
                    detailed_items = v_res.json().get("items", items)

            signals: list[TrendSignal] = []
            for it in detailed_items:
                snippet = it.get("snippet", {})
                stats = it.get("statistics", {})
                title = snippet.get("title", "").strip() or clean_topic
                channel = snippet.get("channelTitle", "")
                pub_date = snippet.get("publishedAt", datetime.now(timezone.utc).isoformat())

                view_count = int(stats.get("viewCount", 0))
                like_count = int(stats.get("likeCount", 0))
                comment_count = int(stats.get("commentCount", 0))

                signal_desc = f"{view_count:,} views, {like_count:,} likes"
                competition = self._estimate_competition(view_count)
                relevance = self._compute_relevance(
                    clean_topic, title + " " + snippet.get("description", "")
                )
                confidence = min(0.95, round(0.6 + (min(view_count, 1_000_000) / 1_000_000) * 0.35, 3))

                raw_id = it.get("id")
                video_id_str = raw_id if isinstance(raw_id, str) else (raw_id.get("videoId") if isinstance(raw_id, dict) else "")

                signals.append(
                    TrendSignal(
                        topic=title,
                        search_volume_or_signal=signal_desc,
                        relevance=relevance,
                        freshness=pub_date,
                        competition=competition,
                        source=self.name,
                        confidence=confidence,
                        metadata={
                            "video_id": video_id_str,
                            "channel": channel,
                            "view_count": view_count,
                            "like_count": like_count,
                            "comment_count": comment_count,
                        },
                    )
                )

            logger.info("youtube_trend_signals_fetched", count=len(signals), topic=clean_topic)
            return signals

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in (403, 429):
                logger.warning("youtube_trend_quota_or_rate_limit", status_code=status_code)
            else:
                logger.warning("youtube_trend_http_error", status_code=status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("youtube_trend_network_error", error=str(exc))
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("youtube_trend_unexpected_error", error=str(exc))
            return []
        finally:
            if own_client:
                await client.aclose()
