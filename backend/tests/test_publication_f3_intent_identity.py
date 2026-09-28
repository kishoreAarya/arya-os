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
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

from app.api.routers.publishing import (
    PublishRequest,
    _F3_INTENT_IDENTITY_NAMESPACE,
    _synthetic_video_id,
    publish_asset,
)
from app.models.publication import PublicationAttempt  # noqa: F401 — registers the table on Base.metadata
from app.platforms.postiz import PostizAdapter


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
    real_video_id = uuid.uuid4()
    kwargs = _payload(asset_storage_path=asset, video_id=str(real_video_id))
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


# ---------------------------------------------------------------------------
# 3. video_id omitted: identical retry resolves to the EXISTING attempt
# ---------------------------------------------------------------------------


def test_f3_duplicate_succeeded_retry_resolves_existing_attempt(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(asset_storage_path=asset)
    synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs)))
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.attempt_status == "succeeded"
        assert second.success is True  # idempotent duplicate, not a second post
        assert second.attempt_id == first.attempt_id  # SAME durable attempt
        assert transport.posts_calls == 1  # provider publish called ONCE
        attempts = _attempts_sync(synthetic)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].video_id == synthetic  # deterministic across requests
    finally:
        _cleanup_sync(synthetic)


# ---------------------------------------------------------------------------
# 4. video_id omitted: PENDING attempt blocks retry (provider untouched)
# ---------------------------------------------------------------------------


def test_f3_pending_attempt_blocks_retry_without_video_id(monkeypatch):
    """A seeded PENDING attempt under the synthetic intent family blocks
    a retry (same admission branch as IN_PROGRESS): the provider is
    never contacted — not even the upload."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(asset_storage_path=asset)
    req = PublishRequest(**kwargs)
    synthetic = uuid.UUID(_synthetic_video_id(req))

    async def _seed():
        from app.services.publication_attempts import admit_attempt

        engine, session = await _session()
        try:
            attempt, created = await admit_attempt(
                session,
                video_id=synthetic,
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
        attempts = _attempts_sync(synthetic)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
    finally:
        _cleanup_sync(synthetic)


# ---------------------------------------------------------------------------
# 5. video_id omitted: UNKNOWN blocks retry (manual operations)
# ---------------------------------------------------------------------------


def test_f3_unknown_blocks_retry_without_video_id(monkeypatch):
    transport = _ScriptedTransport(publish_behavior=("raise", httpx.ReadTimeout("read timed out")))
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(asset_storage_path=asset)
    synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs)))
    try:
        first = _publish(kwargs)
        assert first.success is False
        assert "UNKNOWN" in (first.error or "") or "AMBIGUOUS" in (first.error or "")

        transport.publish_behavior = ("ok", "post-2")
        second = _publish(kwargs)
        assert second.success is False
        assert "manual reconciliation" in (second.error or "")

        assert transport.posts_calls == 1  # the ambiguous dispatch ONLY
        attempts = _attempts_sync(synthetic)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status.value == "unknown"
    finally:
        _cleanup_sync(synthetic)


# ---------------------------------------------------------------------------
# 6. video_id omitted: FAILED -> retry admits attempt_number + 1
# ---------------------------------------------------------------------------


def test_f3_failed_retry_admits_attempt_number_two(monkeypatch):
    transport = _ScriptedTransport(publish_behavior=("status", 400))
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(asset_storage_path=asset)
    synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs)))
    try:
        first = _publish(kwargs)
        assert first.success is False  # provider rejection -> FAILED

        transport.publish_behavior = ("ok", "post-2")
        second = _publish(kwargs)
        assert second.success is True
        assert second.attempt_status == "succeeded"
        assert second.attempt_id != first.attempt_id

        assert transport.posts_calls == 2  # retry legitimately re-dispatches
        attempts = _attempts_sync(synthetic)
        assert [a.attempt_number for a in attempts] == [1, 2]
        assert attempts[0].status.value == "failed"
        assert attempts[1].status.value == "succeeded"
    finally:
        _cleanup_sync(synthetic)


# ---------------------------------------------------------------------------
# 7. video_id omitted: scheduled submission cannot double-schedule
# ---------------------------------------------------------------------------


def test_f3_scheduled_duplicate_protected_without_video_id(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    kwargs = _payload(
        asset_storage_path=asset,
        publish_type="schedule",
        scheduled_at="2026-12-01T10:00:00Z",
    )
    synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs)))
    try:
        first = _publish(kwargs)
        second = _publish(kwargs)

        assert first.success is True
        assert first.publish_status == "scheduled"
        assert second.success is True  # duplicate schedule refused silently
        assert second.attempt_id == first.attempt_id
        assert transport.posts_calls == 1  # ONE scheduled post at the provider
        attempts = _attempts_sync(synthetic)
        assert len(attempts) == 1
    finally:
        _cleanup_sync(synthetic)


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
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = _tmp_video()
    base_kwargs = _payload(asset_storage_path=asset)
    base_synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**base_kwargs)))
    other_full = _payload(asset_storage_path=asset, **other_kwargs)
    other_synthetic = uuid.UUID(_synthetic_video_id(PublishRequest(**other_full)))
    try:
        first = _publish(base_kwargs)
        second = _publish(other_full)

        assert first.success is True
        assert second.success is True
        assert second.attempt_id != first.attempt_id  # distinct intents
        assert transport.posts_calls == 2  # both legitimately dispatched
        assert len(_attempts_sync(base_synthetic)) == 1
        assert len(_attempts_sync(other_synthetic)) == 1
    finally:
        _cleanup_sync(base_synthetic, other_synthetic)


def test_f3_distinct_assets_do_not_collide(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset_a = _tmp_video()
    asset_b = _tmp_video()
    kwargs_a = _payload(asset_storage_path=asset_a)
    kwargs_b = _payload(asset_storage_path=asset_b)
    synthetic_a = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs_a)))
    synthetic_b = uuid.UUID(_synthetic_video_id(PublishRequest(**kwargs_b)))
    try:
        first = _publish(kwargs_a)
        second = _publish(kwargs_b)

        assert first.success is True
        assert second.success is True
        assert second.attempt_id != first.attempt_id
        assert transport.posts_calls == 2
        assert len(_attempts_sync(synthetic_a)) == 1
        assert len(_attempts_sync(synthetic_b)) == 1
    finally:
        _cleanup_sync(synthetic_a, synthetic_b)
