"""
PublishingAgent — publishes a video to a platform via PlatformAdapter.

Uses the shared adapter architecture (app/platforms/) to abstract
which platform is being published to. PublishingAgent only knows:
- the platform name (from context)
- the video to publish (from context)
- the metadata (title, description, tags from context)

Everything platform-specific (authentication, upload protocol, publish
flow, URL format) lives in the PlatformAdapter implementation.
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.platforms.registry import UnknownPlatformError, get_platform_adapter
from app.utils.asset_manager import ensure_local_asset

from uuid import UUID

from sqlalchemy import or_, update

from app.models.enums import PublishStatus
from app.models.media import Video

logger = get_logger(__name__)


@dataclass
class PublishingResult:
    """Strongly-typed output of PublishingAgent.run() — attached under
    AgentResult.output["publishing_result"]. Field names mirror
    Video.publish_status / Video.youtube_video_id (app/models/media.py)
    generalized to "platform" rather than hardcoded to YouTube."""

    platform: str
    video_id: str | None
    published_content_id: str | None = None
    publish_status: str = "failed"


class PublishingAgent(BaseAgent):
    name = "publishing_agent"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        platform (str, required) — e.g. "youtube"
        video_id (str, required)
        video_storage_path (str, required)
        thumbnail_storage_path (str, optional)
        topic (str, optional) — carried forward for AnalyticsAgent
        title (str, optional)
        description (str, optional)
        tags (str, optional) — comma-separated
        """
        platform = context.get("platform")
        video_id = context.get("video_id")
        video_storage_path = context.get("video_storage_path")

        missing = [
            name
            for name, value in (
                ("platform", platform),
                ("video_id", video_id),
                ("video_storage_path", video_storage_path),
            )
            if not value
        ]
        if missing:
            return AgentResult(
                success=False,
                error=f"Missing required context field(s): {', '.join(missing)}",
            )

        is_dry_run = bool(context.get("dry_run") or context.get("is_dry_run"))

        # Phase 53B (finding 53A-01): AryaOS enforces its own approval
        # policy at this single boundary — every dispatch path (the
        # /publishing/publish route, the orchestrator pipeline, and direct
        # agent construction) crosses run(). Dry-run requests bypass the
        # human gate: adapters perform validation only with ZERO external
        # API calls when is_dry_run is set (verified per adapter), so no
        # external side effect can occur. Everything else must present an
        # authorized THUMBNAIL checkpoint for the exact (workflow run,
        # video) pair. Fail closed — denial never dispatches.
        if not is_dry_run:
            from app.services.publish_gate import (
                PublishApprovalDenied,
                assert_publish_authorized,
            )

            if not context.get("workflow_run_id"):
                return AgentResult(
                    success=False,
                    error="publish_approval_denied: missing_workflow_run_id",
                )
            try:
                await assert_publish_authorized(
                    self._db, context["workflow_run_id"], video_id
                )
            except PublishApprovalDenied as exc:
                logger.warning(
                    "publishing_agent_blocked_by_approval_gate",
                    reason_code=exc.reason_code,
                )
                return AgentResult(
                    success=False,
                    error=f"publish_approval_denied: {exc.reason_code}",
                )

        # Resolve platform adapter via factory
        try:
            adapter = get_platform_adapter(platform, self._db)
        except UnknownPlatformError as exc:
            logger.error(
                "publishing_agent_unknown_platform",
                platform=platform,
                error=str(exc),
            )
            return AgentResult(success=False, error=str(exc))

        # Publication-attempt core (operator-authorized slice): the
        # durable, DB-idempotent attempt record for THIS publication
        # intent. Written BEFORE any external call. Dry-run validates
        # only and records no attempt. Duplicate intents resolve to the
        # existing attempt — never a second external publication.
        # (is_dry_run computed above, before the Phase 53B approval gate.)
        social_platform = context.get("social_platform") or context.get("platform_type") or "youtube"
        attempt = None
        if not is_dry_run:
            from app.models.enums import PublicationAttemptStatus
            from app.services.publication_attempts import admit_attempt

            try:
                attempt_video_uuid = UUID(str(video_id))
            except (ValueError, TypeError, AttributeError):
                # Non-UUID video ids are tolerated by the existing path
                # (the Video writeback skips them the same way); they get
                # no attempt record rather than failing the publication.
                attempt_video_uuid = None
            if attempt_video_uuid is None:
                # Phase 54B-I2 belt-and-braces: a real (non-dry-run)
                # dispatch with no durable attempt row has no anchor
                # surface at all, so adapter.publish() would be
                # untrackable. The 53B gate already denies non-UUID ids
                # on every API path; this covers direct agent
                # construction only. Refuse — never publish untracked.
                return AgentResult(
                    success=False,
                    error="Publication refused: no durable publication-attempt "
                    "record can be created for this video id, so the external "
                    "content anchor cannot be persisted; publication requires a "
                    "trackable attempt (dry_run requests are unaffected)",
                )
            if attempt_video_uuid is not None:
                attempt, created = await admit_attempt(
                    self._db,
                    video_id=attempt_video_uuid,
                    platform=platform,
                    social_platform=social_platform,
                    integration_id=context.get("integration_id"),
                    workflow_run_id=(
                        UUID(str(context["workflow_run_id"]))
                        if context.get("workflow_run_id")
                        else None
                    ),
                    scheduled_at=context.get("scheduled_at"),
                )
                if not created:
                    if attempt.status == PublicationAttemptStatus.SUCCEEDED:
                        # F-10a (ratified): duplicate-path Video writeback
                        # self-heal. The attempt row is authoritative; if
                        # the original post-success writeback never landed
                        # (transient failure or crash before it), re-attempt
                        # it now — an idempotent, STALENESS-GUARDED update
                        # (only rows still missing the external id) that is
                        # a deliberate no-op for synthetic identities (no
                        # Video row exists) and never a provider call,
                        # publication attempt, or state transition. Heal
                        # failures are non-fatal: surfaced as a warning,
                        # and the duplicate response remains truthful.
                        if attempt.external_post_id:
                            try:
                                heal_uuid = UUID(str(video_id))
                            except (ValueError, TypeError):
                                heal_uuid = None
                            if heal_uuid is not None:
                                # Captured BEFORE any rollback can expire
                                # the ORM instance (logging-only value).
                                attempt_id_str = str(attempt.id)
                                healed_status = (
                                    PublishStatus.SCHEDULED
                                    if attempt.scheduled_at
                                    else PublishStatus.PUBLISHED
                                )
                                try:
                                    heal_result = await self._db.execute(
                                        update(Video)
                                        .where(
                                            Video.id == heal_uuid,
                                            or_(
                                                Video.youtube_video_id.is_(None),
                                                Video.youtube_video_id == "",
                                            ),
                                        )
                                        .values(
                                            youtube_video_id=attempt.external_post_id,
                                            publish_status=healed_status,
                                        )
                                    )
                                    await self._db.commit()
                                    if heal_result.rowcount == 1:
                                        logger.info(
                                            "publishing_agent_video_writeback_healed",
                                            video_id=video_id,
                                            youtube_video_id=attempt.external_post_id,
                                            attempt_id=attempt_id_str,
                                            publish_status=healed_status.value,
                                        )
                                except Exception as exc:  # heal is best-effort; the duplicate response stays truthful
                                    try:
                                        await self._db.rollback()
                                        # Rollback expires ORM instances; rehydrate
                                        # (best-effort) so the duplicate response
                                        # below cannot trip a lazy load.
                                        await self._db.refresh(attempt)
                                    except Exception:  # best-effort session recovery
                                        pass
                                    logger.warning(
                                        "publishing_agent_video_writeback_heal_failed",
                                        video_id=video_id,
                                        attempt_id=attempt_id_str,
                                        error=str(exc),
                                    )
                        # Idempotent duplicate: the identical intent already
                        # published — return the existing outcome, no second
                        # external publication.
                        return AgentResult(
                            success=True,
                            output={
                                "publishing_result": None,
                                "published_video_id": attempt.external_post_id,
                                "public_url": attempt.public_url,
                                "attempt_id": str(attempt.id),
                                "attempt_status": attempt.status.value,
                                "attempt_number": attempt.attempt_number,
                                "duplicate": True,
                            },
                            error=None,
                        )
                    reason = {
                        PublicationAttemptStatus.PENDING: "a submission of this publication "
                        "intent is already pending",
                        PublicationAttemptStatus.IN_PROGRESS: "a publication of this intent "
                        "is currently in progress",
                        PublicationAttemptStatus.UNKNOWN: "a previous publication of this "
                        "intent has an AMBIGUOUS outcome (manual reconciliation required; "
                        "automatic retry is blocked)",
                    }[attempt.status]
                    return AgentResult(
                        success=False,
                        error=f"Publication attempt {attempt.attempt_number} for this intent "
                        f"is {attempt.status.value}: {reason}",
                    )

        # Phase 54B-I5: dispatch-time manifest verification. Fail closed
        # (recorded FAILED on the admitted attempt, ZERO external calls)
        # unless the authorizing checkpoint is content-bound to a
        # verified manifest whose video/thumbnail bytes, destination, and
        # effective parameters exactly match what will be dispatched.
        # Legacy unbound approvals are denied here for real publishing.
        prepared = None
        if not is_dry_run:
            prepared = await self._verify_publication_manifest(context, attempt)
            if isinstance(prepared, AgentResult):
                return prepared

        try:
            return await self._dispatch(
                context=context,
                adapter=adapter,
                platform=platform,
                video_id=video_id,
                social_platform=social_platform,
                is_dry_run=is_dry_run,
                attempt=attempt,
                prepared=prepared,
            )
        finally:
            # Snapshot cleanup on EVERY path (success, failure, abort):
            # only this execution's private snapshots are removed — the
            # user-owned source artifacts are never touched.
            if prepared is not None:
                from app.services.publication_manifest_service import cleanup_snapshot

                cleanup_snapshot(prepared.video_snapshot_path)
                cleanup_snapshot(prepared.thumbnail_snapshot_path)

    async def _verify_publication_manifest(self, context: dict, attempt):
        """Phase 54B-I5 verification: manifest binding and integrity,
        destination/content drift, path authority, and stable verified
        artifact snapshots. Returns a prepared namespace on success, or
        an AgentResult denial (attempt recorded FAILED; no external
        call was possible)."""
        from types import SimpleNamespace
        from uuid import UUID as _UUID

        from sqlalchemy import select as _select

        from app.models.media import Video
        from app.services.publication_attempts import mark_failed
        from app.services.publication_manifest_service import (
            THUMBNAIL_HASH_MAX_BYTES,
            VIDEO_HASH_MAX_BYTES,
            ArtifactVerificationError,
            DispatchBlocked,
            canonical_asset_reference,
            cleanup_snapshot,
            destination_parameter_drift,
            derive_effective_parameters,
            effective_parameter_drift,
            load_authorizing_manifest,
            snapshot_and_verify_artifact,
        )

        run_uuid = _UUID(str(context["workflow_run_id"]))
        video_uuid = _UUID(str(context["video_id"]))

        async def _deny(reason_code: str, detail: str, snapshots=()):
            for path in snapshots:
                cleanup_snapshot(path)
            if attempt is not None:
                await mark_failed(
                    self._db, attempt, f"publication_blocked: {reason_code}"
                )
            logger.warning(
                "publishing_dispatch_blocked", reason_code=reason_code
            )
            return AgentResult(
                success=False,
                error=f"publication_blocked: {reason_code}: {detail}",
            )

        try:
            _checkpoint, manifest, parsed = await load_authorizing_manifest(
                self._db, workflow_run_id=run_uuid, video_id=video_uuid
            )
        except DispatchBlocked as exc:
            return await _deny(exc.reason_code, exc.detail)

        drift = destination_parameter_drift(context, parsed)
        if drift is not None:
            return await _deny(
                f"parameter_drift:{drift}",
                f"the request {drift} differs from the approved manifest; "
                "the approved manifest is authoritative",
            )

        ctx_video_path = context.get("video_storage_path")
        if ctx_video_path and canonical_asset_reference(ctx_video_path) != canonical_asset_reference(
            manifest.video_storage_path
        ):
            return await _deny(
                "manifest_path_mismatch",
                "the request asset path differs from the approved manifest's "
                "authoritative artifact",
            )
        ctx_thumb_path = context.get("thumbnail_storage_path")
        if manifest.thumbnail_storage_path:
            if ctx_thumb_path and canonical_asset_reference(
                ctx_thumb_path
            ) != canonical_asset_reference(manifest.thumbnail_storage_path):
                return await _deny(
                    "manifest_path_mismatch",
                    "the request thumbnail path differs from the approved "
                    "manifest's authoritative artifact",
                )
        elif ctx_thumb_path:
            return await _deny(
                "thumbnail_not_in_manifest",
                "a thumbnail was supplied but the approved manifest has none",
            )

        video_row = (
            await self._db.execute(_select(Video).where(Video.id == video_uuid))
        ).scalar_one_or_none()
        if video_row is None:
            return await _deny("unknown_video", "the video row no longer exists")

        derived = derive_effective_parameters(
            video_row,
            platform=context.get("platform") or parsed["platform"],
            social_platform=context.get("social_platform") or parsed["social_platform"],
            integration_id=(
                context.get("integration_id")
                if context.get("integration_id") is not None
                else parsed.get("integration_id")
            ),
            privacy_status=context.get("privacy_status") or parsed["privacy_status"],
            publish_type=context.get("publish_type") or parsed["publish_type"],
            scheduled_at=(
                context.get("scheduled_at")
                if context.get("scheduled_at") is not None
                else parsed.get("scheduled_at")
            ),
        )
        drift = effective_parameter_drift(derived, parsed)
        if drift is not None:
            return await _deny(
                f"content_drift:{drift}",
                "the persisted content or effective parameters changed since "
                "approval; a fresh manifest and approval are required",
            )

        try:
            video_snapshot = await snapshot_and_verify_artifact(
                manifest.video_storage_path,
                expected_sha256=manifest.video_sha256,
                expected_size_bytes=manifest.video_size_bytes,
                max_bytes=VIDEO_HASH_MAX_BYTES,
            )
        except ArtifactVerificationError as exc:
            return await _deny(exc.reason_code, exc.detail)
        thumbnail_snapshot = None
        if manifest.thumbnail_storage_path:
            try:
                thumbnail_snapshot = await snapshot_and_verify_artifact(
                    manifest.thumbnail_storage_path,
                    expected_sha256=manifest.thumbnail_sha256,
                    expected_size_bytes=manifest.thumbnail_size_bytes,
                    max_bytes=THUMBNAIL_HASH_MAX_BYTES,
                )
            except ArtifactVerificationError as exc:
                return await _deny(exc.reason_code, exc.detail, [video_snapshot])

        return SimpleNamespace(
            manifest=manifest,
            parsed=parsed,
            derived=derived,
            video_snapshot_path=video_snapshot,
            thumbnail_snapshot_path=thumbnail_snapshot,
        )

    async def _dispatch(
        self,
        *,
        context: dict,
        adapter,
        platform: str,
        video_id,
        social_platform: str,
        is_dry_run: bool,
        attempt,
        prepared,
    ):
        """The post-verification dispatch flow: authenticate, acquire the
        authorization-bound permit (I3/I5), upload the VERIFIED snapshot
        bytes, persist the anchor (I2), and publish with the approved
        parameters. `prepared` is None only for dry-run (legacy
        context-derived path, zero external calls)."""
        # Authenticate with the platform
        from app.services.publication_attempts import mark_failed as _attempt_failed

        try:
            auth_result = await adapter.authenticate()
        except Exception as exc:  # auth is a read-only call: no submission possible → FAILED
            logger.error("publishing_agent_authentication_error", platform=platform, error=str(exc))
            if attempt is not None:
                await _attempt_failed(self._db, attempt, f"authentication error: {type(exc).__name__}")
            return AgentResult(success=False, error=f"Authentication failed for '{platform}': {exc}")
        if not auth_result.success:
            logger.error(
                "publishing_agent_authentication_failed",
                platform=platform,
                error=auth_result.error,
            )
            if attempt is not None:
                await _attempt_failed(
                    self._db, attempt, f"authentication failed: {auth_result.error}"
                )
            return AgentResult(
                success=False,
                error=f"Authentication failed for '{platform}': {auth_result.error}",
            )

        if prepared is not None:
            # Phase 54B-I5: the approved manifest's effective parameters
            # (derived once, shared with manifest creation) are THE
            # dispatch parameters; request content fields are inert.
            aspect_ratio = prepared.derived["aspect_ratio"]
            title = prepared.derived["title"]
            description = prepared.derived["description"]
            tags = prepared.derived["tags"]
        else:
            aspect_ratio = context.get("aspect_ratio", "16:9")
            title = context.get("title")
            description = context.get("description")
            tags_raw = context.get("tags")
            tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

            if aspect_ratio == "9:16":
                if "#Shorts" not in (title or "") and "#Shorts" not in (description or ""):
                    description = f"{description or ''}\n\n#Shorts".strip()
                if "Shorts" not in tags:
                    tags.append("Shorts")

        from app.models.enums import PublicationAttemptStatus
        from app.services.publication_attempts import (
            TransitionOutcome,
            mark_failed,
            mark_succeeded,
            mark_unknown,
            persist_external_content_anchor,
        )

        if prepared is not None:
            # Phase 54B-I5: authorization + permit in ONE transaction.
            # Under the authorizing checkpoint's row lock: re-evaluate
            # the cached action, the latest append-only decision, and
            # TTL; re-verify the manifest binding, target, and digest;
            # then CAS PENDING -> IN_PROGRESS stamping the manifest id
            # and digest atomically with the permit. This preserves the
            # I3 ordering (permit precedes EVERY upload) and closes the
            # 53B gate-to-permit window against REVOKE/REJECT/expiry.
            # Residual (documented): a revocation committing after this
            # transaction cannot stop in-flight external calls.
            from app.services.publication_manifest_service import (
                DispatchBlocked,
                authorize_and_permit,
            )

            # Captured BEFORE the transaction: a denial-path rollback
            # expires the ORM instance (attribute access would trip a
            # lazy refresh outside the async context).
            attempt_id_str = str(attempt.id)
            attempt_number = attempt.attempt_number
            try:
                _manifest, parsed = await authorize_and_permit(
                    self._db,
                    attempt,
                    workflow_run_id=UUID(str(context["workflow_run_id"])),
                    video_id=UUID(str(video_id)),
                    manifest_id=prepared.manifest.id,
                    manifest_digest=prepared.manifest.manifest_digest,
                )
                prepared.parsed = parsed
            except DispatchBlocked as exc:
                logger.error(
                    "publishing_agent_permit_denied",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=attempt_id_str,
                    reason_code=exc.reason_code,
                )
                # Durably record the refusal on the attempt (best-effort:
                # if the CAS itself refused because an operator already
                # resolved the row, that resolution stands).
                try:
                    await self._db.refresh(attempt)
                except Exception:  # refresh best-effort
                    pass
                try:
                    await mark_failed(
                        self._db, attempt, f"permit denied: {exc.reason_code}"
                    )
                except Exception:  # the denial stands regardless
                    logger.warning(
                        "publishing_agent_permit_denial_state_write_failed",
                        attempt_id=attempt_id_str,
                    )
                try:
                    current_status = attempt.status.value
                except Exception:  # reporting must never break the abort
                    current_status = "unavailable"
                return AgentResult(
                    success=False,
                    error=f"Publication permit denied for attempt {attempt_number} of "
                    f"this intent ({exc.reason_code}; the attempt is now {current_status}); "
                    "no external upload or publish was made",
                )

        if prepared is not None:
            # The VERIFIED private snapshot — the only bytes the adapter
            # may upload (Phase 54B-I5 TOCTOU closure). The original
            # mutable artifact is never re-resolved after verification.
            local_video_path = prepared.video_snapshot_path
        else:
            try:
                local_video_path = await ensure_local_asset(
                    context.get("video_storage_path")
                )
            except (RuntimeError, ValueError, OSError) as exc:
                # Known local asset-resolution/validation failures only
                # (missing file, SSRF-rejected remote URL, size/download/
                # zero-byte guards, filesystem errors). This happens BEFORE
                # any adapter submission call: evidence supports "no public
                # post was created" — FAILED (F-07), never a stranded
                # PENDING row and never UNKNOWN (nothing external was
                # attempted). Deliberately NARROW: unexpected programming
                # errors (AttributeError/KeyError/...) stay loud — they are
                # defects to observe, not business-level FAILED
                # classifications.
                logger.error(
                    "publishing_agent_asset_error",
                    platform=platform,
                    video_id=video_id,
                    error=str(exc),
                )
                if attempt is not None:
                    await _attempt_failed(
                        self._db, attempt, f"asset resolution failed: {type(exc).__name__}: {exc}"
                    )
                return AgentResult(
                    success=False,
                    error=f"Asset resolution failed for '{platform}': {exc}",
                )

        try:
            upload_result = await adapter.upload_content(
                file_path=local_video_path,
                title=title,
                description=description,
                tags=tags or None,
                credentials=auth_result.credentials,
                is_dry_run=is_dry_run,
            )
        except Exception as exc:  # external ambiguity: provider may hold the media → UNKNOWN
            # External submission ambiguity (the provider may hold the
            # media): UNKNOWN — never silently FAILED.
            logger.error("publishing_agent_upload_error", platform=platform, error=str(exc))
            recorded_unknown = True
            if attempt is not None:
                recorded_unknown = await mark_unknown(
                    self._db, attempt, f"upload exception: {type(exc).__name__}"
                )
            suffix = (
                " (attempt recorded UNKNOWN)"
                if recorded_unknown
                else " (attempt already resolved — transition refused)"
            )
            return AgentResult(
                success=False,
                error=f"Upload raised for '{platform}': {exc}{suffix}",
            )
        if not upload_result.success:
            logger.error(
                "publishing_agent_upload_failed",
                platform=platform,
                video_id=video_id,
                error=upload_result.error,
            )
            if attempt is not None:
                await mark_failed(self._db, attempt, f"upload rejected: {upload_result.error}")
            return AgentResult(
                success=False,
                error=f"Upload failed for '{platform}': {upload_result.error}",
            )
        if attempt is not None:
            # Phase 54B-I2: MANDATORY external-content anchor
            # precondition. adapter.publish() (and the thumbnail upload)
            # are UNREACHABLE unless the provider media id is positively
            # confirmed persisted (row matched AND committed). A provider
            # upload that returned success may still have landed even
            # when its anchor could not be persisted — the media id is
            # surfaced for manual cleanup; this is NOT exactly-once and
            # is NEVER auto-retried.
            if not upload_result.content_id:
                # Upload signalled success but produced no provider
                # media id: an anchor is impossible, so publish is
                # unreachable (fail closed). Epistemic twin of the
                # adapters' F-15a: the provider may hold media whose
                # identity is unknown → UNKNOWN, never FAILED.
                recorded_unknown = await mark_unknown(
                    self._db,
                    attempt,
                    "upload succeeded without a provider media id; anchor impossible",
                )
                logger.error(
                    "publishing_agent_anchor_missing_media_id",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                )
                suffix = (
                    " (attempt recorded UNKNOWN; manual reconciliation required)"
                    if recorded_unknown
                    else " (attempt already resolved — transition refused)"
                )
                return AgentResult(
                    success=False,
                    error=f"Upload for '{platform}' returned success but no provider "
                    f"media id; publication aborted before any thumbnail upload or "
                    f"publish call{suffix}",
                )
            try:
                anchor_outcome = await persist_external_content_anchor(
                    self._db, attempt, upload_result.content_id
                )
            except Exception as exc:  # persistence itself raised: fail closed
                # The persistence layer normally converts execute/commit
                # failures into UNCERTAIN; a raise escaping it is treated
                # identically — never as success, never retried.
                logger.error(
                    "publishing_agent_anchor_persistence_raised",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                    error_type=type(exc).__name__,
                )
                anchor_outcome = TransitionOutcome.UNCERTAIN
            if anchor_outcome is not TransitionOutcome.PERSISTED:
                # Abort publication: no thumbnail upload and no
                # adapter.publish(). The uploaded media may exist at the
                # provider — surface its id for manual cleanup.
                try:
                    current_status = attempt.status.value
                except Exception:  # never let reporting break the abort
                    current_status = "unavailable"
                if anchor_outcome is TransitionOutcome.REFUSED:
                    # The attempt was resolved underneath this execution
                    # (operator resolution or concurrent transition) —
                    # that resolution STANDS (H1); no state is written.
                    logger.error(
                        "publishing_agent_anchor_refused_publication_aborted",
                        platform=platform,
                        video_id=video_id,
                        attempt_id=str(attempt.id),
                        attempt_status=current_status,
                        external_content_id=upload_result.content_id,
                    )
                    return AgentResult(
                        success=False,
                        error=f"Publication aborted for attempt {attempt.attempt_number} of "
                        f"this intent: the attempt is now {current_status} (resolved by an "
                        "operator or another execution), so the external-content anchor "
                        "could not be persisted; no thumbnail upload or external publish "
                        f"was made; the uploaded provider media id {upload_result.content_id} "
                        "was not published and remains at the provider (manual cleanup may "
                        "be required)",
                    )
                # UNCERTAIN: execute/commit raised — the anchor may or may
                # not be recorded. Fail closed, record the ambiguity
                # best-effort, and preserve operator reconciliation
                # evidence. Never auto-retry.
                recorded_unknown = await mark_unknown(
                    self._db,
                    attempt,
                    "external-content anchor persistence failed with an uncertain "
                    "database outcome after a successful upload; publication aborted "
                    "before publish",
                )
                logger.error(
                    "publishing_agent_anchor_uncertain_publication_aborted",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                    external_content_id=upload_result.content_id,
                    anchor_recorded_unknown=recorded_unknown,
                )
                suffix = (
                    " (attempt recorded UNKNOWN; manual reconciliation required)"
                    if recorded_unknown
                    else " (attempt state could not be updated — manual reconciliation required)"
                )
                return AgentResult(
                    success=False,
                    error=f"Publication aborted for attempt {attempt.attempt_number} of "
                    "this intent: persistence of the external-content anchor failed "
                    "with an UNCERTAIN database outcome (the anchor may or may not be "
                    "recorded); no thumbnail upload or external publish was made; the "
                    f"uploaded provider media id {upload_result.content_id} remains at "
                    f"the provider{suffix}",
                )

        # Upload thumbnail if provided. A resolution failure here is a
        # post-permit, pre-publish local failure (F-07): the publish call
        # has not been made, so no post can exist — FAILED, never a
        # stranded in-flight row and never UNKNOWN (nothing external was
        # attempted beyond the already-anchored video upload). Same
        # NARROW exception set as the main asset resolver (the same
        # ensure_local_asset code path): unexpected programming errors
        # stay loud.
        if prepared is not None:
            # Phase 54B-I5: the manifest's verified thumbnail snapshot
            # (prepared pre-permit) — or no thumbnail at all when the
            # manifest approved none. Request thumbnail paths were
            # denied earlier if they differed.
            thumbnail_path = prepared.thumbnail_snapshot_path
        else:
            try:
                thumbnail_path = await ensure_local_asset(
                    context.get("thumbnail_storage_path")
                )
            except (RuntimeError, ValueError, OSError) as exc:
                logger.error(
                    "publishing_agent_thumbnail_asset_error",
                    platform=platform,
                    video_id=video_id,
                    error=str(exc),
                )
                if attempt is not None:
                    await mark_failed(
                        self._db, attempt, f"thumbnail resolution failed: {type(exc).__name__}: {exc}"
                    )
                return AgentResult(
                    success=False,
                    error=f"Thumbnail resolution failed for '{platform}': {exc}",
                )

        if thumbnail_path and upload_result.content_id:
            try:
                thumb_result = await adapter.upload_thumbnail(
                    video_content_id=upload_result.content_id,
                    thumbnail_path=thumbnail_path,
                    credentials=auth_result.credentials,
                    is_dry_run=is_dry_run,
                )
                if not thumb_result.success:
                    logger.warning(
                        "publishing_agent_thumbnail_upload_failed",
                        platform=platform,
                        video_id=video_id,
                        error=thumb_result.error,
                    )
                    # Non-fatal: video uploaded successfully, thumbnail failed.
            except Exception as exc:  # non-fatal thumbnail ambiguity; publish below decides
                # Non-fatal (parity with thumbnail rejection): the
                # publication itself has not been submitted; the publish
                # call below determines the attempt outcome.
                logger.warning(
                    "publishing_agent_thumbnail_upload_error",
                    platform=platform,
                    video_id=video_id,
                    error=str(exc),
                )

        # Publish or schedule the video — the final irreversible
        # external call. Reachable only on the established chain of
        # proof: authorization gate (53B) → admission → verified
        # content-bound manifest (I5) → dispatch permit acquired BEFORE
        # every upload under the checkpoint lock (I3/I5) → verified
        # snapshot bytes uploaded → external-content anchor positively
        # persisted (I2 precondition). The permit stays valid through
        # this call because every execution transition below is
        # CAS-guarded; a mid-flight operator resolution refuses the
        # SUCCEEDED write and stands.
        if prepared is not None:
            privacy_status = prepared.parsed["privacy_status"]
            publish_type = prepared.parsed["publish_type"]
            scheduled_at = prepared.parsed.get("scheduled_at")
            integration_id = prepared.parsed.get("integration_id")
            platform_type = prepared.parsed["social_platform"]
        else:
            privacy_status = context.get("privacy_status") or (context.get("metadata") or {}).get("privacy_status") or "private"
            default_pub_type = "schedule" if context.get("scheduled_at") else ("draft" if is_dry_run else "now")
            publish_type = context.get("publish_type") or default_pub_type
            scheduled_at = context.get("scheduled_at")
            integration_id = context.get("integration_id")
            platform_type = context.get("social_platform") or context.get("platform_type") or "youtube"

        try:
            publish_result = await adapter.publish(
                content_id=upload_result.content_id,
                credentials=auth_result.credentials,
                privacy_status=privacy_status,
                title=title,
                description=description,
                caption=description or title,
                tags=tags or None,
                integration_id=integration_id,
                platform_type=platform_type,
                publish_type=publish_type,
                scheduled_at=scheduled_at,
                is_dry_run=is_dry_run,
            )
        except Exception as exc:  # ambiguity after possible submission → UNKNOWN
            # Ambiguity after external submission may have occurred:
            # durable UNKNOWN — never auto-retried, never FAILED without
            # evidence (ratified §2/§11). If the CAS refuses, an operator
            # resolution already moved the attempt: it stands (H1).
            logger.error("publishing_agent_publish_error", platform=platform, error=str(exc))
            recorded_unknown = True
            if attempt is not None:
                recorded_unknown = await mark_unknown(
                    self._db, attempt, f"publish exception: {type(exc).__name__}"
                )
            suffix = (
                " (attempt recorded UNKNOWN; manual reconciliation required)"
                if recorded_unknown
                else " (attempt already resolved — transition refused)"
            )
            return AgentResult(
                success=False,
                error=f"Publish raised for '{platform}': {exc}{suffix}",
            )
        if not publish_result.success:
            logger.error(
                "publishing_agent_publish_failed",
                platform=platform,
                video_id=video_id,
                error=publish_result.error,
            )
            if attempt is not None:
                await mark_failed(self._db, attempt, f"publish rejected: {publish_result.error}")
            return AgentResult(
                success=False,
                error=f"Publish failed for '{platform}': {publish_result.error}",
            )
        if attempt is not None:
            # External identifiers persisted immediately at confirmed
            # success — independent of the Video writeback below. The
            # CAS refuses if an operator resolution moved the attempt
            # while the publish call was in flight: that resolution
            # stands (H1) — never resurrect it; surface for manual review.
            succeeded_recorded = await mark_succeeded(
                self._db,
                attempt,
                external_post_id=publish_result.published_content_id,
                public_url=publish_result.url,
            )
            if not succeeded_recorded:
                logger.error(
                    "publishing_agent_success_bookkeeping_refused",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                    attempt_status=attempt.status.value,
                    external_post_id=publish_result.published_content_id,
                )
                if attempt.status == PublicationAttemptStatus.SUCCEEDED:
                    # F-11a (ratified): AGREEMENT, not conflict — a
                    # concurrent evidence-based operator resolution already
                    # recorded the same terminal outcome (the refused CAS
                    # refreshed the in-memory attempt). The attempt row is
                    # the system of record: return success with the row's
                    # external ids, surface the agent-observed id as a
                    # warning, and make no provider call, no new attempt,
                    # and no state write.
                    logger.warning(
                        "publishing_agent_success_recorded_concurrently",
                        platform=platform,
                        video_id=video_id,
                        attempt_id=str(attempt.id),
                        recorded_external_post_id=attempt.external_post_id,
                        agent_observed_external_post_id=publish_result.published_content_id,
                    )
                    return AgentResult(
                        success=True,
                        output={
                            "publishing_result": None,
                            "published_video_id": attempt.external_post_id,
                            "public_url": attempt.public_url,
                            "attempt_id": str(attempt.id),
                            "attempt_status": attempt.status.value,
                            "attempt_number": attempt.attempt_number,
                            "writeback_warnings": [
                                "outcome recorded concurrently by an operator "
                                f"resolution; the agent-observed external id "
                                f"{publish_result.published_content_id} was not "
                                "re-recorded (the attempt row holds "
                                f"{attempt.external_post_id})"
                            ],
                        },
                        provider_used=platform,
                        error=None,
                    )
                return AgentResult(
                    success=False,
                    error=f"Publish succeeded externally for '{platform}' "
                    f"(content id {publish_result.published_content_id}), but publication "
                    f"attempt {attempt.attempt_number} is now {attempt.status.value} "
                    "(resolved underneath this execution); the operator resolution stands — "
                    "manual review required",
                )

        # The external publication is now authoritative: SUCCEEDED is
        # durably committed. Every operation below is bookkeeping; a
        # failure in any of them is surfaced as a recovery warning and
        # NEVER reverts the attempt, re-publishes, or reports the
        # publication as failed (F-07).
        writeback_warnings: list[str] = []

        # Update the existing Video row after successful publish.
        status_map = {
            "published": PublishStatus.PUBLISHED,
            "scheduled": PublishStatus.SCHEDULED,
            "draft": PublishStatus.DRAFT,
            "failed": PublishStatus.FAILED,
        }
        db_status = status_map.get(publish_result.publish_status, PublishStatus.PUBLISHED)

        if video_id and publish_result.published_content_id:
            try:
                vid_uuid = UUID(str(video_id))
                await self._db.execute(
                    update(Video)
                    .where(Video.id == vid_uuid)
                    .values(
                        youtube_video_id=publish_result.published_content_id,
                        publish_status=db_status,
                    )
                )
                await self._db.commit()

                logger.info(
                    "video_row_updated",
                    video_id=video_id,
                    youtube_video_id=publish_result.published_content_id,
                    publish_status=db_status.value,
                )
            except (ValueError, TypeError):
                logger.debug("video_id_not_uuid_skipping_row_update", video_id=video_id)
            except Exception as exc:  # post-success bookkeeping must never falsify the publication
                try:
                    await self._db.rollback()
                    # Rollback expires ORM instances; rehydrate the attempt
                    # (best-effort) so later attribute access cannot trip a
                    # lazy load.
                    if attempt is not None:
                        await self._db.refresh(attempt)
                except Exception:  # best-effort session recovery
                    pass
                writeback_warnings.append(
                    f"video writeback failed: {type(exc).__name__}: {exc}"
                )
                logger.error(
                    "publishing_agent_video_writeback_failed",
                    video_id=video_id,
                    published_content_id=publish_result.published_content_id,
                    error=str(exc),
                )

        # Persist provenance in SystemLog if workflow_run_id is attached
        workflow_run_id = context.get("workflow_run_id")
        if workflow_run_id:
            try:
                import json
                from app.models.system import SystemLog
                log_entry = SystemLog(
                    workflow_run_id=UUID(str(workflow_run_id)),
                    event_type="PostPublished" if platform != "postiz" else "PostizPublishDispatched",
                    message=json.dumps({
                        "platform": platform,
                        "video_id": video_id,
                        "published_content_id": publish_result.published_content_id,
                        "publish_status": publish_result.publish_status,
                        "scheduled_at": context.get("scheduled_at"),
                        "social_platform": context.get("social_platform") or "youtube",
                        "is_dry_run": is_dry_run,
                    }),
                    level="info",
                )
                self._db.add(log_entry)
                await self._db.commit()
            except Exception as exc:
                # Post-success provenance bookkeeping failure: recover the
                # session and surface it — never falsify the publication.
                try:
                    await self._db.rollback()
                    if attempt is not None:
                        await self._db.refresh(attempt)
                except Exception:  # best-effort session recovery
                    pass
                writeback_warnings.append(f"provenance log persist failed: {exc}")
                logger.warning("publishing_log_persist_failed", error=str(exc))

        # Fetch the public URL. Post-success (F-07): a failure here is a
        # recovery problem, never a publication failure.
        public_url = None
        if publish_result.published_content_id:
            try:
                public_url = await adapter.fetch_url(
                    published_content_id=publish_result.published_content_id,
                    credentials=auth_result.credentials,
                )
            except Exception as exc:  # post-success recovery problem
                writeback_warnings.append(
                    f"public url fetch failed: {type(exc).__name__}: {exc}"
                )
                logger.warning(
                    "publishing_agent_public_url_fetch_failed",
                    platform=platform,
                    published_content_id=publish_result.published_content_id,
                    error=str(exc),
                )

        publishing_result = PublishingResult(
            platform=platform,
            video_id=video_id,
            published_content_id=publish_result.published_content_id,
            publish_status=publish_result.publish_status,
        )

        logger.info(
            "publishing_agent_succeeded",
            platform=platform,
            video_id=video_id,
            published_content_id=publish_result.published_content_id,
            url=public_url,
        )

        result_output = {
            "publishing_result": publishing_result,
            "published_video_id": publish_result.published_content_id,
        }
        if attempt is not None:
            # Additive: the durable attempt identity for this publication.
            result_output["attempt_id"] = str(attempt.id)
            result_output["attempt_status"] = attempt.status.value
            result_output["attempt_number"] = attempt.attempt_number
            if public_url and attempt.public_url is None:
                from app.services.publication_attempts import _transition

                # Status-preserving CAS bookkeeping (best-effort): only
                # while the attempt still holds its recorded status.
                public_url_persisted = await _transition(
                    self._db, attempt, None, (attempt.status,), public_url=public_url
                )
                if not public_url_persisted:
                    # Surfaced, not swallowed: the attempt moved (operator
                    # resolution) or the commit failed — the publication
                    # itself is unaffected.
                    logger.warning(
                        "publishing_agent_public_url_persist_skipped",
                        attempt_id=str(attempt.id),
                        attempt_status=attempt.status.value,
                    )

        if writeback_warnings:
            # Truthful surfacing (F-07): the publication SUCCEEDED; these
            # are recovery problems for the operator, not publication
            # failures. Absent on the normal path (output unchanged).
            result_output["writeback_warnings"] = writeback_warnings

        # Carry forward context for AnalyticsAgent
        if public_url:
            result_output["public_url"] = public_url
        if platform:
            result_output["platform"] = platform
        topic = context.get("topic")
        if topic:
            result_output["topic"] = topic
        if video_id:
            result_output["video_id"] = video_id
        result_output["aspect_ratio"] = aspect_ratio


        return AgentResult(
            success=True,
            output=result_output,
            provider_used=platform,
            duration_seconds=None,
            error=None,
        )
