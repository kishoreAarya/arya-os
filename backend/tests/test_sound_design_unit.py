"""Unit tests for sound design management and multi-layer FFmpeg filtergraphs.

Covers Section 16 requirements:
- voice remains primary
- music ducking works
- ambient layer works
- SFX events work
- silence is supported
- missing optional audio degrades gracefully
- clipping is prevented where possible
"""

from pathlib import Path
import pytest
from app.core.sound_design import SoundDesignManager
from app.schemas.cinematic import AmbientSoundIntent, FoleyEvent, SilenceInterval


def test_sound_design_manager_asset_resolution(tmp_path):
    """Manager resolves existing local audio assets and gracefully returns None for missing ones."""
    # Set up mock assets folder
    amb_dir = tmp_path / "ambient"
    sfx_dir = tmp_path / "sfx"
    amb_dir.mkdir(parents=True)
    sfx_dir.mkdir(parents=True)

    test_wind = amb_dir / "wind.mp3"
    test_wind.write_bytes(b"dummy_audio")
    test_door = sfx_dir / "door_creak.mp3"
    test_door.write_bytes(b"dummy_audio")

    mgr = SoundDesignManager(base_asset_dir=tmp_path)

    assert mgr.resolve_ambient_asset("wind") == str(test_wind)
    assert mgr.resolve_ambient_asset("ocean") is None  # Missing asset returns None gracefully
    assert mgr.resolve_foley_asset("door_creak") == str(test_door)
    assert mgr.resolve_foley_asset("footstep") is None


def test_audio_filtergraph_primary_voice_and_music_ducking():
    """Voice is mapped uncompressed at 0dB while music is ducked via sidechain compressor."""
    mgr = SoundDesignManager()
    filtergraph, out_label = mgr.build_audio_filtergraph(
        video_duration=20.0,
        voice_input_idx=1,
        music_input_idx=2,
        music_volume=0.22,
        music_ducking_volume=0.06,
    )

    assert "[1:a]volume=1.0[voice_track]" in filtergraph
    assert "[2:a]" in filtergraph
    assert "sidechaincompress=threshold=0.06:ratio=4" in filtergraph
    assert out_label == "[aout]"
    assert "alimiter=limit=0.95" in filtergraph


def test_audio_filtergraph_intentional_silence_volume_gating():
    """Intentional silence mutates music volume during specified time windows."""
    mgr = SoundDesignManager()
    silences = [
        SilenceInterval(silence_start=12.0, silence_duration=1.5, reason="Suspense before monster reveal")
    ]
    filtergraph, _ = mgr.build_audio_filtergraph(
        video_duration=20.0,
        voice_input_idx=1,
        music_input_idx=2,
        silence_intervals=silences,
    )

    # Music chain must include volume gating during [12.00, 13.50]
    assert "volume=enable='between(t,12.00,13.50)':volume=0" in filtergraph


def test_audio_filtergraph_ambient_and_foley_layering():
    """Ambient and foley layers are delayed to correct timestamps and mixed with limiter."""
    mgr = SoundDesignManager()
    ambient = [(3, AmbientSoundIntent(environment="wind", start_time=0.0, duration=10.0, volume=0.08))]
    foley = [(4, FoleyEvent(event="metal_clank", start_time=4.5, duration=1.0, volume=0.5))]

    filtergraph, out_label = mgr.build_audio_filtergraph(
        video_duration=20.0,
        voice_input_idx=1,
        music_input_idx=2,
        ambient_inputs=ambient,
        foley_inputs=foley,
    )

    # Ambient input 3
    assert "[3:a]volume=0.08,atrim=start=0:end=10.00,adelay=0|0[amb_0]" in filtergraph
    # Foley input 4 at 4.5s (4500ms)
    assert "[4:a]volume=0.5,atrim=start=0:end=1.00,adelay=4500|4500[foley_0]" in filtergraph
    # 4 audio streams mixed: voice, amb, foley, music
    assert "amix=inputs=4:duration=first:dropout_transition=2" in filtergraph
    # Limiter prevents digital clipping
    assert "alimiter=limit=0.95" in filtergraph


def test_audio_filtergraph_graceful_degradation_missing_layers():
    """When optional layers (ambient, foley, music) are omitted, filtergraph degrades cleanly."""
    mgr = SoundDesignManager()
    # Voice only
    fg1, out1 = mgr.build_audio_filtergraph(
        video_duration=15.0,
        voice_input_idx=1,
        music_input_idx=None,
    )
    assert "[1:a]volume=1.0[voice_track]" in fg1
    assert "sidechaincompress" not in fg1
    assert "alimiter=limit=0.95" in fg1

    # Neither voice nor music (fallback)
    fg2, out2 = mgr.build_audio_filtergraph(
        video_duration=10.0,
        voice_input_idx=None,
        music_input_idx=None,
    )
    assert "anullsrc" in fg2
