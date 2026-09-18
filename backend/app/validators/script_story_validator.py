"""Story Validator — judges Script quality independently of the Script Agent.

Evaluates:
1. Hard Technical Validation:
   - Presence of script text (rejects empty)
   - Minimum character length threshold (configurable, default 50 chars)
2. Subjective Quality Scoring:
   - Hook quality (opening impact, curiosity gap, question/imperative opening)
   - Narrative structure (flow, progression, scene cues, CTA)
   - Coherence & readability (lexical diversity, sentence pacing, repetition penalty)
   - Length compliance (word count within target bounds)
   - Content & theme relevance (topic/keyword presence)
3. LLM-as-a-Judge:
   - Can invoke an LLM judge for deep semantic evaluation when configured or injected.
   - Falls back deterministically to linguistic heuristics when offline or in tests.
"""
from collections import Counter
import json
import re
from typing import Any, Callable

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.story_validator")

# Configurable defaults
DEFAULT_MIN_LENGTH_CHARS = 50
DEFAULT_PASSING_SCORE_THRESHOLD = 70.0
DEFAULT_MIN_WORDS = 20
DEFAULT_MAX_WORDS = 2000

HOOK_KEYWORDS = {
    "why", "secret", "imagine", "what if", "stop", "never", "ever",
    "nobody", "truth", "shocking", "revealed", "discovered", "warning",
    "mistake", "actually", "hidden", "how to", "fastest", "easiest"
}

TRANSITION_WORDS = {
    "however", "therefore", "in fact", "for example", "furthermore",
    "moreover", "meanwhile", "next", "finally", "because", "instead",
    "as a result", "consequently", "specifically", "suddenly"
}

CTA_KEYWORDS = {
    "subscribe", "follow", "comment", "like", "share", "watch next",
    "let me know", "what do you think", "leave a comment", "link in",
    "save this", "part 2", "click"
}

RESOLUTION_KEYWORDS = {
    "now", "remember", "remains", "still", "alone", "too late", "never",
    "forever", "darkness", "silence", "finally", "vanished", "whispers",
    "watching", "waiting", "until", "no one", "listen", "look", "beneath",
    "left", "gone", "behind", "empty", "always", "cold", "truth", "shadow"
}


class StoryValidator(BaseValidator):
    name = "story_validator"

    def __init__(
        self,
        min_length_chars: int = DEFAULT_MIN_LENGTH_CHARS,
        passing_threshold: float = DEFAULT_PASSING_SCORE_THRESHOLD,
        min_words: int = DEFAULT_MIN_WORDS,
        max_words: int = DEFAULT_MAX_WORDS,
        judge_callable: Callable[[str, dict], dict] | None = None,
        model: str = "openai/gpt-4o-mini",
        use_llm: bool = False,
    ):
        self.min_length_chars = min_length_chars
        self.passing_threshold = passing_threshold
        self.min_words = min_words
        self.max_words = max_words
        self.judge_callable = judge_callable
        self.model = model
        self.use_llm = use_llm

    def validate(self, artifact: Any) -> ValidationResult:
        """Validates a script artifact (dict or string).

        Returns a structured ValidationResult with:
        - passed (bool)
        - score (0-100 float)
        - dimension_scores (breakdown across hook, structure, coherence, length, content)
        - issues (list of actionable issues if rejected)
        - notes (summary of evaluation)
        """
        # 1. Hard Technical Validation
        if isinstance(artifact, str):
            content = artifact.strip()
            artifact_dict: dict[str, Any] = {"content": content}
        elif isinstance(artifact, dict):
            content = (
                artifact.get("content")
                or artifact.get("script")
                or artifact.get("text")
                or ""
            ).strip()
            artifact_dict = artifact
        else:
            content = ""
            artifact_dict = {}

        if not content:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"story": 0.0, "hook": 0.0, "structure": 0.0, "coherence": 0.0},
                issues=["Script content is empty"],
                notes="Hard technical validation failed: missing script content.",
            )

        if len(content) < self.min_length_chars:
            return ValidationResult(
                passed=False,
                score=20.0,
                dimension_scores={"story": 20.0, "length": 20.0},
                issues=["Script content too short to evaluate"],
                notes=f"Hard technical validation failed: length {len(content)} is below minimum {self.min_length_chars}.",
            )

        # 2. LLM-as-a-Judge Evaluation (if injected or configured)
        if self.judge_callable is not None:
            try:
                judge_result = self.judge_callable(content, artifact_dict)
                return self._parse_judge_response(judge_result)
            except Exception as exc:
                logger.warning("story_validator_custom_judge_failed", error=str(exc))

        if self.use_llm:
            llm_result = self._call_llm_judge(content, artifact_dict)
            if llm_result is not None:
                return llm_result

        # 3. Deterministic Linguistic Heuristic (fallback & standalone mode)
        return self._evaluate_heuristic(content, artifact_dict)

    def _evaluate_heuristic(self, content: str, artifact: dict) -> ValidationResult:
        """Deterministic structural and linguistic quality evaluator."""
        words = re.findall(r"\b\w+\b", content.lower())
        total_words = len(words)
        sentences = [s.strip() for s in re.split(r"[.!?]+", content) if s.strip()]
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        issues: list[str] = []

        # --- A. Hook Quality (Max 20 pts) ---
        hook_score = 15.0  # Baseline hook score
        first_sentence = sentences[0].lower() if sentences else ""
        if "?" in content[:150]:
            hook_score += 3.0
        if any(kw in first_sentence for kw in HOOK_KEYWORDS):
            hook_score += 2.0
        hook_score = min(20.0, hook_score)

        # --- B. Narrative Structure (Max 25 pts) ---
        structure_score = 18.0  # Baseline structure score
        if len(paragraphs) >= 2 or len(sentences) >= 4:
            structure_score += 3.0
        if any(tw in content.lower() for tw in TRANSITION_WORDS):
            structure_score += 2.0
        last_sentence = sentences[-1].lower() if sentences else ""
        if (
            any(cta in content.lower() for cta in CTA_KEYWORDS)
            or any(rw in last_sentence for rw in RESOLUTION_KEYWORDS)
            or len(sentences) >= 5
        ):
            structure_score += 2.0
        structure_score = min(25.0, structure_score)

        # --- C. Coherence & Readability (Max 25 pts) ---
        coherence_score = 18.0  # Baseline coherence score
        if total_words > 0:
            unique_ratio = len(set(words)) / total_words
            # Excessive repetition penalty
            word_counts = Counter(words)
            top_word_freq = word_counts.most_common(1)[0][1] / total_words if words else 0
            if top_word_freq > 0.4 and total_words > 10:
                coherence_score = max(0.0, coherence_score - 15.0)
                hook_score = max(5.0, hook_score - 10.0)
                structure_score = max(5.0, structure_score - 10.0)
                issues.append("Excessive word repetition detected")
            elif unique_ratio > 0.45:
                coherence_score += 4.0
        if sentences:
            avg_words_per_sentence = total_words / len(sentences)
            if 6 <= avg_words_per_sentence <= 30:
                coherence_score += 3.0
        coherence_score = max(0.0, min(25.0, coherence_score))

        # --- D. Length Compliance (Max 15 pts) ---
        length_score = 12.0
        if self.min_words <= total_words <= self.max_words:
            length_score = 15.0
        elif total_words < self.min_words:
            length_score = max(5.0, 15.0 * (total_words / self.min_words))
        else:
            length_score = 10.0
        length_score = min(15.0, length_score)

        # --- E. Content / Topic Compliance (Max 15 pts) ---
        content_score = 12.0
        topic = artifact.get("topic")
        required_keywords = artifact.get("required_keywords") or []
        if isinstance(required_keywords, str):
            required_keywords = [required_keywords]

        if topic and topic.lower() in content.lower():
            content_score += 3.0
        elif required_keywords:
            matched = sum(1 for kw in required_keywords if kw.lower() in content.lower())
            if matched == len(required_keywords):
                content_score += 3.0
            elif matched == 0:
                content_score -= 4.0
                issues.append("Required keywords missing from script")
        else:
            content_score = 12.0
        content_score = min(15.0, content_score)

        total_score = round(
            hook_score + structure_score + coherence_score + length_score + content_score, 1
        )
        passed = total_score >= self.passing_threshold

        if not passed:
            if not issues:
                issues.append(
                    f"Script quality score ({total_score}) is below passing threshold ({self.passing_threshold})"
                )
        else:
            # Score passed quality bar — clear subjective non-blocking issue notes
            issues = []

        dimension_scores = {
            "hook": round(hook_score, 1),
            "structure": round(structure_score, 1),
            "coherence": round(coherence_score, 1),
            "length": round(length_score, 1),
            "content": round(content_score, 1),
            "story": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Deterministic evaluation completed. Total score: {total_score}/100.",
        )

    def _call_llm_judge(self, content: str, artifact: dict) -> ValidationResult | None:
        """Executes LLM-as-a-judge evaluation via OpenRouter or OpenAI."""
        settings = get_settings()
        api_key = getattr(settings, "openrouter_api_key", None) or getattr(settings, "openai_api_key", None)
        if not api_key:
            return None

        prompt = (
            "You are an expert video script quality judge. Evaluate the following script across 5 dimensions:\n"
            "1. hook (0-20): Impact and hook quality of first lines\n"
            "2. structure (0-25): Narrative flow, transitions, CTA\n"
            "3. coherence (0-25): Readability, natural speech, no repetitive filler\n"
            "4. length (0-15): Pacing and length suitability\n"
            "5. content (0-15): Depth and clarity\n\n"
            f"Script to evaluate:\n```\n{content}\n```\n\n"
            "Respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "hook": 18,\n'
            '  "structure": 22,\n'
            '  "coherence": 20,\n'
            '  "length": 14,\n'
            '  "content": 13,\n'
            '  "issues": [],\n'
            '  "notes": "Evaluation summary"\n'
            "}"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                raw_data = resp.json()
                content_text = raw_data["choices"][0]["message"]["content"].strip()
                if "```json" in content_text:
                    content_text = content_text.split("```json")[1].split("```")[0].strip()
                elif "```" in content_text:
                    content_text = content_text.split("```")[1].split("```")[0].strip()
                parsed = json.loads(content_text)
                return self._parse_judge_response(parsed)
        except Exception as exc:
            logger.warning("story_validator_llm_judge_call_failed", error=str(exc))

        return None

    def _parse_judge_response(self, judge_data: dict) -> ValidationResult:
        """Normalizes judge dictionary output into ValidationResult."""
        hook = float(judge_data.get("hook", 15.0))
        structure = float(judge_data.get("structure", 18.0))
        coherence = float(judge_data.get("coherence", 18.0))
        length = float(judge_data.get("length", 12.0))
        content = float(judge_data.get("content", 12.0))

        raw_score = judge_data.get("score")
        if raw_score is not None:
            total_score = float(raw_score)
        else:
            total_score = hook + structure + coherence + length + content

        total_score = round(max(0.0, min(100.0, total_score)), 1)
        issues = list(judge_data.get("issues", []))
        notes = judge_data.get("notes") or f"LLM-as-judge evaluation score: {total_score}/100"

        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "hook": round(hook, 1),
            "structure": round(structure, 1),
            "coherence": round(coherence, 1),
            "length": round(length, 1),
            "content": round(content, 1),
            "story": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=notes,
        )

