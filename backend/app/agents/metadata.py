"""MetadataAgent — generates optimized YouTube video metadata (title, description, tags, hashtags, category).

Generates metadata directly from the actual final script and topic, optimizing
for CTR and search discoverability without clickbait or spam.

Uses Capability.TEXT_GENERATION through the shared ExecutionEngine/router architecture,
enforcing structured JSON output and validating via MetadataValidator.
"""
from dataclasses import dataclass
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.models.media import Video
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine
from app.validators.metadata_validator import (
    MAX_TITLE_LENGTH,
    VALID_YOUTUBE_CATEGORIES,
    normalize_category,
)

logger = get_logger("arya.agents.metadata")


@dataclass
class MetadataResult:
    """Strongly-typed metadata output for publishing and persistence."""
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]
    category: str
    target_audience: str | None = None
    character_count_title: int = 0
    character_count_description: int = 0


def _build_metadata_prompt(
    script_content: str,
    topic: str,
    target_audience: str | None = None,
    style: str | None = None,
) -> str:
    """Constructs prompt instructing LLM to generate structured YouTube metadata."""
    prompt_lines = [
        "You are an expert YouTube SEO and metadata strategist.",
        "Generate optimized metadata for a video based on the script and topic below.",
        "",
        f"Topic: {topic}",
    ]
    if target_audience:
        prompt_lines.append(f"Target Audience: {target_audience}")
    if style:
        prompt_lines.append(f"Channel / Video Style: {style}")

    # Include script excerpt or full text
    script_snippet = script_content.strip()
    if len(script_snippet) > 2000:
        script_snippet = script_snippet[:2000] + "\n...[script continued]..."
    prompt_lines.extend([
        "",
        "Video Script Content:",
        "```",
        script_snippet,
        "```",
        "",
        "Instructions:",
        "1. title: Create a high-CTR, curiosity-inducing title under 75 characters. Do NOT use misleading clickbait or ALL CAPS.",
        "2. description: Write an engaging 150-400 word description including a compelling hook, key takeaways from the script, relevant search keywords, and a call-to-action to like and subscribe.",
        "3. tags: Provide 10-18 highly targeted YouTube tags (mix of broad topic and specific long-tail keywords). No single character tags. Total combined length under 400 characters.",
        "4. hashtags: Provide 3-5 relevant hashtags starting with # (e.g., #Science, #History).",
        f"5. category: Select the SINGLE best category from: {', '.join(sorted(VALID_YOUTUBE_CATEGORIES))}.",
        "",
        "Respond ONLY with valid JSON in this exact structure:",
        "{",
        '  "title": "...",',
        '  "description": "...",',
        '  "tags": ["tag1", "tag2", "tag3"],',
        '  "hashtags": ["#tag1", "#tag2", "#tag3"],',
        '  "category": "Education"',
        "}",
    ])

    return "\n".join(prompt_lines)


def _sanitize_metadata(data: dict, default_topic: str, default_script: str) -> dict:
    """Sanitizes and applies safe defaults to metadata fields."""
    raw_title = str(data.get("title") or default_topic).strip()
    # Strip quotes if model wrapped title in quotes
    raw_title = raw_title.strip('"\'')
    if len(raw_title) > MAX_TITLE_LENGTH:
        # Truncate at word boundary
        raw_title = raw_title[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0]
    title = raw_title or f"Exploring {default_topic}"

    raw_description = str(data.get("description") or "").strip()
    if len(raw_description) < 30:
        # Generate safe fallback description from script
        first_lines = " ".join(default_script.split()[:40]) if default_script else default_topic
        raw_description = f"{first_lines}...\n\nSubscribe to the channel for more videos!"
    description = raw_description

    raw_tags = data.get("tags")
    if isinstance(raw_tags, str):
        tags_candidates = [t.strip() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, list):
        tags_candidates = [str(t).strip() for t in raw_tags if str(t).strip()]
    else:
        tags_candidates = []

    # Filter, deduplicate, limit combined length
    seen = set()
    clean_tags = []
    total_chars = 0
    for t in tags_candidates:
        t_clean = re.sub(r"[<>]", "", t)
        if len(t_clean) > 1 and t_clean.lower() not in seen:
            seen.add(t_clean.lower())
            if total_chars + len(t_clean) <= 450:
                clean_tags.append(t_clean)
                total_chars += len(t_clean)

    if len(clean_tags) < 3:
        # Safe tag fallbacks
        topic_words = default_topic.split()
        for w in topic_words:
            if len(w) > 2 and w.lower() not in seen:
                clean_tags.append(w)
                seen.add(w.lower())
        clean_tags.extend(["video", "explainer", "overview"])

    raw_hashtags = data.get("hashtags")
    if isinstance(raw_hashtags, str):
        ht_candidates = [h.strip() for h in raw_hashtags.split() if h.strip()]
    elif isinstance(raw_hashtags, list):
        ht_candidates = [str(h).strip() for h in raw_hashtags if str(h).strip()]
    else:
        ht_candidates = []

    clean_hashtags = []
    seen_ht = set()
    for h in ht_candidates:
        tag = h if h.startswith("#") else f"#{h}"
        tag = re.sub(r"[^#A-Za-z0-9_]", "", tag)
        if len(tag) > 2 and tag.lower() not in seen_ht:
            seen_ht.add(tag.lower())
            clean_hashtags.append(tag)

    if not clean_hashtags:
        clean_hashtags = [f"#{re.sub(r'[^A-Za-z0-9]', '', default_topic)}", "#Shorts", "#Video"]

    raw_cat = str(data.get("category") or "").strip()
    category = normalize_category(raw_cat) or "Education"

    return {
        "title": title,
        "description": description,
        "tags": clean_tags,
        "hashtags": clean_hashtags,
        "category": category,
    }


class MetadataAgent(BaseAgent):
    name = "metadata_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        script_content (str) or script (str) or voice_text (str)
        topic (str, optional)
        target_audience (str, optional)
        style (str, optional)
        video_id (str | UUID, optional) — for persisting to Video table
        workflow_run_id (str | UUID, optional)
        """
        script_content = (
            context.get("script_content")
            or context.get("script")
            or context.get("voice_text")
            or ""
        )
        topic = str(context.get("topic") or "").strip()

        if not script_content.strip() and not topic:
            return AgentResult(
                success=False,
                error="context.script_content or context.topic is required and was empty",
            )

        if not topic and script_content:
            # Extract basic topic from first words of script
            topic = " ".join(script_content.split()[:5])

        prompt = _build_metadata_prompt(
            script_content=script_content,
            topic=topic,
            target_audience=context.get("target_audience"),
            style=context.get("style"),
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="metadata_generation",
            validator_name="metadata",
        )

        if not exec_result.success:
            return AgentResult(
                success=False,
                error=exec_result.error or "ExecutionEngine failed to generate metadata",
            )

        # Parse output
        raw_output = exec_result.output
        parsed_data = {}
        if isinstance(raw_output, dict):
            parsed_data = raw_output
        elif isinstance(raw_output, str):
            text = raw_output.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            try:
                parsed_data = json.loads(text)
            except Exception as exc:
                logger.warning("metadata_json_parse_fallback", error=str(exc))
                parsed_data = {}

        # Sanitize and validate
        sanitized = _sanitize_metadata(parsed_data, default_topic=topic, default_script=script_content)

        title = sanitized["title"]
        description = sanitized["description"]
        tags = sanitized["tags"]
        hashtags = sanitized["hashtags"]
        category = sanitized["category"]

        metadata_result = MetadataResult(
            title=title,
            description=description,
            tags=tags,
            hashtags=hashtags,
            category=category,
            target_audience=context.get("target_audience"),
            character_count_title=len(title),
            character_count_description=len(description),
        )

        # Update Video row in DB if video_id is present
        video_id = context.get("video_id")
        if video_id:
            try:
                v_uuid = UUID(str(video_id))
                await self._db.execute(
                    update(Video)
                    .where(Video.id == v_uuid)
                    .values(
                        title=title,
                        description=description,
                        tags=", ".join(tags),
                    )
                )
                await self._db.commit()
                logger.info("video_row_metadata_updated", video_id=str(video_id), title=title)
            except Exception as exc:
                logger.warning("video_row_metadata_update_failed", video_id=str(video_id), error=str(exc))

        output = {
            "metadata_result": metadata_result,
            "title": title,
            "description": description,
            "tags": ", ".join(tags),
            "tags_list": tags,
            "hashtags": hashtags,
            "category": category,
        }

        return AgentResult(
            success=True,
            output=output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
