"""
Fail-closed Hermes source-integrity verification (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §2 (commit pin),
§14.1 (source provisioning: Git submodule + AryaOS-controlled source
record), §15 (upgrade policy).

Two verification contexts, one module:

- Build boundary (Git available): emit_hermes_source_record() refuses
  to write anything unless the vendored submodule's actual commit and
  tree SHAs equal the approved pins, then writes the tiny source record
  consumed at runtime. Run via `uv run python -m app.hermes.source`
  before building an image.
- Runtime (no Git metadata in production images): verify_hermes_source()
  checks the approved pins, the presence of the source tree, and the
  source record's exact commit/tree values. It never reconstructs a
  Git tree hash from filesystem bytes and never treats a filesystem
  digest as equivalent to a Git tree hash. Git is consulted only when
  usable Git metadata happens to exist (development cross-check).

Hermes itself is not imported. Startup wiring is a later slice.
"""
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.config import HERMES_COMMIT_PIN, HERMES_TREE_PIN

# backend/app/hermes/source.py -> parents[3] is the AryaOS repository root.
_ARYA_OS_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _ARYA_OS_ROOT / "vendor" / "hermes-agent"
_SOURCE_RECORD = Path(__file__).resolve().parent / "source_record.json"
_RECORD_KEYS = ("hermes_commit", "hermes_tree")
_SHA_CHARS = set("0123456789abcdef")
_SHA_LENGTH = 40
_GIT_TIMEOUT_SECONDS = 10.0


class HermesSourceError(RuntimeError):
    """The Hermes source failed integrity verification. Fail-closed: the
    caller must treat any raise as "do not start or trust Hermes".

    `violations` is a list of (code, detail) tuples, mirroring
    app.hermes.config.HermesConfigError.
    """

    def __init__(self, violations: list[tuple[str, str]]):
        self.violations = violations
        rendered = "; ".join(f"{code}: {detail}" for code, detail in violations)
        super().__init__(f"invalid Hermes source ({rendered})")


@dataclass(frozen=True)
class HermesSourceVerification:
    """The verified Hermes source identity.

    `git_verified` is True only when the Git cross-check actually ran and
    agreed (build boundary / development). Runtime verification without
    Git metadata is anchored on the verified-build source record.
    """

    commit: str
    tree: str
    git_verified: bool


def _is_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA_LENGTH
        and all(c in _SHA_CHARS for c in value)
    )


def _check_pins(violations: list[tuple[str, str]]) -> None:
    if not _is_sha(HERMES_COMMIT_PIN):
        violations.append(
            (
                "commit_pin_malformed",
                f"HERMES_COMMIT_PIN must be a 40-character lowercase hex SHA, "
                f"got {HERMES_COMMIT_PIN!r}",
            )
        )
    if not _is_sha(HERMES_TREE_PIN):
        violations.append(
            (
                "tree_pin_malformed",
                f"HERMES_TREE_PIN must be a 40-character lowercase hex SHA, "
                f"got {HERMES_TREE_PIN!r}",
            )
        )


def _check_source(source_root: Path, violations: list[tuple[str, str]]) -> None:
    if not source_root.is_dir():
        violations.append(
            (
                "source_missing",
                f"Hermes source directory {source_root} does not exist "
                f"(submodule not checked out?)",
            )
        )
        return
    try:
        empty = not any(source_root.iterdir())
    except OSError as exc:
        violations.append(
            ("source_unreadable", f"Hermes source directory {source_root}: {exc}")
        )
        return
    if empty:
        violations.append(
            (
                "source_missing",
                f"Hermes source directory {source_root} is empty "
                f"(submodule not checked out?)",
            )
        )


def _load_record(record_path: Path, violations: list[tuple[str, str]]) -> dict | None:
    try:
        raw = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        violations.append(("record_missing", f"source record {record_path}: {exc}"))
        return None
    except UnicodeDecodeError as exc:
        violations.append(
            (
                "record_malformed",
                f"source record {record_path} is not valid UTF-8: {exc}",
            )
        )
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        violations.append(
            (
                "record_malformed",
                f"source record {record_path} is not valid JSON: {exc}",
            )
        )
        return None
    if not isinstance(record, dict) or set(record) != set(_RECORD_KEYS):
        violations.append(
            (
                "record_malformed",
                f"source record {record_path} must be a JSON object with exactly "
                f"the keys {list(_RECORD_KEYS)}",
            )
        )
        return None
    if not all(_is_sha(record[key]) for key in _RECORD_KEYS):
        violations.append(
            (
                "record_malformed",
                f"source record {record_path} values must be 40-character "
                f"lowercase hex SHAs",
            )
        )
        return None
    return record


def _git_identity(source_root: Path) -> tuple[str, str] | None:
    """Return (commit, tree) of the checkout, or None when Git cannot
    establish identity (no git binary, no usable metadata, timeout)."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(source_root),
                "rev-parse",
                "HEAD^{commit}",
                "HEAD^{tree}",
            ],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.split()
    if len(lines) != 2 or not all(_is_sha(sha) for sha in lines):
        return None
    return lines[0], lines[1]


def verify_hermes_source(
    source_root: Path | None = None,
    record_path: Path | None = None,
) -> HermesSourceVerification:
    """Verify the Hermes source identity fail-closed.

    Checks the approved pins, the source tree's presence, and the source
    record's exact commit/tree values. When usable Git metadata exists
    (development), the checkout's identity is cross-checked against the
    pins too. Raises HermesSourceError listing every violation.
    """
    source_root = _SOURCE_ROOT if source_root is None else Path(source_root)
    record_path = _SOURCE_RECORD if record_path is None else Path(record_path)

    violations: list[tuple[str, str]] = []
    _check_pins(violations)
    _check_source(source_root, violations)
    record = _load_record(record_path, violations)
    if record is not None:
        if record["hermes_commit"] != HERMES_COMMIT_PIN:
            violations.append(
                (
                    "record_commit_mismatch",
                    f"source record commit {record['hermes_commit']} is not the "
                    f"approved pin {HERMES_COMMIT_PIN}",
                )
            )
        if record["hermes_tree"] != HERMES_TREE_PIN:
            violations.append(
                (
                    "record_tree_mismatch",
                    f"source record tree {record['hermes_tree']} is not the "
                    f"approved pin {HERMES_TREE_PIN}",
                )
            )

    git_verified = False
    if (source_root / ".git").exists():
        identity = _git_identity(source_root)
        if identity is None:
            violations.append(
                (
                    "git_unavailable",
                    f"{source_root} has Git metadata but its identity cannot be "
                    f"established; refusing to trust an unusable checkout",
                )
            )
        else:
            commit, tree = identity
            if commit != HERMES_COMMIT_PIN:
                violations.append(
                    (
                        "git_commit_mismatch",
                        f"checked-out Hermes commit {commit} is not the approved "
                        f"pin {HERMES_COMMIT_PIN}",
                    )
                )
            if tree != HERMES_TREE_PIN:
                violations.append(
                    (
                        "git_tree_mismatch",
                        f"checked-out Hermes tree {tree} is not the approved "
                        f"pin {HERMES_TREE_PIN}",
                    )
                )
            git_verified = commit == HERMES_COMMIT_PIN and tree == HERMES_TREE_PIN

    if violations:
        raise HermesSourceError(violations)
    return HermesSourceVerification(
        commit=HERMES_COMMIT_PIN, tree=HERMES_TREE_PIN, git_verified=git_verified
    )


def emit_hermes_source_record(
    source_root: Path | None = None,
    record_path: Path | None = None,
) -> HermesSourceVerification:
    """Generate the runtime source record at the verified build boundary.

    Refuses to write unless the submodule's actual commit and tree SHAs
    equal the approved pins, and refuses to overwrite a record holding
    different values. The emitted JSON is deterministic.
    """
    source_root = _SOURCE_ROOT if source_root is None else Path(source_root)
    record_path = _SOURCE_RECORD if record_path is None else Path(record_path)

    violations: list[tuple[str, str]] = []
    _check_pins(violations)
    _check_source(source_root, violations)
    identity = _git_identity(source_root) if (source_root / ".git").exists() else None
    if identity is None:
        violations.append(
            (
                "git_unavailable",
                f"cannot establish the Git identity of {source_root}; the build "
                f"boundary requires usable Git metadata",
            )
        )
    else:
        commit, tree = identity
        if commit != HERMES_COMMIT_PIN:
            violations.append(
                (
                    "git_commit_mismatch",
                    f"checked-out Hermes commit {commit} is not the approved "
                    f"pin {HERMES_COMMIT_PIN}",
                )
            )
        if tree != HERMES_TREE_PIN:
            violations.append(
                (
                    "git_tree_mismatch",
                    f"checked-out Hermes tree {tree} is not the approved "
                    f"pin {HERMES_TREE_PIN}",
                )
            )
    if violations:
        raise HermesSourceError(violations)

    payload = (
        json.dumps(
            {
                "hermes_commit": HERMES_COMMIT_PIN,
                "hermes_tree": HERMES_TREE_PIN,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if record_path.exists():
        try:
            existing = record_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HermesSourceError(
                [("record_conflict", f"cannot read existing {record_path}: {exc}")]
            ) from exc
        if existing != payload:
            raise HermesSourceError(
                [
                    (
                        "record_conflict",
                        f"{record_path} already holds different values; remove it "
                        f"explicitly before regenerating",
                    )
                ]
            )
    else:
        record_path.write_text(payload, encoding="utf-8")
    return HermesSourceVerification(
        commit=HERMES_COMMIT_PIN, tree=HERMES_TREE_PIN, git_verified=True
    )


if __name__ == "__main__":
    try:
        verification = emit_hermes_source_record()
    except HermesSourceError as exc:
        for code, detail in exc.violations:
            print(f"{code}: {detail}", file=sys.stderr)
        sys.exit(1)
    print(
        f"wrote {_SOURCE_RECORD} "
        f"(commit {verification.commit}, tree {verification.tree})"
    )
