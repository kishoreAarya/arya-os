"""Publication manifest creation and checkpoint binding (Phase 54B-I4).

Connects the Phase 54B-I1 manifest foundation to the existing approval
system: server-side manifest creation from AUTHORITATIVE PERSISTED
RECORDS (the Video row, its Thumbnail relationship, and the persisted
storage artifacts), followed by immutable binding of the manifest to
the run's pending THUMBNAIL checkpoint BEFORE a reviewer decides.

Contracts (Phase 54B-R2 §3, ratified):
- Artifact identity is NEVER caller-supplied: the request carries only
  the intended dispatch destination parameters; paths, digests, and
  sizes are derived from the persisted Video/Thumbnail rows and the
  bytes actually read through the existing safe asset-resolution path
  (SSRF-guarded, bounded downloads; streaming local hashing).
- Effective parameters are the values the CURRENT dispatch would send:
  persisted title/description/tags/aspect_ratio (including the 9:16
  "#Shorts" transform mirrored from agents/publishing.py), the
  requested destination/privacy/publish-type/schedule, and the Postiz
  default-integration resolution mirrored from platforms/postiz.py.
- The manifest row is persisted BEFORE it is presented for review, and
  deduplicated by digest: byte-identical derivations resolve to one
  row (video_id/workflow_run_id/paths/digests all participate in the
  canonical bytes, so distinct intents NEVER merge).
- Binding (all under the checkpoint row lock that decide_checkpoint
  also takes): the run's LATEST THUMBNAIL checkpoint, if still
  UNDECIDED, is (re)bound to the new manifest — an undecided binding
  may be superseded by newer content, and a stale approval attempt is
  rejected by the decide-time echo check. If the latest checkpoint is
  already DECIDED (or none exists), a NEW pending checkpoint bound to
  the manifest is created — approved bindings and append-only history
  are never mutated; a content change opens a new approval cycle under
  the existing lifecycle.
- The Hermes parameter_digest is not used; TTL/REVOKE/latest-decision
  behavior is untouched.

Known residual (documented, not pretended away): artifacts are hashed
at creation time from their current bytes; a local file mutated between
creation and dispatch is NOT prevented here — dispatch-time byte
verification (a later phase) detects it. Presigned review URLs are
deferred until a storage layer exposes them (the local provider's
get_url returns an absolute filesystem path, which must not be exposed).

This module does NOT enforce manifests at dispatch. Publishing is not
content-bound until the separate dispatch-verification phase.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid as uuid_mod
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.approval import ApprovalCheckpoint
from app.models.enums import ApprovalStage
from app.models.media import Video
from app.models.publication import PublicationManifest
from app.services.publication_manifest import (
    PublicationManifestError,
    build_manifest,
    canonical_bytes,
    manifest_digest,
)
from app.utils.asset_manager import ensure_local_asset

logger = get_logger(__name__)

# Bounded download size for hashing REMOTE artifacts via the existing
# ensure_local_asset path. Local artifacts are stream-hashed from disk
# (no download). No repo-wide video size cap exists on the publication
# path today (the YouTube adapter streams; Postiz reads whole files);
# current artifacts are short-form (<1 MB in dev storage). 512 MiB is a
# deliberately generous hashing-download bound — it does not change any
# dispatch behavior and exists to bound temp-disk use, not policy.
VIDEO_HASH_MAX_BYTES = 512 * 1024 * 1024
THUMBNAIL_HASH_MAX_BYTES = 50 * 1024 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024


class ManifestCreationError(Exception):
    """Fail-closed manifest creation refusal. `reason_code` is a stable,
    non-sensitive machine code; `http_status` maps it to the API edge."""

    def __init__(self, reason_code: str, detail: str, http_status: int = 422):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail
        self.http_status = http_status


def _stream_sha256(path: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        raise ValueError("artifact is zero bytes")
    return digest.hexdigest(), size


async def _hash_artifact(storage_path: str, *, max_bytes: int) -> tuple[str, int]:
    """Resolve the persisted artifact through the existing safe path and
    stream-hash the exact bytes. Known resolution/validation failures
    propagate to the caller as fail-closed creation refusals."""
    local_path = await ensure_local_asset(storage_path, max_bytes=max_bytes)
    return await asyncio.to_thread(_stream_sha256, local_path)


def _effective_parameters(
    video: Video,
    *,
    platform: str,
    social_platform: str,
    integration_id: str | None,
    privacy_status: str,
    publish_type: str,
    scheduled_at: datetime | str | None,
) -> dict:
    """Derive the EFFECTIVE values the current dispatch would send.

    Content metadata comes from the persisted Video row (never the
    request); the 9:16 "#Shorts" transform and the Postiz default
    integration resolution mirror agents/publishing.py and
    platforms/postiz.py respectively. These mirrored transforms are a
    documented reconciliation point for the dispatch-verification
    phase (which must reuse this derivation)."""
    title = video.title or ""
    description = video.description or ""
    tags = [t.strip() for t in video.tags.split(",")] if video.tags else []
    aspect_ratio = video.aspect_ratio or "16:9"

    if aspect_ratio == "9:16":
        if "#Shorts" not in title and "#Shorts" not in description:
            description = f"{description}\n\n#Shorts".strip()
        if "Shorts" not in tags:
            tags.append("Shorts")

    effective_integration = integration_id
    if effective_integration is None and platform == "postiz":
        from app.core.config import get_settings

        effective_integration = get_settings().postiz_default_integration_id or None

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "aspect_ratio": aspect_ratio,
        "platform": platform,
        "social_platform": social_platform,
        "integration_id": effective_integration,
        "privacy_status": privacy_status,
        "publish_type": publish_type,
        "scheduled_at": scheduled_at,
    }


# Phase 54B-I5: the single shared derivation used BOTH at manifest
# creation and at dispatch — one authority, no subtly drifting copies.
derive_effective_parameters = _effective_parameters


async def _resolve_manifest_by_digest(
    db: AsyncSession, digest: str
) -> PublicationManifest | None:
    return (
        await db.execute(
            select(PublicationManifest).where(
                PublicationManifest.manifest_digest == digest
            )
        )
    ).scalar_one_or_none()


async def create_and_bind_manifest(
    db: AsyncSession,
    *,
    workflow_run_id: uuid_mod.UUID,
    video_id: uuid_mod.UUID,
    platform: str,
    social_platform: str,
    integration_id: str | None,
    privacy_status: str,
    publish_type: str,
    scheduled_at: datetime | str | None,
) -> tuple[PublicationManifest, ApprovalCheckpoint]:
    """Derive, persist, and bind one publication-content manifest.

    Returns (manifest, checkpoint). Raises ManifestCreationError on
    every fail-closed refusal (unknown video, run mismatch, missing or
    unreadable artifacts, invalid parameters)."""
    video = (
        await db.execute(select(Video).where(Video.id == video_id))
    ).scalar_one_or_none()
    if video is None:
        raise ManifestCreationError("unknown_video", "no such video row", 404)
    if video.workflow_run_id != workflow_run_id:
        raise ManifestCreationError(
            "video_not_in_workflow_run",
            "the video does not belong to the workflow run",
        )
    # Captured BEFORE any rollback can expire the ORM instance — the
    # binding section below must never trip a lazy refresh.
    run_id = video.workflow_run_id
    vid_id = video.id

    # F-05a parity: YouTube scheduling is refused at the API edge before
    # any manifest is persisted (same rule as POST /publishing/publish).
    if platform == "youtube" and (
        scheduled_at is not None or publish_type == "schedule"
    ):
        raise ManifestCreationError(
            "scheduling_not_supported_on_youtube",
            "Scheduling is not supported on youtube: scheduled_at (or "
            "publish_type='schedule') is rejected",
        )

    params = _effective_parameters(
        video,
        platform=platform,
        social_platform=social_platform,
        integration_id=integration_id,
        privacy_status=privacy_status,
        publish_type=publish_type,
        scheduled_at=scheduled_at,
    )

    try:
        video_sha, video_size = await _hash_artifact(
            video.storage_path, max_bytes=VIDEO_HASH_MAX_BYTES
        )
    except (RuntimeError, ValueError, OSError) as exc:
        raise ManifestCreationError(
            "video_artifact_unavailable",
            f"the authoritative video artifact could not be resolved or hashed "
            f"({type(exc).__name__}); no manifest was created",
        ) from None

    thumb_sha = None
    thumb_size = None
    thumbnail_storage_path = None
    if video.thumbnail_id is not None:
        from app.models.media import Thumbnail

        thumbnail = (
            await db.execute(
                select(Thumbnail).where(Thumbnail.id == video.thumbnail_id)
            )
        ).scalar_one_or_none()
        if thumbnail is None:
            raise ManifestCreationError(
                "thumbnail_row_missing",
                "the video references a thumbnail row that does not exist",
                404,
            )
        try:
            thumb_sha, thumb_size = await _hash_artifact(
                thumbnail.storage_path, max_bytes=THUMBNAIL_HASH_MAX_BYTES
            )
        except (RuntimeError, ValueError, OSError) as exc:
            raise ManifestCreationError(
                "thumbnail_artifact_unavailable",
                f"the authoritative thumbnail artifact could not be resolved or "
                f"hashed ({type(exc).__name__}); no manifest was created",
            ) from None
        thumbnail_storage_path = thumbnail.storage_path

    try:
        manifest_data = build_manifest(
            workflow_run_id=video.workflow_run_id,
            video_id=video.id,
            video_storage_path=video.storage_path,
            video_sha256=video_sha,
            video_size_bytes=video_size,
            thumbnail_storage_path=thumbnail_storage_path,
            thumbnail_sha256=thumb_sha,
            thumbnail_size_bytes=thumb_size,
            title=params["title"],
            description=params["description"],
            tags=params["tags"],
            platform=params["platform"],
            social_platform=params["social_platform"],
            privacy_status=params["privacy_status"],
            publish_type=params["publish_type"],
            aspect_ratio=params["aspect_ratio"],
            integration_id=params["integration_id"],
            scheduled_at=params["scheduled_at"],
        )
    except PublicationManifestError as exc:
        raise ManifestCreationError(
            f"invalid_publication_parameters:{exc.reason_code}",
            f"the effective publication parameters are invalid: {exc.reason_code}",
        ) from None

    cb = canonical_bytes(manifest_data)
    digest = manifest_digest(cb)

    manifest = PublicationManifest(
        schema_version=manifest_data["schema_version"],
        workflow_run_id=video.workflow_run_id,
        video_id=video.id,
        canonical_bytes=cb.decode("utf-8"),
        manifest_digest=digest,
        video_storage_path=video.storage_path,
        video_sha256=video_sha,
        video_size_bytes=video_size,
        thumbnail_storage_path=thumbnail_storage_path,
        thumbnail_sha256=thumb_sha,
        thumbnail_size_bytes=thumb_size,
    )
    db.add(manifest)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent identical derivation won the digest-UNIQUE race:
        # resolve to the winner's row (never a second manifest).
        await db.rollback()
        existing = await _resolve_manifest_by_digest(db, digest)
        if existing is None:
            raise ManifestCreationError(
                "manifest_persistence_failed",
                "the manifest could not be persisted or resolved after a "
                "concurrent duplicate",
                500,
            ) from None
        manifest = existing
        logger.info(
            "publication_manifest_deduplicated",
            manifest_id=str(existing.id),
        )

    # Binding (under the same checkpoint row lock decide_checkpoint
    # takes, serializing against decisions and concurrent bindings).
    checkpoint = (
        await db.execute(
            select(ApprovalCheckpoint)
            .where(
                ApprovalCheckpoint.workflow_run_id == run_id,
                ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
            )
            .order_by(ApprovalCheckpoint.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if checkpoint is not None and checkpoint.action is None:
        # Undecided latest checkpoint: (re)bind it to this manifest. An
        # undecided binding may be superseded by newer content; a stale
        # approval echo is rejected at decide time (409).
        checkpoint.publication_manifest_id = manifest.id
    else:
        # Decided latest (or no checkpoint at all): NEVER mutate an
        # approved binding or history — open a NEW pending approval
        # cycle under the existing lifecycle.
        checkpoint = ApprovalCheckpoint(
            workflow_run_id=run_id,
            stage=ApprovalStage.THUMBNAIL,
            reference_table="videos",
            reference_id=vid_id,
            publication_manifest_id=manifest.id,
        )
        db.add(checkpoint)

    await db.commit()
    await db.refresh(checkpoint)

    logger.info(
        "publication_manifest_created_and_bound",
        manifest_id=str(manifest.id),
        checkpoint_id=str(checkpoint.id),
        workflow_run_id=str(run_id),
        video_id=str(vid_id),
    )
    return manifest, checkpoint


async def get_manifest_with_binding(
    db: AsyncSession, manifest_id: uuid_mod.UUID
) -> tuple[PublicationManifest, dict[str, Any], ApprovalCheckpoint | None]:
    """Load a manifest (verifying its stored canonical bytes and digest
    via the I1 fail-closed verifier) plus the LATEST checkpoint bound
    to it. Raises ManifestCreationError(404) when unknown."""
    manifest = (
        await db.execute(
            select(PublicationManifest).where(PublicationManifest.id == manifest_id)
        )
    ).scalar_one_or_none()
    if manifest is None:
        raise ManifestCreationError(
            "unknown_manifest", "no such publication manifest", 404
        )

    from app.services.publication_manifest import verify_stored_manifest

    try:
        parsed = verify_stored_manifest(
            manifest.canonical_bytes, manifest.manifest_digest
        )
    except PublicationManifestError as exc:
        raise ManifestCreationError(
            f"manifest_integrity_failure:{exc.reason_code}",
            "the stored manifest failed integrity verification",
            500,
        ) from None

    checkpoint = (
        await db.execute(
            select(ApprovalCheckpoint)
            .where(ApprovalCheckpoint.publication_manifest_id == manifest.id)
            .order_by(ApprovalCheckpoint.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return manifest, parsed, checkpoint


# ---------------------------------------------------------------------------
# Phase 54B-I5: dispatch-time manifest verification, snapshotting, and the
# authorize-and-permit transaction. None of this retroactively blesses
# legacy unbound approvals — an unbound authorizing checkpoint DENIES real
# dispatch (fail closed).
# ---------------------------------------------------------------------------


class DispatchBlocked(Exception):
    """Fail-closed dispatch refusal. `reason_code` is a stable machine
    code; `detail` never embeds sensitive values or local paths."""

    def __init__(self, reason_code: str, detail: str):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class ArtifactVerificationError(DispatchBlocked):
    """Artifact bytes missing, changed, oversized, or unresolvable."""


def _latest_authorizing_checkpoint_stmt(run_id):
    from sqlalchemy import select as sa_select

    return (
        sa_select(ApprovalCheckpoint)
        .where(
            ApprovalCheckpoint.workflow_run_id == run_id,
            ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
        )
        .order_by(ApprovalCheckpoint.created_at.desc())
        .limit(1)
    )


async def load_authorizing_manifest(
    db: AsyncSession,
    *,
    workflow_run_id: uuid_mod.UUID,
    video_id: uuid_mod.UUID,
    for_update: bool = False,
) -> tuple[ApprovalCheckpoint, PublicationManifest, dict]:
    """Load and verify the manifest bound to the run's authorizing
    (THUMBNAIL) checkpoint. Fail closed on missing checkpoint, unbound
    legacy checkpoint, missing manifest, target mismatch, or any I1
    canonical-bytes/digest verification failure. Returns the parsed
    effective parameters for dispatch comparison."""
    stmt = _latest_authorizing_checkpoint_stmt(workflow_run_id)
    if for_update:
        stmt = stmt.with_for_update()
    checkpoint = (await db.execute(stmt)).scalar_one_or_none()
    if checkpoint is None:
        raise DispatchBlocked("no_thumbnail_checkpoint", "no authorizing checkpoint")
    if checkpoint.publication_manifest_id is None:
        raise DispatchBlocked(
            "no_content_bound_manifest",
            "the authorizing approval is not content-bound to a publication "
            "manifest; legacy unbound approvals cannot authorize publication",
        )

    manifest = (
        await db.execute(
            select(PublicationManifest).where(
                PublicationManifest.id == checkpoint.publication_manifest_id
            )
        )
    ).scalar_one_or_none()
    if manifest is None:
        raise DispatchBlocked(
            "manifest_missing", "the bound publication manifest row does not exist"
        )
    if manifest.video_id != video_id or manifest.workflow_run_id != workflow_run_id:
        raise DispatchBlocked(
            "manifest_target_mismatch",
            "the bound manifest targets a different video or workflow run",
        )

    from app.services.publication_manifest import (
        PublicationManifestError,
        verify_stored_manifest,
    )

    try:
        parsed = verify_stored_manifest(
            manifest.canonical_bytes, manifest.manifest_digest
        )
    except PublicationManifestError as exc:
        raise DispatchBlocked(
            f"manifest_integrity_failure:{exc.reason_code}",
            "the stored manifest failed canonical-bytes/digest verification",
        ) from None
    return checkpoint, manifest, parsed


_SNAPSHOT_PREFIX = "arya-i5-snapshot-"


def _snapshot_source(local_path: str) -> tuple[str, str, int]:
    """Private snapshot: stream-copy the resolved local artifact to a
    fresh temp file, hashing WHILE copying (single read). The snapshot
    is owned by this execution; the adapter is handed the SNAPSHOT
    path, so the bytes uploaded are exactly the bytes verified. The
    original mutable source is never re-opened after verification."""
    import tempfile

    digest = hashlib.sha256()
    size = 0
    fd, snapshot_path = tempfile.mkstemp(prefix=_SNAPSHOT_PREFIX)
    try:
        with open(local_path, "rb") as src, os.fdopen(fd, "wb") as dst:
            while chunk := src.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
                dst.write(chunk)
    except Exception:
        _safe_unlink(snapshot_path)
        raise
    return snapshot_path, digest.hexdigest(), size


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


async def snapshot_and_verify_artifact(
    storage_path: str,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    max_bytes: int,
) -> str:
    """Resolve the AUTHORITATIVE persisted artifact reference through the
    existing safe asset-resolution path, snapshot it privately, and
    verify the snapshot's exact bytes against the approved manifest.
    Returns the snapshot path (the only path the adapter may upload).
    Raises ArtifactVerificationError on any mismatch or resolution
    failure — never returns an unverified artifact."""
    try:
        local_path = await ensure_local_asset(storage_path, max_bytes=max_bytes)
    except (RuntimeError, ValueError, OSError) as exc:
        raise ArtifactVerificationError(
            "artifact_resolution_failed",
            f"the authoritative artifact could not be resolved safely "
            f"({type(exc).__name__})",
        ) from None
    try:
        snapshot_path, actual_sha, actual_size = await asyncio.to_thread(
            _snapshot_source, local_path
        )
    except OSError as exc:
        raise ArtifactVerificationError(
            "artifact_read_failed",
            f"the authoritative artifact could not be read ({type(exc).__name__})",
        ) from None
    try:
        if actual_size != expected_size_bytes or actual_sha != expected_sha256:
            raise ArtifactVerificationError(
                "artifact_bytes_changed",
                "the artifact bytes no longer match the approved manifest "
                "(changed, replaced, or truncated since approval)",
            )
    except Exception:
        _safe_unlink(snapshot_path)
        raise
    return snapshot_path


def cleanup_snapshot(path: str | None) -> None:
    """Best-effort snapshot cleanup (success and failure paths). Never
    touches user-owned source assets — only this execution's private
    snapshot."""
    _safe_unlink(path)


_DESTINATION_FIELDS = (
    "platform",
    "social_platform",
    "integration_id",
    "privacy_status",
    "publish_type",
)


def destination_parameter_drift(context: dict, parsed: dict) -> str | None:
    """Compare caller-supplied dispatch values against the approved
    manifest's effective parameters. A caller-provided value that
    DIFFERS from the approved manifest is an override attempt — denied.
    Omitted values defer to the manifest (the authority). Returns the
    drifting field name, or None. Content fields (title/description/
    tags/aspect_ratio) are derived from the persisted Video row on BOTH
    sides and are compared separately via full derivation; request
    content fields are inert for manifest-bound dispatch."""
    from app.services.publication_manifest import normalize_timestamp

    for field in _DESTINATION_FIELDS:
        if field not in context or context[field] is None:
            continue
        value = context[field]
        if field == "integration_id":
            approved = parsed.get("integration_id")
            if (value or None) != (approved or None):
                return field
            continue
        if value != parsed[field]:
            return field
    if context.get("scheduled_at") is not None:
        try:
            normalized = normalize_timestamp(context["scheduled_at"])
        except Exception:  # noqa: BLE001 — unparseable input is drift-shaped
            return "scheduled_at"
        if normalized != parsed.get("scheduled_at"):
            return "scheduled_at"
    return None


def effective_parameter_drift(derived: dict, parsed: dict) -> str | None:
    """Compare the freshly derived effective parameters (persisted Video
    row + shared transforms) against the approved manifest. Any changed
    content or parameter — including the #Shorts transform and aspect
    ratio — fails closed. Returns the drifting field name, or None."""
    from app.services.publication_manifest import normalize_timestamp

    for field in (
        "title",
        "description",
        "tags",
        "aspect_ratio",
        "platform",
        "social_platform",
        "integration_id",
        "privacy_status",
        "publish_type",
    ):
        derived_value = derived.get(field)
        approved = parsed.get(field)
        if field == "integration_id":
            if (derived_value or None) != (approved or None):
                return field
            continue
        if derived_value != approved:
            return field
    derived_scheduled = derived.get("scheduled_at")
    approved_scheduled = parsed.get("scheduled_at")
    if (derived_scheduled is None) != (approved_scheduled is None):
        return "scheduled_at"
    if (
        derived_scheduled is not None
        and normalize_timestamp(derived_scheduled) != approved_scheduled
    ):
        return "scheduled_at"
    return None


def canonical_asset_reference(storage_path: str) -> str:
    """The router's F3 canonical identity form (ratified F-01): URLs keep
    their raw string; other references canonicalize through the storage
    provider's resolution. Used to compare a caller-supplied path against
    the manifest's authoritative path WITHOUT breaking the ratified alias
    semantics — a genuinely different path is still a mismatch."""
    if storage_path.startswith(("http://", "https://")):
        return storage_path
    try:
        from app.storage import get_storage_provider

        return get_storage_provider().canonical_key(storage_path)
    except Exception:  # noqa: BLE001 — provider unavailable: raw reference
        return storage_path


async def authorize_and_permit(
    db: AsyncSession,
    attempt,
    *,
    workflow_run_id: uuid_mod.UUID,
    video_id: uuid_mod.UUID,
    manifest_id: uuid_mod.UUID,
    manifest_digest: str,
):
    """Phase 54B-I5: authorization + dispatch permit in ONE transaction.

    Under the authorizing checkpoint's row lock (the same lock
    decide_checkpoint takes): re-evaluate the cached action, the latest
    append-only decision, and TTL; re-verify the checkpoint's manifest
    binding and the bound manifest's target identity; then CAS the
    attempt PENDING -> IN_PROGRESS, stamping the manifest id and digest
    atomically with the permit. A REVOKE/REJECT/expired approval or a
    moved binding that lands before this transaction blocks the permit
    and therefore every external call. Returns (manifest, parsed).
    Raises DispatchBlocked on every denial (after rolling back to
    release the lock). Residual (documented): a revocation committing
    AFTER this transaction cannot stop in-flight external calls."""
    from app.models.enums import PublicationAttemptStatus
    from app.services.publication_attempts import (
        TransitionOutcome,
        _transition_detailed,
    )
    from app.services.publish_gate import (
        PublishApprovalDenied,
        evaluate_authorizing_checkpoint,
    )

    stmt = _latest_authorizing_checkpoint_stmt(workflow_run_id).with_for_update()
    checkpoint = (await db.execute(stmt)).scalar_one_or_none()
    if checkpoint is None:
        await db.rollback()
        raise DispatchBlocked("no_thumbnail_checkpoint", "no authorizing checkpoint")

    try:
        await evaluate_authorizing_checkpoint(db, checkpoint)
    except PublishApprovalDenied as exc:
        await db.rollback()
        raise DispatchBlocked(
            exc.reason_code, "approval denied at permit time"
        ) from None

    if checkpoint.publication_manifest_id is None:
        await db.rollback()
        raise DispatchBlocked(
            "no_content_bound_manifest",
            "the authorizing approval is not content-bound to a publication manifest",
        )
    if checkpoint.publication_manifest_id != manifest_id:
        await db.rollback()
        raise DispatchBlocked(
            "manifest_binding_changed",
            "the checkpoint's manifest binding no longer matches the verified manifest",
        )

    manifest = (
        await db.execute(
            select(PublicationManifest).where(PublicationManifest.id == manifest_id)
        )
    ).scalar_one_or_none()
    if manifest is None:
        await db.rollback()
        raise DispatchBlocked(
            "manifest_missing", "the bound manifest row does not exist"
        )
    if manifest.video_id != video_id or manifest.workflow_run_id != workflow_run_id:
        await db.rollback()
        raise DispatchBlocked(
            "manifest_target_mismatch",
            "the bound manifest targets a different video or workflow run",
        )
    if manifest.manifest_digest != manifest_digest:
        await db.rollback()
        raise DispatchBlocked(
            "manifest_digest_changed",
            "the manifest digest no longer matches the verified digest",
        )

    from app.services.publication_manifest import verify_stored_manifest

    try:
        parsed = verify_stored_manifest(
            manifest.canonical_bytes, manifest.manifest_digest
        )
    except Exception:  # noqa: BLE001 — any verification failure blocks
        await db.rollback()
        raise DispatchBlocked(
            "manifest_integrity_failure",
            "the stored manifest failed canonical-bytes/digest verification",
        ) from None

    outcome = await _transition_detailed(
        db,
        attempt,
        PublicationAttemptStatus.IN_PROGRESS,
        (PublicationAttemptStatus.PENDING,),
        manifest_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        # Phase 54B-I6: the attempt's scheduling metadata is stamped from
        # the AUTHORITATIVE manifest's effective schedule, atomically with
        # the permit — a request-supplied scheduled_at (recorded at
        # admission) can never survive into the dispatched state. Parsed
        # scheduled_at is the manifest's canonical normalized form (or
        # absent for unscheduled manifests: null/unscheduled semantics
        # preserved). Existing historical rows are never rewritten; only
        # the row being permitted right now receives the manifest value.
        scheduled_at=parsed.get("scheduled_at"),
    )
    if outcome is not TransitionOutcome.PERSISTED:
        # The CAS itself refused (resolved underneath) or its commit
        # raised (uncertain): the permit is NOT granted — no external
        # call may follow.
        raise DispatchBlocked(
            "permit_not_persisted",
            "the dispatch permit could not be positively persisted "
            "(resolved underneath or uncertain commit); no external call was made",
        )
    return manifest, parsed
