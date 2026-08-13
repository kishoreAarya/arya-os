"""ThumbnailAgent — generates a thumbnail image with bold text overlay."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine

logger = get_logger("arya.agents.thumbnail")


@dataclass
class ThumbnailResult:
    prompt: str = ""
    storage_path: str | None = None


def _build_thumbnail_prompt(topic: str, style_guide: str | None) -> str:
    """Build CTR-optimized thumbnail prompt."""
    prompt = f"YouTube thumbnail: dramatic close-up of {topic}, bold contrasting colors, cinematic lighting, face showing strong emotion, text overlay space at top, viral-style composition, 4K, photorealistic"
    if style_guide:
        prompt += f", {style_guide}"
    return prompt


class ThumbnailAgent(BaseAgent):
    name = "thumbnail_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        topic = context.get("topic")
        if not topic:
            return AgentResult(
                success=False,
                error="context.topic is required and was empty",
            )

        prompt = _build_thumbnail_prompt(topic, context.get("style_guide"))

        exec_result = await self._execution_engine.execute(
            capability=Capability.IMAGE_GENERATION,
            call=build_media_generation_call(
                capability=Capability.IMAGE_GENERATION,
                prompt=prompt,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="thumbnail_generation",
            validator_name="thumbnail",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        storage_path = output.get("storage_path")

        # Add bold text overlay to thumbnail
        if storage_path:
            storage_path = await self._add_text_overlay(storage_path, topic)

        thumbnail_result = ThumbnailResult(
            prompt=prompt,
            storage_path=storage_path,
        )

        result_output = {
            "thumbnail_result": thumbnail_result,
            "thumbnail_storage_path": storage_path,
            "topic": topic,
        }

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )

    async def _add_text_overlay(self, image_url: str, topic: str) -> str | None:
        """Download image and add bold white text with black outline."""
        try:
            # Download image
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()

            tmp_dir = Path(tempfile.gettempdir()) / f"arya_thumb_{uuid.uuid4().hex}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            input_path = tmp_dir / "input.png"
            output_path = tmp_dir / "output.jpg"

            input_path.write_bytes(resp.content)

            # Open image
            img = Image.open(input_path).convert("RGB")
            draw = ImageDraw.Draw(img)

            # Create shortened title (max 6 words)
            words = topic.split()
            title = " ".join(words[:6]) if len(words) > 6 else topic
            title = title.upper()

            # Try to load a bold font, fallback to default
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
            except Exception:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 60)
                except Exception:
                    font = ImageFont.load_default()

            # Calculate text position (centered, bottom area)
            bbox = draw.textbbox((0, 0), title, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            img_width, img_height = img.size
            x = (img_width - text_width) // 2
            y = img_height - text_height - 40

            # Draw black outline
            outline_range = 3
            for dx in range(-outline_range, outline_range + 1):
                for dy in range(-outline_range, outline_range + 1):
                    draw.text((x + dx, y + dy), title, font=font, fill="black")

            # Draw white text
            draw.text((x, y), title, font=font, fill="white")

            # Save
            img.save(output_path, "JPEG", quality=95)

            return str(output_path)

        except Exception as exc:
            logger.warning("thumbnail_text_overlay_failed", error=str(exc))
            return image_url