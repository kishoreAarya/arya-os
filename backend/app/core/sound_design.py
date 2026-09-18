"""Sound design management and multi-layer audio mixing engine.

Grounded in Sections 16-19 of CINEMATIC_PRODUCTION_BIBLE.md.
Orchestrates:
  Primary Voice (intelligibility layer, 0dB)
  + Ambient / Room Tone (subtle environment bed, ~ -22dB)
  + Foley / SFX (timestamped events with adelay)
  + Background Music (ducked under voice, muted during intentional silence)
  + Master Limiter / Normalization (prevents clipping)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.schemas.cinematic import AmbientSoundIntent, FoleyEvent, MasterAudioPlan, SilenceInterval

logger = get_logger("arya.core.sound_design")

# Asset search locations for local audio assets
_AUDIO_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"


class SoundDesignManager:
    """Manages ambient, foley, silence, and music audio assets."""

    def __init__(self, base_asset_dir: Path | None = None) -> None:
        self._asset_dir = base_asset_dir or _AUDIO_ASSETS_DIR

    def resolve_ambient_asset(self, environment: str) -> str | None:
        """Resolve local ambient audio file if available.

        Gracefully returns None if asset does not exist (never invents fake assets).
        """
        if not environment:
            return None
        env_slug = environment.lower().strip().replace(" ", "_")
        for ext in [".mp3", ".wav", ".aac", ".ogg"]:
            candidate = self._asset_dir / "ambient" / f"{env_slug}{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                return str(candidate)
        return None

    def resolve_foley_asset(self, event: str) -> str | None:
        """Resolve local Foley/SFX audio file if available.

        Gracefully returns None if asset does not exist.
        """
        if not event:
            return None
        event_slug = event.lower().strip().replace(" ", "_")
        for ext in [".mp3", ".wav", ".aac", ".ogg"]:
            candidate = self._asset_dir / "sfx" / f"{event_slug}{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                return str(candidate)
        return None

    def build_audio_filtergraph(
        self,
        video_duration: float,
        voice_input_idx: int | None = 1,
        music_input_idx: int | None = 2,
        music_volume: float = 0.22,
        music_ducking_volume: float = 0.06,
        ambient_inputs: list[tuple[int, AmbientSoundIntent]] | None = None,
        foley_inputs: list[tuple[int, FoleyEvent]] | None = None,
        silence_intervals: list[SilenceInterval] | None = None,
        fade_in_seconds: float = 1.0,
        fade_out_seconds: float = 2.0,
    ) -> tuple[str, str]:
        """Construct FFmpeg filter_complex and output audio map label.

        Returns:
            tuple (filter_complex_string, output_label) e.g. ("...filtergraph...", "[aout]")
        """
        filters: list[str] = []
        mix_inputs: list[str] = []

        # 1. Voice layer (primary)
        if voice_input_idx is not None:
            filters.append(f"[{voice_input_idx}:a]volume=1.0[voice_track]")
            if music_input_idx is not None:
                filters.append(
                    f"[voice_track]asplit=2[voice_raw1][voice_raw2];"
                    f"[voice_raw1]apad,atrim=end={video_duration:.2f}[voice_main];"
                    f"[voice_raw2]apad,atrim=end={video_duration:.2f}[voice_sidechain]"
                )
                mix_inputs.append("[voice_main]")
            else:
                filters.append(f"[voice_track]apad,atrim=end={video_duration:.2f}[voice_main]")
                mix_inputs.append("[voice_main]")

        # 2. Ambient sound beds
        if ambient_inputs:
            for idx, (inp_idx, intent) in enumerate(ambient_inputs):
                vol = max(0.01, min(0.3, intent.volume))
                st_ms = int(intent.start_time * 1000)
                dur = max(0.5, intent.duration)
                filters.append(
                    f"[{inp_idx}:a]volume={vol},atrim=start=0:end={dur:.2f},"
                    f"adelay={st_ms}|{st_ms}[amb_{idx}]"
                )
                mix_inputs.append(f"[amb_{idx}]")

        # 3. Foley / SFX events
        if foley_inputs:
            for idx, (inp_idx, event) in enumerate(foley_inputs):
                vol = max(0.05, min(1.0, event.volume))
                st_ms = int(event.start_time * 1000)
                dur = max(0.2, event.duration)
                filters.append(
                    f"[{inp_idx}:a]volume={vol},atrim=start=0:end={dur:.2f},"
                    f"adelay={st_ms}|{st_ms}[foley_{idx}]"
                )
                mix_inputs.append(f"[foley_{idx}]")

        # 4. Background Music with silence gating & voice ducking
        if music_input_idx is not None:
            m_vol = max(0.01, min(1.0, music_volume))
            duck_thresh = max(0.01, min(0.5, music_ducking_volume))
            fade_out_start = max(0.0, video_duration - fade_out_seconds)

            music_pre_chain = [
                f"volume={m_vol}",
                f"afade=t=in:st=0:d={fade_in_seconds}",
                f"afade=t=out:st={fade_out_start:.2f}:d={fade_out_seconds}",
            ]

            # Intentional silence volume gating on music
            if silence_intervals:
                for sil in silence_intervals:
                    sil_end = sil.silence_start + sil.silence_duration
                    music_pre_chain.append(
                        f"volume=enable='between(t,{sil.silence_start:.2f},{sil_end:.2f})':volume=0"
                    )

            chain_str = ",".join(music_pre_chain)
            filters.append(f"[{music_input_idx}:a]{chain_str}[music_shaped]")

            # Sidechain ducking under voice if voice is present
            if voice_input_idx is not None:
                filters.append(
                    f"[music_shaped][voice_sidechain]sidechaincompress="
                    f"threshold={duck_thresh}:ratio=4:attack=50:release=500[music_ducked]"
                )
                mix_inputs.append("[music_ducked]")
            else:
                mix_inputs.append("[music_shaped]")

        # 5. Composite Mix & Master Limiter
        if not mix_inputs:
            # Fallback silence generator if literally no audio
            return "anullsrc=r=48000:cl=stereo[aout]", "[aout]"

        if len(mix_inputs) == 1:
            filters.append(f"{mix_inputs[0]}alimiter=limit=0.95:attack=5:release=50[aout]")
        else:
            joined_inputs = "".join(mix_inputs)
            filters.append(
                f"{joined_inputs}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2[amixed];"
                f"[amixed]alimiter=limit=0.95:attack=5:release=50[aout]"
            )

        return ";".join(filters), "[aout]"
