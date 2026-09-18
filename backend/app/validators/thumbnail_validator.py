"""Thumbnail Validator — evaluates YouTube thumbnail assets against platform standards.

Evaluates:
1. Hard Technical Validation:
   - File existence and readability
   - YouTube thumbnail maximum size limit (2MB)
   - Minimum resolution (640x360)
2. Quality Scoring Dimensions:
   - Resolution compliance (recommended 1280x720)
   - Aspect ratio (strictly 16:9 YouTube standard)
   - Contrast and visual entropy (legibility and CTR potential)
   - File integrity (valid format PNG, JPEG, WEBP)
"""
import os
from typing import Any

from PIL import Image, ImageStat

from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.thumbnail_validator")

YOUTUBE_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
RECOMMENDED_WIDTH = 1280
RECOMMENDED_HEIGHT = 720
MIN_THUMBNAIL_WIDTH = 640
MIN_THUMBNAIL_HEIGHT = 360
DEFAULT_PASSING_THRESHOLD = 70.0


class ThumbnailValidator(BaseValidator):
    name = "thumbnail_validator"

    def __init__(
        self,
        min_width: int = MIN_THUMBNAIL_WIDTH,
        min_height: int = MIN_THUMBNAIL_HEIGHT,
        max_file_size_bytes: int = YOUTUBE_MAX_FILE_SIZE_BYTES,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
    ):
        self.min_width = min_width
        self.min_height = min_height
        self.max_file_size_bytes = max_file_size_bytes
        self.passing_threshold = passing_threshold

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = (
            artifact.get("storage_path")
            or artifact.get("thumbnail_path")
            or artifact.get("path")
        )

        issues: list[str] = []

        if not storage_path:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"thumbnail": 0.0},
                issues=["No thumbnail file present"],
                notes="Hard failure: missing storage_path in artifact.",
            )

        # Unit test mock support
        mock_data = artifact.get("mock_image_data")
        if mock_data is not None:
            width = int(mock_data.get("width", RECOMMENDED_WIDTH))
            height = int(mock_data.get("height", RECOMMENDED_HEIGHT))
            format_name = str(mock_data.get("format", "JPEG")).upper()
            file_size = int(mock_data.get("file_size", 500_000))
            stddev = float(mock_data.get("stddev", 35.0))
        else:
            inspect_path = str(storage_path)
            tmp_download_path: str | None = None
            if inspect_path.startswith(("http://", "https://")):
                import tempfile
                import urllib.request
                try:
                    fd, tmp_download_path = tempfile.mkstemp(suffix=".img", prefix="arya_val_thumb_")
                    os.close(fd)
                    req = urllib.request.Request(inspect_path, headers={"User-Agent": "AryaOS/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_download_path, "wb") as f:
                        f.write(resp.read())
                    inspect_path = tmp_download_path
                except Exception as exc:
                    if tmp_download_path and os.path.exists(tmp_download_path):
                        try:
                            os.remove(tmp_download_path)
                        except OSError:
                            pass
                    return ValidationResult(
                        passed=False,
                        score=0.0,
                        dimension_scores={"thumbnail": 0.0},
                        issues=[f"Failed to retrieve remote thumbnail: {exc}"],
                        notes=f"Hard failure: remote thumbnail download failed: {exc}",
                    )

            if not os.path.exists(inspect_path):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"thumbnail": 0.0},
                    issues=[f"Thumbnail file not found at path: {storage_path}"],
                    notes="Hard failure: file does not exist on disk.",
                )

            file_size = os.path.getsize(inspect_path)
            try:
                with Image.open(inspect_path) as img:
                    img.verify()
                with Image.open(inspect_path) as img:
                    width, height = img.size
                    format_name = (img.format or "UNKNOWN").upper()
                    gray = img.convert("L")
                    stat = ImageStat.Stat(gray)
                    stddev = stat.stddev[0] if stat.stddev else 0.0
            except Exception as exc:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"thumbnail": 0.0},
                    issues=[f"Corrupted thumbnail image file: {exc}"],
                    notes="Hard failure: Pillow decode failed.",
                )
            finally:
                if tmp_download_path and os.path.exists(tmp_download_path):
                    try:
                        os.remove(tmp_download_path)
                    except OSError:
                        pass

        # File size check
        if file_size > self.max_file_size_bytes:
            issues.append(
                f"File size ({file_size / (1024*1024):.2f}MB) exceeds YouTube maximum (2MB)"
            )

        # Dimensions check
        target_ar = artifact.get("aspect_ratio")
        ratio = width / height if height > 0 else 0
        if target_ar == "9:16" or (target_ar is None and ratio < 1.0):
            target_ratio = 9 / 16
            min_w, min_h = 360, 640
            rec_w, rec_h = 1080, 1920
            expected_name = "9:16"
        else:
            target_ratio = 16 / 9
            min_w, min_h = self.min_width, self.min_height
            rec_w, rec_h = RECOMMENDED_WIDTH, RECOMMENDED_HEIGHT
            expected_name = "16:9"

        if width < min_w or height < min_h:
            issues.append(
                f"Resolution {width}x{height} is below YouTube minimum ({min_w}x{min_h})"
            )

        # Aspect ratio check
        ar_diff = abs(ratio - target_ratio)
        if ar_diff > 0.05:
            issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected {expected_name} ({target_ratio:.2f})")

        # Blank check
        if stddev < 3.0:
            return ValidationResult(
                passed=False,
                score=10.0,
                dimension_scores={"thumbnail": 10.0},
                issues=["Thumbnail appears completely blank or uniform solid color"],
                notes="Hard failure: blank thumbnail.",
            )

        # Scoring
        # A. Resolution Compliance (Max 30 pts)
        if width >= rec_w and height >= rec_h:
            res_score = 30.0
        elif width >= min_w and height >= min_h:
            res_score = 22.0
        else:
            res_score = 10.0


        # B. Aspect Ratio (Max 25 pts)
        if ar_diff <= 0.02:
            ar_score = 25.0
        elif ar_diff <= 0.05:
            ar_score = 20.0
        else:
            ar_score = 10.0

        # C. Visual Contrast & Entropy (Max 25 pts)
        if stddev >= 25.0:
            contrast_score = 25.0
        elif stddev >= 15.0:
            contrast_score = 20.0
        else:
            contrast_score = 12.0

        # D. File Size & Format (Max 20 pts)
        if file_size <= self.max_file_size_bytes and format_name in {"JPEG", "JPG", "PNG", "WEBP"}:
            size_score = 20.0
        else:
            size_score = 10.0

        total_score = round(res_score + ar_score + contrast_score + size_score, 1)
        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "resolution": round(res_score, 1),
            "aspect_ratio": round(ar_score, 1),
            "contrast": round(contrast_score, 1),
            "file_specs": round(size_score, 1),
            "thumbnail": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Thumbnail validation completed. Dimensions: {width}x{height}, Aspect: {ratio:.2f}, Size: {file_size / 1024:.1f}KB.",
        )

