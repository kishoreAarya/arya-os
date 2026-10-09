"""Phase 54B-I1 — publication-manifest canonicalization unit tests.

Offline only: no database, no providers, no publishing. Pins the
canonical serialization, digest domain separation, strict schema
rejections, fail-closed verification, model additivity, and the
unchanged THUMBNAIL authorization contract.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from app.models.enums import ApprovalStage
from app.services.publication_manifest import (
    PublicationManifestError,
    build_manifest,
    canonical_bytes,
    manifest_digest,
    normalize_timestamp,
    verify_stored_manifest,
)
from app.services.publish_gate import AUTHORIZING_STAGE

RUN = uuid.uuid4()
VIDEO = uuid.uuid4()
VIDEO_SHA = "a" * 64
THUMB_SHA = "b" * 64


def _manifest(**overrides):
    base = {
        "workflow_run_id": RUN,
        "video_id": VIDEO,
        "video_storage_path": "storage/videos/final.mp4",
        "video_sha256": VIDEO_SHA,
        "video_size_bytes": 1_048_576,
        "title": "Test Title",
        "description": "Test description",
        "tags": ["alpha", "beta"],
        "platform": "youtube",
        "social_platform": "youtube",
        "privacy_status": "public",
        "publish_type": "now",
        "aspect_ratio": "16:9",
    }
    base.update(overrides)
    return build_manifest(**base)


def _roundtrip(manifest):
    cb = canonical_bytes(manifest)
    return cb, manifest_digest(cb)


# ---------------------------------------------------------------------------
# Determinism and digest sensitivity
# ---------------------------------------------------------------------------


def test_identical_manifests_produce_identical_bytes_and_digest():
    a = _manifest()
    b = _manifest()
    assert canonical_bytes(a) == canonical_bytes(b)
    assert manifest_digest(canonical_bytes(a)) == manifest_digest(canonical_bytes(b))


def test_key_insertion_order_does_not_change_digest():
    reference = _manifest()
    reordered = dict(reversed(list(reference.items())))
    assert canonical_bytes(reordered) == canonical_bytes(reference)


def test_tag_order_is_preserved_and_affects_digest():
    m1 = _manifest(tags=["alpha", "beta"])
    m2 = _manifest(tags=["beta", "alpha"])
    assert json.loads(canonical_bytes(m1))["tags"] == ["alpha", "beta"]
    assert manifest_digest(canonical_bytes(m1)) != manifest_digest(canonical_bytes(m2))


def test_changed_video_digest_changes_manifest_digest():
    d1 = manifest_digest(canonical_bytes(_manifest(video_sha256="c" * 64)))
    d2 = manifest_digest(canonical_bytes(_manifest(video_sha256=VIDEO_SHA)))
    assert d1 != d2


def test_changed_thumbnail_digest_changes_manifest_digest():
    without = _manifest()
    with_thumb = _manifest(
        thumbnail_storage_path="storage/thumbs/t.jpg",
        thumbnail_sha256=THUMB_SHA,
        thumbnail_size_bytes=2048,
    )
    assert manifest_digest(canonical_bytes(without)) != manifest_digest(
        canonical_bytes(with_thumb)
    )
    with_other = _manifest(
        thumbnail_storage_path="storage/thumbs/t.jpg",
        thumbnail_sha256="d" * 64,
        thumbnail_size_bytes=2048,
    )
    assert manifest_digest(canonical_bytes(with_thumb)) != manifest_digest(
        canonical_bytes(with_other)
    )


@pytest.mark.parametrize(
    "override",
    [
        {"title": "Different Title"},
        {"description": "Different description"},
        {"platform": "postiz"},
        {"social_platform": "tiktok"},
        {"integration_id": "chan-42"},
        {"privacy_status": "private"},
        {"publish_type": "draft"},
        {"scheduled_at": "2030-01-01T12:00:00Z"},
        {"aspect_ratio": "9:16"},
        {"video_storage_path": "storage/videos/other.mp4"},
        {"video_size_bytes": 42},
        {"workflow_run_id": uuid.uuid4()},
        {"video_id": uuid.uuid4()},
    ],
)
def test_changed_effective_parameters_change_digest(override):
    baseline = manifest_digest(canonical_bytes(_manifest()))
    assert manifest_digest(canonical_bytes(_manifest(**override))) != baseline


# ---------------------------------------------------------------------------
# Strict schema rejection
# ---------------------------------------------------------------------------


def test_unknown_fields_rejected():
    m = _manifest()
    m["unexpected_field"] = "x"
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code == "unknown_field"


def test_unsupported_schema_version_rejected():
    with pytest.raises(PublicationManifestError) as ei:
        build_manifest(schema_version=2, **_raw_kwargs())
    assert ei.value.reason_code == "unsupported_schema_version"
    m = _manifest()
    m["schema_version"] = 99
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code == "unsupported_schema_version"


def _raw_kwargs():
    return {
        "workflow_run_id": RUN,
        "video_id": VIDEO,
        "video_storage_path": "storage/videos/final.mp4",
        "video_sha256": VIDEO_SHA,
        "video_size_bytes": 1024,
        "title": "T",
        "description": "D",
        "tags": [],
        "platform": "youtube",
        "social_platform": "youtube",
        "privacy_status": "public",
        "publish_type": "now",
        "aspect_ratio": "16:9",
    }


def _build_with(**overrides):
    """build_manifest over _raw_kwargs with per-test overrides applied
    by key (avoids duplicate-keyword TypeErrors in the tests)."""
    kwargs = _raw_kwargs()
    kwargs.update(overrides)
    return build_manifest(**kwargs)


@pytest.mark.parametrize("bad_size", [1.5, float("nan"), float("inf"), True, "1024"])
def test_floats_bools_and_strings_rejected_where_integer_required(bad_size):
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(video_size_bytes=bad_size)
    assert ei.value.reason_code in {"invalid_field_type", "non_finite_number"}


def test_nan_and_infinity_rejected_in_any_position():
    m = _manifest()
    m["video_size_bytes"] = float("nan")
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code in {"invalid_field_type", "non_finite_number"}
    m2 = _manifest()
    m2["thumbnail_size_bytes"] = float("inf")
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m2)
    assert ei.value.reason_code in {"invalid_field_type", "non_finite_number"}


def test_naive_timestamp_rejected():
    naive = datetime(2030, 1, 1, 12, 0, 0)  # naive BY INTENT
    with pytest.raises(PublicationManifestError) as ei:
        normalize_timestamp(naive)
    assert ei.value.reason_code == "naive_timestamp"
    with pytest.raises(PublicationManifestError) as ei:
        normalize_timestamp("2030-01-01T12:00:00")
    assert ei.value.reason_code == "naive_timestamp"
    m = _manifest()
    m["scheduled_at"] = "2030-01-01T12:00:00"
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code == "naive_timestamp"


def test_utc_timestamp_formatting_is_deterministic():
    a = normalize_timestamp(datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC))
    b = normalize_timestamp("2030-01-01T12:00:00+00:00")
    c = normalize_timestamp("2030-01-01T07:00:00-05:00")
    assert a == b == c == "2030-01-01T12:00:00Z"
    assert (
        normalize_timestamp(datetime(2030, 1, 1, 12, 0, 5, tzinfo=UTC))
        == "2030-01-01T12:00:05Z"
    )
    # Equal instants expressed in different offsets canonicalize identically.
    m1 = _manifest(scheduled_at="2030-01-01T07:00:00-05:00")
    m2 = _manifest(scheduled_at=datetime(2030, 1, 1, 12, tzinfo=UTC))
    assert canonical_bytes(m1) == canonical_bytes(m2)
    # Different instants differ.
    assert canonical_bytes(m1) != canonical_bytes(
        _manifest(scheduled_at="2030-01-01T12:00:01Z")
    )


def test_partial_thumbnail_triplet_rejected():
    with pytest.raises(PublicationManifestError) as ei:
        build_manifest(thumbnail_storage_path="storage/thumbs/t.jpg", **_raw_kwargs())
    assert ei.value.reason_code == "thumbnail_fields_partial"


def test_optional_fields_are_omitted_not_null():
    m = _manifest()
    assert "thumbnail_storage_path" not in m
    assert "thumbnail_sha256" not in m
    assert "thumbnail_size_bytes" not in m
    assert "integration_id" not in m
    assert "scheduled_at" not in m
    assert "null" not in canonical_bytes(m).decode("utf-8")
    # Empty integration_id normalizes to absent (intent-key precedent).
    m2 = _manifest(integration_id="")
    assert "integration_id" not in m2


def test_missing_required_field_rejected():
    m = _manifest()
    del m["video_sha256"]
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code == "missing_field"


def test_invalid_digest_format_rejected():
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(video_sha256="XYZ" + "a" * 61)
    assert ei.value.reason_code == "invalid_digest_format"


def test_non_canonical_uuid_and_bad_values_rejected():
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(video_id="not-a-uuid")
    assert ei.value.reason_code == "invalid_uuid"
    m = _manifest()
    m["tags"] = "alpha,beta"
    with pytest.raises(PublicationManifestError) as ei:
        canonical_bytes(m)
    assert ei.value.reason_code == "invalid_field_type"


def test_invalid_closed_set_values_rejected():
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(privacy_status="friends")
    assert ei.value.reason_code == "invalid_privacy_status"
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(publish_type="someday")
    assert ei.value.reason_code == "invalid_publish_type"
    with pytest.raises(PublicationManifestError) as ei:
        _build_with(aspect_ratio="4:3")
    assert ei.value.reason_code == "invalid_aspect_ratio"


# ---------------------------------------------------------------------------
# Unicode
# ---------------------------------------------------------------------------


def test_unicode_round_trips_without_normalization():
    nfc = "caf\u00e9"  # precomposed é
    nfd = "cafe\u0301"  # decomposed e + combining acute
    m_nfc = _manifest(title=nfc)
    m_nfd = _manifest(title=nfd)
    raw_nfc = canonical_bytes(m_nfc)
    raw_nfd = canonical_bytes(m_nfd)
    # ensure_ascii=False: raw UTF-8 code points, no \u escapes.
    assert "caf\u00e9".encode("utf-8") in raw_nfc
    assert b"\\u" not in raw_nfc
    # No implicit normalization: distinct code points stay distinct.
    assert raw_nfc != raw_nfd
    assert manifest_digest(raw_nfc) != manifest_digest(raw_nfd)
    # Verification round-trips both without complaint.
    verify_stored_manifest(raw_nfc, manifest_digest(raw_nfc))
    verify_stored_manifest(raw_nfd, manifest_digest(raw_nfd))


# ---------------------------------------------------------------------------
# Fail-closed verification of stored bytes + digest
# ---------------------------------------------------------------------------


def test_valid_stored_manifest_verifies():
    m = _manifest(
        thumbnail_storage_path="s://t.jpg",
        thumbnail_sha256=THUMB_SHA,
        thumbnail_size_bytes=1,
    )
    cb = canonical_bytes(m)
    parsed = verify_stored_manifest(cb, manifest_digest(cb))
    assert parsed == m


def test_non_canonical_stored_bytes_fail_verification():
    m = _manifest()
    cb = canonical_bytes(m)
    spaced = json.dumps(m, indent=2, ensure_ascii=False).encode("utf-8")  # whitespace
    assert spaced != cb
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(spaced, manifest_digest(spaced))
    assert ei.value.reason_code == "stored_bytes_not_canonical"
    reordered = json.dumps(
        dict(reversed(list(m.items()))), separators=(",", ":"), ensure_ascii=False
    ).encode(
        "utf-8"
    )  # key order
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(reordered, manifest_digest(reordered))
    assert ei.value.reason_code == "stored_bytes_not_canonical"


def test_jsonb_style_null_vs_absent_fails_verification():
    m = _manifest()
    with_null = dict(m)
    with_null["scheduled_at"] = None  # JSONB-style null where canonical omits
    raw = json.dumps(
        with_null, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    with pytest.raises(PublicationManifestError):
        verify_stored_manifest(raw, manifest_digest(raw))


def test_duplicate_keys_in_stored_bytes_fail_verification():
    m = _manifest()
    # json.loads keeps the LAST duplicate; re-canonicalization loses the
    # duplicate spelling and the byte comparison catches it.
    raw = b'{"aspect_ratio":"16:9","aspect_ratio":"9:16",' + canonical_bytes(m)[1:]
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(raw, manifest_digest(raw))
    assert ei.value.reason_code == "stored_bytes_not_canonical"


def test_stored_digest_inconsistent_with_bytes_fails():
    cb = canonical_bytes(_manifest())
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(cb, "e" * 64)
    assert ei.value.reason_code == "digest_mismatch"
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(cb, "short")
    assert ei.value.reason_code == "invalid_digest_format"


def test_corrupted_stored_bytes_fail():
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(b"\xff\xfe not json", "a" * 64)
    assert ei.value.reason_code == "stored_bytes_malformed_json"
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(b"[1,2,3]", manifest_digest(b"[1,2,3]"))
    assert ei.value.reason_code == "manifest_not_object"
    nan_bytes = b'{"schema_version":1,"video_size_bytes":NaN}'
    with pytest.raises(PublicationManifestError) as ei:
        verify_stored_manifest(nan_bytes, "a" * 64)
    assert ei.value.reason_code == "non_finite_number"


# ---------------------------------------------------------------------------
# Hermes digest separation + unchanged authorization semantics
# ---------------------------------------------------------------------------


def test_hermes_parameter_digest_unchanged_and_domain_separated():
    """Pins (a) the Hermes Model-B digest's existing semantics byte-for-
    byte, and (b) that the publication manifest digest can never equal
    it for the same input object."""
    from app.hermes.audit import compute_parameter_digest

    payload = {"capability": "x", "parameters": {"a": 1, "b": ["t", "u"]}}
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    assert compute_parameter_digest(payload) == expected  # semantics unchanged
    assert compute_parameter_digest(None) == hashlib.sha256(b"{}").hexdigest()

    m = _manifest()
    # Same underlying object through both digest functions: different
    # domains (prefix + different serialization) must yield different
    # digests — the manifest digest is NOT the Hermes digest.
    assert manifest_digest(canonical_bytes(m)) != compute_parameter_digest(dict(m))


def test_thumbnail_authorization_semantics_unchanged():
    """Phase 54B-I1 must not move the Phase 53B authorization boundary."""
    assert AUTHORIZING_STAGE == ApprovalStage.THUMBNAIL
    assert not hasattr(ApprovalStage, "PUBLICATION")


def test_models_are_additive_only():
    """Offline metadata check: publication_attempts/approval_checkpoints
    keep every pre-54B column (nullable additions only) and the new
    table carries the approved contract columns."""
    import app.models  # registers all tables
    from app.database.base import Base

    def columns(table):
        return {c.name: c.nullable for c in Base.metadata.tables[table].columns}

    attempt_cols = columns("publication_attempts")
    for legacy in [
        "id",
        "video_id",
        "workflow_run_id",
        "platform",
        "social_platform",
        "integration_id",
        "intent_key",
        "attempt_number",
        "status",
        "scheduled_at",
        "external_content_id",
        "external_post_id",
        "public_url",
        "error",
        "created_at",
        "updated_at",
    ]:
        assert legacy in attempt_cols, f"pre-54B column lost: {legacy}"
    assert attempt_cols["manifest_id"] is True
    assert attempt_cols["manifest_digest"] is True

    checkpoint_cols = columns("approval_checkpoints")
    for legacy in [
        "id",
        "workflow_run_id",
        "stage",
        "reference_table",
        "reference_id",
        "action",
        "reviewer_notes",
        "decided_at",
        "parameter_digest",
        "parameter_preview",
        "created_at",
        "updated_at",
    ]:
        assert legacy in checkpoint_cols, f"pre-54B column lost: {legacy}"
    assert checkpoint_cols["publication_manifest_id"] is True

    manifest_cols = columns("publication_manifests")
    assert manifest_cols == {
        "id": False,
        "schema_version": False,
        "workflow_run_id": False,
        "video_id": False,
        "canonical_bytes": False,
        "manifest_digest": False,
        "video_storage_path": False,
        "video_sha256": False,
        "video_size_bytes": False,
        "thumbnail_storage_path": True,
        "thumbnail_sha256": True,
        "thumbnail_size_bytes": True,
        "created_at": False,
        "updated_at": False,
    }
