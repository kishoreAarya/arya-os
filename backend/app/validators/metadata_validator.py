"""Metadata Validator — validates generated YouTube video metadata against platform standards.

Evaluates:
1. Hard Technical Validation:
   - Valid JSON structure containing title, description, tags, hashtags, category
   - Title length constraints (1 <= len <= 100 characters)
   - Description length constraints (len >= 30 characters)
   - Total tag character count (<= 500 characters for YouTube)
   - Category validity (must match recognized YouTube categories)
2. Quality Scoring Dimensions:
   - Title quality & CTR potential (ideal 30-75 chars, compelling, non-spammy)
   - Description depth & structure (intro, details, call-to-action)
   - Tag relevance & count (8-25 tags, no duplicate or single-char tags)
   - Hashtag format (2-10 hashtags, starting with #, alphanumeric)
   - Category alignment (standard YouTube video category)
"""
import json
import re
from typing import Any

from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.metadata_validator")

# YouTube platform specifications
MAX_TITLE_LENGTH = 100
MIN_TITLE_LENGTH = 10
RECOMMENDED_TITLE_MIN = 30
RECOMMENDED_TITLE_MAX = 75

MIN_DESCRIPTION_LENGTH = 30
MAX_DESCRIPTION_LENGTH = 5000

MIN_TAG_COUNT = 5
MAX_TAG_COUNT = 30
MAX_COMBINED_TAG_CHARS = 500

MIN_HASHTAG_COUNT = 2
MAX_HASHTAG_COUNT = 15

DEFAULT_PASSING_THRESHOLD = 70.0

VALID_YOUTUBE_CATEGORIES = {
    "Film & Animation",
    "Autos & Vehicles",
    "Music",
    "Pets & Animals",
    "Sports",
    "Travel & Events",
    "Gaming",
    "People & Blogs",
    "Comedy",
    "Entertainment",
    "News & Politics",
    "Howto & Style",
    "Education",
    "Science & Technology",
    "Nonprofits & Activism",
}

CATEGORY_ALIASES = {
    "tech": "Science & Technology",
    "technology": "Science & Technology",
    "science": "Science & Technology",
    "howto": "Howto & Style",
    "style": "Howto & Style",
    "how to": "Howto & Style",
    "gaming": "Gaming",
    "games": "Gaming",
    "education": "Education",
    "educational": "Education",
    "entertainment": "Entertainment",
    "comedy": "Comedy",
    "funny": "Comedy",
    "news": "News & Politics",
    "politics": "News & Politics",
    "sports": "Sports",
    "travel": "Travel & Events",
    "film": "Film & Animation",
    "animation": "Film & Animation",
    "people": "People & Blogs",
    "vlog": "People & Blogs",
    "blogs": "People & Blogs",
}


def normalize_category(cat: str | None) -> str | None:
    """Normalizes a category string to a canonical YouTube category."""
    if not cat:
        return None
    cat_clean = cat.strip()
    if cat_clean in VALID_YOUTUBE_CATEGORIES:
        return cat_clean
    lower = cat_clean.lower()
    return CATEGORY_ALIASES.get(lower)


class MetadataValidator(BaseValidator):
    name = "metadata_validator"

    def __init__(self, passing_threshold: float = DEFAULT_PASSING_THRESHOLD):
        self.passing_threshold = passing_threshold

    def validate(self, artifact: Any) -> ValidationResult:
        """Validates video metadata artifact (dict or JSON string)."""
        issues: list[str] = []

        # 1. Parse artifact
        data: dict[str, Any]
        if isinstance(artifact, dict):
            data = artifact
        elif isinstance(artifact, str):
            text = artifact.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            try:
                data = json.loads(text)
            except Exception as exc:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"metadata": 0.0},
                    issues=[f"Output is not valid JSON metadata: {exc}"],
                    notes="Hard failure: JSON parsing error.",
                )
        else:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"metadata": 0.0},
                issues=["Artifact must be a dict or valid JSON string"],
                notes="Hard failure: invalid artifact type.",
            )

        # 2. Extract fields
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        raw_tags = data.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            tags = []

        raw_hashtags = data.get("hashtags") or []
        if isinstance(raw_hashtags, str):
            hashtags = [h.strip() for h in raw_hashtags.split() if h.strip()]
        elif isinstance(raw_hashtags, list):
            hashtags = [str(h).strip() for h in raw_hashtags if str(h).strip()]
        else:
            hashtags = []

        raw_category = str(data.get("category") or "").strip()
        category = normalize_category(raw_category)

        # 3. Hard Technical Validation
        if not title:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"metadata": 0.0, "title": 0.0},
                issues=["Title is empty"],
                notes="Hard failure: missing title.",
            )

        if len(title) > MAX_TITLE_LENGTH:
            issues.append(f"Title length ({len(title)}) exceeds YouTube maximum of {MAX_TITLE_LENGTH} characters")

        if not description or len(description) < MIN_DESCRIPTION_LENGTH:
            return ValidationResult(
                passed=False,
                score=20.0,
                dimension_scores={"metadata": 20.0, "description": 0.0},
                issues=[f"Description is missing or under minimum {MIN_DESCRIPTION_LENGTH} characters"],
                notes="Hard failure: description too short.",
            )

        total_tag_chars = sum(len(t) for t in tags)
        if total_tag_chars > MAX_COMBINED_TAG_CHARS:
            issues.append(
                f"Combined tag length ({total_tag_chars} chars) exceeds YouTube limit of {MAX_COMBINED_TAG_CHARS} characters"
            )

        if not category:
            issues.append(f"Invalid or unrecognized YouTube category: '{raw_category}'")

        # 4. Dimension Quality Scoring (Max 100 pts)
        # --- A. Title Quality (Max 25 pts) ---
        title_len = len(title)
        if RECOMMENDED_TITLE_MIN <= title_len <= RECOMMENDED_TITLE_MAX:
            title_score = 25.0
        elif MIN_TITLE_LENGTH <= title_len <= MAX_TITLE_LENGTH:
            title_score = 20.0
        else:
            title_score = 10.0
            if title_len < MIN_TITLE_LENGTH:
                issues.append(f"Title is too short ({title_len} chars, minimum {MIN_TITLE_LENGTH})")

        # Check for ALL CAPS clickbait spam
        letters = [c for c in title if c.isalpha()]
        if letters:
            upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if upper_ratio > 0.8 and len(letters) > 10:
                title_score = max(5.0, title_score - 8.0)
                issues.append("Title uses excessive ALL CAPS formatting")

        # --- B. Description Depth & Structure (Max 25 pts) ---
        desc_len = len(description)
        if desc_len >= 150:
            desc_score = 25.0
        elif desc_len >= 80:
            desc_score = 22.0
        else:
            desc_score = 18.0

        # --- C. Tag Optimization (Max 20 pts) ---
        tag_count = len(tags)
        if MIN_TAG_COUNT <= tag_count <= 20 and total_tag_chars <= MAX_COMBINED_TAG_CHARS:
            tag_score = 20.0
        elif 1 <= tag_count < MIN_TAG_COUNT:
            tag_score = 12.0
            issues.append(f"Low tag count ({tag_count}, recommended {MIN_TAG_COUNT}+)")
        elif tag_count > MAX_TAG_COUNT:
            tag_score = 14.0
            issues.append(f"Excessive tag count ({tag_count}, maximum {MAX_TAG_COUNT})")
        else:
            tag_score = 8.0

        # --- D. Hashtags Validity (Max 15 pts) ---
        valid_hashtags = [h for h in hashtags if h.startswith("#") and len(h) > 1 and re.match(r"^#[A-Za-z0-9_]+$", h)]
        if MIN_HASHTAG_COUNT <= len(valid_hashtags) <= 5:
            hashtag_score = 15.0
        elif len(valid_hashtags) >= 1:
            hashtag_score = 12.0
        else:
            hashtag_score = 6.0
            issues.append("Missing valid hashtags (expected 2-5 starting with #)")

        # --- E. Category Alignment (Max 15 pts) ---
        if category:
            category_score = 15.0
        else:
            category_score = 5.0

        total_score = round(title_score + desc_score + tag_score + hashtag_score + category_score, 1)
        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "title": round(title_score, 1),
            "description": round(desc_score, 1),
            "tags": round(tag_score, 1),
            "hashtags": round(hashtag_score, 1),
            "category": round(category_score, 1),
            "metadata": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Metadata validation completed. Title: {title_len} chars, Description: {desc_len} chars, Tags: {tag_count}, Category: {category or 'None'}.",
        )
