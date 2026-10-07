"""Phase 54B-I5 shared fixtures: a MANIFEST-BOUND approved publish target.

Seeds Project -> WorkflowRun -> Video (storage_path = a REAL artifact) ->
publication manifest (created through the REAL Phase 54B-I4 service from
the persisted records) -> THUMBNAIL checkpoint bound to it -> APPROVE
decision (append-only event + cache refresh, mirroring decide
semantics). This is the minimum authorization state the Phase 54B-I5
dispatch contract accepts for real publishing.

Offline: touches only the local test database and temp files; no
providers are contacted.
"""

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.models.approval import ApprovalCheckpoint, ApprovalDecision
from app.models.enums import ApprovalAction
from app.models.media import Video


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


def _tmp_artifact(data: bytes, suffix: str) -> str:
    path = Path(tempfile.mkstemp(prefix="pub-i5-", suffix=suffix)[1])
    path.write_bytes(data)
    return str(path)


async def _seed_manifest_bound_target(
    *,
    video_path: str | None = None,
    video_bytes: bytes = b"manifest-bound-video-bytes",
    thumbnail_path: str | None = None,
    thumbnail_bytes: bytes = b"manifest-bound-thumb-bytes",
    title: str | None = None,
    description: str | None = None,
    tags: str | None = None,
    aspect_ratio: str | None = None,
    platform: str = "postiz",
    social_platform: str = "youtube",
    integration_id: str | None = "integ-1",
    privacy_status: str = "public",
    publish_type: str = "now",
    scheduled_at: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, str | None]:
    """Returns (run_id, video_id, manifest_id, video_path, thumbnail_path)."""
    from app.models.core import Project, WorkflowRun
    from app.models.media import Thumbnail
    from app.services.publication_manifest_service import create_and_bind_manifest

    if video_path is None:
        video_path = _tmp_artifact(video_bytes, ".mp4")
    if thumbnail_path == "__none__":
        thumbnail_path = None

    engine, session = await _session()
    try:
        project = Project(name=f"i5-{uuid.uuid4().hex[:8]}")
        session.add(project)
        await session.flush()
        run = WorkflowRun(project_id=project.id)
        session.add(run)
        await session.flush()
        thumb_id = None
        if thumbnail_path is not None:
            thumb = Thumbnail(workflow_run_id=run.id, storage_path=thumbnail_path)
            session.add(thumb)
            await session.flush()
            thumb_id = thumb.id
        video = Video(
            workflow_run_id=run.id,
            storage_path=video_path,
            title=title,
            description=description,
            tags=tags,
            aspect_ratio=aspect_ratio,
            thumbnail_id=thumb_id,
        )
        session.add(video)
        await session.commit()
        run_id, video_id = run.id, video.id

        manifest, checkpoint = await create_and_bind_manifest(
            session,
            workflow_run_id=run_id,
            video_id=video_id,
            platform=platform,
            social_platform=social_platform,
            integration_id=integration_id,
            privacy_status=privacy_status,
            publish_type=publish_type,
            scheduled_at=scheduled_at,
        )

        decided_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            ApprovalDecision(
                checkpoint_id=checkpoint.id,
                sequence_number=1,
                action=ApprovalAction.APPROVE,
                decided_at=decided_at,
                decided_by="i5-seeder",
            )
        )
        checkpoint.action = ApprovalAction.APPROVE
        checkpoint.decided_at = decided_at
        await session.commit()
        return run_id, video_id, manifest.id, video_path, thumbnail_path
    finally:
        await session.close()
        await engine.dispose()


def seed_manifest_bound_target(**kwargs):
    def _inner():
        return asyncio.run(_seed_manifest_bound_target(**kwargs))

    return _inner()


async def _cleanup_manifest_bound_target(
    run_id: uuid.UUID, video_id: uuid.UUID, *asset_paths: str
) -> None:
    from app.models.core import Project, WorkflowRun
    from app.models.media import Thumbnail
    from app.models.publication import PublicationAttempt, PublicationManifest
    from sqlalchemy import delete, select

    engine, session = await _session()
    try:
        # Successful dispatches write SystemLog provenance rows that
        # reference workflow_runs (same schema gap the 53B fixtures
        # work around) — remove them first.
        from app.models.system import SystemLog

        await session.execute(
            delete(SystemLog).where(SystemLog.workflow_run_id == run_id)
        )
        await session.execute(
            delete(ApprovalDecision).where(
                ApprovalDecision.checkpoint_id.in_(
                    select(ApprovalCheckpoint.id).where(
                        ApprovalCheckpoint.workflow_run_id == run_id
                    )
                )
            )
        )
        await session.execute(
            delete(PublicationAttempt).where(PublicationAttempt.video_id == video_id)
        )
        await session.execute(
            delete(ApprovalCheckpoint).where(
                ApprovalCheckpoint.workflow_run_id == run_id
            )
        )
        await session.execute(
            delete(PublicationManifest).where(
                PublicationManifest.workflow_run_id == run_id
            )
        )
        video = await session.get(Video, video_id)
        thumb_ids = (
            [video.thumbnail_id] if video is not None and video.thumbnail_id else []
        )
        await session.execute(delete(Video).where(Video.id == video_id))
        if thumb_ids:
            await session.execute(delete(Thumbnail).where(Thumbnail.id.in_(thumb_ids)))
        run = await session.get(WorkflowRun, run_id)
        project_id = run.project_id if run is not None else None
        if run is not None:
            await session.delete(run)
        await session.commit()
        if project_id is not None:
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
                await session.commit()
    finally:
        await session.close()
        await engine.dispose()
    for path in asset_paths:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass


def cleanup_manifest_bound_target(run_id, video_id, *asset_paths):
    asyncio.run(_cleanup_manifest_bound_target(run_id, video_id, *asset_paths))
