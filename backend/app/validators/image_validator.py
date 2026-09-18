"""Image Validator — evaluates generated image assets for technical integrity and visual quality.

Evaluates:
1. Hard Technical Validation:
   - File existence and container readability via Pillow (detects corrupted files)
   - Resolution bounds (width/height > 0 and >= minimums)
   - Blank / solid uniform color detection (low entropy / standard deviation check)
2. Quality Scoring Dimensions:
   - File integrity (valid format, container, color mode)
   - Resolution compliance (meets target HD / 4K / social dimensions)
   - Visual entropy (dynamic range, contrast, pixel variance)
   - Content compliance (vision-model evaluation or aspect-ratio alignment)
"""
import os
from typing import Any, Callable

from PIL import Image, ImageStat

from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.image_validator")

# Configurable defaults
DEFAULT_MIN_WIDTH = 256
DEFAULT_MIN_HEIGHT = 256
DEFAULT_MIN_STDDEV_VARIANCE = 3.0  # stddev threshold below which image is blank/solid
DEFAULT_PASSING_THRESHOLD = 70.0

RECOGNIZED_IMAGE_FORMATS = {"PNG", "JPEG", "JPG", "WEBP"}


class ImageValidator(BaseValidator):
    name = "image_validator"

    def __init__(
        self,
        min_width: int = DEFAULT_MIN_WIDTH,
        min_height: int = DEFAULT_MIN_HEIGHT,
        target_width: int | None = None,
        target_height: int | None = None,
        min_stddev_variance: float = DEFAULT_MIN_STDDEV_VARIANCE,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
        vision_judge_callable: Callable[[str, dict], dict] | None = None,
    ):
        self.min_width = min_width
        self.min_height = min_height
        self.target_width = target_width
        self.target_height = target_height
        self.min_stddev_variance = min_stddev_variance
        self.passing_threshold = passing_threshold
        self.vision_judge_callable = vision_judge_callable

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = (
            artifact.get("storage_path")
            or artifact.get("image_path")
            or artifact.get("path")
        )

        issues: list[str] = []

        # 1. Hard Technical Check: path presence
        if not storage_path:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"image": 0.0},
                issues=["No image file present to validate"],
                notes="Hard failure: missing storage_path in artifact.",
            )

        # 2. Check mock image data (for unit testing without disk)
        mock_data = artifact.get("mock_image_data")
        if mock_data is not None:
            width = int(mock_data.get("width", 1024))
            height = int(mock_data.get("height", 1024))
            format_name = str(mock_data.get("format", "PNG")).upper()
            mode = str(mock_data.get("mode", "RGB"))
            stddev = float(mock_data.get("stddev", 35.0))
            is_corrupt = bool(mock_data.get("is_corrupt", False))
            if is_corrupt:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"image": 0.0},
                    issues=["Corrupted image file: failed to decode image"],
                    notes="Hard failure: mock corruption.",
                )
        else:
            inspect_path = str(storage_path)
            tmp_download_path: str | None = None
            if inspect_path.startswith(("http://", "https://")):
                import tempfile
                import urllib.request
                try:
                    fd, tmp_download_path = tempfile.mkstemp(suffix=".img", prefix="arya_val_img_")
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
                        dimension_scores={"image": 0.0},
                        issues=[f"Failed to retrieve remote image: {exc}"],
                        notes=f"Hard failure: remote image download failed: {exc}",
                    )

            # Check file existence
            if not os.path.exists(inspect_path):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"image": 0.0},
                    issues=[f"Image file not found at path: {storage_path}"],
                    notes="Hard failure: file does not exist on disk.",
                )

            # Pillow Inspection
            try:
                with Image.open(inspect_path) as img:
                    img.verify()
                with Image.open(inspect_path) as img:
                    width, height = img.size
                    format_name = (img.format or "UNKNOWN").upper()
                    mode = img.mode
                    gray = img.convert("L")
                    stat = ImageStat.Stat(gray)
                    stddev = stat.stddev[0] if stat.stddev else 0.0
            except Exception as exc:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"image": 0.0},
                    issues=[f"Corrupted or unreadable image file: {exc}"],
                    notes="Hard failure: Pillow failed to decode image file.",
                )
            finally:
                if tmp_download_path and os.path.exists(tmp_download_path):
                    try:
                        os.remove(tmp_download_path)
                    except OSError:
                        pass

        # 3. Hard Technical Checks
        if width <= 0 or height <= 0:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"image": 0.0, "resolution": 0.0},
                issues=["Invalid image dimensions (zero or negative)"],
                notes="Hard failure: invalid dimensions.",
            )

        if stddev < self.min_stddev_variance:
            return ValidationResult(
                passed=False,
                score=15.0,
                dimension_scores={"image": 15.0, "visual_entropy": 0.0},
                issues=["Image is completely blank or uniform solid color"],
                notes=f"Hard failure: standard deviation {stddev:.2f} is below minimum variance {self.min_stddev_variance}.",
            )

        # 4. Dimension Quality Scoring
        # --- A. File Integrity (Max 25 pts) ---
        if format_name in RECOGNIZED_IMAGE_FORMATS and mode in {"RGB", "RGBA"}:
            integrity_score = 25.0
        elif format_name in RECOGNIZED_IMAGE_FORMATS:
            integrity_score = 20.0
        else:
            integrity_score = 15.0
            issues.append(f"Uncommon image format: {format_name}")

        # --- B. Resolution Compliance (Max 30 pts) ---
        if width < self.min_width or height < self.min_height:
            res_score = 10.0
            issues.append(f"Resolution {width}x{height} is below minimum {self.min_width}x{self.min_height}")
        elif (width >= 1024 and height >= 1024) or (width >= 1920 and height >= 1080) or (width >= 1080 and height >= 1920):
            res_score = 30.0  # High-res output
        elif (width >= 720 and height >= 720) or (width >= 1280 and height >= 720) or (width >= 720 and height >= 1280):
            res_score = 25.0  # 720p HD output
        else:
            res_score = 20.0  # Standard acceptable resolution

        if self.target_width and self.target_height:
            if width != self.target_width or height != self.target_height:
                res_score = max(5.0, res_score - 5.0)
                issues.append(f"Resolution {width}x{height} does not match target {self.target_width}x{self.target_height}")

        # --- C. Visual Entropy & Contrast (Max 20 pts) ---
        if stddev >= 20.0:
            entropy_score = 20.0
        elif stddev >= 10.0:
            entropy_score = 16.0
        else:
            entropy_score = 10.0
            issues.append("Image exhibits low contrast or low visual detail")

        # --- D. Content Compliance & Vision Judge (Max 25 pts) ---
        content_score = 22.0
        if self.vision_judge_callable is not None:
            try:
                v_res = self.vision_judge_callable(str(storage_path), artifact)
                content_score = float(v_res.get("score", 22.0))
                v_issues = v_res.get("issues", [])
                if v_issues:
                    issues.extend(v_issues)
            except Exception as exc:
                logger.warning("vision_judge_evaluation_failed", error=str(exc))
                content_score = 20.0
        else:
            # Check aspect ratio compliance if requested
            target_ar = artifact.get("aspect_ratio")
            if target_ar:
                ratio = width / height
                if target_ar == "16:9" and abs(ratio - 16 / 9) > 0.05:
                    content_score -= 5.0
                    issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected 16:9")
                elif target_ar == "9:16" and abs(ratio - 9 / 16) > 0.05:
                    content_score -= 5.0
                    issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected 9:16")
                elif target_ar == "1:1" and abs(ratio - 1.0) > 0.05:
                    content_score -= 5.0
                    issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected 1:1")

        content_score = max(0.0, min(25.0, content_score))

        total_score = round(
            integrity_score + res_score + entropy_score + content_score, 1
        )
        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "file_integrity": round(integrity_score, 1),
            "resolution": round(res_score, 1),
            "visual_entropy": round(entropy_score, 1),
            "content_compliance": round(content_score, 1),
            "image": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Image validation completed. Dimensions: {width}x{height}, Stddev: {stddev:.1f}, Format: {format_name}.",
        )

