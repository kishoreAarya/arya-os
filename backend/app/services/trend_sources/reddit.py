"""Reddit research and discussion scraping integration for Arya OS V1.

Extracts content signals, discussion themes, community sentiment, and post
metadata from public Reddit discussions without paid generation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import html
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import SimpleRateLimiter

logger = get_logger("arya.trend_sources.reddit")

_REDDIT_PUBLIC_BASE = "https://www.reddit.com"
_REDDIT_OAUTH_BASE = "https://oauth.reddit.com"
_REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

_COMMON_DISCUSSION_WORDS = {
    "what", "why", "how", "best", "vs", "versus", "anyone", "issue", "question",
    "thoughts", "problem", "review", "guide", "tips", "experience", "advice",
    "alternative", "discussion", "update", "new", "released", "recommend"
}


def _clean_text_content(text: str | None, max_length: int = 1000) -> str:
    """Clean and safely truncate post selftext or excerpt."""
    if not text:
        return ""
    # Unescape HTML entities
    unescaped = html.unescape(text)
    # Remove markdown link markup: [anchor](url) -> anchor
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", unescaped)
    # Normalize multiple newlines and spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_length:
        return cleaned[:max_length].rstrip() + "..."
    return cleaned


def _extract_discussion_themes(title: str, selftext: str) -> list[str]:
    """Extract key themes, questions, and topic clusters from a Reddit discussion."""
    themes: list[str] = []
    combined = f"{title} {selftext}".lower()

    # Question detection
    if "?" in combined:
        themes.append("user_question")
    if any(q in combined for q in ("how to", "how do i", "how can", "why does", "what is")):
        if "how_to_guide" not in themes:
            themes.append("how_to_inquiry")

    # Comparison detection
    if any(comp in combined for comp in (" vs ", " versus ", " compared to ", " better than ")):
        themes.append("comparison_analysis")

    # Troubleshooting / Pain points
    if any(w in combined for w in ("bug", "broken", "issue", "error", "fails", "problem", "struggling")):
        themes.append("pain_point_troubleshooting")

    # Recommendations / Best of
    if any(w in combined for w in ("recommend", "recommendation", "favorite", "best of", "top tier", "must have")):
        themes.append("recommendation_consensus")

    # Opinion / Discussion
    if any(w in combined for w in ("thoughts on", "unpopular opinion", "does anyone else", "what do you think")):
        themes.append("community_debate")

    if not themes:
        themes.append("general_discussion")

    return themes


class RedditTrendSource(BaseTrendSource):
    """Fetches discussion signals, topics, and sentiment from Reddit."""

    name = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
        client: httpx.AsyncClient | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
        timeout: float = 10.0,
    ) -> None:
        settings = get_settings()
        self._client_id = client_id or settings.reddit_client_id
        self._client_secret = client_secret or settings.reddit_client_secret
        self._user_agent = user_agent or settings.reddit_user_agent
        self._client = client
        self._rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_seconds=1.0)
        self._timeout = timeout

        # OAuth token cache
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _compute_relevance(self, topic_hint: str, title: str, selftext: str) -> float:
        """Compute keyword relevance score between 0.5 and 1.0."""
        clean_hint = topic_hint.strip().lower()
        if not clean_hint:
            return 0.7
        words = set(re.findall(r"\w+", clean_hint))
        if not words:
            return 0.7
        full_text = f"{title} {selftext}".lower()
        matches = sum(1 for w in words if w in full_text)
        ratio = matches / len(words)
        return round(0.5 + (0.5 * ratio), 3)

    def _estimate_competition(self, score: int, comments: int) -> str:
        """Categorize competition based on discussion volume and karma."""
        engagement = score + (comments * 2)
        if engagement >= 5000:
            return "high"
        elif engagement >= 500:
            return "medium"
        return "low"

    def _compute_confidence(self, upvote_ratio: float | None, score: int, comments: int) -> float:
        """Compute confidence score based on community consensus and engagement."""
        base = 0.5
        if upvote_ratio is not None:
            base = min(0.9, max(0.4, float(upvote_ratio)))
        if score > 100 or comments > 50:
            base = min(0.95, base + 0.05)
        return round(base, 3)

    def _compute_opportunity_score(self, relevance: float, confidence: float, competition: str) -> float:
        """Calculate composite opportunity score (0.0 to 100.0)."""
        comp_mult = 1.0 if competition == "low" else (0.85 if competition == "medium" else 0.7)
        score = (relevance * 60.0 + confidence * 40.0) * comp_mult
        return round(min(100.0, max(0.0, score)), 2)

    async def _get_access_token(self, client: httpx.AsyncClient) -> str | None:
        """Obtain application-only OAuth token if credentials are provided."""
        if not self._client_id or not self._client_secret:
            return None

        now = asyncio.get_event_loop().time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        try:
            auth = (self._client_id, self._client_secret)
            headers = {"User-Agent": self._user_agent}
            data = {"grant_type": "client_credentials"}
            res = await client.post(_REDDIT_TOKEN_URL, data=data, auth=auth, headers=headers)
            if res.status_code == 200:
                body = res.json()
                self._access_token = body.get("access_token")
                expires_in = body.get("expires_in", 3600)
                self._token_expires_at = now + max(60, expires_in - 120)
                logger.info("reddit_oauth_token_refreshed")
                return self._access_token
            else:
                logger.warning("reddit_oauth_token_failed", status_code=res.status_code)
                return None
        except Exception as exc:
            logger.warning("reddit_oauth_token_exception", error=str(exc))
            return None

    def _build_request_params(
        self,
        topic_hint: str,
        limit: int,
        subreddit: str | None = None,
        time_filter: str = "all",
        sort: str = "relevance",
    ) -> tuple[str, dict[str, Any]]:
        """Construct the URL and query parameters for Reddit API."""
        clean_topic = topic_hint.strip()
        max_limit = min(max(1, limit), 50)
        valid_t = time_filter if time_filter in ("hour", "day", "week", "month", "year", "all") else "all"

        base_host = _REDDIT_PUBLIC_BASE
        clean_sub = subreddit.strip().lstrip("r/").lstrip("/") if subreddit else None

        if clean_sub:
            if clean_topic:
                # Subreddit scoped search
                url = f"{base_host}/r/{clean_sub}/search.json"
                params = {
                    "q": clean_topic,
                    "restrict_sr": 1,
                    "sort": sort,
                    "t": valid_t,
                    "limit": max_limit,
                }
            else:
                # Subreddit hot / top listing
                listing = "top" if valid_t != "all" else "hot"
                url = f"{base_host}/r/{clean_sub}/{listing}.json"
                params = {
                    "limit": max_limit,
                    "t": valid_t,
                }
        else:
            if clean_topic:
                # Global search
                url = f"{base_host}/search.json"
                params = {
                    "q": clean_topic,
                    "sort": sort,
                    "t": valid_t,
                    "limit": max_limit,
                }
            else:
                # Global popular
                url = f"{base_host}/r/popular/hot.json"
                params = {"limit": max_limit}

        return url, params

    def _normalize_post_item(
        self,
        post_data: dict[str, Any],
        topic_hint: str,
        retrieved_at_iso: str,
    ) -> TrendSignal | None:
        """Parse raw Reddit post JSON object into a normalized TrendSignal."""
        title = post_data.get("title", "").strip()
        if not title:
            return None

        subreddit = post_data.get("subreddit", "unknown")
        post_id = post_data.get("id") or post_data.get("name", "")
        selftext = post_data.get("selftext", "")
        clean_content = _clean_text_content(selftext)
        score = int(post_data.get("score") or 0)
        comments = int(post_data.get("num_comments") or 0)
        upvote_ratio = post_data.get("upvote_ratio")

        created_utc = post_data.get("created_utc")
        if created_utc:
            try:
                post_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                freshness_iso = post_dt.isoformat()
            except Exception:
                post_dt = datetime.now(timezone.utc)
                freshness_iso = post_dt.isoformat()
        else:
            post_dt = datetime.now(timezone.utc)
            freshness_iso = post_dt.isoformat()

        raw_permalink = post_data.get("permalink", "")
        if raw_permalink:
            permalink = (
                raw_permalink
                if raw_permalink.startswith("http")
                else f"https://www.reddit.com{raw_permalink}"
            )
        else:
            permalink = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}"

        target_url = post_data.get("url") or permalink

        relevance = self._compute_relevance(topic_hint, title, selftext)
        competition = self._estimate_competition(score, comments)
        confidence = self._compute_confidence(upvote_ratio, score, comments)
        opp_score = self._compute_opportunity_score(relevance, confidence, competition)
        themes = _extract_discussion_themes(title, selftext)

        signal_str = f"{score:,} upvotes, {comments:,} comments"

        metadata: dict[str, Any] = {
            "source": "reddit",
            "subreddit": subreddit,
            "post_id": post_id,
            "title": title,
            "url": target_url,
            "permalink": permalink,
            "timestamp": freshness_iso,
            "score": score,
            "comment_count": comments,
            "content": clean_content,
            "author": post_data.get("author", "[deleted]"),
            "upvote_ratio": float(upvote_ratio) if upvote_ratio is not None else None,
            "retrieved_at": retrieved_at_iso,
            "extracted_themes": themes,
            "over_18": bool(post_data.get("over_18", False)),
            "is_self": bool(post_data.get("is_self", False)),
        }

        return TrendSignal(
            topic=title,
            search_volume_or_signal=signal_str,
            relevance=relevance,
            freshness=freshness_iso,
            competition=competition,
            source="reddit",
            timestamp=post_dt,
            confidence=confidence,
            opportunity_score=opp_score,
            metadata=metadata,
        )

    async def fetch_trends(
        self,
        topic_hint: str,
        limit: int = 10,
        subreddit: str | None = None,
        time_filter: str = "all",
        sort: str = "relevance",
    ) -> list[TrendSignal]:
        """Fetch and normalize Reddit discussions for a given topic or subreddit."""
        url, params = self._build_request_params(
            topic_hint=topic_hint,
            limit=limit,
            subreddit=subreddit,
            time_filter=time_filter,
            sort=sort,
        )

        own_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            own_client = True

        retrieved_at_iso = datetime.now(timezone.utc).isoformat()

        try:
            await self._rate_limiter.acquire()

            headers = {
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            }

            # If OAuth credentials exist, attempt token authentication
            token = await self._get_access_token(client)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                # Redirect to oauth.reddit.com
                url = url.replace(_REDDIT_PUBLIC_BASE, _REDDIT_OAUTH_BASE)

            logger.info("reddit_fetch_started", url=url, topic=topic_hint, subreddit=subreddit)

            res = await client.get(url, params=params, headers=headers)

            if res.status_code == 429:
                logger.warning("reddit_rate_limited", status_code=429, retry_after=res.headers.get("retry-after"))
                return []

            if res.status_code in (401, 403):
                logger.warning(
                    "reddit_access_forbidden",
                    status_code=res.status_code,
                    detail="Reddit requires authentication or blocked the public client",
                )
                return []

            if res.status_code == 404:
                logger.warning("reddit_subreddit_not_found", subreddit=subreddit, status_code=404)
                return []

            res.raise_for_status()

            data = res.json()
            if not isinstance(data, dict):
                logger.warning("reddit_malformed_response", data_type=type(data).__name__)
                return []

            children = data.get("data", {}).get("children", [])
            signals: list[TrendSignal] = []

            for child in children:
                post_data = child.get("data")
                if not isinstance(post_data, dict):
                    continue
                # Ignore NSFW / over_18 posts in clean creator workflows
                if post_data.get("over_18", False):
                    continue

                sig = self._normalize_post_item(post_data, topic_hint, retrieved_at_iso)
                if sig:
                    signals.append(sig)

            logger.info("reddit_fetch_succeeded", signal_count=len(signals), topic=topic_hint)
            return signals[:limit]

        except httpx.TimeoutException as exc:
            logger.warning("reddit_request_timeout", error=str(exc))
            return []
        except httpx.HTTPError as exc:
            logger.warning("reddit_network_error", error=str(exc))
            return []
        except Exception as exc:
            logger.warning("reddit_unexpected_error", error=str(exc))
            return []
        finally:
            if own_client:
                await client.aclose()
