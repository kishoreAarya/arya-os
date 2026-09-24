"""Unit tests for Hermes source-integrity verification (Slice 3).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §2 (commit pin),
§14.1 (submodule + verified-build source record), §15 (upgrade policy).

Build-boundary tests construct throwaway Git repositories in tmp_path;
runtime tests never require Git. No test imports or executes Hermes.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import HERMES_COMMIT_PIN, HERMES_TREE_PIN
from app.hermes.source import (
    HermesSourceError,
    HermesSourceVerification,
    emit_hermes_source_record,
    verify_hermes_source,
)

# Top-level Hermes modules that must never appear in sys.modules as a
# side effect of source verification.
HERMES_MODULES = (
    "run_agent",
    "hermes_bootstrap",
    "hermes_constants",
    "model_tools",
    "toolsets",
)

_OTHER_SHA = "f" * 40


def _codes(exc_info: pytest.ExceptionInfo[HermesSourceError]) -> set[str]:
    return {code for code, _ in exc_info.value.violations}


def _write_source(root: Path) -> Path:
    source = root / "hermes-agent"
    source.mkdir()
    (source / "run_agent.py").write_text(
        "# synthetic hermes source\n", encoding="utf-8"
    )
    return source


def _write_record(
    record_path: Path,
    commit: str = HERMES_COMMIT_PIN,
    tree: str = HERMES_TREE_PIN,
) -> None:
    record_path.write_text(
        json.dumps({"hermes_commit": commit, "hermes_tree": tree}), encoding="utf-8"
    )


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_source(source: Path) -> tuple[str, str]:
    _git(source, "init", "--quiet", "-b", "main")
    _git(source, "config", "user.email", "tests@arya-os.local")
    _git(source, "config", "user.name", "AryaOS Tests")
    _git(source, "add", "-A")
    _git(source, "commit", "--quiet", "-m", "synthetic hermes source")
    return (
        _git(source, "rev-parse", "HEAD^{commit}"),
        _git(source, "rev-parse", "HEAD^{tree}"),
    )


# ---------------------------------------------------------------------------
# 1. Runtime verification (no Git metadata required)
# ---------------------------------------------------------------------------

def test_valid_record_and_source_passes(tmp_path):
    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    _write_record(record)

    verification = verify_hermes_source(source_root=source, record_path=record)

    assert isinstance(verification, HermesSourceVerification)
    assert verification.commit == HERMES_COMMIT_PIN
    assert verification.tree == HERMES_TREE_PIN
    assert verification.git_verified is False


def test_missing_source_fails_closed(tmp_path):
    record = tmp_path / "source_record.json"
    _write_record(record)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=tmp_path / "absent", record_path=record)

    assert _codes(exc_info) == {"source_missing"}


def test_empty_source_fails_closed(tmp_path):
    source = tmp_path / "hermes-agent"
    source.mkdir()
    record = tmp_path / "source_record.json"
    _write_record(record)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"source_missing"}


def test_missing_record_fails_closed(tmp_path):
    source = _write_source(tmp_path)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=tmp_path / "absent.json")

    assert _codes(exc_info) == {"record_missing"}


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        '{"hermes_commit": "%s"}' % HERMES_COMMIT_PIN,
        json.dumps(
            {
                "hermes_commit": HERMES_COMMIT_PIN,
                "hermes_tree": HERMES_TREE_PIN,
                "extra": "field",
            }
        ),
        json.dumps({"hermes_commit": HERMES_COMMIT_PIN, "hermes_tree": "not-a-sha"}),
        json.dumps(
            {"hermes_commit": HERMES_COMMIT_PIN.upper(), "hermes_tree": HERMES_TREE_PIN}
        ),
        json.dumps(["hermes_commit", "hermes_tree"]),
    ],
)
def test_malformed_record_fails_closed(tmp_path, payload):
    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    record.write_text(payload, encoding="utf-8")

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"record_malformed"}


def test_non_utf8_record_fails_closed(tmp_path):
    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    record.write_bytes(b"\xff\xfe\x00\x01 not utf-8")

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"record_malformed"}


def test_record_commit_mismatch_fails_closed(tmp_path):
    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    _write_record(record, commit=_OTHER_SHA)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"record_commit_mismatch"}


def test_record_tree_mismatch_fails_closed(tmp_path):
    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    _write_record(record, tree=_OTHER_SHA)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"record_tree_mismatch"}


def test_malformed_expected_pins_fail_closed(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    _write_record(record)

    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", "not-a-sha")
    with pytest.raises(HermesSourceError) as exc_info:
        source.verify_hermes_source(source_root=source_dir, record_path=record)
    assert "commit_pin_malformed" in _codes(exc_info)

    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", HERMES_COMMIT_PIN)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", "ALSO-NOT-A-SHA")
    with pytest.raises(HermesSourceError) as exc_info:
        source.verify_hermes_source(source_root=source_dir, record_path=record)
    assert "tree_pin_malformed" in _codes(exc_info)


# ---------------------------------------------------------------------------
# 2. Opportunistic Git cross-check
# ---------------------------------------------------------------------------

def test_git_cross_check_passes_when_metadata_present(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    _write_record(record, commit=commit, tree=tree)
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    verification = source.verify_hermes_source(
        source_root=source_dir, record_path=record
    )

    assert verification.git_verified is True


def test_unusable_git_metadata_fails_closed(tmp_path):
    source = _write_source(tmp_path)
    (source / ".git").mkdir()
    record = tmp_path / "source_record.json"
    _write_record(record)

    with pytest.raises(HermesSourceError) as exc_info:
        verify_hermes_source(source_root=source, record_path=record)

    assert _codes(exc_info) == {"git_unavailable"}


def test_git_cross_check_detects_commit_drift(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    _git(source_dir, "commit", "--quiet", "--allow-empty", "-m", "drift")
    record = tmp_path / "source_record.json"
    _write_record(record, commit=commit, tree=tree)
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    with pytest.raises(HermesSourceError) as exc_info:
        source.verify_hermes_source(source_root=source_dir, record_path=record)

    assert _codes(exc_info) == {"git_commit_mismatch"}


def test_git_cross_check_detects_tree_drift(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    (source_dir / "extra.py").write_text("# drift\n", encoding="utf-8")
    _git(source_dir, "add", "-A")
    _git(source_dir, "commit", "--quiet", "-m", "tree drift")
    record = tmp_path / "source_record.json"
    _write_record(record, commit=commit, tree=tree)
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    with pytest.raises(HermesSourceError) as exc_info:
        source.verify_hermes_source(source_root=source_dir, record_path=record)

    # A content-bearing follow-up commit moves both the commit and the tree.
    assert _codes(exc_info) == {"git_commit_mismatch", "git_tree_mismatch"}


# ---------------------------------------------------------------------------
# 3. Build boundary (record generation)
# ---------------------------------------------------------------------------

def test_emit_refuses_commit_mismatch(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", _OTHER_SHA)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    with pytest.raises(HermesSourceError) as exc_info:
        source.emit_hermes_source_record(source_root=source_dir, record_path=record)

    assert _codes(exc_info) == {"git_commit_mismatch"}
    assert not record.exists()


def test_emit_refuses_tree_mismatch(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", _OTHER_SHA)

    with pytest.raises(HermesSourceError) as exc_info:
        source.emit_hermes_source_record(source_root=source_dir, record_path=record)

    assert _codes(exc_info) == {"git_tree_mismatch"}
    assert not record.exists()


def test_emit_writes_deterministic_record(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    verification = source.emit_hermes_source_record(
        source_root=source_dir, record_path=record
    )

    expected = (
        json.dumps(
            {"hermes_commit": commit, "hermes_tree": tree}, indent=2, sort_keys=True
        )
        + "\n"
    )
    assert record.read_text(encoding="utf-8") == expected
    assert verification.git_verified is True
    assert (
        source.verify_hermes_source(source_root=source_dir, record_path=record).commit
        == commit
    )


def test_emit_is_idempotent(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    source.emit_hermes_source_record(source_root=source_dir, record_path=record)
    first = record.read_text(encoding="utf-8")
    source.emit_hermes_source_record(source_root=source_dir, record_path=record)

    assert record.read_text(encoding="utf-8") == first


def test_emit_refuses_overwrite_of_conflicting_record(tmp_path, monkeypatch):
    from app.hermes import source

    source_dir = _write_source(tmp_path)
    commit, tree = _commit_source(source_dir)
    record = tmp_path / "source_record.json"
    _write_record(record, commit=_OTHER_SHA, tree=_OTHER_SHA)
    original = record.read_text(encoding="utf-8")
    monkeypatch.setattr(source, "HERMES_COMMIT_PIN", commit)
    monkeypatch.setattr(source, "HERMES_TREE_PIN", tree)

    with pytest.raises(HermesSourceError) as exc_info:
        source.emit_hermes_source_record(source_root=source_dir, record_path=record)

    assert _codes(exc_info) == {"record_conflict"}
    assert record.read_text(encoding="utf-8") == original


def test_emit_requires_git_metadata(tmp_path):
    source_dir = _write_source(tmp_path)
    record = tmp_path / "source_record.json"

    with pytest.raises(HermesSourceError) as exc_info:
        emit_hermes_source_record(source_root=source_dir, record_path=record)

    assert _codes(exc_info) == {"git_unavailable"}
    assert not record.exists()


# ---------------------------------------------------------------------------
# 4. Purity and the real repository
# ---------------------------------------------------------------------------

def test_verification_does_not_import_hermes(tmp_path):
    """Source verification must not import Hermes. Checked in a fresh
    subprocess: the runtime integration tests (test_hermes_runtime_unit)
    legitimately import Hermes into the shared pytest process, so a
    process-global sys.modules scan here would test file ordering, not
    this module."""
    import subprocess
    import sys as _sys

    source = _write_source(tmp_path)
    record = tmp_path / "source_record.json"
    _write_record(record)
    backend_dir = Path(__file__).resolve().parents[1]

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "from pathlib import Path\n"
        "from app.hermes.source import verify_hermes_source\n"
        f"verify_hermes_source(source_root=Path({str(source)!r}), record_path=Path({str(record)!r}))\n"
        f"assert not any(name in sys.modules for name in {HERMES_MODULES!r}), 'source verification imported Hermes'\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr


def test_real_repo_submodule_state():
    """The checked-out repository must either verify cleanly (submodule and
    generated record present) or fail with exactly the legitimate pre-build
    states: submodule not checked out, or record not yet generated (fresh
    clone). In CI — where the workflow provisions the submodule and
    generates the record — verification must succeed with the approved
    pins; absence is an explicit integration-environment failure, never a
    silent pass (spec §16)."""
    try:
        verification = verify_hermes_source()
    except HermesSourceError as exc:
        if os.environ.get("CI") == "true":
            pytest.fail(f"CI must verify the Hermes source: {exc.violations}")
        codes = {code for code, _ in exc.violations}
        assert codes <= {"source_missing", "record_missing"}
    else:
        assert verification.commit == HERMES_COMMIT_PIN
        assert verification.tree == HERMES_TREE_PIN
