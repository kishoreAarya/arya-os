"""Phase 54B-I4 — manifest creation, binding, review, and decide-time
consistency tests.

Real production paths: the REAL FastAPI app (authenticated ASGI
client), REAL models/database, REAL storage provider (local backend),
REAL approval routes and gate. No providers are contacted; artifacts
are real bytes in the local storage root.

This phase does NOT enforce manifests at dispatch — these tests prove
the creation/binding/review/consistency contracts only.
"""

import asyncio
import hashlib
import uuid

import pytest
from app.models.approval import ApprovalCheckpoint, ApprovalDecision
from app.models.enums import ApprovalAction, ApprovalStage
from app.models.media import Video
from app.models.publication import PublicationAttempt, PublicationManifest
from app.services.publication_manifest import verify_stored_manifest
from app.services.publish_gate import PublishApprovalDenied, assert_publish_authorized


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


async def _store_artifact(key: str, data: bytes) -> str:
    from app.storage import get_storage_provider

    engine, session = await _session()
    try:
        return await get_storage_provider().upload(key, data)
    finally:
        await session.close()
        await engine.dispose()


async def _delete_artifact(key: str) -> None:
    from app.storage import get_storage_provider

    engine, session = await _session()
    try:
        await get_storage_provider().delete(key)
    finally:
        await session.close()
        await engine.dispose()


async def _seed_video(
    *,
    with_thumbnail: bool = False,
    aspect_ratio: str | None = "16:9",
    title: str | None = "Manifest Title",
    description: str | None = "Manifest description",
    tags: str | None = "alpha, beta",
    video_bytes: bytes = b"manifest-test-video-bytes",
    thumb_bytes: bytes = b"manifest-test-thumb-bytes",
):
    """Seed Project -> WorkflowRun -> Video (+Thumbnail) with REAL
    artifacts in the storage root. Returns (run_id, video_id, vkey, tkey)."""
    from app.models.core import Project, WorkflowRun
    from app.models.media import Thumbnail

    vkey = f"test-manifests/{uuid.uuid4()}.mp4"
    stored_vkey = await _store_artifact(vkey, video_bytes)
    tkey = None
    if with_thumbnail:
        tkey = f"test-manifests/{uuid.uuid4()}.jpg"
        stored_tkey = await _store_artifact(tkey, thumb_bytes)

    engine, session = await _session()
    try:
        project = Project(name=f"i4-{uuid.uuid4().hex[:8]}")
        session.add(project)
        await session.flush()
        run = WorkflowRun(project_id=project.id)
        session.add(run)
        await session.flush()
        thumb_id = None
        if with_thumbnail:
            thumb = Thumbnail(
                workflow_run_id=run.id,
                storage_path=stored_tkey,
            )
            session.add(thumb)
            await session.flush()
            thumb_id = thumb.id
        video = Video(
            workflow_run_id=run.id,
            storage_path=stored_vkey,
            title=title,
            description=description,
            tags=tags,
            aspect_ratio=aspect_ratio,
            thumbnail_id=thumb_id,
        )
        session.add(video)
        await session.commit()
        return run.id, video.id, stored_vkey, tkey
    finally:
        await session.close()
        await engine.dispose()


async def _cleanup_seed(
    run_id: uuid.UUID, video_id: uuid.UUID, *storage_keys: str
) -> None:
    from app.models.core import Project, WorkflowRun
    from app.models.media import Thumbnail
    from sqlalchemy import delete, select

    engine, session = await _session()
    try:
        video = await session.get(Video, video_id)
        if video is not None and video.thumbnail_id is not None:
            thumb_ids = [video.thumbnail_id]
        else:
            thumb_ids = []
        # FK-respecting order: decisions -> attempts -> checkpoints ->
        # manifests -> thumbnails/videos -> run -> project.
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
    for key in storage_keys:
        if key:
            await _delete_artifact(key)


def _create_payload(run_id, video_id, **overrides):
    base = {
        "workflow_run_id": str(run_id),
        "video_id": str(video_id),
        "platform": "postiz",
        "social_platform": "youtube",
        "integration_id": "integ-42",
        "privacy_status": "public",
        "publish_type": "now",
    }
    base.update(overrides)
    return base


async def _count_manifests(run_id) -> int:
    from sqlalchemy import func, select

    engine, session = await _session()
    try:
        return (
            await session.execute(
                select(func.count())
                .select_from(PublicationManifest)
                .where(PublicationManifest.workflow_run_id == run_id)
            )
        ).scalar()
    finally:
        await session.close()
        await engine.dispose()


async def _decisions_for_checkpoint(checkpoint_id) -> list:
    from sqlalchemy import select

    engine, session = await _session()
    try:
        return list(
            (
                await session.execute(
                    select(ApprovalDecision).where(
                        ApprovalDecision.checkpoint_id == checkpoint_id
                    )
                )
            )
            .scalars()
            .all()
        )
    finally:
        await session.close()
        await engine.dispose()


async def _latest_thumbnail_checkpoint(run_id):
    from sqlalchemy import select

    engine, session = await _session()
    try:
        return (
            (
                await session.execute(
                    select(ApprovalCheckpoint)
                    .where(
                        ApprovalCheckpoint.workflow_run_id == run_id,
                        ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
                    )
                    .order_by(ApprovalCheckpoint.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
    finally:
        await session.close()
        await engine.dispose()


async def _get_checkpoint(checkpoint_id):
    engine, session = await _session()
    try:
        return await session.get(ApprovalCheckpoint, checkpoint_id)
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Creation: authoritative derivation
# ---------------------------------------------------------------------------


async def test_manifest_derived_from_persisted_records(client):
    video_bytes = b"exact-video-bytes-0123456789"
    run_id, video_id, vkey, _ = await _seed_video(video_bytes=video_bytes)
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Artifact identity is the PERSISTED storage key — the request
        # carries no path/URL/digest fields at all (extra=forbid).
        assert body["video_storage_key"] == vkey
        assert body["video_sha256"] == hashlib.sha256(video_bytes).hexdigest()
        assert body["video_size_bytes"] == len(video_bytes)
        # Content metadata comes from the Video row.
        assert body["effective_parameters"]["title"] == "Manifest Title"
        assert body["effective_parameters"]["tags"] == ["alpha", "beta"]
        assert body["effective_parameters"]["integration_id"] == "integ-42"
        # Bound before review: a pending THUMBNAIL checkpoint exists.
        assert body["checkpoint"]["stage"] == "thumbnail"
        assert body["checkpoint"]["action"] is None
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_thumbnail_bytes_included_and_verified(client):
    video_bytes = b"v-bytes"
    thumb_bytes = b"t-bytes"
    run_id, video_id, vkey, tkey = await _seed_video(
        with_thumbnail=True, video_bytes=video_bytes, thumb_bytes=thumb_bytes
    )
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["thumbnail_storage_key"] == tkey
        assert body["thumbnail_sha256"] == hashlib.sha256(thumb_bytes).hexdigest()
        assert body["thumbnail_size_bytes"] == len(thumb_bytes)
    finally:
        await _cleanup_seed(run_id, video_id, vkey, tkey)


async def test_effective_transforms_reflected(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "postiz_default_integration_id",
        "default-integ-9",
        raising=False,
    )
    run_id, video_id, vkey, _ = await _seed_video(
        aspect_ratio="9:16", title="Short", description="Short body", tags="dance"
    )
    try:
        payload = _create_payload(
            run_id,
            video_id,
            integration_id=None,
            scheduled_at="2030-01-01T07:00:00-05:00",
            publish_type="schedule",
        )
        resp = await client.post("/publishing/manifests", json=payload)
        assert resp.status_code == 200, resp.text
        eff = resp.json()["effective_parameters"]
        # The 9:16 transform, mirrored from the dispatch agent.
        assert "#Shorts" in eff["description"]
        assert eff["tags"] == ["dance", "Shorts"]
        assert eff["aspect_ratio"] == "9:16"
        # Postiz default-integration resolution, mirrored from the adapter.
        assert eff["integration_id"] == "default-integ-9"
        # Timestamp normalized to canonical UTC Z form (I1 contract).
        assert eff["scheduled_at"] == "2030-01-01T12:00:00Z"
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_missing_artifact_fails_closed_with_no_manifest(client):
    run_id, video_id, vkey, _ = await _seed_video()
    await _delete_artifact(vkey)
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        assert resp.status_code == 422
        assert "artifact" in resp.json()["detail"].lower()
        # Fail closed: nothing persisted, nothing bound.
        assert await _count_manifests(run_id) == 0
        assert await _latest_thumbnail_checkpoint(run_id) is None
    finally:
        await _cleanup_seed(run_id, video_id)


async def test_unknown_video_and_run_mismatch_rejected(client):
    run_id, video_id, vkey, _ = await _seed_video()
    try:
        resp = await client.post(
            "/publishing/manifests",
            json=_create_payload(run_id, uuid.uuid4()),
        )
        assert resp.status_code == 404
        resp = await client.post(
            "/publishing/manifests",
            json=_create_payload(uuid.uuid4(), video_id),
        )
        assert resp.status_code == 422
        resp = await client.post(
            "/publishing/manifests",
            json=_create_payload(
                run_id,
                video_id,
                platform="youtube",
                scheduled_at="2030-01-01T12:00:00Z",
            ),
        )
        assert resp.status_code == 422  # F-05a parity: youtube scheduling refused
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_canonical_bytes_and_digest_use_i1_module(client):
    video_bytes = b"canonical-check"
    run_id, video_id, vkey, _ = await _seed_video(video_bytes=video_bytes)
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        assert resp.status_code == 200
        digest = resp.json()["manifest_digest"]
        mid = resp.json()["id"]

        engine, session = await _session()
        try:
            row = await session.get(PublicationManifest, uuid.UUID(mid))
            raw, stored_digest = row.canonical_bytes, row.manifest_digest
        finally:
            await session.close()
            await engine.dispose()
        # The I1 verifier accepts the stored bytes and digest as-is.
        parsed = verify_stored_manifest(raw, stored_digest)
        assert parsed["video_sha256"] == hashlib.sha256(video_bytes).hexdigest()
        assert digest == stored_digest
        # The GET review endpoint re-verifies and returns the same digest.
        get_resp = await client.get(f"/publishing/manifests/{mid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["manifest_digest"] == digest
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


# ---------------------------------------------------------------------------
# Binding, review, and decide-time consistency
# ---------------------------------------------------------------------------


async def test_decide_consistency_echo_rules(client):
    run_id, video_id, vkey, _ = await _seed_video()
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        assert resp.status_code == 200
        checkpoint_id = resp.json()["checkpoint"]["id"]
        manifest_id = resp.json()["id"]

        # Omitting the echo on a bound checkpoint: 422, no event.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide", json={"action": "approve"}
        )
        assert r.status_code == 422
        assert await _decisions_for_checkpoint(uuid.UUID(checkpoint_id)) == []

        # A foreign manifest id cannot select or replace the binding: 409.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "approve", "manifest_id": str(uuid.uuid4())},
        )
        assert r.status_code == 409
        assert await _decisions_for_checkpoint(uuid.UUID(checkpoint_id)) == []

        # The correct echo approves; the binding is recorded and stable.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={
                "action": "approve",
                "manifest_id": manifest_id,
                "decided_by": "reviewer-1",
            },
        )
        assert r.status_code == 200, r.text
        events = await _decisions_for_checkpoint(uuid.UUID(checkpoint_id))
        assert len(events) == 1 and events[0].action == ApprovalAction.APPROVE
        checkpoint = await _latest_thumbnail_checkpoint(run_id)
        assert str(checkpoint.publication_manifest_id) == manifest_id
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_revoke_latest_still_denies_gate(client):
    from types import SimpleNamespace

    run_id, video_id, vkey, _ = await _seed_video()
    try:
        resp = await client.post(
            "/publishing/manifests", json=_create_payload(run_id, video_id)
        )
        checkpoint_id = resp.json()["checkpoint"]["id"]
        manifest_id = resp.json()["id"]
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "approve", "manifest_id": manifest_id},
        )
        assert r.status_code == 200
        # REVOKE (with the echo — required on bound checkpoints) becomes
        # the latest decision and denies the existing 53B gate.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "revoke", "manifest_id": manifest_id},
        )
        assert r.status_code == 200, r.text
        events = await _decisions_for_checkpoint(uuid.UUID(checkpoint_id))
        assert [e.action for e in events] == [
            ApprovalAction.APPROVE,
            ApprovalAction.REVOKE,
        ]
        checkpoint = await _latest_thumbnail_checkpoint(run_id)
        assert checkpoint.action == ApprovalAction.REVOKE

        video_row = SimpleNamespace(id=video_id, workflow_run_id=run_id)
        decision_row = SimpleNamespace(action=ApprovalAction.REVOKE, sequence_number=2)

        class _ExecResult:
            def __init__(self, scalar):
                self._scalar = scalar

            def scalar_one_or_none(self):
                return self._scalar

        class _GateSession:
            def __init__(self, *results):
                self._queue = list(results)

            async def execute(self, *_a, **_k):
                return _ExecResult(self._queue.pop(0))

        db = _GateSession(video_row, checkpoint, decision_row, None)
        with pytest.raises(PublishApprovalDenied) as ei:
            await assert_publish_authorized(db, run_id, video_id)
        # The cached REVOKE denies at the gate's step 3; the authoritative
        # history check (step 4) would deny identically. Either code
        # proves revocation still blocks dispatch.
        assert ei.value.reason_code in {
            "checkpoint_revoke",
            "latest_decision_not_approve",
        }
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_approved_binding_immutable_and_new_cycle_on_change(client):
    run_id, video_id, vkey, _ = await _seed_video(video_bytes=b"original-content")
    try:
        first = (
            await client.post(
                "/publishing/manifests", json=_create_payload(run_id, video_id)
            )
        ).json()
        checkpoint_id = first["checkpoint"]["id"]
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "approve", "manifest_id": first["id"]},
        )
        assert r.status_code == 200

        # Content changes: new bytes under the same persisted key.
        await _delete_artifact(vkey)
        await _store_artifact(vkey, b"mutated-content-xyz")
        second = (
            await client.post(
                "/publishing/manifests", json=_create_payload(run_id, video_id)
            )
        ).json()
        assert second["manifest_digest"] != first["manifest_digest"]

        # The approved checkpoint is untouched: still bound to the FIRST
        # manifest, decision history intact (never rewritten).
        refreshed_approved = await _get_checkpoint(uuid.UUID(checkpoint_id))
        assert refreshed_approved.publication_manifest_id == uuid.UUID(first["id"])
        assert refreshed_approved.action == ApprovalAction.APPROVE
        assert len(await _decisions_for_checkpoint(uuid.UUID(checkpoint_id))) == 1

        # A NEW pending cycle was opened for the new manifest.
        new_latest = await _latest_thumbnail_checkpoint(run_id)
        assert new_latest.id != uuid.UUID(checkpoint_id)
        assert new_latest.action is None
        assert new_latest.publication_manifest_id == uuid.UUID(second["id"])
        assert await _count_manifests(run_id) == 2
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_stale_echo_rejected_after_supersession(client):
    run_id, video_id, vkey, _ = await _seed_video()
    try:
        first = (
            await client.post(
                "/publishing/manifests", json=_create_payload(run_id, video_id)
            )
        ).json()
        checkpoint_id = first["checkpoint"]["id"]

        # Newer content while still pending: the undecided checkpoint is
        # REBOUND to the new manifest (supersession).
        await _delete_artifact(vkey)
        await _store_artifact(vkey, b"newer-content")
        second = (
            await client.post(
                "/publishing/manifests", json=_create_payload(run_id, video_id)
            )
        ).json()
        assert await _count_manifests(run_id) == 2
        checkpoint = await _latest_thumbnail_checkpoint(run_id)
        assert checkpoint.id == uuid.UUID(checkpoint_id)
        assert checkpoint.publication_manifest_id == uuid.UUID(second["id"])

        # A reviewer holding the OLD manifest id is rejected BEFORE any
        # event is written (the server-bound manifest is authoritative).
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "approve", "manifest_id": first["id"]},
        )
        assert r.status_code == 409
        assert await _decisions_for_checkpoint(uuid.UUID(checkpoint_id)) == []

        # The current echo approves the CURRENT binding.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "approve", "manifest_id": second["id"]},
        )
        assert r.status_code == 200
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_concurrent_creation_dedupes_and_binds_consistently(client):
    video_bytes = b"concurrent-identical"
    run_id, video_id, vkey, _ = await _seed_video(video_bytes=video_bytes)
    try:
        payload = _create_payload(run_id, video_id)
        first, second = await asyncio.gather(
            client.post("/publishing/manifests", json=payload),
            client.post("/publishing/manifests", json=payload),
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["manifest_digest"] == second.json()["manifest_digest"]
        # Digest dedupe: ONE manifest row for identical derivations.
        assert await _count_manifests(run_id) == 1
        # The single pending checkpoint is bound to it — review and
        # approval cannot diverge.
        checkpoint = await _latest_thumbnail_checkpoint(run_id)
        assert checkpoint.action is None
        assert str(checkpoint.publication_manifest_id) == first.json()["id"]
    finally:
        await _cleanup_seed(run_id, video_id, vkey)


async def test_distinct_intents_are_not_merged(client):
    run_a, vid_a, key_a, _ = await _seed_video(video_bytes=b"video-a")
    run_b, vid_b, key_b, _ = await _seed_video(video_bytes=b"video-b")
    try:
        resp_a = await client.post(
            "/publishing/manifests", json=_create_payload(run_a, vid_a)
        )
        resp_b = await client.post(
            "/publishing/manifests", json=_create_payload(run_b, vid_b)
        )
        assert resp_a.status_code == 200 and resp_b.status_code == 200
        assert resp_a.json()["manifest_digest"] != resp_b.json()["manifest_digest"]
        assert resp_a.json()["id"] != resp_b.json()["id"]
        # Same content, DIFFERENT destination parameters: also distinct.
        resp_c = await client.post(
            "/publishing/manifests",
            json=_create_payload(run_a, vid_a, privacy_status="private"),
        )
        assert resp_c.json()["manifest_digest"] != resp_a.json()["manifest_digest"]
    finally:
        await _cleanup_seed(run_a, vid_a, key_a)
        await _cleanup_seed(run_b, vid_b, key_b)


async def test_legacy_unbound_decisions_unchanged(client):
    """Unbound checkpoints keep the exact pre-I4 decide behavior and
    never silently become content-bound."""
    from app.models.core import Project, WorkflowRun
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        project = Project(name=f"legacy-{uuid.uuid4().hex[:8]}")
        session.add(project)
        await session.flush()
        run = WorkflowRun(project_id=project.id)
        session.add(run)
        await session.commit()
        run_id, project_id = run.id, project.id
    finally:
        await session.close()
        await engine.dispose()

    checkpoint_id = None
    try:
        resp = await client.post(
            "/approvals/",
            json={
                "workflow_run_id": str(run_id),
                "stage": "script",
                "reference_table": "workflow_runs",
                "reference_id": str(run_id),
            },
        )
        assert resp.status_code == 200
        checkpoint_id = resp.json()["id"]
        # No echo required (unbound) — the existing n8n/dashboard flow.
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide", json={"action": "approve"}
        )
        assert r.status_code == 200, r.text
        row = await _get_checkpoint(uuid.UUID(checkpoint_id))
        assert row.publication_manifest_id is None
        # Sending an echo to an UNBOUND checkpoint is a mismatch (409).
        r = await client.post(
            f"/approvals/{checkpoint_id}/decide",
            json={"action": "reject", "manifest_id": str(uuid.uuid4())},
        )
        assert r.status_code == 409
    finally:
        engine, session = await _session()
        try:
            if checkpoint_id is not None:
                await session.execute(
                    delete(ApprovalDecision).where(
                        ApprovalDecision.checkpoint_id == uuid.UUID(checkpoint_id)
                    )
                )
                await session.execute(
                    delete(ApprovalCheckpoint).where(
                        ApprovalCheckpoint.id == uuid.UUID(checkpoint_id)
                    )
                )
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            await session.commit()
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
                await session.commit()
        finally:
            await session.close()
            await engine.dispose()


async def test_review_endpoint_unknown_manifest_404(client):
    resp = await client.get(f"/publishing/manifests/{uuid.uuid4()}")
    assert resp.status_code == 404
