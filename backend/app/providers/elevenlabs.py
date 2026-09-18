"""ElevenLabs Text-to-Speech provider adapter with character/word alignment timestamps.

Calls https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps
Returns audio file storage path, measured duration, and raw alignment data.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger("arya.providers.elevenlabs")

_ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
# Default cinematic narrative voice: "George - Warm, Deep, Storyteller"
_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
_DEFAULT_MODEL = "eleven_turbo_v2_5"
# ElevenLabs Creator tier pricing: approx $0.30 per 1,000 characters
_COST_PER_1K_CHARS_USD = 0.30


def _probe_duration(path: str) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not os.path.exists(path):
        return None
    try:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except Exception:
        pass
    return None


async def generate_speech(
    text: str,
    api_key: str,
    model: str | None = None,
    voice_id: str | None = None,
) -> tuple[dict[str, Any], float]:
    """Synthesize speech with character-level alignment timestamps using ElevenLabs.

    Returns:
      tuple of (result_dict, estimated_cost_usd)
      result_dict contains:
        storage_path: local MP3 file path
        duration_seconds: measured duration in seconds
        alignment: dict containing character alignment arrays
        raw: response payload
    """
    if not api_key or not api_key.strip():
        raise RuntimeError("ElevenLabs API key is missing or empty")

    if not text or not text.strip():
        raise RuntimeError("Text to synthesize is empty")

    from app.core.config import get_settings

    settings = get_settings()
    voice = voice_id or getattr(settings, "elevenlabs_voice_id", None) or _DEFAULT_VOICE_ID
    model_id = model or getattr(settings, "elevenlabs_model_id", None) or _DEFAULT_MODEL
    timeout_sec = float(getattr(settings, "elevenlabs_timeout_seconds", 60))
    rate_per_1k = getattr(settings, "elevenlabs_cost_per_1k_chars_usd", None)
    if rate_per_1k is None:
        rate_per_1k = _COST_PER_1K_CHARS_USD

    url = f"{_ELEVENLABS_BASE_URL}/text-to-speech/{voice}/with-timestamps"
    headers = {
        "xi-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }
    payload = {
        "text": text.strip(),
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            err_text = resp.text[:300]
            if api_key:
                err_text = err_text.replace(api_key.strip(), "[REDACTED]")
            logger.error(
                "elevenlabs_request_failed",
                status_code=resp.status_code,
                response_text=err_text,
            )
            raise RuntimeError(
                f"ElevenLabs TTS failed with HTTP {resp.status_code}: {err_text}"
            )

        data = resp.json()
    except httpx.RequestError as exc:
        err_msg = str(exc)
        if api_key:
            err_msg = err_msg.replace(api_key.strip(), "[REDACTED]")
        logger.exception("elevenlabs_network_error", error=err_msg)
        raise RuntimeError(f"ElevenLabs network error: {err_msg}") from exc

    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        raise RuntimeError("ElevenLabs response did not contain audio_base64")

    audio_bytes = base64.b64decode(audio_b64)
    tmp_path = Path(tempfile.gettempdir()) / f"arya_elevenlabs_{uuid.uuid4().hex}.mp3"
    tmp_path.write_bytes(audio_bytes)

    duration = _probe_duration(str(tmp_path))
    if duration is None or duration <= 0:
        duration = max(2.0, len(text) / 14.0)

    char_count = len(text)
    cost_usd = round((char_count / 1000.0) * float(rate_per_1k), 4)

    alignment = data.get("alignment") or {}

    logger.info(
        "elevenlabs_speech_generated",
        path=str(tmp_path),
        duration_seconds=duration,
        char_count=char_count,
        has_alignment=bool(alignment.get("characters")),
        cost_usd=cost_usd,
    )

    return {
        "storage_path": str(tmp_path),
        "duration_seconds": round(duration, 3),
        "alignment": alignment,
        "raw": {"normalized_alignment": data.get("normalized_alignment")},
    }, cost_usd
