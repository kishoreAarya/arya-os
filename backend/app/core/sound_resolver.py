"""Deterministic sound asset resolver and SFX cache.

Grounded in Sections 9-14 of Task 16 specification and CINEMATIC_PRODUCTION_BIBLE.md.
Resolves sound design requests (ambient, foley, diegetic, transition cues) into
concrete local audio assets according to strict priority:
1. Existing local/project asset
2. Existing cached asset
3. Existing generated asset (deterministic procedural synthesis)
4. Configured external SFX provider (if available)
5. Graceful omission
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.cinematic import (
    AmbientSoundIntent,
    FoleyEvent,
    MasterAudioPlan,
    SFXCacheEntry,
    SFXResolutionResult,
    SoundDesignPlan,
)

logger = get_logger("arya.core.sound_resolver")

# Asset directories
_BASE_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"
_AMBIENT_DIR = _BASE_ASSETS_DIR / "ambient"
_SFX_DIR = _BASE_ASSETS_DIR / "sfx"
_CACHE_DIR = _BASE_ASSETS_DIR / "cache"

# Procedural FFmpeg filtergraph recipes for canonical horror cues
_PROCEDURAL_HORROR_RECIPES: dict[str, dict[str, Any]] = {
    "room_tone": {
        "sound_type": "ambient",
        "duration": 10.0,
        "filter": "anoisesrc=d=10:c=pink:r=44100,volume=0.03,lowpass=f=350",
    },
    "heartbeat": {
        "sound_type": "foley",
        "duration": 3.0,
        "filter": "sine=f=55:d=3,volume=eval=frame:volume='if(lt(mod(t,1.0),0.12),0.85,if(lt(mod(t,1.0),0.32),0.55,0.0))'",
    },
    "footsteps": {
        "sound_type": "foley",
        "duration": 3.0,
        "filter": "anoisesrc=d=3:c=pink:r=44100,lowpass=f=450,volume=eval=frame:volume='if(lt(mod(t,0.65),0.12),exp(-18*mod(t,0.65)),0)'",
    },
    "breathing": {
        "sound_type": "foley",
        "duration": 4.0,
        "filter": "anoisesrc=d=4:c=pink:r=44100,bandpass=f=600:w=180,volume=eval=frame:volume='0.15*(0.5+0.5*sin(2*3.14159*t/2.5))'",
    },
    "door_creak": {
        "sound_type": "foley",
        "duration": 2.2,
        "filter": "anoisesrc=d=2.2:c=pink:r=44100,bandpass=f=820:w=40,volume=eval=frame:volume='0.35*(0.5+0.5*sin(22*t))*exp(-0.2*t)'",
    },
    "knock": {
        "sound_type": "foley",
        "duration": 1.2,
        "filter": "sine=f=110:d=1.2,volume=eval=frame:volume='if(lt(mod(t,0.35),0.09),exp(-28*mod(t,0.35)),0)'",
    },
    "metal_scrape": {
        "sound_type": "foley",
        "duration": 2.0,
        "filter": "anoisesrc=d=2:c=white:r=44100,bandpass=f=3100:w=150,volume=eval=frame:volume='0.22*(0.5+0.5*sin(14*t))*exp(-0.3*t)'",
    },
    "whisper": {
        "sound_type": "foley",
        "duration": 2.5,
        "filter": "anoisesrc=d=2.5:c=white:r=44100,bandpass=f=1600:w=350,volume=eval=frame:volume='0.16*(0.5+0.5*sin(7*t))*exp(-0.2*t)'",
    },
    "wind": {
        "sound_type": "ambient",
        "duration": 8.0,
        "filter": "anoisesrc=d=8:c=pink:r=44100,bandpass=f=320:w=120,volume=eval=frame:volume='0.12*(0.7+0.3*sin(0.8*t))'",
    },
    "rain": {
        "sound_type": "ambient",
        "duration": 8.0,
        "filter": "anoisesrc=d=8:c=white:r=44100,highpass=f=1400,volume=0.07",
    },
    "thunder": {
        "sound_type": "foley",
        "duration": 3.5,
        "filter": "anoisesrc=d=3.5:c=brown:r=44100,lowpass=f=220,volume=eval=frame:volume='exp(-1.1*t)'",
    },
    "distant_impact": {
        "sound_type": "foley",
        "duration": 2.0,
        "filter": "sine=f=62:d=2.0,volume=eval=frame:volume='0.9*exp(-2.5*t)'",
    },
    "water_drip": {
        "sound_type": "foley",
        "duration": 1.0,
        "filter": "sine=f=1350:d=1.0,volume=eval=frame:volume='exp(-14*t)'",
    },
}


def normalize_sound_key(sound_type: str, description: str) -> tuple[str, str]:
    """Normalize sound type and description to canonical keys.

    Returns:
        (canonical_type, normalized_description)
    """
    clean_type = sound_type.lower().strip()
    if clean_type in ("ambience", "ambient", "room_tone", "environment"):
        c_type = "ambient"
    elif clean_type in ("sfx", "foley", "diegetic", "effect"):
        c_type = "foley"
    else:
        c_type = clean_type

    desc = description.lower().strip()
    desc = re.sub(r"[^\w\s-]", "", desc)
    desc = re.sub(r"[\s-]+", "_", desc)

    # Alias mappings for common descriptive variants
    alias_map = {
        "creak": "door_creak",
        "creaking": "door_creak",
        "creaking_door": "door_creak",
        "heart": "heartbeat",
        "footstep": "footsteps",
        "step": "footsteps",
        "steps": "footsteps",
        "running_footsteps": "footsteps",
        "breathe": "breathing",
        "breath": "breathing",
        "heavy_breathing": "breathing",
        "knocking": "knock",
        "door_knock": "knock",
        "scrape": "metal_scrape",
        "scraping": "metal_scrape",
        "metal": "metal_scrape",
        "whispering": "whisper",
        "whispers": "whisper",
        "drip": "water_drip",
        "dripping": "water_drip",
        "water_drops": "water_drip",
        "impact": "distant_impact",
        "boom": "distant_impact",
        "thud": "distant_impact",
        "thunderclap": "thunder",
        "rainstorm": "rain",
        "storm": "thunder",
        "roomtone": "room_tone",
        "silence": "room_tone",
    }
    normalized_desc = alias_map.get(desc, desc)
    return c_type, normalized_desc


class SFXCache:
    """Deterministic, persistent metadata cache for sound assets."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or _CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache_dir / "sfx_cache_index.json"
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._entries = data
            except Exception as exc:
                logger.warning("sfx_cache_load_failed", error=str(exc))
                self._entries = {}

    def _save(self) -> None:
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2)
        except Exception as exc:
            logger.warning("sfx_cache_save_failed", error=str(exc))

    def get(self, sound_type: str, description: str) -> SFXCacheEntry | None:
        """Lookup cached asset entry. Increments hit_count on hit."""
        c_type, norm_desc = normalize_sound_key(sound_type, description)
        key = f"{c_type}:{norm_desc}"
        raw = self._entries.get(key)
        if raw:
            asset_path = raw.get("asset_path")
            if asset_path and Path(asset_path).exists() and Path(asset_path).stat().st_size > 0:
                raw["hit_count"] = raw.get("hit_count", 0) + 1
                self._save()
                return SFXCacheEntry.model_validate(raw)
            else:
                # Evict invalid entry
                self._entries.pop(key, None)
                self._save()
        return None

    def put(
        self,
        sound_type: str,
        description: str,
        asset_path: str,
        duration_seconds: float,
        cost_usd: float = 0.0,
        provider: str = "local_asset",
        model: str = "procedural",
    ) -> SFXCacheEntry:
        """Store new asset metadata in cache."""
        c_type, norm_desc = normalize_sound_key(sound_type, description)
        key = f"{c_type}:{norm_desc}"
        entry = SFXCacheEntry(
            key=key,
            sound_type=c_type,
            normalized_description=norm_desc,
            asset_path=str(asset_path),
            duration_seconds=round(duration_seconds, 3),
            cost_usd=round(cost_usd, 5),
            provider=provider,
            model=model,
            created_at=datetime.now(timezone.utc).isoformat(),
            hit_count=0,
        )
        self._entries[key] = entry.model_dump()
        self._save()
        return entry

    def stats(self) -> dict[str, Any]:
        """Summary metrics of cached assets."""
        total_items = len(self._entries)
        total_hits = sum(e.get("hit_count", 0) for e in self._entries.values())
        return {
            "total_items": total_items,
            "total_hits": total_hits,
            "index_path": str(self.index_file),
        }


class SoundAssetResolver:
    """Resolves abstract sound design intents into verified local audio files.

    Follows Section 10 Resolution Priority:
    1. Existing local/project asset
    2. Existing cached asset
    3. Existing generated asset (procedural synthesis)
    4. Configured external SFX provider (ElevenLabs SFX if enabled)
    5. Graceful omission
    """

    def __init__(
        self,
        assets_dir: Path | None = None,
        cache: SFXCache | None = None,
    ) -> None:
        self.assets_dir = assets_dir or _BASE_ASSETS_DIR
        self.ambient_dir = self.assets_dir / "ambient"
        self.sfx_dir = self.assets_dir / "sfx"
        self.ambient_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.cache = cache or SFXCache(self.assets_dir / "cache")

    def _find_local_project_file(self, sound_type: str, norm_desc: str) -> str | None:
        """Priority 1: Look for an existing local asset in project repository."""
        target_dir = self.ambient_dir if sound_type == "ambient" else self.sfx_dir
        for ext in (".wav", ".mp3", ".aac", ".ogg", ".flac"):
            p = target_dir / f"{norm_desc}{ext}"
            if p.exists() and p.stat().st_size > 0:
                return str(p)
        return None

    def _synthesize_procedural_asset(
        self,
        sound_type: str,
        norm_desc: str,
        duration: float | None = None,
    ) -> str | None:
        """Priority 3: Synthesize clean, deterministic audio cue using FFmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None

        recipe = _PROCEDURAL_HORROR_RECIPES.get(norm_desc)
        if not recipe:
            return None

        target_dur = duration or recipe["duration"]
        target_dur = max(0.5, float(target_dur))

        out_dir = self.cache.cache_dir / "synthesized"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{sound_type}_{norm_desc}_{int(target_dur*10)}s.wav"

        if out_path.exists() and out_path.stat().st_size > 0:
            return str(out_path)

        filt = recipe["filter"]

        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", filt,
            "-t", f"{target_dur:.2f}",
            "-c:a", "pcm_s16le",
            str(out_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
            if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                return str(out_path)
        except Exception as exc:
            logger.warning("sfx_procedural_synthesis_failed", cue=norm_desc, error=str(exc))

        return None

    def _resolve_external_provider(
        self,
        sound_type: str,
        description: str,
        duration: float = 2.0,
    ) -> str | None:
        """Priority 4: Configured external SFX provider (e.g. ElevenLabs sound-effects)."""
        settings = get_settings()
        api_key = getattr(settings, "elevenlabs_api_key", None) or os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            return None

        try:
            import urllib.request
            url = "https://api.elevenlabs.io/v1/sound-effects"
            payload = json.dumps({
                "text": description,
                "duration_seconds": max(1.0, min(10.0, duration)),
                "prompt_influence": 0.3,
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            out_dir = self.cache.cache_dir / "external"
            out_dir.mkdir(parents=True, exist_ok=True)
            _, norm_desc = normalize_sound_key(sound_type, description)
            out_path = out_dir / f"elevenlabs_{norm_desc}_{int(time.time())}.mp3"
            with urllib.request.urlopen(req, timeout=15) as resp, open(out_path, "wb") as f:
                f.write(resp.read())
            if out_path.exists() and out_path.stat().st_size > 0:
                return str(out_path)
        except Exception as exc:
            logger.warning("external_sfx_provider_failed", error=str(exc))
        return None

    def resolve_sound(
        self,
        sound_type: str,
        description: str,
        duration: float | None = None,
    ) -> SFXCacheEntry | None:
        """Resolve a single sound request across priority tiers."""
        if not description or not description.strip():
            return None

        c_type, norm_desc = normalize_sound_key(sound_type, description)

        # Tier 1: Local project asset
        local_file = self._find_local_project_file(c_type, norm_desc)
        if local_file:
            logger.info("sfx_resolved_tier1_local", cue=norm_desc, path=local_file)
            return self.cache.put(
                sound_type=c_type,
                description=norm_desc,
                asset_path=local_file,
                duration_seconds=duration or 2.0,
                cost_usd=0.0,
                provider="project_asset",
                model="local_file",
            )

        # Tier 2: Cache hit
        cached = self.cache.get(c_type, norm_desc)
        if cached:
            logger.info("sfx_resolved_tier2_cache", cue=norm_desc, hits=cached.hit_count)
            return cached

        # Tier 3: Procedural synthesis into cache
        synth_file = self._synthesize_procedural_asset(c_type, norm_desc, duration)
        if synth_file:
            logger.info("sfx_resolved_tier3_procedural", cue=norm_desc, path=synth_file)
            return self.cache.put(
                sound_type=c_type,
                description=norm_desc,
                asset_path=synth_file,
                duration_seconds=duration or 2.0,
                cost_usd=0.0,
                provider="local_engine",
                model="procedural_horror",
            )

        # Tier 4: External provider
        ext_file = self._resolve_external_provider(c_type, description, duration or 2.0)
        if ext_file:
            logger.info("sfx_resolved_tier4_external", cue=norm_desc, path=ext_file)
            return self.cache.put(
                sound_type=c_type,
                description=norm_desc,
                asset_path=ext_file,
                duration_seconds=duration or 2.0,
                cost_usd=0.05,
                provider="elevenlabs",
                model="sound_effects",
            )

        # Tier 5: Graceful omission
        logger.info("sfx_tier5_graceful_omission", cue=norm_desc)
        return None

    def resolve_ambient_intent(self, intent: AmbientSoundIntent) -> AmbientSoundIntent:
        """Resolve an AmbientSoundIntent, attaching local source_path if resolved."""
        if intent.source_path and Path(intent.source_path).exists():
            return intent

        resolved = self.resolve_sound("ambient", intent.environment, intent.duration)
        if resolved and Path(resolved.asset_path).exists():
            intent.source_path = resolved.asset_path
        return intent

    def resolve_foley_event(self, event: FoleyEvent) -> FoleyEvent:
        """Resolve a FoleyEvent, attaching local source_path if resolved."""
        if event.source_path and Path(event.source_path).exists():
            return event

        resolved = self.resolve_sound("foley", event.event, event.duration)
        if resolved and Path(resolved.asset_path).exists():
            event.source_path = resolved.asset_path
        return event

    def resolve_master_plan(self, master_plan: MasterAudioPlan) -> SFXResolutionResult:
        """Resolve all ambient beds and foley events in a MasterAudioPlan.

        Mutates the plan in place (sets source_path) and returns a summary result.
        """
        resolved_ambient: list[AmbientSoundIntent] = []
        resolved_foley: list[FoleyEvent] = []
        cache_hits = 0
        cache_misses = 0
        total_cost = 0.0
        omitted = 0

        for amb in master_plan.ambient_layers:
            prev_path = amb.source_path
            self.resolve_ambient_intent(amb)
            if amb.source_path:
                resolved_ambient.append(amb)
                if prev_path != amb.source_path:
                    cache_misses += 1
                else:
                    cache_hits += 1
            else:
                omitted += 1

        for fol in master_plan.foley_events:
            prev_path = fol.source_path
            self.resolve_foley_event(fol)
            if fol.source_path:
                resolved_foley.append(fol)
                if prev_path != fol.source_path:
                    cache_misses += 1
                else:
                    cache_hits += 1
            else:
                omitted += 1

        return SFXResolutionResult(
            resolved_foley=resolved_foley,
            resolved_ambient=resolved_ambient,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            total_cost_usd=total_cost,
            omitted_count=omitted,
        )
