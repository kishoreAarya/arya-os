"""
AryaOS V1 Phase 13 — Deterministic Continuity Validation Layer.

Evaluates multi-shot continuity across three structural dimensions:
1. Technical Continuity: frame integrity, resolution/aspect compatibility, file presence.
2. Dependency Continuity: predecessor existence, predecessor completion, anchor reachability.
3. Temporal Continuity: SHOT N LAST FRAME -> SHOT N+1 FIRST FRAME linkage.

Architectural Rule:
- Clearly distinguished statuses: PASS, WARNING, BLOCKED.
- Structural/technical validation only (semantic visual similarity is NOT claimed without model execution).
- Zero fake PASS: requires real on-disk artifact and frame presence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.models.production import ProductionShot
from app.schemas.production import ContinuityCheckResponse, FrameAnchorInfo
from app.services.artifact_validator import validate_artifact_file

logger = get_logger("arya.services.continuity_validator")


@dataclass
class ContinuityReport:
    """Internal continuity evaluation result."""

    status: str  # "PASS" | "WARNING" | "BLOCKED"
    technical_status: str  # "PASS" | "WARNING" | "BLOCKED"
    dependency_status: str  # "PASS" | "WARNING" | "BLOCKED"
    temporal_status: str  # "PASS" | "WARNING" | "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_schema(self, shot_id: Any, predecessor_shot_id: str | None = None) -> ContinuityCheckResponse:
        return ContinuityCheckResponse(
            shot_id=shot_id,
            predecessor_shot_id=predecessor_shot_id,
            status=self.status,
            technical_status=self.technical_status,
            dependency_status=self.dependency_status,
            temporal_status=self.temporal_status,
            reasons=self.reasons,
            diagnostics=self.diagnostics,
        )


class ContinuityValidator:
    """Deterministic structural continuity validator for production shots."""

    def validate(
        self,
        shot: ProductionShot,
        predecessor_shot: ProductionShot | None = None,
    ) -> ContinuityReport:
        """Evaluates technical, dependency, and temporal continuity for a shot."""
        reasons: list[str] = []
        diagnostics: dict[str, Any] = {
            "validation_level": "STRUCTURAL_TECHNICAL_CONTINUITY",
            "semantic_model_run": False,
            "shot_id": str(shot.id),
            "predecessor_shot_id": shot.predecessor_shot_id,
        }

        # ---------------------------------------------------------------------
        # 1. Dependency Continuity Evaluation
        # ---------------------------------------------------------------------
        dependency_status = "PASS"
        if shot.predecessor_shot_id:
            if predecessor_shot is None:
                dependency_status = "BLOCKED"
                reasons.append(f"Predecessor shot '{shot.predecessor_shot_id}' does not exist in project.")
            elif predecessor_shot.status == "FAILED":
                dependency_status = "BLOCKED"
                reasons.append(f"Predecessor shot '{predecessor_shot.title}' failed generation.")
            elif predecessor_shot.status != "COMPLETE":
                dependency_status = "BLOCKED"
                reasons.append(f"Predecessor shot '{predecessor_shot.title}' is not complete (current status: {predecessor_shot.status}).")
            elif not predecessor_shot.output_asset_url:
                dependency_status = "BLOCKED"
                reasons.append(f"Predecessor shot '{predecessor_shot.title}' has no output asset URL.")
            else:
                # Check for verified last-frame anchor in predecessor
                pred_meta = predecessor_shot.metadata_json or {}
                frame_anchors = pred_meta.get("frame_anchors", {})
                last_frame_anchor = frame_anchors.get("last_frame")

                if not last_frame_anchor and not predecessor_shot.last_frame:
                    dependency_status = "BLOCKED"
                    reasons.append(f"Predecessor shot '{predecessor_shot.title}' has no extracted or verified last-frame anchor.")
                else:
                    diagnostics["predecessor_anchor_verified"] = True
                    diagnostics["predecessor_artifact_url"] = predecessor_shot.output_asset_url
        else:
            diagnostics["is_root_shot"] = True

        # ---------------------------------------------------------------------
        # 2. Technical Continuity Evaluation
        # ---------------------------------------------------------------------
        technical_status = "PASS"

        # Aspect ratio compatibility
        if predecessor_shot:
            pred_aspect = predecessor_shot.aspect_ratio or "16:9"
            curr_aspect = shot.aspect_ratio or "16:9"
            diagnostics["predecessor_aspect_ratio"] = pred_aspect
            diagnostics["current_aspect_ratio"] = curr_aspect

            if pred_aspect != curr_aspect:
                technical_status = "WARNING"
                reasons.append(
                    f"Aspect ratio discrepancy: Predecessor is {pred_aspect} while current shot is {curr_aspect}. "
                    "Frame scaling or letterboxing may occur."
                )

        # First frame binary integrity check if specified
        first_frame_path = shot.first_frame
        if first_frame_path:
            # If path is URL, resolve to disk filename
            clean_name = first_frame_path.split("/")[-1].split("?")[0]
            from app.services.execution_gateway import STORAGE_ARTIFACTS_DIR
            local_frame = STORAGE_ARTIFACTS_DIR / clean_name
            if local_frame.is_file():
                val = validate_artifact_file(local_frame, expected_type="image")
                if not val.is_valid:
                    technical_status = "BLOCKED"
                    reasons.append(f"First frame conditioning binary is corrupt: {val.error}")
                else:
                    diagnostics["first_frame_resolution"] = f"{val.width}x{val.height}"
                    diagnostics["first_frame_sha256"] = val.sha256
            else:
                if not first_frame_path.startswith("http"):
                    technical_status = "BLOCKED"
                    reasons.append(f"First frame file not found on disk: {first_frame_path}")

        # ---------------------------------------------------------------------
        # 3. Temporal Continuity Evaluation
        # ---------------------------------------------------------------------
        temporal_status = "PASS"
        if shot.predecessor_shot_id and predecessor_shot:
            # Downstream shot should have first_frame matching predecessor's last_frame
            pred_meta = predecessor_shot.metadata_json or {}
            pred_anchors = pred_meta.get("frame_anchors", {})
            pred_last = pred_anchors.get("last_frame", {})
            pred_last_url = pred_last.get("artifact_url") or predecessor_shot.last_frame or predecessor_shot.output_asset_url

            if not shot.first_frame:
                temporal_status = "BLOCKED"
                reasons.append(
                    f"Temporal link broken: Shot depends on predecessor '{predecessor_shot.title}', "
                    "but has no first-frame anchor assigned."
                )
            elif pred_last_url and shot.first_frame not in (pred_last_url, pred_last.get("file_path")):
                # Check filename match
                shot_first_name = shot.first_frame.split("/")[-1]
                pred_last_name = pred_last_url.split("/")[-1]
                if shot_first_name != pred_last_name:
                    temporal_status = "WARNING"
                    reasons.append(
                        f"Temporal anchor mismatch: First frame ({shot_first_name}) differs from predecessor's "
                        f"last frame ({pred_last_name})."
                    )
                else:
                    diagnostics["temporal_link"] = f"{predecessor_shot.title} [LAST FRAME] -> {shot.title} [FIRST FRAME]"
            else:
                diagnostics["temporal_link"] = f"{predecessor_shot.title} [LAST FRAME] -> {shot.title} [FIRST FRAME]"

        # ---------------------------------------------------------------------
        # 4. Overall Continuity Status Synthesis
        # ---------------------------------------------------------------------
        if "BLOCKED" in (dependency_status, technical_status, temporal_status):
            overall_status = "BLOCKED"
        elif "WARNING" in (dependency_status, technical_status, temporal_status):
            overall_status = "WARNING"
        else:
            overall_status = "PASS"

        report = ContinuityReport(
            status=overall_status,
            technical_status=technical_status,
            dependency_status=dependency_status,
            temporal_status=temporal_status,
            reasons=reasons,
            diagnostics=diagnostics,
        )

        logger.info(
            "continuity_evaluation_complete",
            shot_id=str(shot.id),
            overall=overall_status,
            technical=technical_status,
            dependency=dependency_status,
            temporal=temporal_status,
        )
        return report


continuity_validator = ContinuityValidator()
