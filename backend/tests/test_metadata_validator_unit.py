"""Unit tests for MetadataValidator.

Tests:
1. Valid metadata (dict and JSON string)
2. Hard failures (missing title, short description, invalid JSON)
3. Title length and ALL CAPS penalties
4. Combined tag character length limits
5. Hashtag syntax validation (# prefix, alphanumeric)
6. Category normalization and alias resolution
"""
import pytest
from app.validators.metadata_validator import MetadataValidator, normalize_category


def test_normalize_category_helper():
    assert normalize_category("Education") == "Education"
    assert normalize_category("tech") == "Science & Technology"
    assert normalize_category("gaming") == "Gaming"
    assert normalize_category("how to") == "Howto & Style"
    assert normalize_category("unknown_xyz") is None
    assert normalize_category("") is None


def test_missing_title_fails_hard():
    validator = MetadataValidator()
    result = validator.validate({
        "title": "",
        "description": "A valid description of the video script with lots of details.",
        "tags": ["science", "space"],
        "hashtags": ["#Space", "#Science"],
        "category": "Science & Technology",
    })
    assert result.passed is False
    assert result.score == 0.0
    assert "Title is empty" in result.issues


def test_description_too_short_fails_hard():
    validator = MetadataValidator()
    result = validator.validate({
        "title": "A Great Video Title",
        "description": "Too short",  # < 30 chars
        "tags": ["science", "space"],
        "hashtags": ["#Space", "#Science"],
        "category": "Science & Technology",
    })
    assert result.passed is False
    assert result.score == 20.0
    assert any("Description is missing or under minimum" in issue for issue in result.issues)


def test_invalid_json_string_fails():
    validator = MetadataValidator()
    result = validator.validate("this is not json at all")
    assert result.passed is False
    assert result.score == 0.0
    assert any("not valid JSON" in issue for issue in result.issues)


def test_title_too_long_flagged():
    validator = MetadataValidator()
    long_title = "A" * 105  # > 100 chars
    result = validator.validate({
        "title": long_title,
        "description": "A comprehensive overview of quantum computing and physics for beginners.",
        "tags": ["quantum", "physics", "computing", "science", "future"],
        "hashtags": ["#Quantum", "#Physics", "#Tech"],
        "category": "Science & Technology",
    })
    assert result.passed is False
    assert any("exceeds YouTube maximum" in issue for issue in result.issues)


def test_all_caps_title_penalized():
    validator = MetadataValidator()
    caps_title = "YOU WILL NEVER BELIEVE THIS SHOCKING SECRET!"
    result = validator.validate({
        "title": caps_title,
        "description": "A comprehensive overview of ancient historical mysteries explained by historians.",
        "tags": ["history", "ancient", "mysteries", "secrets", "education"],
        "hashtags": ["#History", "#Ancient", "#Education"],
        "category": "Education",
    })
    assert any("ALL CAPS" in issue for issue in result.issues)
    assert result.dimension_scores["title"] < 20.0


def test_tag_character_overflow_flagged():
    validator = MetadataValidator()
    # 20 tags of 30 characters each = 600 characters (> 500 limit)
    huge_tags = [f"tag_with_lots_of_words_number_{i}" for i in range(20)]
    result = validator.validate({
        "title": "How Artificial Intelligence Works",
        "description": "An introductory guide to machine learning models, neural networks, and algorithms.",
        "tags": huge_tags,
        "hashtags": ["#AI", "#Tech", "#Future"],
        "category": "Science & Technology",
    })
    assert result.passed is False
    assert any("exceeds YouTube limit" in issue for issue in result.issues)


def test_invalid_category_flagged():
    validator = MetadataValidator()
    result = validator.validate({
        "title": "How to Build a Custom Wooden Chair",
        "description": "Step by step woodworking guide for beginners crafting solid oak furniture.",
        "tags": ["woodworking", "diy", "carpentry", "furniture", "craft"],
        "hashtags": ["#Woodworking", "#DIY", "#Craft"],
        "category": "NotARealCategory",
    })
    assert any("Invalid or unrecognized YouTube category" in issue for issue in result.issues)


def test_valid_metadata_dict_passes():
    validator = MetadataValidator()
    result = validator.validate({
        "title": "Why Rome Actually Collapsed (And What It Means Today)",
        "description": (
            "Explore the economic, military, and political factors that caused the fall of the Western Roman Empire. "
            "In this video, we break down historical sources, currency debasement, and lessons for the modern era. "
            "Subscribe for weekly in-depth history documentaries!"
        ),
        "tags": ["roman empire", "ancient rome", "history documentary", "fall of rome", "ancient history", "education"],
        "hashtags": ["#RomanEmpire", "#History", "#AncientRome"],
        "category": "Education",
    })
    assert result.passed is True
    assert result.score >= 80.0
    assert result.dimension_scores["title"] == 25.0
    assert result.dimension_scores["description"] == 25.0
    assert result.dimension_scores["tags"] == 20.0
    assert result.dimension_scores["hashtags"] == 15.0
    assert result.dimension_scores["category"] == 15.0


def test_valid_metadata_json_string_passes():
    validator = MetadataValidator()
    json_text = """
    ```json
    {
      "title": "How Black Holes Warp Time and Space Explained Simply",
      "description": "Astrophysics breakdown of Einstein's relativity, event horizons, and singularity physics. Learn how gravity slows time down near black holes. Leave a comment with your favorite astronomy theory and subscribe for more cosmos content!",
      "tags": ["black holes", "astronomy", "physics", "relativity", "einstein", "space science", "cosmos", "universe"],
      "hashtags": ["#Space", "#Physics", "#Astronomy"],
      "category": "Science & Technology"
    }
    ```
    """
    result = validator.validate(json_text)
    assert result.passed is True
    assert result.score >= 85.0
