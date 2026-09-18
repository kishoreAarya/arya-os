"""Unit tests for SoundAssetResolver and SFXCache."""

import tempfile
from pathlib import Path

import pytest

from app.core.sound_resolver import (
    SFXCache,
    SoundAssetResolver,
    normalize_sound_key,
)
from app.schemas.cinematic import (
    AmbientSoundIntent,
    FoleyEvent,
    MasterAudioPlan,
    SFXCacheEntry,
)


def test_normalize_sound_key():
    assert normalize_sound_key("ambience", "Room Tone") == ("ambient", "room_tone")
    assert normalize_sound_key("sfx", "creaking door") == ("foley", "door_creak")
    assert normalize_sound_key("foley", "heart") == ("foley", "heartbeat")
    assert normalize_sound_key("diegetic", "footstep") == ("foley", "footsteps")
    assert normalize_sound_key("foley", "heavy breathing") == ("foley", "breathing")


def test_sfx_cache_put_and_get():
    tmp_dir = Path(tempfile.mkdtemp())
    cache = SFXCache(cache_dir=tmp_dir)

    # Create dummy audio asset file
    dummy_wav = tmp_dir / "door_creak.wav"
    dummy_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")

    entry = cache.put(
        sound_type="foley",
        description="door_creak",
        asset_path=str(dummy_wav),
        duration_seconds=2.0,
        cost_usd=0.0,
    )
    assert entry.key == "foley:door_creak"
    assert entry.duration_seconds == 2.0
    assert entry.hit_count == 0

    # Retrieve from cache
    fetched = cache.get("foley", "door_creak")
    assert fetched is not None
    assert fetched.asset_path == str(dummy_wav)
    assert fetched.hit_count == 1

    stats = cache.stats()
    assert stats["total_items"] == 1
    assert stats["total_hits"] == 1


def test_sfx_cache_evicts_missing_file():
    tmp_dir = Path(tempfile.mkdtemp())
    cache = SFXCache(cache_dir=tmp_dir)
    missing_file = tmp_dir / "does_not_exist.wav"

    cache.put(
        sound_type="foley",
        description="ghost_sound",
        asset_path=str(missing_file),
        duration_seconds=1.0,
    )

    # Should evict and return None because file doesn't exist
    assert cache.get("foley", "ghost_sound") is None
    assert cache.stats()["total_items"] == 0


def test_sound_resolver_tier1_local_asset():
    tmp_dir = Path(tempfile.mkdtemp())
    ambient_dir = tmp_dir / "ambient"
    ambient_dir.mkdir(parents=True)
    local_wind = ambient_dir / "wind.mp3"
    local_wind.write_bytes(b"ID3\x03\x00\x00\x00")

    resolver = SoundAssetResolver(assets_dir=tmp_dir)
    res = resolver.resolve_sound("ambient", "wind")
    assert res is not None
    assert res.provider == "project_asset"
    assert res.asset_path == str(local_wind)


def test_sound_resolver_tier3_procedural_horror_synthesis():
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    # Resolve door creak procedurally
    res = resolver.resolve_sound("foley", "door_creak", duration=1.5)
    assert res is not None
    assert res.cost_usd == 0.0
    assert Path(res.asset_path).exists()
    assert Path(res.asset_path).stat().st_size > 0

    # Next call should hit cache (Tier 2)
    cached = resolver.resolve_sound("foley", "door_creak")
    assert cached is not None
    assert cached.hit_count >= 1


def test_sound_resolver_master_plan_resolution():
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    plan = MasterAudioPlan(
        ambient_layers=[AmbientSoundIntent(environment="room_tone", duration=5.0)],
        foley_events=[
            FoleyEvent(event="heartbeat", start_time=1.0, duration=2.0),
            FoleyEvent(event="door_creak", start_time=3.5, duration=1.8),
        ],
    )

    result = resolver.resolve_master_plan(plan)
    assert len(result.resolved_ambient) == 1
    assert len(result.resolved_foley) == 2
    assert result.total_cost_usd == 0.0

    # Ensure source_path is populated on the intents
    assert plan.ambient_layers[0].source_path is not None
    assert Path(plan.ambient_layers[0].source_path).exists()
    assert plan.foley_events[0].source_path is not None
    assert Path(plan.foley_events[0].source_path).exists()


def test_sound_resolver_graceful_omission():
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)
    assert resolver.resolve_sound("foley", "") is None
    assert resolver.resolve_sound("foley", "   ") is None
