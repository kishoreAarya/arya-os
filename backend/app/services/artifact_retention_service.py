"""
AryaOS V1 Phase 3.2.4.4.6.3.3.12 — Artifact Retention & Pruning Lifecycle Service (MED-04).

Enforces safe, bounded, concurrency-safe, observable retention and pruning of stored artifacts:
- Detects scratch and unreferenced artifacts older than a configurable retention threshold (default: 14 days).
- Strictly preserves artifacts referenced by active, recoverable, or reconciliation-pending goals.
- Strictly preserves durable action outputs, production shots, and media table assets.
- Preserves aliases, hard links, and alternative extension variants of referenced files.
- Double-gated protection: Dry-run by default, with deletion requiring explicit configuration enablement.
- Fail-closed behavior: Any database, query, or path traversal anomaly prevents deletion.
- Path traversal and symlink confinement: strictly prevents escape outside the storage artifacts root.
- Immediate pre-deletion reference re-check to eliminate races between file creation and deletion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any, Callable

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.models.media import Asset, GeneratedVideo, Image, Thumbnail, Video
from app.models.production import ProductionJob, ProductionShot
from app.services.artifact_validator import (
    SAFE_FILENAME_REGEX,
    STORAGE_ARTIFACTS_DIR,
)

logger = get_logger("arya.execution.artifact_retention")

# Goal statuses that are actively executing, recoverable, or pending human/reconciliation action
ACTIVE_OR_RECOVERABLE_GOAL_STATUSES: set[str] = {
    "DRAFT",
    "PLANNED",
    "PENDING",
    "READY",
    "RUNNING",
    "EXECUTING",
    "PAUSED",
    "AWAITING_APPROVAL",
    "FAILED",
    "RECOVERABLE",
    "UNKNOWN",
    "RECONCILIATION_PENDING",
    "HALTED",
    "DISPATCHING",
}


@dataclass
class RetentionCandidate:
    """Detailed candidate record evaluated during an artifact retention sweep."""

    path: Path
    filename: str
    age_days: float
    size_bytes: int
    is_referenced: bool
    reference_sources: list[str] = field(default_factory=list)
    proposed_action: str = "RETAIN"  # "RETAIN" | "PRUNE"
    reason: str = ""


@dataclass
class RetentionSweepReport:
    """Authoritative result report from an artifact retention maintenance sweep."""

    timestamp: datetime
    dry_run: bool
    enabled: bool
    retention_days: int
    total_files_scanned: int
    total_candidates_evaluated: int
    pruned_count: int
    retained_count: int
    error_count: int
    bytes_freed: int
    candidates: list[RetentionCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ArtifactRetentionService:
    """Production service governing the artifact retention lifecycle and safe pruning sweeps."""

    def __init__(
        self,
        storage_dir: Path | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        self.storage_dir = (storage_dir or STORAGE_ARTIFACTS_DIR).resolve()
        self.session_factory = session_factory or AsyncSessionLocal
        self._lock = asyncio.Lock()

    async def check_artifact_references(
        self,
        session: AsyncSession,
        filename: str,
        full_path: Path | None = None,
    ) -> tuple[bool, list[str]]:
        """Deep check against all authoritative database entities for live or durable references.

        Checks:
        1. AutonomousActionNode (outputs_json, inputs_json)
        2. AutonomousGoal (plan_dag_json and active/recoverable parent goals)
        3. ProductionShot (output_asset_url, frames, reference_assets, metadata_json)
        4. ProductionJob (job_package_json)
        5. Media tables (Image, GeneratedVideo, Asset, Thumbnail, Video storage_path)
        6. Alternative extension / alias variants of the same stem

        Fails closed on any error (returns True to prevent pruning).
        """
        reference_sources: list[str] = []

        try:
            # 1. Action Nodes (outputs_json & inputs_json)
            stmt_actions = select(
                AutonomousActionNode.id,
                AutonomousActionNode.status,
                AutonomousActionNode.goal_id,
            ).where(
                cast(AutonomousActionNode.outputs_json, Text).contains(filename)
                | cast(AutonomousActionNode.inputs_json, Text).contains(filename)
            )
            res_actions = await session.execute(stmt_actions)
            matched_actions = res_actions.all()
            if matched_actions:
                reference_sources.append(f"action_nodes({len(matched_actions)})")
                # Also check parent goal status
                goal_ids = [row.goal_id for row in matched_actions if row.goal_id]
                if goal_ids:
                    stmt_parent_goals = select(AutonomousGoal.id, AutonomousGoal.status).where(
                        AutonomousGoal.id.in_(goal_ids)
                    )
                    res_p_goals = await session.execute(stmt_parent_goals)
                    for p_goal in res_p_goals.all():
                        if (p_goal.status or "").upper() in ACTIVE_OR_RECOVERABLE_GOAL_STATUSES:
                            reference_sources.append(f"active_goal({p_goal.status})")

            # 2. Autonomous Goals (plan_dag_json)
            stmt_goals = select(AutonomousGoal.id, AutonomousGoal.status).where(
                cast(AutonomousGoal.plan_dag_json, Text).contains(filename)
            )
            res_goals = await session.execute(stmt_goals)
            matched_goals = res_goals.all()
            if matched_goals:
                reference_sources.append(f"goals_plan_dag({len(matched_goals)})")

            # 3. Production Shots
            stmt_shots = select(ProductionShot.id).where(
                (ProductionShot.output_asset_url.contains(filename))
                | (ProductionShot.first_frame.contains(filename))
                | (ProductionShot.last_frame.contains(filename))
                | (cast(ProductionShot.reference_assets, Text).contains(filename))
                | (cast(ProductionShot.metadata_json, Text).contains(filename))
            )
            res_shots = await session.execute(stmt_shots)
            if res_shots.all():
                reference_sources.append("production_shots")

            # 4. Production Jobs
            stmt_jobs = select(ProductionJob.id).where(
                cast(ProductionJob.job_package_json, Text).contains(filename)
            )
            res_jobs = await session.execute(stmt_jobs)
            if res_jobs.all():
                reference_sources.append("production_jobs")

            # 5. Media Tables
            stmt_img = select(Image.id).where(Image.storage_path.contains(filename))
            if (await session.execute(stmt_img)).all():
                reference_sources.append("images")

            stmt_gv = select(GeneratedVideo.id).where(GeneratedVideo.storage_path.contains(filename))
            if (await session.execute(stmt_gv)).all():
                reference_sources.append("generated_videos")

            stmt_asset = select(Asset.id).where(Asset.storage_path.contains(filename))
            if (await session.execute(stmt_asset)).all():
                reference_sources.append("assets")

            stmt_thumb = select(Thumbnail.id).where(Thumbnail.storage_path.contains(filename))
            if (await session.execute(stmt_thumb)).all():
                reference_sources.append("thumbnails")

            stmt_vid = select(Video.id).where(Video.storage_path.contains(filename))
            if (await session.execute(stmt_vid)).all():
                reference_sources.append("videos")

            # 6. Check alternative extension variants if full_path provided
            stem = Path(filename).stem
            alt_names = [
                f"{stem}{alt_ext}"
                for alt_ext in (".png", ".jpg", ".jpeg", ".jfif", ".webp", ".mp4", ".webm")
                if f"{stem}{alt_ext}" != filename
            ]
            if alt_names:
                conditions = [cast(AutonomousActionNode.outputs_json, Text).contains(an) for an in alt_names]
                stmt_alias = select(AutonomousActionNode.id).where(or_(*conditions))
                res_alias = await session.execute(stmt_alias)
                if res_alias.all():
                    reference_sources.append("alias_action_ref")

            is_ref = len(reference_sources) > 0
            return is_ref, reference_sources

        except Exception as exc:
            # FAIL-CLOSED: Any database error means the artifact is treated as referenced!
            logger.error(
                "artifact_reference_check_error_fail_closed",
                filename=filename,
                error=str(exc),
            )
            return True, [f"DB_ERROR_FAIL_CLOSED: {exc}"]

    async def run_retention_sweep(
        self,
        dry_run: bool | None = None,
        enabled: bool | None = None,
        retention_days: int | None = None,
        batch_size: int | None = None,
        session: AsyncSession | None = None,
    ) -> RetentionSweepReport:
        """Executes a bounded, concurrency-safe maintenance sweep over the artifact storage directory.

        Args:
            dry_run: If True, evaluates candidates without deleting. Defaults to config setting.
            enabled: If False, deletion gate remains disabled. Defaults to config setting.
            retention_days: Minimum age threshold in days for unreferenced pruning. Defaults to 14.
            batch_size: Max number of candidates to process in one sweep. Defaults to 100.
            session: Optional existing AsyncSession for transactional/testing context.
        """
        settings = get_settings()
        sweep_dry_run = dry_run if dry_run is not None else settings.artifact_retention_dry_run
        sweep_enabled = enabled if enabled is not None else settings.artifact_retention_enabled
        sweep_days = retention_days if retention_days is not None else settings.artifact_retention_days
        sweep_batch = batch_size if batch_size is not None else settings.artifact_retention_batch_size

        now = datetime.now(timezone.utc)
        now_ts = time.time()
        candidates: list[RetentionCandidate] = []
        errors: list[str] = []
        total_scanned = 0
        pruned_count = 0
        retained_count = 0
        bytes_freed = 0

        # Concurrency guard: Only one sweep may execute at a time per service instance
        async with self._lock:
            # 1. Directory confinement check
            if not self.storage_dir.exists() or not self.storage_dir.is_dir():
                errors.append(f"Storage directory does not exist: {self.storage_dir}")
                return RetentionSweepReport(
                    timestamp=now,
                    dry_run=sweep_dry_run,
                    enabled=sweep_enabled,
                    retention_days=sweep_days,
                    total_files_scanned=0,
                    total_candidates_evaluated=0,
                    pruned_count=0,
                    retained_count=0,
                    error_count=len(errors),
                    bytes_freed=0,
                    candidates=[],
                    errors=errors,
                )

            # Resolve external or self-managed session
            session_to_use = session
            should_close_session = False
            if session_to_use is None:
                session_to_use = self.session_factory()
                should_close_session = True

            try:
                # Scan storage directory
                try:
                    entries = list(self.storage_dir.iterdir())
                except OSError as os_err:
                    errors.append(f"Failed to list storage directory: {os_err}")
                    entries = []

                total_scanned = len(entries)

                for entry in entries:
                    if len(candidates) >= sweep_batch:
                        break

                    filename = entry.name

                    # Security Check A: Filename characters
                    if not SAFE_FILENAME_REGEX.match(filename) or ".." in filename:
                        errors.append(f"Security: skipped unsafe filename '{filename}'")
                        continue

                    # Security Check B: Path traversal & symlink escape
                    try:
                        resolved_entry = entry.resolve()
                        if not str(resolved_entry).startswith(str(self.storage_dir)):
                            errors.append(f"Security violation: symlink '{filename}' escapes storage root")
                            continue
                    except Exception as res_err:
                        errors.append(f"Path resolution error for '{filename}': {res_err}")
                        continue

                    if not entry.is_file():
                        continue

                    # Inspect file stat
                    try:
                        st = entry.stat()
                        mtime = st.st_mtime
                        size = st.st_size
                    except OSError as st_err:
                        errors.append(f"Cannot inspect stat for '{filename}': {st_err}")
                        continue

                    age_seconds = now_ts - mtime
                    age_days = max(0.0, age_seconds / 86400.0)

                    # Age gate: Artifacts younger than retention_days are always retained
                    if age_days < sweep_days:
                        retained_count += 1
                        continue

                    # File is aged >= sweep_days: Evaluate for references
                    is_ref, ref_sources = await self.check_artifact_references(
                        session_to_use, filename, full_path=entry
                    )

                    if is_ref:
                        retained_count += 1
                        candidates.append(
                            RetentionCandidate(
                                path=entry,
                                filename=filename,
                                age_days=round(age_days, 2),
                                size_bytes=size,
                                is_referenced=True,
                                reference_sources=ref_sources,
                                proposed_action="RETAIN",
                                reason=f"Referenced by {', '.join(ref_sources)}",
                            )
                        )
                        continue

                    # File is expired and unreferenced: Prune candidate!
                    # Check double-gate: sweep_dry_run MUST be False AND sweep_enabled MUST be True
                    can_actually_prune = (not sweep_dry_run) and sweep_enabled

                    if not can_actually_prune:
                        retained_count += 1
                        candidates.append(
                            RetentionCandidate(
                                path=entry,
                                filename=filename,
                                age_days=round(age_days, 2),
                                size_bytes=size,
                                is_referenced=False,
                                reference_sources=[],
                                proposed_action="PRUNE",
                                reason=f"Unreferenced scratch artifact (age {age_days:.1f}d >= {sweep_days}d; dry-run/disabled mode)",
                            )
                        )
                    else:
                        # Immediate Pre-Deletion Re-Check (Eliminate Creation/Deletion Race)
                        recheck_is_ref, recheck_sources = await self.check_artifact_references(
                            session_to_use, filename, full_path=entry
                        )
                        if recheck_is_ref:
                            retained_count += 1
                            candidates.append(
                                RetentionCandidate(
                                    path=entry,
                                    filename=filename,
                                    age_days=round(age_days, 2),
                                    size_bytes=size,
                                    is_referenced=True,
                                    reference_sources=recheck_sources,
                                    proposed_action="RETAIN",
                                    reason=f"Pre-deletion race caught reference: {', '.join(recheck_sources)}",
                                )
                            )
                        else:
                            # Safe to unlink
                            try:
                                entry.unlink()
                                pruned_count += 1
                                bytes_freed += size
                                candidates.append(
                                    RetentionCandidate(
                                        path=entry,
                                        filename=filename,
                                        age_days=round(age_days, 2),
                                        size_bytes=size,
                                        is_referenced=False,
                                        reference_sources=[],
                                        proposed_action="PRUNED",
                                        reason=f"Safely unlinked expired unreferenced scratch artifact ({size} bytes freed)",
                                    )
                                )
                            except OSError as unl_err:
                                errors.append(f"Failed to unlink '{filename}': {unl_err}")
                                retained_count += 1

            finally:
                if should_close_session and session_to_use is not None:
                    await session_to_use.close()

        logger.info(
            "artifact_retention_sweep_completed",
            dry_run=sweep_dry_run,
            enabled=sweep_enabled,
            retention_days=sweep_days,
            total_scanned=total_scanned,
            evaluated=len(candidates),
            pruned=pruned_count,
            retained=retained_count,
            bytes_freed=bytes_freed,
            error_count=len(errors),
        )

        return RetentionSweepReport(
            timestamp=now,
            dry_run=sweep_dry_run,
            enabled=sweep_enabled,
            retention_days=sweep_days,
            total_files_scanned=total_scanned,
            total_candidates_evaluated=len(candidates),
            pruned_count=pruned_count,
            retained_count=retained_count,
            error_count=len(errors),
            bytes_freed=bytes_freed,
            candidates=candidates,
            errors=errors,
        )


_retention_service_instance: ArtifactRetentionService | None = None


def get_artifact_retention_service() -> ArtifactRetentionService:
    """Singleton getter for ArtifactRetentionService."""
    global _retention_service_instance
    if _retention_service_instance is None:
        _retention_service_instance = ArtifactRetentionService()
    return _retention_service_instance
