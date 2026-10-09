"""Step-3 regression: publication intent identity must be canonical.

Finding (Step-2 review of PR #15): the admission intent key was derived
from REQUEST-SUPPLIED destination values, while dispatch authority is
the approved MANIFEST's destination. The one nullable destination
field, integration_id, could therefore mint two intent families for
the SAME approved publication:

  Request A: integration_id omitted  -> intent key "...|"
  Request B: integration_id = "X"    -> intent key "...|X"

Both requests passed manifest verification (omission defers to the
manifest's value; an explicit value equal to the manifest's is
accepted), and the same approved checkpoint/manifest authorized BOTH
families — two external publications of the same approved content.

These tests pin the SAFE behavior: requests that differ only in
omitted-vs-explicit integration_id resolve to ONE attempt family with
exactly one external publish, and any post-success request of either
spelling resolves through the duplicate guard instead of publishing
again. The mismatched-value denial itself is already covered by
test_publication_dispatch_enforcement.py::test_destination_parameter_drift_denies_dispatch
(the integration_id parametrize case).
"""

from app.models.enums import PublicationAttemptStatus
from tests.test_publication_dispatch_enforcement import (
    _ScriptedTransport,
    _attempts_for,
    _cleanup,
    _ctx,
    _install_real_postiz,
    _run_agent,
    _seed,
)


def test_explicit_then_omitted_integration_id_share_one_intent(monkeypatch):
    """Publish with integration_id="integ-1" (matching the approved
    manifest), then submit the identical publication with integration_id
    OMITTED. Both describe the same approved destination, so the second
    request must resolve to the existing attempt (duplicate) — never a
    second external publication."""
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"intent-regression-a")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        first = _run_agent(_ctx(run_id, video_id, asset))
        assert first.success, first.error

        second = _run_agent(_ctx(run_id, video_id, asset, integration_id=None))

        assert transport.posts_calls == 1, (
            "UNSAFE: the omitted-integration_id request performed a second "
            "external publish"
        )
        assert (
            transport.upload_calls == 1
        ), "UNSAFE: the omitted-integration_id request performed a second upload"
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED], (
            f"UNSAFE: distinct attempt families were created: "
            f"{[(r.intent_key, r.status.value) for r in rows]}"
        )
        assert len({r.intent_key for r in rows}) == 1, (
            "UNSAFE: equivalent requests minted different intent keys: "
            f"{sorted({r.intent_key for r in rows})}"
        )
        assert second.success, second.error
        assert second.output.get("duplicate") is True
    finally:
        _cleanup(run_id, video_id, asset)


def test_omitted_then_explicit_integration_id_share_one_intent(monkeypatch):
    """The reverse order: the first submission OMITS integration_id, the
    retry supplies it explicitly with the manifest's value. Same
    invariant: one attempt family, one external publish."""
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"intent-regression-b")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        first = _run_agent(_ctx(run_id, video_id, asset, integration_id=None))
        assert first.success, first.error

        second = _run_agent(_ctx(run_id, video_id, asset))

        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert (
            len({r.intent_key for r in rows}) == 1
        ), f"UNSAFE: {sorted({r.intent_key for r in rows})}"
        assert second.success, second.error
        assert second.output.get("duplicate") is True
    finally:
        _cleanup(run_id, video_id, asset)


def test_omitted_twice_resolves_as_duplicate(monkeypatch):
    """Both requests omit integration_id: the classic duplicate path
    (same intent key) must hold regardless of the canonicalization."""
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"intent-regression-c")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        first = _run_agent(_ctx(run_id, video_id, asset, integration_id=None))
        assert first.success, first.error
        second = _run_agent(_ctx(run_id, video_id, asset, integration_id=None))
        assert second.success, second.error
        assert second.output.get("duplicate") is True
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
    finally:
        _cleanup(run_id, video_id, asset)


def test_mismatched_integration_id_after_success_never_republishes(monkeypatch):
    """After a successful publication, a request carrying a WRONG
    integration_id must never create a second external publish. Under
    canonical intent identity it resolves through the duplicate guard
    (the approved publication stands); it must not mint a new family
    that reaches the adapter."""
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"intent-regression-d")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        first = _run_agent(_ctx(run_id, video_id, asset))
        assert first.success, first.error

        mismatched = _run_agent(_ctx(run_id, video_id, asset, integration_id="integ-9"))

        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED], (
            f"a mismatched-integration request changed the attempt ledger: "
            f"{[(r.intent_key, r.status.value) for r in rows]}"
        )
        # Either a duplicate resolution or a denial is acceptable — what
        # is pinned is that no second publication happened and no second
        # family was minted.
        assert mismatched.success is False or mismatched.output.get("duplicate") is True
    finally:
        _cleanup(run_id, video_id, asset)
