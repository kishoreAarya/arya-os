"""Unit tests for StoryValidator.

Tests:
1. Hard technical validation (empty content, below min length)
2. Deterministic linguistic heuristic evaluation (hook, structure, coherence, length, content)
3. Word repetition penalties
4. Custom threshold configuration
5. LLM-as-a-judge injection and parsing
6. Mocked external OpenRouter LLM call
7. Graceful fallback on LLM network failure
"""
from unittest.mock import MagicMock, patch

import pytest
from app.validators.script_story_validator import StoryValidator


def test_empty_script_fails_hard():
    validator = StoryValidator()
    result = validator.validate({"content": ""})
    assert result.passed is False
    assert result.score == 0.0
    assert "Script content is empty" in result.issues


def test_short_script_fails_length_threshold():
    validator = StoryValidator(min_length_chars=50)
    result = validator.validate({"content": "Short intro."})
    assert result.passed is False
    assert result.score == 20.0
    assert "too short to evaluate" in result.issues[0]


def test_valid_rich_script_passes_heuristic():
    validator = StoryValidator()
    script = (
        "Why does everybody get pasta wrong? The secret isn't more salt—it's boiling water timing!\n\n"
        "In fact, Italian chefs have known this rule for generations. When you drop fresh noodles "
        "into gently simmering broth instead of violent bubbles, the starch forms a silky glaze. "
        "For example, traditional carbonara relies entirely on this emulsion technique.\n\n"
        "What do you think about this cooking secret? Leave a comment below and subscribe for part 2!"
    )
    result = validator.validate({"content": script, "topic": "pasta"})
    assert result.passed is True
    assert result.score >= 70.0
    assert len(result.issues) == 0
    assert "hook" in result.dimension_scores
    assert "structure" in result.dimension_scores
    assert "coherence" in result.dimension_scores
    assert "length" in result.dimension_scores
    assert "content" in result.dimension_scores


def test_excessive_word_repetition_penalized():
    validator = StoryValidator()
    # Content >= 50 chars but full of repeated word
    script = "pizza " * 30
    result = validator.validate({"content": script})
    assert any("repetition" in issue.lower() for issue in result.issues)
    assert result.dimension_scores["coherence"] < 15.0


def test_custom_passing_threshold_honored():
    # Set impossible threshold of 99.0
    strict_validator = StoryValidator(passing_threshold=99.0)
    script = "Imagine a world where coffee is free. However, that changes tomorrow! Subscribe now."
    result = strict_validator.validate({"content": script})
    assert result.passed is False
    assert result.score < 99.0


def test_llm_judge_callable_success():
    def mock_judge(content, artifact):
        return {
            "hook": 19.0,
            "structure": 24.0,
            "coherence": 23.0,
            "length": 14.0,
            "content": 14.0,
            "issues": [],
            "notes": "Excellent hook and strong structure.",
        }

    validator = StoryValidator(judge_callable=mock_judge)
    result = validator.validate({"content": "A sufficiently long script for testing judge callable injection."})
    assert result.passed is True
    assert result.score == 94.0
    assert result.dimension_scores["hook"] == 19.0
    assert result.notes == "Excellent hook and strong structure."


def test_llm_judge_callable_failure_rejection():
    def mock_judge_reject(content, artifact):
        return {
            "hook": 8.0,
            "structure": 10.0,
            "coherence": 9.0,
            "length": 5.0,
            "content": 6.0,
            "issues": ["Weak hook", "Incoherent structure"],
            "notes": "Low quality draft.",
        }

    validator = StoryValidator(judge_callable=mock_judge_reject)
    result = validator.validate({"content": "A sufficiently long script for testing judge callable rejection."})
    assert result.passed is False
    assert result.score == 38.0
    assert "Weak hook" in result.issues


def test_llm_judge_mocked_network_call():
    validator = StoryValidator(use_llm=True)
    fake_json_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"hook": 18, "structure": 22, "coherence": 21, "length": 14, "content": 13, "issues": [], "notes": "Solid script"}'
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_json_payload

    with patch("app.core.config.get_settings") as mock_settings, \
         patch("httpx.Client.post", return_value=mock_resp):
        mock_settings.return_value.openrouter_api_key = "sk-fake-key"
        result = validator.validate({"content": "Why is the ocean blue? In fact, water absorbs red light. Subscribe!"})

    assert result.passed is True
    assert result.score == 88.0
    assert result.notes == "Solid script"


def test_llm_judge_fallback_on_network_error():
    validator = StoryValidator(use_llm=True)

    with patch("app.core.config.get_settings") as mock_settings, \
         patch("httpx.Client.post", side_effect=RuntimeError("Connection refused")):
        mock_settings.return_value.openrouter_api_key = "sk-fake-key"
        # Should gracefully fall back to deterministic heuristic without crashing
        result = validator.validate({
            "content": "Why is the sky blue? Science has an incredible answer. In fact, Rayleigh scattering explains it. Subscribe!"
        })

    assert result.passed is True
    assert result.score >= 70.0
    assert "Deterministic evaluation" in result.notes
