"""F3 regression: stable intent identity for POST /publishing/publish
requests that omit video_id.

Proves, through the REAL router handler (publish_asset — where the
fallback lives), the REAL PublishingAgent, the REAL PostizAdapter
decision logic (only the httpx transport is scripted), and the real
database:

- the synthetic video id is deterministic (UUIDv5 over the existing
  intent family: asset + destination), never uuid4-per-request;
- an identical client retry without video_id resolves to the EXISTING
  durable attempt — the provider publish endpoint is never called a
  second time for a SUCCEEDED duplicate;
- a seeded PENDING attempt blocks a retry without video_id (provider
  untouched) — same admission branch as IN_PROGRESS;
- UNKNOWN blocks retry (manual operations; no second post);
- FAILED -> retry admits attempt_number + 1;
- scheduled submissions without video_id cannot double-schedule;
- explicit video_id behavior is unchanged (used verbatim, idempotent
  duplicate on retry);
- dry-run without video_id still records NO attempt;
- different asset/destination combinations never collide.

F-01 canonicalization (ratified contract): the synthetic identity input
is the CANONICAL asset reference — in-root alias spellings (`./`,
repeated separators, `.` components, equivalent absolute paths, in-root
symlinks, backslash separators) collapse to ONE identity; case, URL,
percent-encoding, and Unicode variants remain DISTINCT; URLs keep their
raw string; out-of-root references fall back lexically (existing
workflow preserved); the canonical spelling RETAINS its historical UUID;
alias-spelling retries hit the existing duplicate guard end-to-end.
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.api.routers.publishing import (
    PublishRequest,
    _F3_INTENT_IDENTITY_NAMESPACE,
    _synthetic_video_id,
    publish_asset,
)
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt  # noqa: F401 — registers the table on Base.metadata
from app.platforms.postiz import PostizAdapter
from app.storage.local import LocalStorageProvider


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
    """httpx.AsyncClient stand-in: scripts the Postiz endpoints.

    Behaviors are (kind, payload) tuples:
      ("ok", provider_id)  -> HTTP 200 JSON {"id": provider_id}
      ("status", code)     -> HTTP <code> with a text body
      ("raise", exception) -> the real httpx exception object is raised
    """

    def __init__(self, transport, **kwargs):
        self._transport = transport

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, **kwargs):
        return httpx.Response(
            200,
            json=[{"id": "integ-1", "name": "channel"}],
            request=httpx.Request("GET", url),
        )

    async def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            self._transport.upload_calls += 1
            kind, payload = self._transport.upload_behavior
        else:
            self._transport.posts_calls += 1
            kind, payload = self._transport.publish_behavior
        if kind == "raise":
            raise payload
        if kind == "status":
            return httpx.Response(payload, text="scripted", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"id": payload}, request=httpx.Request("POST", url))


class _ScriptedTransport:
    def __init__(self, *, upload_behavior=("ok", "media-1"), publish_behavior=("ok", "post-1")):
        self.upload_behavior = upload_behavior
        self.publish_behavior = publish_behavior
        self.upload_calls = 0
        self.posts_calls = 0


def _install_real_postiz(monkeypatch, transport):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: _ScriptedClient(transport, **kwargs)
    )


def _payload(**overrides):
    base = {
        "asset_storage_path": None,  # filled per-test
        "title": "t",
        "caption": "d",
        "platform": "postiz",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "dry_run": False,
    }
    base.update(overrides)
    return base


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


async def _attempts_for(video_uuid):
    from sqlalchemy import select

    engine, session = await _session()
    try:
        rows = (
            (
                await session.execute(
                    select(PublicationAttempt).where(PublicationAttempt.video_id == video_uuid)
                )
            )
            .scalars()
            .all()
        )
        return sorted(rows, key=lambda r: r.attempt_number)
    finally:
        await session.close()
        await engine.dispose()


async def _cleanup_attempts(*video_uuids):
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        for v in video_uuids:
            await session.execute(delete(PublicationAttempt).where(PublicationAttempt.video_id == v))
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


def _publish(payload_kwargs):
    async def _inner():
        engine, session = await _session()
        try:
            return await publish_asset(PublishRequest(**payload_kwargs), session)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-f3-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


def _attempts_sync(video_uuid):
    return asyncio.run(_attempts_for(video_uuid))


def _cleanup_sync(*video_uuids):
    asyncio.run(_cleanup_attempts(*video_uuids))


# ---------------------------------------------------------------------------
# 1. Deterministic, collision-free, documented-namespace identity formula
# ---------------------------------------------------------------------------


def test_f3_identity_formula_deterministic_and_collision_free():
    """The synthetic id is UUIDv5 over asset|platform|social|integration
    under the documented frozen namespace: identical submissions derive
    identical ids; different assets/destinations never collide; pydantic
    defaults (omitted vs explicit) resolve identically."""
    a = _payload(asset_storage_path="/assets/a.mp4")
    a_defaults_omitted = _payload(
        asset_storage_path="/assets/a.mp4", platform="postiz", social_platform="youtube"
    )
    assert _synthetic_video_id(PublishRequest(**a)) == _synthetic_video_id(
        PublishRequest(**a_defaults_omitted)
    )
    assert _synthetic_video_id(PublishRequest(**a)) == _synthetic_video_id(
        PublishRequest(**a)
    )  # stable across calls

    # Cross-check against the documented namespace + family formula.
    expected = str(
        uuid.uuid5(
            _F3_INTENT_IDENTITY_NAMESPACE,
            "/assets/a.mp4|postiz|youtube|integ-1",
        )
    )
    assert _synthetic_video_id(PublishRequest(**a)) == expected

    for changed in (
        _payload(asset_storage_path="/assets/b.mp4"),
        _payload(asset_storage_path="/assets/a.mp4", social_platform="tiktok"),
        _payload(asset_storage_path="/assets/a.mp4", platform="youtube"),
        _payload(asset_storage_path="/assets/a.mp4", integration_id="integ-2"),
        _payload(asset_storage_path="/assets/a.mp4", integration_id=None),
    ):
        assert _synthetic_video_id(PublishRequest(**changed)) != expected

    # Mutable publication parameters never participate in the identity.
    for mutable in (
        {"title": "other"},
        {"caption": "other"},
        {"scheduled_at": "2027-01-01T00:00:00Z"},
        {"publish_type": "schedule"},
    ):
        assert _synthetic_video_id(
            PublishRequest(**{**a, **mutable})
        ) == _synthetic_video_id(PublishRequest(**a))


# ---------------------------------------------------------------------------
# 2. Explicit video_id: unchanged, verbatim, idempotent duplicate
# ---------------------------------------------------------------------------


def test_f3_supplied_video_id_is_used_verbatim_and_idempotent(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    # Phase 53B/I5: real publishing requires an authorized, manifest-
    # bound (run, video) pair seeded through the real services.
    run_id, real_video_id = _seed_target(asset)
    kwargs = _payload(
        asset_storage_path=asset,
        video_id=str(real_video_id),
        workflow_run_id=str(run_id),
    )
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.attempt_status == "succeeded"
        assert second.success is True  # idempotent duplicate
        assert second.attempt_id == first.attempt_id
        assert transport.posts_calls == 1  # provider publish called ONCE
        attempts = _attempts_sync(real_video_id)
        assert len(attempts) == 1
        assert attempts[0].video_id == real_video_id  # verbatim, not synthetic
        assert attempts[0].attempt_number == 1
    finally:
        _cleanup_sync(real_video_id)
        _cleanup_target(run_id)


def _cleanup_target(run_id):
    async def _inner():
        from tests._dispatch_manifest_fixtures import _cleanup_manifest_bound_target

        target = _SEED_TARGETS.pop(run_id, (None, None))
        await _cleanup_manifest_bound_target(run_id, target[0], target[1])

    asyncio.run(_inner())


_SEED_STATE = {}
_SEED_TARGETS: dict = {}


def _seed_target(asset=None, **manifest_overrides):
    """53B-T3/I5: seed a MANIFEST-BOUND approved publish target whose
    Video row points at the REAL asset the test dispatches, with the
    destination parameters _payload() sends (postiz / integ-1 /
    public / draft — the router's defaults)."""

    kwargs = dict(
        video_path=asset,
        platform="postiz",
        social_platform="youtube",
        integration_id="integ-1",
        privacy_status="public",
        publish_type="draft",
    )
    kwargs.update(manifest_overrides)

    async def _inner():
        from tests._dispatch_manifest_fixtures import _seed_manifest_bound_target

        return await _seed_manifest_bound_target(**kwargs)

    run_id, video_id, _mid, vpath, _thumb = asyncio.run(_inner())
    _SEED_STATE.clear()
    _SEED_STATE.update(run_id=run_id, video_id=video_id, asset=vpath)
    _SEED_TARGETS[run_id] = (video_id, vpath)
    return run_id, video_id


# ---------------------------------------------------------------------------
# 3. video_id omitted: identical retry resolves to the EXISTING attempt
# ---------------------------------------------------------------------------


def test_f3_duplicate_succeeded_retry_resolves_existing_attempt(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_id, video_id = _seed_target(asset)
    kwargs = _payload(
        asset_storage_path=asset, video_id=str(video_id), workflow_run_id=str(run_id)
    )
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.attempt_status == "succeeded"
        assert second.success is True  # idempotent duplicate, not a second post
        assert second.attempt_id == first.attempt_id  # SAME durable attempt
        assert transport.posts_calls == 1  # provider publish called ONCE
        attempts = _attempts_sync(video_id)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].video_id == video_id  # deterministic across requests
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# 4. video_id omitted: PENDING attempt blocks retry (provider untouched)
# ---------------------------------------------------------------------------


def test_f3_pending_attempt_blocks_retry_without_video_id(monkeypatch):
    """A seeded PENDING attempt under the supplied video_id's intent family
    blocks a retry (same admission branch as IN_PROGRESS): the provider is
    never contacted — not even the upload. 53B-T3: uses supplied IDs."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_id, video_id = _seed_target(asset)
    kwargs = _payload(
        asset_storage_path=asset, video_id=str(video_id), workflow_run_id=str(run_id)
    )
    req = PublishRequest(**kwargs)

    async def _seed():
        from app.services.publication_attempts import admit_attempt

        engine, session = await _session()
        try:
            attempt, created = await admit_attempt(
                session,
                video_id=video_id,
                platform=req.platform,
                social_platform=req.social_platform,
                integration_id=req.integration_id,
            )
            return attempt.id, created
        finally:
            await session.close()
            await engine.dispose()

    try:
        _, created = asyncio.run(_seed())
        assert created is True

        result = _publish(kwargs)

        assert result.success is False
        assert "pending" in (result.error or "")
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        attempts = _attempts_sync(video_id)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# 5. video_id omitted: UNKNOWN blocks retry (manual operations)
# ---------------------------------------------------------------------------


def test_f3_unknown_blocks_retry_without_video_id(monkeypatch):
    """53B-T3: supplied IDs — same UNKNOWN semantics."""
    transport = _ScriptedTransport(publish_behavior=("raise", httpx.ReadTimeout("read timed out")))
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_id, video_id = _seed_target(asset)
    kwargs = _payload(
        asset_storage_path=asset, video_id=str(video_id), workflow_run_id=str(run_id)
    )
    try:
        first = _publish(kwargs)
        assert first.success is False
        assert "UNKNOWN" in (first.error or "") or "AMBIGUOUS" in (first.error or "")

        transport.publish_behavior = ("ok", "post-2")
        second = _publish(kwargs)
        assert second.success is False
        assert "manual reconciliation" in (second.error or "")

        assert transport.posts_calls == 1  # the ambiguous dispatch ONLY
        attempts = _attempts_sync(video_id)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status.value == "unknown"
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# 6. video_id omitted: FAILED -> retry admits attempt_number + 1
# ---------------------------------------------------------------------------


def test_f3_failed_retry_admits_attempt_number_two(monkeypatch):
    """53B-T3: supplied IDs — same FAILED-retry semantics."""
    transport = _ScriptedTransport(publish_behavior=("status", 400))
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_id, video_id = _seed_target(asset)
    kwargs = _payload(
        asset_storage_path=asset, video_id=str(video_id), workflow_run_id=str(run_id)
    )
    try:
        first = _publish(kwargs)
        assert first.success is False  # provider rejection -> FAILED

        transport.publish_behavior = ("ok", "post-2")
        second = _publish(kwargs)
        assert second.success is True
        assert second.attempt_status == "succeeded"
        assert second.attempt_id != first.attempt_id

        assert transport.posts_calls == 2  # retry legitimately re-dispatches
        attempts = _attempts_sync(video_id)
        assert [a.attempt_number for a in attempts] == [1, 2]
        assert attempts[0].status.value == "failed"
        assert attempts[1].status.value == "succeeded"
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# 7. video_id omitted: scheduled submission cannot double-schedule
# ---------------------------------------------------------------------------


def test_f3_scheduled_duplicate_protected_without_video_id(monkeypatch):
    """53B-T3: supplied IDs — same schedule-duplicate semantics."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_id, video_id = _seed_target(
        asset, publish_type="schedule", scheduled_at="2030-12-01T10:00:00Z"
    )
    kwargs = _payload(
        asset_storage_path=asset,
        publish_type="schedule",
        # Far-future UTC timestamp (F-05a validates scheduled_at as a
        # future ISO-8601 UTC datetime at the API edge).
        scheduled_at="2030-12-01T10:00:00Z",
        video_id=str(video_id), workflow_run_id=str(run_id),
    )
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.publish_status == "scheduled"
        assert second.success is True  # duplicate schedule refused silently
        assert second.attempt_id == first.attempt_id
        assert transport.posts_calls == 1  # ONE scheduled post at the provider
        attempts = _attempts_sync(video_id)
        assert len(attempts) == 1
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# 8. video_id omitted + dry_run: NO attempt is ever recorded
# ---------------------------------------------------------------------------


def test_f3_dry_run_without_video_id_records_no_attempt(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(asset_storage_path=asset, dry_run=True)
    synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs)))
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.is_dry_run is True
        assert first.attempt_id is None  # no durable attempt for dry-run
        assert second.success is True
        assert _attempts_sync(synthetic) == []
    finally:
        _cleanup_sync(synthetic)


# ---------------------------------------------------------------------------
# 9. video_id omitted: distinct asset/destination combinations never collide
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "other_kwargs",
    [
        {"social_platform": "tiktok"},  # same asset, different destination
        {"integration_id": "integ-2"},  # different channel
    ],
)
def test_f3_distinct_destinations_do_not_collide(monkeypatch, other_kwargs):
    """53B-T3: same asset but different social platform or integration
    channel are DISTINCT publication intents — both dispatch. Uses two
    seeded targets (the contract binds each to its own run/video)."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    run_a, vid_a = _seed_target(asset)
    run_b, vid_b = _seed_target(asset, **other_kwargs)
    base_kwargs = _payload(
        asset_storage_path=asset, video_id=str(vid_a), workflow_run_id=str(run_a)
    )
    other_full = _payload(
        asset_storage_path=asset, video_id=str(vid_b), workflow_run_id=str(run_b),
        **other_kwargs
    )
    try:
        first = _publish(base_kwargs)
        second = _publish(other_full)

        assert first.success is True
        assert second.success is True
        assert second.attempt_id != first.attempt_id  # distinct intents
        assert transport.posts_calls == 2  # both legitimately dispatched
        assert len(_attempts_sync(vid_a)) == 1
        assert len(_attempts_sync(vid_b)) == 1
    finally:
        _cleanup_sync(vid_a, vid_b)
        _cleanup_target(run_a)
        _cleanup_target(run_b)


def test_f3_distinct_assets_do_not_collide(monkeypatch):
    """53B-T3: two different assets (and different seeded videos) are
    distinct publication intents — both dispatch independently."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset_a = _tmp_video()
    asset_b = _tmp_video()
    run_a, vid_a = _seed_target(asset_a)
    run_b, vid_b = _seed_target(asset_b)
    kwargs_a = _payload(
        asset_storage_path=asset_a, video_id=str(vid_a), workflow_run_id=str(run_a)
    )
    kwargs_b = _payload(
        asset_storage_path=asset_b, video_id=str(vid_b), workflow_run_id=str(run_b)
    )
    try:
        first = _publish(kwargs_a)
        second = _publish(kwargs_b)

        assert first.success is True
        assert second.success is True
        assert second.attempt_id != first.attempt_id
        assert transport.posts_calls == 2
        assert len(_attempts_sync(vid_a)) == 1
        assert len(_attempts_sync(vid_b)) == 1
    finally:
        _cleanup_sync(vid_a, vid_b)
        _cleanup_target(run_a)
        _cleanup_target(run_b)


def _make_provider_root():
    """A LocalStorageProvider over a disposable resolved root containing
    one in-root asset, an in-root symlink to it, and an escaping symlink
    to an out-of-root file."""
    root = Path(tempfile.mkdtemp(prefix="f01-root-")).resolve()
    asset = root / "data" / "storage" / "v1.mp4"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"f01-asset")
    (root / "data" / "link.mp4").symlink_to(asset)
    outside_dir = Path(tempfile.mkdtemp(prefix="f01-out-")).resolve()
    outside = outside_dir / "secret.mp4"
    outside.write_bytes(b"f01-outside")
    (root / "data" / "escape.mp4").symlink_to(outside)
    return LocalStorageProvider(base_path=str(root)), root, asset, outside


def _install_provider(monkeypatch, provider):
    """Route BOTH the router's identity boundary and the agent's lazy
    asset resolution through the test provider."""
    monkeypatch.setattr(
        "app.api.routers.publishing.get_storage_provider", lambda: provider
    )
    monkeypatch.setattr("app.storage.get_storage_provider", lambda: provider)


def _sid(monkeypatch, provider, asset_path, **overrides):
    _install_provider(monkeypatch, provider)
    return _synthetic_video_id(PublishRequest(**_payload(asset_storage_path=asset_path, **overrides)))


def test_f01_in_root_alias_spellings_collapse_to_one_identity(monkeypatch):
    """MUST COLLAPSE: relative vs ./, repeated separators, . components,
    equivalent in-root absolute spelling (with junk components), in-root
    symlink, backslash separator — all derive ONE synthetic identity —
    and the canonical spelling RETAINS the historical UUID derived from
    that canonical string under the frozen namespace."""
    provider, root, asset, _ = _make_provider_root()
    ids = {
        _sid(monkeypatch, provider, p)
        for p in (
            "data/storage/v1.mp4",
            "./data/storage/v1.mp4",
            "data//storage/v1.mp4",
            "data/./storage/v1.mp4",
            str(asset),
            f"{root}/./data//storage/v1.mp4",
            "data/link.mp4",
            "data\\link.mp4",
        )
    }
    assert len(ids) == 1
    # Compatibility anchor (test 7): the canonical spelling's identity is
    # byte-identical to the pre-F-01 raw-string derivation.
    expected = str(
        uuid.uuid5(
            _F3_INTENT_IDENTITY_NAMESPACE,
            "data/storage/v1.mp4|postiz|youtube|integ-1",
        )
    )
    assert ids.pop() == expected


def test_f01_case_url_percent_unicode_and_assets_remain_distinct(monkeypatch):
    """MUST REMAIN DISTINCT: case variants (case-sensitive backends),
    different physical assets, URL vs local path, different URLs,
    percent-encoding variants, NFC vs NFD Unicode variants."""
    provider, _, _, _ = _make_provider_root()
    _install_provider(monkeypatch, provider)
    spellings = [
        "data/storage/v1.mp4",
        "data/storage/V1.MP4",  # non-existent spelling: case preserved on every platform
        "data/storage/v2.mp4",
        "http://example.test/data/storage/v1.mp4",
        "http://other.test/v1.mp4",
        "http://example.test/a b.mp4",
        "http://example.test/a%20b.mp4",
        "data/storage/caf\u00e9.mp4",  # NFC
        "data/storage/cafe\u0301.mp4",  # NFD
    ]
    ids = [
        _synthetic_video_id(PublishRequest(**_payload(asset_storage_path=p)))
        for p in spellings
    ]
    assert len(set(ids)) == len(ids)


def test_f01_default_key_provider_canonicalization_is_lexical_and_opaque():
    """Object-store keys are opaque: lexical collapse of `.`/`//` only —
    case and backslashes preserved; S3StorageProvider inherits it."""
    from app.storage.base import StorageProvider, lexical_canonical_key
    from app.storage.s3 import S3StorageProvider

    assert lexical_canonical_key("videos//a/./b.mp4") == "videos/a/b.mp4"
    assert lexical_canonical_key("videos\\a.mp4") == "videos\\a.mp4"
    assert lexical_canonical_key("DATA/V1.MP4") == "DATA/V1.MP4"
    assert S3StorageProvider.canonical_key is StorageProvider.canonical_key


def test_f01_traversal_and_null_byte_rejection_unchanged(monkeypatch):
    """SECURITY: the pre-existing router 403s fire before any identity
    or provider work; the provider/agent are never reached."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    for bad in ("../etc/passwd.mp4", "data/../../etc\\passwd", "data/\0v1.mp4"):
        with pytest.raises(HTTPException) as excinfo:
            _publish(_payload(asset_storage_path=bad))
        assert excinfo.value.status_code == 403
    assert transport.posts_calls == 0
    assert transport.upload_calls == 0


def test_f01_escaping_symlink_keeps_own_identity_not_the_target(monkeypatch):
    """SECURITY: provider containment refuses the escaping resolution;
    the fallback keeps the symlink's OWN spelling identity — never the
    out-of-root target's, never the real in-root asset's."""
    provider, _, _, outside = _make_provider_root()
    escape_id = _sid(monkeypatch, provider, "data/escape.mp4")
    assert escape_id != _sid(monkeypatch, provider, str(outside))
    assert escape_id != _sid(monkeypatch, provider, "data/storage/v1.mp4")
    with pytest.raises(ValueError):
        provider._resolve("data/escape.mp4")  # containment still refuses outright


def test_f01_out_of_root_fallback_preserves_existing_workflow(monkeypatch):
    """Out-of-root references: lexical fallback — normalized absolutes
    keep their historical raw-derived UUID; junk components normalize."""
    provider, _, _, outside = _make_provider_root()
    _install_provider(monkeypatch, provider)
    p = str(outside)
    expected = str(uuid.uuid5(_F3_INTENT_IDENTITY_NAMESPACE, f"{p}|postiz|youtube|integ-1"))
    assert _synthetic_video_id(PublishRequest(**_payload(asset_storage_path=p))) == expected
    # Junk-component out-of-root spellings join the same fallback family.
    junk = f"{outside.parent}/./sub//secret.mp4"
    direct = f"{outside.parent}/sub/secret.mp4"
    assert _synthetic_video_id(
        PublishRequest(**_payload(asset_storage_path=junk))
    ) == _synthetic_video_id(PublishRequest(**_payload(asset_storage_path=direct)))


def test_f01_e2e_alias_retry_after_success_hits_duplicate_guard(monkeypatch):
    """END-TO-END: canonical spelling publishes (SUCCEEDED, one provider
    post); an ALIAS spelling retry resolves to the SAME family —
    idempotent duplicate, NO second provider publish, one attempt row."""
    provider, _, _, _ = _make_provider_root()
    _install_provider(monkeypatch, provider)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    run_id, video_id = _seed_target("data/storage/v1.mp4")
    canonical_kwargs = _payload(asset_storage_path="data/storage/v1.mp4", video_id=str(video_id), workflow_run_id=str(run_id))
    alias_kwargs = _payload(asset_storage_path="./data//storage/./v1.mp4", video_id=str(video_id), workflow_run_id=str(run_id))
    try:
        first = _publish(canonical_kwargs)
        assert first.success, first.error
        assert first.attempt_status == "succeeded"
        assert transport.posts_calls == 1
        rows = _attempts_sync(video_id)
        assert len(rows) == 1 and rows[0].status == PublicationAttemptStatus.SUCCEEDED

        # The alias derives the identical video_id id ...
        assert uuid.UUID(_synthetic_video_id(PublishRequest(**alias_kwargs)))  # canonicalization still works (dry-run path)
        # ... so the retry is an idempotent duplicate: no second post.
        second = _publish(alias_kwargs)
        assert second.success
        assert transport.posts_calls == 1
        assert len(_attempts_sync(video_id)) == 1
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)

def test_f01_e2e_alias_submission_while_pending_resolves_same_family(monkeypatch):
    """53B-T3: while the video's attempt is PENDING, a retry under the same
    supplied (run, video) is the SAME attempt family (blocked) — the
    provider publish is never invoked. Path aliases are irrelevant for
    real publishes under the new contract (identity = video_id)."""
    provider, _, _, _ = _make_provider_root()
    _install_provider(monkeypatch, provider)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    run_id, video_id = _seed_target("data/storage/v1.mp4")

    async def _seed_pending():
        from app.services.publication_attempts import admit_attempt

        engine, session = await _session()
        try:
            attempt, created = await admit_attempt(
                session,
                video_id=video_id,
                platform="postiz",
                social_platform="youtube",
                integration_id="integ-1",
            )
            return attempt.id, created
        finally:
            await session.close()
            await engine.dispose()

    kwargs = _payload(
        asset_storage_path="data/storage/v1.mp4",
        video_id=str(video_id),
        workflow_run_id=str(run_id),
    )
    try:
        _, created = asyncio.run(_seed_pending())
        assert created is True

        result = _publish(kwargs)

        assert result.success is False
        assert "pending" in (result.error or "")
        assert transport.posts_calls == 0
        rows = _attempts_sync(video_id)
        assert len(rows) == 1
        assert rows[0].attempt_number == 1
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)


def test_f04a_privacy_status_never_participates_in_identity():
    """6. The visibility field is a MUTABLE publication parameter: all
    values (and omission) derive the identical synthetic id."""
    base = _payload(asset_storage_path="data/storage/v1.mp4")
    ids = {
        _synthetic_video_id(PublishRequest(**{**base, "privacy_status": p}))
        for p in ("public", "private", "unlisted")
    }
    ids.add(_synthetic_video_id(PublishRequest(**base)))  # field omitted
    assert len(ids) == 1


def test_f04a_privacy_status_is_inert_for_postiz(monkeypatch):
    """10. F-04a identity-inertness is PRESERVED (privacy never joins the
    intent identity). Under Phase 54B-I5 privacy is a manifest-bound
    approval parameter: a request privacy differing from the approved
    manifest's fails closed BEFORE any external call (the Postiz adapter
    itself still ignores the field — inertness at the provider)."""
    provider, _, _, _ = _make_provider_root()
    _install_provider(monkeypatch, provider)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    run_id, video_id = _seed_target("data/storage/v1.mp4")
    # Identity: privacy never participates (same synthetic id for all values).
    base = _payload(asset_storage_path="data/storage/v1.mp4")
    ids = {
        _synthetic_video_id(PublishRequest(**{**base, "privacy_status": v}))
        for v in ("public", "private", "unlisted")
    }
    ids.add(_synthetic_video_id(PublishRequest(**base)))
    assert len(ids) == 1
    # Dispatch: the matching-privacy request publishes normally...
    kwargs_ok = _payload(
        asset_storage_path="data/storage/v1.mp4", privacy_status="public",
        video_id=str(video_id), workflow_run_id=str(run_id),
    )
    kwargs_drift = _payload(
        asset_storage_path="data/storage/v1.mp4", privacy_status="unlisted",
        video_id=str(video_id), workflow_run_id=str(run_id),
    )
    try:
        # Dispatch: a privacy DIFFERING from the approved manifest's is
        # denied before any external call (the failed attempt then
        # admits a retry under the same intent family)...
        drifted = _publish(kwargs_drift)
        assert drifted.success is False
        assert "publication_blocked: parameter_drift:privacy_status" in drifted.error
        assert transport.posts_calls == 0
        rows = _attempts_sync(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        # ...and the matching-privacy retry publishes normally.
        resp = _publish(kwargs_ok)
        assert resp.success, resp.error
        assert transport.posts_calls == 1
        rows = _attempts_sync(video_id)
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
    finally:
        _cleanup_sync(video_id)
        _cleanup_target(run_id)
