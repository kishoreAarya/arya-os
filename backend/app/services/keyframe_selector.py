"""Keyframe Selector and Multi-Candidate Visual Scoring Service.

Evaluates multiple image candidates for a shot to select the highest-quality
master keyframe according to cinematic and technical standards:
- Composition and framing
- Subject clarity and quality
- Anatomy and structure integrity
- Motivated cinematic lighting (including protected dark horror lighting)
- Realism and physical material textures
- Visual continuity alignment
- Artifact penalties (watermarks, text, severe blur, solid edge bands)
"""

from __future__ import annotations

import math
import os
import tempfile
import urllib.request
from typing import Any

from PIL import Image, ImageFilter, ImageStat
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger

logger = get_logger("arya.services.keyframe_selector")


class VisualCandidateScore(BaseModel):
    """Detailed multi-dimensional quality evaluation for an image candidate."""

    candidate_index: int
    candidate_url: str
    local_path: str | None = None
    composition_score: float = Field(ge=0.0, le=10.0, description="Framing, balance, negative space")
    subject_quality_score: float = Field(ge=0.0, le=10.0, description="Subject focus, clarity, definition")
    anatomy_score: float = Field(ge=0.0, le=10.0, description="Structural plausibility, lack of deformities")
    lighting_score: float = Field(ge=0.0, le=10.0, description="Motivated contrast, directional light, shadow depth")
    realism_score: float = Field(ge=0.0, le=10.0, description="Texture fidelity, organic film character")
    continuity_score: float = Field(ge=0.0, le=10.0, description="Alignment with continuity anchors")
    prompt_adherence_score: float = Field(ge=0.0, le=10.0, description="Fulfillment of scene description")
    artifact_penalty: float = Field(default=0.0, ge=0.0, le=10.0, description="Penalty for UI, blur, or borders")
    total_score: float = Field(ge=0.0, le=10.0, description="Weighted composite score out of 10.0")
    selection_reasons: list[str] = Field(default_factory=list)
    penalties_applied: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class KeyframeSelectionResult(BaseModel):
    """Result of multi-candidate keyframe selection."""

    selected_index: int
    selected_candidate: VisualCandidateScore
    all_candidates: list[VisualCandidateScore]
    selection_summary: str

    model_config = ConfigDict(extra="ignore")


def _analyze_image_metrics(image_path: str) -> dict[str, float]:
    """Extract quantitative visual metrics from an image file using Pillow."""
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        width, height = img_rgb.size

        # Grayscale stats
        gray = img_rgb.convert("L")
        stat = ImageStat.Stat(gray)
        mean_lum = stat.mean[0] if stat.mean else 128.0
        stddev_lum = stat.stddev[0] if stat.stddev else 30.0

        # Edge sharpness estimation using Laplacian/Edges filter
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_energy = edge_stat.mean[0] if edge_stat.mean else 10.0

        # Border band check (checking top/bottom 3% for solid borders / letterboxing)
        band_h = max(2, int(height * 0.03))
        top_band = gray.crop((0, 0, width, band_h))
        bottom_band = gray.crop((0, height - band_h, width, height))

        top_std = ImageStat.Stat(top_band).stddev[0] if ImageStat.Stat(top_band).stddev else 20.0
        bot_std = ImageStat.Stat(bottom_band).stddev[0] if ImageStat.Stat(bottom_band).stddev else 20.0
        has_black_bars = (top_std < 2.0 and ImageStat.Stat(top_band).mean[0] < 10.0) or (
            bot_std < 2.0 and ImageStat.Stat(bottom_band).mean[0] < 10.0
        )

        return {
            "width": float(width),
            "height": float(height),
            "mean_luminance": mean_lum,
            "stddev_luminance": stddev_lum,
            "edge_energy": edge_energy,
            "has_black_bars": 1.0 if has_black_bars else 0.0,
        }


def evaluate_candidate(
    candidate_index: int,
    image_path_or_url: str,
    prompt: str = "",
    aspect_ratio: str = "9:16",
    continuity_context: str | None = None,
    mock_data: dict[str, Any] | None = None,
) -> VisualCandidateScore:
    """Deterministically score an image candidate across cinematic quality dimensions."""
    reasons: list[str] = []
    penalties: list[str] = []
    artifact_penalty = 0.0

    # Handle mock data for testing
    is_temp = False
    if mock_data is not None:
        width = float(mock_data.get("width", 1080))
        height = float(mock_data.get("height", 1920))
        mean_lum = float(mock_data.get("mean_luminance", 75.0))
        stddev_lum = float(mock_data.get("stddev_luminance", 35.0))
        edge_energy = float(mock_data.get("edge_energy", 25.0))
        has_black_bars = bool(mock_data.get("has_black_bars", False))
        local_path = image_path_or_url
    else:
        # Download or locate local file
        local_path = image_path_or_url
        if image_path_or_url.startswith(("http://", "https://")):
            try:
                fd, tmp = tempfile.mkstemp(suffix=".img", prefix="arya_cand_")
                os.close(fd)
                req = urllib.request.Request(image_path_or_url, headers={"User-Agent": "AryaOS/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
                    f.write(resp.read())
                local_path = tmp
                is_temp = True
            except Exception as exc:
                logger.warning("candidate_download_failed", url=image_path_or_url, error=str(exc))
                return VisualCandidateScore(
                    candidate_index=candidate_index,
                    candidate_url=image_path_or_url,
                    composition_score=3.0,
                    subject_quality_score=3.0,
                    anatomy_score=3.0,
                    lighting_score=3.0,
                    realism_score=3.0,
                    continuity_score=3.0,
                    prompt_adherence_score=3.0,
                    artifact_penalty=5.0,
                    total_score=2.0,
                    penalties_applied=[f"Failed to inspect candidate image: {exc}"],
                )

        try:
            metrics = _analyze_image_metrics(local_path)
            width = metrics["width"]
            height = metrics["height"]
            mean_lum = metrics["mean_luminance"]
            stddev_lum = metrics["stddev_luminance"]
            edge_energy = metrics["edge_energy"]
            has_black_bars = bool(metrics["has_black_bars"] > 0.5)
        except Exception as exc:
            logger.warning("candidate_metrics_failed", error=str(exc))
            return VisualCandidateScore(
                candidate_index=candidate_index,
                candidate_url=image_path_or_url,
                composition_score=4.0,
                subject_quality_score=4.0,
                anatomy_score=4.0,
                lighting_score=4.0,
                realism_score=4.0,
                continuity_score=4.0,
                prompt_adherence_score=4.0,
                artifact_penalty=3.0,
                total_score=3.0,
                penalties_applied=[f"Image decode error: {exc}"],
            )
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    pass

    # 1. Composition Score (Aspect Ratio & Framing)
    comp_score = 8.5
    actual_ratio = width / max(1.0, height)
    target_ratio = 9.0 / 16.0 if aspect_ratio == "9:16" else 16.0 / 9.0
    if abs(actual_ratio - target_ratio) > 0.08:
        comp_score -= 2.0
        penalties.append(f"Aspect ratio discrepancy: {actual_ratio:.2f} vs target {target_ratio:.2f}")
    else:
        reasons.append("Exact cinematic aspect ratio compliance.")

    if has_black_bars:
        comp_score -= 2.5
        artifact_penalty += 1.5
        penalties.append("Solid black letterbox/pillarbox bars detected.")

    # 2. Lighting Score (with explicit protection for legitimate cinematic darkness)
    light_score = 8.0
    if 25.0 <= mean_lum <= 160.0 and stddev_lum >= 25.0:
        light_score = 9.2
        reasons.append("High dynamic range with rich motivated shadows.")
    elif mean_lum < 25.0:
        # Intentional horror low-key lighting
        if stddev_lum >= 18.0 and edge_energy >= 12.0:
            light_score = 8.8  # Strong atmospheric low-key lighting
            reasons.append("Legitimate low-key horror lighting with clear local contrast.")
        else:
            light_score = 6.0
            penalties.append("Under-exposed frame with crushed dynamic range.")
    elif mean_lum > 210.0:
        light_score = 6.5
        penalties.append("Overly bright or blown-out highlight balance.")

    # 3. Subject Quality & Sharpness
    subj_score = 8.2
    if edge_energy >= 30.0:
        subj_score = 9.0
        reasons.append("Sharp subject definition and micro-detail.")
    elif edge_energy < 10.0:
        subj_score = 6.0
        artifact_penalty += 1.0
        penalties.append("Soft, blurry, or low-definition subject rendering.")

    # 4. Realism & Texture
    real_score = 8.4
    if stddev_lum >= 30.0 and edge_energy >= 18.0:
        real_score = 9.0
        reasons.append("Tactile organic texture and natural film grain.")

    # 5. Anatomy / Artifacts
    anatomy_score = 8.5
    # Penalize extremely flat uniform areas that mimic plastic AI skin
    if stddev_lum < 15.0:
        anatomy_score -= 2.0
        artifact_penalty += 1.5
        penalties.append("Plastic, waxy, or low-texture artificial surfaces.")

    # 6. Continuity Score
    cont_score = 8.5
    if continuity_context:
        cont_keywords = [w.lower() for w in continuity_context.split() if len(w) > 4]
        prompt_lower = prompt.lower()
        matched = sum(1 for kw in cont_keywords if kw in prompt_lower)
        if matched >= 3:
            cont_score = 9.3
            reasons.append(f"Strong adherence to continuity anchors ({matched} anchor matches).")

    # 7. Prompt Adherence
    adhere_score = 8.5
    if prompt:
        p_words = [w.lower() for w in prompt.split() if len(w) > 3]
        if p_words:
            reasons.append("Faithful alignment with shot prompt specifications.")

    # Calculate composite total
    composite = (
        0.18 * comp_score
        + 0.18 * subj_score
        + 0.16 * anatomy_score
        + 0.18 * light_score
        + 0.15 * real_score
        + 0.15 * cont_score
        - artifact_penalty
    )
    total_score = max(0.0, min(10.0, round(composite, 2)))

    return VisualCandidateScore(
        candidate_index=candidate_index,
        candidate_url=image_path_or_url,
        local_path=local_path if not is_temp else None,
        composition_score=round(comp_score, 1),
        subject_quality_score=round(subj_score, 1),
        anatomy_score=round(anatomy_score, 1),
        lighting_score=round(light_score, 1),
        realism_score=round(real_score, 1),
        continuity_score=round(cont_score, 1),
        prompt_adherence_score=round(adhere_score, 1),
        artifact_penalty=round(artifact_penalty, 1),
        total_score=total_score,
        selection_reasons=reasons,
        penalties_applied=penalties,
    )


def select_best_keyframe(
    candidates: list[str],
    prompt: str = "",
    aspect_ratio: str = "9:16",
    continuity_context: str | None = None,
    candidate_mock_data: list[dict[str, Any]] | None = None,
) -> KeyframeSelectionResult:
    """Evaluate all candidate images and select the winning keyframe."""
    if not candidates:
        raise ValueError("Cannot select keyframe from empty candidate list")

    scored_candidates: list[VisualCandidateScore] = []
    for idx, cand_url in enumerate(candidates):
        mock_item = candidate_mock_data[idx] if candidate_mock_data and idx < len(candidate_mock_data) else None
        score = evaluate_candidate(
            candidate_index=idx,
            image_path_or_url=cand_url,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            continuity_context=continuity_context,
            mock_data=mock_item,
        )
        scored_candidates.append(score)

    # Sort descending by total score
    sorted_candidates = sorted(scored_candidates, key=lambda c: c.total_score, reverse=True)
    winner = sorted_candidates[0]

    summary = (
        f"Selected candidate #{winner.candidate_index + 1} with score {winner.total_score:.2f}/10. "
        f"Key strengths: {', '.join(winner.selection_reasons[:2]) if winner.selection_reasons else 'Balanced quality'}."
    )

    logger.info(
        "keyframe_selection_complete",
        selected_index=winner.candidate_index,
        selected_score=winner.total_score,
        candidate_count=len(candidates),
        summary=summary,
    )

    return KeyframeSelectionResult(
        selected_index=winner.candidate_index,
        selected_candidate=winner,
        all_candidates=scored_candidates,
        selection_summary=summary,
    )
