"""Google Trends research source using Google Trends RSS and public feed."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from app.core.logging import get_logger
from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import SimpleRateLimiter

logger = get_logger("arya.trend_sources.google_trends")


class GoogleTrendsSource(BaseTrendSource):
    """Fetches trending search signals from Google Trends official feeds."""

    name = "google_trends"

    def __init__(
        self,
        geo: str = "US",
        client: httpx.AsyncClient | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._geo = geo
        self._client = client
        self._rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_seconds=0.3)
        self._timeout = timeout

    def _parse_approx_traffic(self, traffic_str: str) -> int:
        """Convert e.g. "100,000+" to int 100000."""
        digits = re.sub(r"[^0-9]", "", traffic_str)
        return int(digits) if digits else 10000

    def _compute_relevance(self, topic_hint: str, title: str, snippet: str) -> float:
        clean_topic = topic_hint.strip().lower()
        if not clean_topic:
            return 0.7
        words = set(re.findall(r"\w+", clean_topic))
        if not words:
            return 0.7
        text = f"{title} {snippet}".lower()
        matches = sum(1 for w in words if w in text)
        ratio = matches / len(words)
        return round(0.5 + (0.5 * ratio), 3)

    def _estimate_competition(self, traffic: int) -> str:
        if traffic >= 500_000:
            return "high"
        elif traffic >= 100_000:
            return "medium"
        return "low"

    async def fetch_trends(
        self, topic_hint: str, limit: int = 10
    ) -> list[TrendSignal]:
        clean_topic = topic_hint.strip()
        max_results = min(max(1, limit), 25)

        own_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            own_client = True

        try:
            await self._rate_limiter.acquire()
            rss_url = f"https://trends.google.com/trending/rss?geo={self._geo}"
            res = await client.get(rss_url)
            res.raise_for_status()

            # Parse XML feed
            root = ET.fromstring(res.text)
            channel = root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")
            signals: list[TrendSignal] = []

            # Namespace map for Google Trends extension
            ns = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}

            matched_signals: list[TrendSignal] = []
            general_signals: list[TrendSignal] = []

            for item in items:
                title_elem = item.find("title")
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                if not title:
                    continue

                traffic_elem = item.find("ht:approx_traffic", ns)
                traffic_str = traffic_elem.text.strip() if traffic_elem is not None and traffic_elem.text else "50,000+"
                traffic_int = self._parse_approx_traffic(traffic_str)

                pub_elem = item.find("pubDate")
                pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else datetime.now(timezone.utc).isoformat()

                news_title = ""
                news_snippet = ""
                news_url = ""
                news_item = item.find("ht:news_item", ns)
                if news_item is not None:
                    nt = news_item.find("ht:news_item_title", ns)
                    nsnip = news_item.find("ht:news_item_snippet", ns)
                    nu = news_item.find("ht:news_item_url", ns)
                    news_title = nt.text.strip() if nt is not None and nt.text else ""
                    news_snippet = nsnip.text.strip() if nsnip is not None and nsnip.text else ""
                    news_url = nu.text.strip() if nu is not None and nu.text else ""

                relevance = self._compute_relevance(clean_topic, title, news_snippet)
                competition = self._estimate_competition(traffic_int)
                confidence = min(0.9, round(0.65 + (min(traffic_int, 1_000_000) / 1_000_000) * 0.25, 3))

                signal = TrendSignal(
                    topic=title,
                    search_volume_or_signal=f"{traffic_str} searches (Google Trends)",
                    relevance=relevance,
                    freshness=pub_date,
                    competition=competition,
                    source=self.name,
                    confidence=confidence,
                    metadata={
                        "approx_traffic": traffic_str,
                        "headline": news_title,
                        "snippet": news_snippet,
                        "source_url": news_url,
                        "geo": self._geo,
                    },
                )

                if clean_topic and relevance > 0.5:
                    matched_signals.append(signal)
                else:
                    general_signals.append(signal)

            # Prioritize matching signals if topic_hint was given
            if clean_topic and matched_signals:
                signals = matched_signals + general_signals
            else:
                signals = general_signals

            final_signals = signals[:max_results]
            logger.info("google_trends_signals_fetched", count=len(final_signals), topic=clean_topic)
            return final_signals

        except httpx.HTTPStatusError as exc:
            logger.warning("google_trends_http_error", status_code=exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("google_trends_network_error", error=str(exc))
            return []
        except ET.ParseError as exc:
            logger.warning("google_trends_xml_parse_error", error=str(exc))
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("google_trends_unexpected_error", error=str(exc))
            return []
        finally:
            if own_client:
                await client.aclose()
