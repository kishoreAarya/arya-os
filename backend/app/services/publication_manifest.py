"""Publication-content manifest canonicalization and digest (Phase 54B-I1).

The immutable publication-content manifest binds a human publication
approval to the EXACT content and effective parameters that will be
published (Phase 54B-R2 contract). This module is the single authority
for its serialization and digest semantics:

- Strict version-1 schema validation BEFORE serialization: unknown
  fields, wrong types, NaN/Infinity, floats/booleans where integers
  are required, naive or non-canonical timestamps, partial thumbnail
  triplets, and non-canonical UUID/digest spellings are all rejected.
  Verification never repairs — it fails closed.
- Canonical serialization: sorted object keys, compact separators,
  UTF-8, ensure_ascii=False, allow_nan=False. Lists keep their order
  (tag order is semantic). Optional fields are OMITTED when absent —
  never written as null. Timestamps are UTC ISO-8601 with an explicit
  trailing "Z". No implicit Unicode normalization is applied.
- Digest: SHA-256 over b"AOS-PUBMANIFEST-v1:" + canonical_bytes —
  domain-separated from every other digest in the codebase. The Hermes
  Model-B parameter_digest (app/hermes/audit.py) is NOT reused and its
  semantics are untouched.

Storage contract: the exact canonical BYTES are authoritative. The
database stores them as Text (publication_manifests.canonical_bytes);
a JSONB re-rendering never re-derives the digest. Pure functions only:
no database, no I/O, no provider calls.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1

_DIGEST_DOMAIN = f"AOS-PUBMANIFEST-v{SUPPORTED_SCHEMA_VERSION}:".encode("ascii")
_SHA256_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

# Version-1 schema: required fields, optional fields (OMITTED when
# absent — never null), integer fields (bool is not an integer here),
# and the closed value sets of the current publication contract
# (routers/publishing.py Literals; models/enums.py AspectRatio).
_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "workflow_run_id",
        "video_id",
        "video_storage_path",
        "video_sha256",
        "video_size_bytes",
        "title",
        "description",
        "tags",
        "platform",
        "social_platform",
        "privacy_status",
        "publish_type",
        "aspect_ratio",
    }
)
_OPTIONAL_FIELDS = frozenset(
    {
        "integration_id",
        "scheduled_at",
        "thumbnail_storage_path",
        "thumbnail_sha256",
        "thumbnail_size_bytes",
    }
)
_INTEGER_FIELDS = frozenset(
    {"schema_version", "video_size_bytes", "thumbnail_size_bytes"}
)
_STRING_FIELDS = frozenset(
    {
        "workflow_run_id",
        "video_id",
        "video_storage_path",
        "video_sha256",
        "title",
        "description",
        "platform",
        "social_platform",
        "privacy_status",
        "publish_type",
        "aspect_ratio",
        "integration_id",
        "scheduled_at",
        "thumbnail_storage_path",
        "thumbnail_sha256",
    }
)
_NON_EMPTY_STRING_FIELDS = frozenset(
    {
        "video_storage_path",
        "video_sha256",
        "platform",
        "social_platform",
        "privacy_status",
        "publish_type",
        "aspect_ratio",
        "integration_id",
        "scheduled_at",
        "thumbnail_storage_path",
        "thumbnail_sha256",
    }
)
_PRIVACY_STATUSES = frozenset({"public", "private", "unlisted"})
_PUBLISH_TYPES = frozenset({"now", "schedule", "draft"})
_ASPECT_RATIOS = frozenset({"9:16", "16:9"})
_THUMBNAIL_FIELDS = frozenset(
    {"thumbnail_storage_path", "thumbnail_sha256", "thumbnail_size_bytes"}
)


class PublicationManifestError(ValueError):
    """Strict-schema or digest failure. `reason_code` is a stable,
    non-sensitive machine code; `detail` names the offending field or
    check but never embeds field VALUES (paths, titles, digests of
    content, etc. are not repeated in errors)."""

    def __init__(self, reason_code: str, detail: str):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


def _reject(reason_code: str, detail: str) -> PublicationManifestError:
    return PublicationManifestError(reason_code, detail)


def _is_canonical_integer(value: Any) -> bool:
    # bool is a subclass of int — rejected explicitly wherever the
    # schema requires an integer.
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_digest_string(field: str, value: Any) -> None:
    if not isinstance(value, str):
        raise _reject(
            "invalid_field_type", f"{field} must be a 64-char lowercase hex string"
        )
    if len(value) != _SHA256_HEX_LENGTH or not set(value) <= _HEX_DIGITS:
        raise _reject(
            "invalid_digest_format", f"{field} must be 64 lowercase hex characters"
        )


def _canonical_uuid_string(field: str, value: Any) -> str:
    """Validate/normalize a UUID to its canonical lowercase-hyphenated
    spelling. Non-canonical spellings (uppercase, braced, urn, no
    hyphens) are NORMALIZED on the build path; the verify path rejects
    them because the re-canonicalized bytes would differ."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise _reject("invalid_field_type", f"{field} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise _reject("invalid_uuid", f"{field} is not a parseable UUID") from None


def normalize_timestamp(value: Any) -> str:
    """Normalize an aware datetime or ISO-8601 string to the canonical
    UTC "...Z" form. Naive values are rejected (a timestamp without a
    timezone is ambiguous and must never be canonicalized by guess)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise _reject("naive_timestamp", "scheduled_at must carry a timezone")
        dt = value.astimezone(UTC)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            raise _reject("invalid_timestamp", "scheduled_at is not ISO-8601") from None
        if dt.tzinfo is None:
            raise _reject("naive_timestamp", "scheduled_at must carry a timezone")
        dt = dt.astimezone(UTC)
    else:
        raise _reject(
            "invalid_field_type", "scheduled_at must be a datetime or ISO-8601 string"
        )
    return dt.isoformat().replace("+00:00", "Z")


def _validate_canonical_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise _reject(
            "invalid_field_type", "scheduled_at must be a canonical UTC ISO-8601 string"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _reject("invalid_timestamp", "scheduled_at is not ISO-8601") from None
    if parsed.tzinfo is None:
        raise _reject(
            "naive_timestamp", "scheduled_at must carry an explicit UTC timezone ('Z')"
        )
    if not value.endswith("Z") or normalize_timestamp(value) != value:
        raise _reject(
            "non_canonical_timestamp", "scheduled_at is not in canonical UTC 'Z' form"
        )


def validate_manifest(manifest: Mapping) -> None:
    """Validate a version-1 manifest against the strict schema.
    Raises PublicationManifestError on the FIRST violation; never
    mutates the input, never repairs, never includes field values in
    the error."""
    if not isinstance(manifest, Mapping):
        raise _reject("manifest_not_object", "manifest must be a JSON object")

    keys = set(manifest.keys())
    for key in keys:
        if not isinstance(key, str):
            raise _reject("non_string_key", "object keys must be strings")
    unknown = keys - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if unknown:
        # Sorted for a deterministic message; names are schema-level,
        # not sensitive data.
        raise _reject(
            "unknown_field",
            f"unknown field(s): {', '.join(sorted(unknown))}",
        )
    missing = _REQUIRED_FIELDS - keys
    if missing:
        raise _reject(
            "missing_field",
            f"missing required field(s): {', '.join(sorted(missing))}",
        )

    version = manifest["schema_version"]
    if not _is_canonical_integer(version):
        raise _reject("invalid_schema_version", "schema_version must be an integer")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise _reject(
            "unsupported_schema_version",
            f"schema_version {version} is not supported "
            f"(supported: {SUPPORTED_SCHEMA_VERSION})",
        )

    for field in sorted(keys & _STRING_FIELDS):
        value = manifest[field]
        if not isinstance(value, str):
            raise _reject("invalid_field_type", f"{field} must be a string")
        if field in _NON_EMPTY_STRING_FIELDS and not value:
            raise _reject("empty_field", f"{field} must not be empty")

    for field in sorted(keys & _INTEGER_FIELDS):
        if not _is_canonical_integer(manifest[field]):
            raise _reject(
                "invalid_field_type",
                f"{field} must be an integer (no floats or booleans)",
            )

    tags = manifest["tags"]
    if not isinstance(tags, list):
        raise _reject("invalid_field_type", "tags must be a list of strings")
    for tag in tags:
        if not isinstance(tag, str):
            raise _reject("invalid_field_type", "every tag must be a string")

    _canonical_uuid_string("workflow_run_id", manifest["workflow_run_id"])
    _canonical_uuid_string("video_id", manifest["video_id"])
    _validate_digest_string("video_sha256", manifest["video_sha256"])

    if manifest["privacy_status"] not in _PRIVACY_STATUSES:
        raise _reject(
            "invalid_privacy_status",
            "privacy_status must be public, private, or unlisted",
        )
    if manifest["publish_type"] not in _PUBLISH_TYPES:
        raise _reject(
            "invalid_publish_type", "publish_type must be now, schedule, or draft"
        )
    if manifest["aspect_ratio"] not in _ASPECT_RATIOS:
        raise _reject("invalid_aspect_ratio", "aspect_ratio must be 9:16 or 16:9")

    present_thumbnail = _THUMBNAIL_FIELDS & keys
    if present_thumbnail and present_thumbnail != _THUMBNAIL_FIELDS:
        raise _reject(
            "thumbnail_fields_partial",
            "thumbnail storage/sha256/size must be present together or all absent",
        )
    if present_thumbnail:
        _validate_digest_string("thumbnail_sha256", manifest["thumbnail_sha256"])

    if "scheduled_at" in keys:
        _validate_canonical_timestamp(manifest["scheduled_at"])


def build_manifest(
    *,
    workflow_run_id: uuid.UUID | str,
    video_id: uuid.UUID | str,
    video_storage_path: str,
    video_sha256: str,
    video_size_bytes: int,
    title: str | None,
    description: str | None,
    tags: list[str] | None,
    platform: str,
    social_platform: str,
    privacy_status: str,
    publish_type: str,
    aspect_ratio: str,
    integration_id: str | None = None,
    scheduled_at: datetime | str | None = None,
    thumbnail_storage_path: str | None = None,
    thumbnail_sha256: str | None = None,
    thumbnail_size_bytes: int | None = None,
    schema_version: int = SUPPORTED_SCHEMA_VERSION,
) -> dict:
    """Build a normalized, validated version-1 manifest dict.

    Normalizations applied here (and ONLY here — the verify path never
    repairs): UUID spellings; scheduled_at to canonical UTC "Z" form;
    optional fields OMITTED when absent/empty; None title/description
    become "" and None tags become [] (the final effective values the
    reviewer and the provider see).
    """
    manifest: dict = {
        "schema_version": schema_version,
        "workflow_run_id": _canonical_uuid_string("workflow_run_id", workflow_run_id),
        "video_id": _canonical_uuid_string("video_id", video_id),
        "video_storage_path": video_storage_path,
        "video_sha256": video_sha256,
        "video_size_bytes": video_size_bytes,
        "title": title if title is not None else "",
        "description": description if description is not None else "",
        "tags": list(tags) if tags is not None else [],
        "platform": platform,
        "social_platform": social_platform,
        "privacy_status": privacy_status,
        "publish_type": publish_type,
        "aspect_ratio": aspect_ratio,
    }
    if integration_id:
        manifest["integration_id"] = integration_id
    if scheduled_at is not None:
        manifest["scheduled_at"] = normalize_timestamp(scheduled_at)
    if thumbnail_storage_path is not None:
        manifest["thumbnail_storage_path"] = thumbnail_storage_path
    if thumbnail_sha256 is not None:
        manifest["thumbnail_sha256"] = thumbnail_sha256
    if thumbnail_size_bytes is not None:
        manifest["thumbnail_size_bytes"] = thumbnail_size_bytes

    validate_manifest(manifest)
    return manifest


def canonical_bytes(manifest: Mapping) -> bytes:
    """Serialize a validated manifest to the exact canonical bytes:
    sorted keys, compact separators, UTF-8, ensure_ascii=False,
    allow_nan=False (NaN/Infinity raise)."""
    validate_manifest(manifest)
    try:
        serialized = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except ValueError as exc:
        # allow_nan=False rejects NaN/Infinity floats wherever they hide.
        raise _reject(
            "non_finite_number", f"manifest contains a non-finite number: {exc}"
        ) from None
    return serialized.encode("utf-8")


def manifest_digest(canonical: bytes) -> str:
    """SHA-256 hex digest over the domain-separated canonical bytes."""
    if not isinstance(canonical, (bytes, bytearray)):
        raise _reject("invalid_field_type", "canonical bytes must be bytes")
    return hashlib.sha256(_DIGEST_DOMAIN + bytes(canonical)).hexdigest()


def verify_stored_manifest(stored_bytes: bytes | str, stored_digest: str) -> dict:
    """Fail-closed verification of stored canonical bytes + digest.

    Order (Phase 54B-R2 contract):
    1. decode the stored bytes (strict UTF-8);
    2. parse (must be a JSON object);
    3. validate version + strict schema;
    4. re-canonicalize and byte-compare with the stored bytes;
    5. recompute the digest;
    6. compare with the stored digest.
    Any mismatch raises PublicationManifestError; on success the
    parsed manifest dict is returned (callers then compare artifact
    bytes/parameters against it — that comparison lives at dispatch,
    not here).
    """
    if isinstance(stored_bytes, str):
        try:
            raw = stored_bytes.encode("utf-8")
        except UnicodeEncodeError:
            raise _reject(
                "stored_bytes_not_utf8", "stored canonical bytes are not valid UTF-8"
            ) from None
    elif isinstance(stored_bytes, (bytes, bytearray)):
        raw = bytes(stored_bytes)
    else:
        raise _reject(
            "invalid_field_type", "stored canonical bytes must be bytes or str"
        )

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _reject(
            "stored_bytes_malformed_json", "stored canonical bytes are not valid JSON"
        ) from None

    if not isinstance(parsed, dict):
        raise _reject("manifest_not_object", "stored bytes must encode a JSON object")

    # Reject NaN/Infinity explicitly before schema typing so the error
    # code is precise (json.loads happily parses them as floats).
    for key, value in parsed.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise _reject("non_finite_number", f"field {key!r} is NaN or Infinity")

    validate_manifest(parsed)

    recomputed = canonical_bytes(parsed)
    if recomputed != raw:
        raise _reject(
            "stored_bytes_not_canonical",
            "stored bytes are not the exact canonical serialization "
            "(key order, whitespace, null-vs-absent, number spelling, or "
            "duplicate keys differ)",
        )

    if not isinstance(stored_digest, str):
        raise _reject("invalid_stored_digest", "stored digest must be a string")
    _validate_digest_string("stored_digest", stored_digest)
    computed_digest = manifest_digest(recomputed)
    if computed_digest != stored_digest:
        raise _reject(
            "digest_mismatch",
            "stored digest does not match the recomputed digest of the stored canonical bytes",
        )
    return parsed
