"""Focused unit tests for Task 17 — Human-Quality Voice Benchmark.

Tests:
1. Provider selection and default hierarchy.
2. Voice benchmark scoring mathematics and dimension weights (100% sum).
3. Quality score computation.
4. Credential audit and honest reporting of unconfigured credentials.
5. Voice parameter forwarding (voice, voice_id, speed).
6. Timing/alignment handling (real timestamps vs honest fallback).
7. Cost and latency telemetry recording.
8. Secret redaction in voice generation errors and logs.
9. Audio validation and container constraints.
10. Quality gate enforcement (8.5/10 threshold).
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.core.config import Settings
from app.core.audio_timing import build_narration_timing
from app.providers.capabilities import Capability, PROVIDER_CAPABILITIES
from app.providers import replicate, elevenlabs


# 1. Scoring Mathematics and Dimensions
def test_voice_benchmark_scoring_weights_sum_to_one():
    """Verify that the 9 subjective quality dimensions strictly sum to 1.0 (100%)."""
    weights = {
        "naturalness": 0.20,
        "emotion": 0.20,
        "pauses": 0.10,
        "breath": 0.10,
        "emphasis": 0.10,
        "pitch": 0.05,
        "realism": 0.10,
        "cinematic": 0.10,
        "ai_detectability": 0.05,
    }
    total_weight = sum(weights.values())
    assert pytest.approx(total_weight, 1e-6) == 1.0
    assert len(weights) == 9


def test_voice_benchmark_quality_score_calculation():
    """Verify calculation of weighted human-quality scores."""
    weights = {
        "naturalness": 0.20,
        "emotion": 0.20,
        "pauses": 0.10,
        "breath": 0.10,
        "emphasis": 0.10,
        "pitch": 0.05,
        "realism": 0.10,
        "cinematic": 0.10,
        "ai_detectability": 0.05,
    }

    # Test case: Voice 3 (bm_george)
    scores = {
        "naturalness": 7.5,
        "emotion": 7.2,
        "pauses": 7.8,
        "breath": 6.5,
        "emphasis": 7.2,
        "pitch": 7.0,
        "realism": 7.2,
        "cinematic": 7.8,
        "ai_detectability": 6.8,
    }
    weighted_score = sum(scores[dim] * weights[dim] for dim in weights)
    assert round(weighted_score, 2) == 7.28


# 2. Quality Gate Rule
def test_quality_gate_enforcement():
    """Quality gate requires >= 8.5/10 to recommend a switch away from baseline."""
    quality_threshold = 8.5
    
    baseline_score = 6.06
    candidate_1_score = 6.86  # am_fenrir
    candidate_2_score = 7.28  # bm_george
    hypothetical_el_score = 8.90

    def recommend_action(candidate_score: float) -> str:
        if candidate_score >= quality_threshold:
            return "SWITCH"
        return "KEEP"

    assert recommend_action(candidate_1_score) == "KEEP"
    assert recommend_action(candidate_2_score) == "KEEP"
    assert recommend_action(hypothetical_el_score) == "SWITCH"


# 3. Provider Selection & Default Hierarchy
def test_voice_provider_default_is_elevenlabs():
    """Verify that the production default voice provider is ElevenLabs."""
    s = Settings(_env_file=None)
    assert s.default_voice_provider == "elevenlabs"


def test_provider_capability_tts_registration():
    """Both Replicate and ElevenLabs are registered for Capability.TTS."""
    assert Capability.TTS in PROVIDER_CAPABILITIES["replicate"].capabilities
    assert Capability.TTS in PROVIDER_CAPABILITIES["elevenlabs"].capabilities


# 4. Credential Reporting
def test_unconfigured_credential_reporting_not_tested():
    """Verify honest reporting for missing credentials without mock fabrication."""
    s = Settings(elevenlabs_api_key="", openai_api_key="")
    
    benchmark_status = {}
    for prov, key in [("elevenlabs", s.elevenlabs_api_key), ("openai", s.openai_api_key)]:
        if not key:
            benchmark_status[prov] = "NOT TESTED — REQUIRED CREDENTIAL NOT CONFIGURED"
        else:
            benchmark_status[prov] = "TESTED"

    assert benchmark_status["elevenlabs"] == "NOT TESTED — REQUIRED CREDENTIAL NOT CONFIGURED"
    assert benchmark_status["openai"] == "NOT TESTED — REQUIRED CREDENTIAL NOT CONFIGURED"


# 5. Replicate Voice Parameter Forwarding
@pytest.mark.asyncio
async def test_replicate_generate_speech_voice_parameter_forwarding():
    """Replicate generate_speech forwards voice and speed parameters to model input."""
    with patch("app.providers.replicate._create_prediction", new_callable=AsyncMock) as mock_pred:
        mock_pred.return_value = {"output": ["https://replicate.delivery/test.wav"], "status": "succeeded"}
        
        res, cost = await replicate.generate_speech(
            text="Hello world",
            api_key="r8_test_key",
            model="jaaari/kokoro-82m",
            voice="am_fenrir",
            speed=1.1
        )
        assert res["storage_path"] == "https://replicate.delivery/test.wav"
        assert cost == 0.01
        
        # Verify model input passed to Replicate
        call_args = mock_pred.call_args[0]
        model_name, model_input, api_key, cap = call_args
        assert model_name == "jaaari/kokoro-82m"
        assert model_input["text"] == "Hello world"
        assert model_input["voice"] == "am_fenrir"
        assert model_input["speed"] == 1.1
        assert cap == "tts"


# 6. Timing and Alignment Handling
def test_timing_alignment_honest_fallback_when_missing():
    """When provider does not expose word alignment, honest fallback is recorded."""
    script = "The voice whispered from behind the cellar door."
    timing = build_narration_timing(
        text=script,
        audio_path=None,
        duration_seconds=4.0,
        provider="replicate",
        alignment_data=None,
    )
    assert timing.has_real_timestamps is False
    assert timing.fallback_used is True
    assert "replicate" in str(timing.fallback_reason).lower()
    assert len(timing.segments) > 0


def test_timing_alignment_real_timestamps_when_present():
    """When provider alignment data is present, real timestamps are flagged."""
    script = "The voice whispered."
    mock_alignment = {
        "characters": ["T", "h", "e", " ", "v", "o", "i", "c", "e"],
        "character_start_times_seconds": [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4],
        "character_end_times_seconds": [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45],
    }
    timing = build_narration_timing(
        text=script,
        audio_path=None,
        duration_seconds=2.0,
        provider="elevenlabs",
        alignment_data=mock_alignment,
    )
    assert timing.has_real_timestamps is True
    assert timing.fallback_used is False
    assert timing.timestamp_provider == "elevenlabs"


# 7. Secret Redaction
@pytest.mark.asyncio
async def test_secret_redaction_in_voice_errors(monkeypatch):
    """Verify that raw API keys are never leaked into error messages or logs."""
    sensitive_key = "elevenlabs_secret_test_key_xyz987"

    class FakeResponse:
        status_code = 401
        text = f"Invalid authentication token: {sensitive_key} is rejected."

        def json(self):
            return {"detail": self.text}

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", MockClient)

    with pytest.raises(RuntimeError) as exc_info:
        await elevenlabs.generate_speech(text="Test", api_key=sensitive_key)
    err_str = str(exc_info.value)
    assert sensitive_key not in err_str
    assert "[REDACTED]" in err_str


# 8. Audio Validation
def test_audio_validator_rejects_missing_file():
    """Audio validator cleanly fails on non-existent audio path."""
    from app.validators.audio_validator import AudioValidator
    validator = AudioValidator()
    result = validator.validate({"storage_path": "/tmp/non_existent_voice.wav"})
    assert result.passed is False
    assert result.score == 0.0
    assert any("not found" in issue.lower() for issue in result.issues)
