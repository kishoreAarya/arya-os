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


def test_sound_resolver_elevenlabs_bounded_stream_success(monkeypatch):
    """Verify ElevenLabs sound effects response is streamed in chunks and writes valid file."""
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    class MockStreamResponse:
        def __init__(self, data: bytes, headers: dict | None = None):
            self._data = data
            self._pos = 0
            self.headers = headers or {"Content-Length": str(len(data))}

        def read(self, size: int = -1) -> bytes:
            if size == -1:
                chunk = self._data[self._pos :]
                self._pos = len(self._data)
                return chunk
            if self._pos >= len(self._data):
                return b""
            chunk = self._data[self._pos : self._pos + size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import urllib.request
    sample_mp3 = b"ID3" + (b"\x00" * 100000)  # ~100KB
    mock_resp = MockStreamResponse(sample_mp3)

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-xi-key")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: mock_resp)

    res_path = resolver._resolve_external_provider("foley", "laser_zap", duration=2.0)
    assert res_path is not None
    assert Path(res_path).exists()
    assert Path(res_path).stat().st_size == len(sample_mp3)


def test_sound_resolver_elevenlabs_oversized_response_rejected(monkeypatch):
    """Verify ElevenLabs sound effects response exceeding 15MB is rejected and cleaned up."""
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    class MockOversizedStreamResponse:
        def __init__(self):
            self.headers = {}
            self.total_read = 0

        def read(self, size: int = 65536) -> bytes:
            # Continuously emit chunks up to 16MB (exceeding 15MB cap)
            if self.total_read > 16 * 1024 * 1024:
                return b""
            self.total_read += size
            return b"A" * size

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import urllib.request
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-xi-key")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: MockOversizedStreamResponse())

    res_path = resolver._resolve_external_provider("foley", "huge_explosion", duration=5.0)
    # Must fail gracefully (return None)
    assert res_path is None

    # Verify no partial files were left in cache external directory
    ext_dir = resolver.cache.cache_dir / "external"
    if ext_dir.exists():
        files = list(ext_dir.glob("*.mp3"))
        assert len(files) == 0


def test_sound_resolver_elevenlabs_content_length_oversized_rejected(monkeypatch):
    """Verify ElevenLabs response with Content-Length > 15MB is aborted before downloading."""
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    class MockContentLengthOversizedResponse:
        def __init__(self):
            self.headers = {"Content-Length": "20000000"}  # ~20MB

        def read(self, size: int = 65536) -> bytes:
            raise RuntimeError("Should not be called if Content-Length check works")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import urllib.request
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-xi-key")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: MockContentLengthOversizedResponse())

    res_path = resolver._resolve_external_provider("foley", "giant_explosion", duration=5.0)
    assert res_path is None
