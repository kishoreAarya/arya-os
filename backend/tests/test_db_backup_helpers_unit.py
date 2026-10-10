"""Unit tests for the database backup/restore helpers
(tools/db/pg_backup.py and tools/db/verify_restore.py).

These tests are deliberately hermetic: every docker interaction is
faked. No container, volume, database, or production resource is
started, stopped, or modified. The fakes also let us assert the SAFETY
properties: which commands may run, what may never appear in them,
and which failures must fail closed.
"""

import datetime
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "tools" / "db" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pg_backup = _load("pg_backup")
verify_restore = _load("verify_restore")

WORKTREE = Path(__file__).resolve().parents[2]


class FakeBackupRunner:
    """Fakes `docker compose exec` for pg_backup: dispatches on the
    in-container script; the dump itself writes scripted bytes to the
    provided stdout file handle."""

    DEFAULTS = {
        'printf %s "$POSTGRES_DB"': ("arya_os", 0),
        "pg_dump --version": ("pg_dump (PostgreSQL) 16.9", 0),
        "SHOW server_version": ("16.9\n", 0),
        "SELECT version_num FROM alembic_version": ("a7b8c9d0e1f2\n", 0),
    }

    def __init__(self, *, dump_bytes=b"x" * 512, dump_rc=0, scripts=None):
        self.calls: list[list[str]] = []
        self.dump_bytes = dump_bytes
        self.dump_rc = dump_rc
        self.scripts = dict(self.DEFAULTS)
        self.scripts.update(scripts or {})

    def __call__(self, cmd, capture_output=False, text=False, stdout=None):
        self.calls.append(cmd)
        if stdout is not None:  # the dump invocation
            stdout.write(self.dump_bytes)
            return subprocess.CompletedProcess(cmd, self.dump_rc, "", "")
        script = cmd[-1]
        for needle, (out, rc) in self.scripts.items():
            if needle in script:
                return subprocess.CompletedProcess(
                    cmd, rc, out, "" if rc == 0 else "boom"
                )
        raise AssertionError(f"unexpected container script: {script!r}")


class _FrozenDateTime:
    timezone = datetime.timezone

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(
                2026, 10, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
            )


BACKUP_STAMP = "20261010T120000Z"
BACKUP_NAME = f"arya_os_backup_{BACKUP_STAMP}.dump"


@pytest.fixture
def dest(tmp_path):
    target = tmp_path / "backups"
    target.mkdir()
    return target


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(pg_backup, "datetime", _FrozenDateTime)


# ---------------------------------------------------------------------------
# destination validation
# ---------------------------------------------------------------------------


def test_validate_dest_refuses_worktree_path():
    with pytest.raises(pg_backup.BackupError, match="worktree"):
        pg_backup.validate_dest_dir(WORKTREE / "backups", worktree=WORKTREE)


def test_validate_dest_refuses_file_destination(tmp_path):
    target = tmp_path / "not-a-dir"
    target.write_text("i am a file")
    with pytest.raises(pg_backup.BackupError, match="not a directory"):
        pg_backup.validate_dest_dir(target, worktree=WORKTREE)


def test_validate_dest_creates_missing_directory(dest):
    resolved = pg_backup.validate_dest_dir(dest, worktree=WORKTREE)
    assert resolved.is_dir()


# ---------------------------------------------------------------------------
# backup orchestration
# ---------------------------------------------------------------------------


def test_backup_success_writes_dump_manifest_and_checksum(dest, frozen_clock):
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner())
    assert rc == 0
    dump = dest / BACKUP_NAME
    assert dump.is_file() and dump.stat().st_size == 512
    manifest = json.loads((dest / f"{BACKUP_NAME}.manifest.json").read_text())
    assert manifest["source"]["database"] == "arya_os"
    assert manifest["source"]["alembic_revision"] == "a7b8c9d0e1f2"
    assert manifest["source"]["pg_server_version"] == "16.9"
    assert manifest["backup"]["sha256"] == pg_backup.sha256_file(dump)
    sidecar = (dest / f"{BACKUP_NAME}.sha256").read_text()
    assert sidecar.startswith(manifest["backup"]["sha256"])


def test_backup_manifest_carries_no_credentials(dest, frozen_clock):
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner())
    assert rc == 0
    blob = (dest / f"{BACKUP_NAME}.manifest.json").read_text().lower()
    for forbidden in ("password", "passwd", "secret", "token", "pwd"):
        assert forbidden not in blob


def test_backup_commands_never_carry_credentials(dest, frozen_clock):
    runner = FakeBackupRunner()
    assert pg_backup.run_backup(["--dest", str(dest)], runner=runner) == 0
    for cmd in runner.calls:
        joined = " ".join(cmd).lower()
        assert "postgress_password" not in joined
        assert "pgpassword" not in joined
        assert "-e " not in joined  # no env vars are ever passed through docker exec
    # The dump script expands USER/DB inside the container only.
    dump_cmds = [
        c for c in runner.calls if any("--format=custom" in part for part in c)
    ]
    assert dump_cmds, "dump command was not issued"
    assert '"$POSTGRES_USER"' in dump_cmds[0][-1]
    assert '"$POSTGRES_DB"' in dump_cmds[0][-1]


def test_backup_refuses_existing_output_without_force(dest, frozen_clock):
    (dest / BACKUP_NAME).write_bytes(b"previous")
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner())
    assert rc == 1
    assert (dest / BACKUP_NAME).read_bytes() == b"previous"
    assert not list(dest.glob("*.manifest.json"))


def test_backup_force_replaces_existing_output(dest, frozen_clock):
    (dest / BACKUP_NAME).write_bytes(b"previous")
    rc = pg_backup.run_backup(
        ["--dest", str(dest), "--force"], runner=FakeBackupRunner()
    )
    assert rc == 0
    assert (dest / BACKUP_NAME).stat().st_size == 512


def test_backup_dump_failure_writes_nothing(dest, frozen_clock):
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner(dump_rc=1))
    assert rc == 1
    assert not list(dest.glob("*.dump"))
    assert not list(dest.glob("*.manifest.json"))
    assert not list(dest.glob("*.sha256"))
    assert not list(dest.glob("*.tmp"))
    assert not list(dest.glob(".arya-backup-*"))


def test_backup_empty_dump_is_failure(dest, frozen_clock):
    rc = pg_backup.run_backup(
        ["--dest", str(dest)], runner=FakeBackupRunner(dump_bytes=b"")
    )
    assert rc == 1
    assert not list(dest.glob("*.dump"))
    assert not list(dest.glob("*.manifest.json"))


def test_backup_preflight_failure_exits_nonzero(dest, frozen_clock):
    rc = pg_backup.run_backup(
        ["--dest", str(dest)],
        runner=FakeBackupRunner(scripts={'printf %s "$POSTGRES_DB"': ("", 1)}),
    )
    assert rc == 1
    assert not list(dest.glob("*.dump"))


def test_backup_survives_unreadable_alembic_revision(dest, frozen_clock):
    rc = pg_backup.run_backup(
        ["--dest", str(dest)],
        runner=FakeBackupRunner(
            scripts={"SELECT version_num FROM alembic_version": ("", 1)}
        ),
    )
    assert rc == 0
    manifest = json.loads((dest / f"{BACKUP_NAME}.manifest.json").read_text())
    assert manifest["source"]["alembic_revision"] is None


# ---------------------------------------------------------------------------
# restore verification: pure guards
# ---------------------------------------------------------------------------


def test_run_args_are_isolated_and_pinned():
    args = verify_restore.build_run_args("arya-restore-verify-test")
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert verify_restore.IMAGE in args
    assert "-p" not in args and "-v" not in args and "--mount" not in args
    verify_restore.assert_isolated_run_args(args)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.extend(["-p", "5433:5432"]),
        lambda a: a.extend(["-v", "some-volume:/data"]),
        lambda a: a.extend(["--mount", "type=bind,src=/,dst=/x"]),
        lambda a: a.__setitem__(a.index("--network") + 1, "bridge"),
        lambda a: a.__setitem__(a.index(verify_restore.IMAGE), "postgres:16-alpine"),
    ],
)
def test_isolation_guard_refuses_unsafe_variants(mutate):
    args = verify_restore.build_run_args("x")
    mutate(args)
    with pytest.raises(verify_restore.RestoreVerifyError):
        verify_restore.assert_isolated_run_args(args)


# ---------------------------------------------------------------------------
# restore verification: manifest and checksum handling
# ---------------------------------------------------------------------------


def _write_backup(dest, *, sha=None, manifest_extra=None, data=b"backup-bytes"):
    dump = dest / BACKUP_NAME
    dump.write_bytes(data)
    manifest = {
        "schema_version": 1,
        "created_at_utc": "2026-10-10T12:00:00+00:00",
        "source": {"alembic_revision": "a7b8c9d0e1f2"},
        "backup": {
            "filename": BACKUP_NAME,
            "sha256": sha or pg_backup.sha256_file(dump),
        },
    }
    manifest.update(manifest_extra or {})
    (dest / f"{BACKUP_NAME}.manifest.json").write_text(json.dumps(manifest))
    return dump


def test_load_manifest_failures(tmp_path):
    with pytest.raises(verify_restore.RestoreVerifyError, match="not found"):
        verify_restore.load_manifest(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(verify_restore.RestoreVerifyError, match="malformed"):
        verify_restore.load_manifest(bad)
    sparse = tmp_path / "sparse.json"
    sparse.write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(verify_restore.RestoreVerifyError, match="required fields"):
        verify_restore.load_manifest(sparse)


def test_checksum_mismatch_aborts_before_any_docker(dest):
    dump = _write_backup(dest, sha="0" * 64)
    runner = FakeVerifyRunner()
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    assert runner.calls == [], "no docker command may run on checksum mismatch"


def test_missing_manifest_aborts_before_any_docker(dest):
    dump = dest / BACKUP_NAME
    dump.write_bytes(b"orphan-dump")
    runner = FakeVerifyRunner()
    assert verify_restore.run_verify([str(dump)], runner=runner) == 1
    assert runner.calls == []


# ---------------------------------------------------------------------------
# restore verification: full flows (faked docker)
# ---------------------------------------------------------------------------


class FakeVerifyRunner:
    """Fakes the docker CLI for verify_restore: one scripted container
    id, name, psql results, and configurable failure modes."""

    # Realistic `docker run --detach` output: a full 64-hex container
    # id (what verify_restore's CONTAINER_ID validation expects).
    CID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    NAME = verify_restore.CONTAINER_NAME_PREFIX + "20261010T120000-backup"

    def __init__(
        self,
        *,
        restore_rc=0,
        tables="24",
        revision="a7b8c9d0e1f2",
        inspect_name=None,
        ready_rc=0,
        run_rc=0,
        run_stderr="",
        run_stdout=None,
        cp_rc=0,
        raise_on_cp=None,
        table_list="alembic_version\nprojects\n",
        unusual="0",
        row_counts=None,
        count_fail_for=None,
        rm_rc=0,
        rm_stderr="",
    ):
        self.calls: list[list[str]] = []
        self.removed: list[str] = []
        self.restore_rc = restore_rc
        self.tables = tables
        self.revision = revision
        self.inspect_name = inspect_name or self.NAME
        self.ready_rc = ready_rc
        self.run_rc = run_rc
        self.run_stderr = run_stderr
        self.run_stdout = run_stdout
        self.cp_rc = cp_rc
        self.raise_on_cp = raise_on_cp
        self.table_list = table_list
        self.unusual = unusual
        if row_counts is None:
            row_counts = {"alembic_version": 1, "projects": 7}
        self.row_counts = row_counts
        self.count_fail_for = count_fail_for or set()
        self.rm_rc = rm_rc
        self.rm_stderr = rm_stderr

    def __call__(self, cmd, capture_output=False, text=True, stdout=None):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            if self.run_rc != 0:
                return subprocess.CompletedProcess(
                    cmd, self.run_rc, "", self.run_stderr
                )
            out = self.CID if self.run_stdout is None else self.run_stdout
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, f"/{self.inspect_name}", "")
        if cmd[:2] == ["docker", "rm"]:
            self.removed.append(cmd[3])
            err = "" if self.rm_rc == 0 else self.rm_stderr
            return subprocess.CompletedProcess(cmd, self.rm_rc, "", err)
        if cmd[:2] == ["docker", "cp"]:
            if self.raise_on_cp is not None:
                raise self.raise_on_cp
            err = "cp failed" if self.cp_rc else ""
            return subprocess.CompletedProcess(cmd, self.cp_rc, "", err)
        if cmd[:2] == ["docker", "exec"]:
            joined = " ".join(cmd)
            if "pg_isready" in joined:
                return subprocess.CompletedProcess(cmd, self.ready_rc, "", "")
            if "pg_restore" in joined:
                err = "" if self.restore_rc == 0 else "pg_restore: error"
                return subprocess.CompletedProcess(cmd, self.restore_rc, "", err)
            if "table_name ~" in joined:
                return subprocess.CompletedProcess(cmd, 0, self.table_list, "")
            if "table_name !~" in joined:
                return subprocess.CompletedProcess(cmd, 0, f"{self.unusual}\n", "")
            if "count(*) FROM information_schema" in joined:
                return subprocess.CompletedProcess(cmd, 0, f"{self.tables}\n", "")
            if 'count(*) FROM "' in joined:
                table = cmd[cmd.index("--command") + 1].split('"')[1]
                if table in self.count_fail_for:
                    return subprocess.CompletedProcess(cmd, 1, "", "permission denied")
                return subprocess.CompletedProcess(
                    cmd, 0, f"{self.row_counts.get(table, 0)}\n", ""
                )
            if "alembic_version" in joined:
                return subprocess.CompletedProcess(cmd, 0, f"{self.revision}\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected docker command: {cmd}")


def test_verify_success_flow_restores_checks_and_cleans_up(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner()
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 0
    run_cmds = [c for c in runner.calls if c[:2] == ["docker", "run"]]
    assert run_cmds, "verification container was never started"
    assert run_cmds[0][run_cmds[0].index("--network") + 1] == "none"
    assert runner.removed == [FakeVerifyRunner.CID]


def test_verify_restore_failure_cleans_up_and_fails(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(restore_rc=1)
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    assert runner.removed == [FakeVerifyRunner.CID]


def test_verify_revision_mismatch_fails(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(revision="deadbeef")
    assert verify_restore.run_verify([str(dump)], runner=runner) == 1


def test_verify_zero_tables_fails(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(tables="0")
    assert verify_restore.run_verify([str(dump)], runner=runner) == 1


def test_safe_remove_refuses_foreign_container():
    runner = FakeVerifyRunner(inspect_name="arya-postgres-prod")
    with pytest.raises(
        verify_restore.RestoreVerifyError, match="not created by this tool"
    ):
        verify_restore.safe_remove_container("some-other-id", runner)
    assert runner.removed == []


# ---------------------------------------------------------------------------
# review fixes: fail-fast restore, guaranteed cleanup, new failure paths
# ---------------------------------------------------------------------------


def test_restore_command_uses_exit_on_error(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner()
    assert verify_restore.run_verify([str(dump)], runner=runner) == 0
    restore_cmds = [c for c in runner.calls if any("pg_restore" in p for p in c)]
    assert restore_cmds, "pg_restore was never invoked"
    assert "--exit-on-error" in restore_cmds[0]


def test_readiness_timeout_fails_and_cleans_up(dest, monkeypatch, capsys):
    monkeypatch.setattr(verify_restore, "READY_TIMEOUT_SECONDS", 0)
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(ready_rc=1)
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    assert runner.removed == [FakeVerifyRunner.CID]
    assert "did not become ready" in capsys.readouterr().err


def test_container_start_failure_reports_and_never_removes(dest, capsys):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(run_rc=1, run_stderr="name already in use")
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    assert runner.removed == [], "nothing was created; nothing may be removed"
    assert (
        "could not start disposable verification container" in capsys.readouterr().err
    )


def test_docker_cp_failure_fails_and_cleans_up(dest, capsys):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(cp_rc=1)
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    assert runner.removed == [FakeVerifyRunner.CID]
    assert "docker cp failed" in capsys.readouterr().err


def test_unexpected_exception_after_creation_still_cleans_up(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(raise_on_cp=RuntimeError("docker daemon exploded"))
    with pytest.raises(RuntimeError, match="docker daemon exploded"):
        verify_restore.run_verify([str(dump)], runner=runner)
    assert runner.removed == [
        FakeVerifyRunner.CID
    ], "cleanup must be attempted even on unexpected exceptions"


def test_keyboard_interrupt_after_creation_still_cleans_up(dest):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(raise_on_cp=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        verify_restore.run_verify([str(dump)], runner=runner)
    assert runner.removed == [FakeVerifyRunner.CID]


def test_keep_flag_success_skips_cleanup_and_reports_name(dest, capsys):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner()
    rc = verify_restore.run_verify([str(dump), "--keep"], runner=runner)
    assert rc == 0
    assert not any(
        c[:2] == ["docker", "rm"] for c in runner.calls
    ), "--keep must not even attempt removal"
    assert runner.removed == [], "--keep must not remove the container"
    out = capsys.readouterr().out
    assert "kept for debugging" in out
    assert verify_restore.CONTAINER_NAME_PREFIX in out


def test_success_reports_informational_row_counts(dest, capsys):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(row_counts={"alembic_version": 1, "projects": 7})
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 0
    out = capsys.readouterr().out
    assert "alembic_version=1" in out
    assert "projects=7" in out
    assert "NOT a completeness proof" in out


def test_manifest_write_failure_removes_unlabelled_dump(
    dest, frozen_clock, monkeypatch, capsys
):
    def _disk_full(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(pg_backup.json, "dumps", _disk_full)
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner())
    assert rc == 1
    assert not list(dest.glob("*.dump")), "unlabelled dump must not survive"
    assert not list(dest.glob("*.manifest.json"))
    assert "manifest/checksum failed" in capsys.readouterr().err


def test_generated_container_names_are_unique_and_well_formed(dest):
    """Exercises run_verify's ACTUAL name generation (not a supplied
    name): two invocations must produce different names, each with the
    safety prefix and a 6-hex random suffix."""

    def generated_name():
        runner = FakeVerifyRunner()
        assert verify_restore.run_verify([str(dump)], runner=runner) == 0
        run_cmd = next(c for c in runner.calls if c[:2] == ["docker", "run"])
        return run_cmd[run_cmd.index("--name") + 1]

    dump = _write_backup(dest)
    first = generated_name()
    second = generated_name()
    for name in (first, second):
        assert name.startswith(verify_restore.CONTAINER_NAME_PREFIX)
        assert re.fullmatch(r"[0-9a-f]{6}", name.rsplit("-", 1)[-1])
    assert first != second, "same-second invocations must never collide"


def test_unusual_table_names_are_skipped_and_reported(dest, capsys):
    """A hostile/garbled catalog listing (quotes, newlines, SQL-shaped
    fragments) must never reach the generated count SQL; safe tables
    are still counted and the skipped ones are reported."""
    dump = _write_backup(dest)
    hostile_list = 'alembic_version\nprojects\nx"; DROP TABLE y; --\nwe"ird\n'
    runner = FakeVerifyRunner(table_list=hostile_list, unusual="1")
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 0
    count_cmds = [" ".join(c) for c in runner.calls if 'count(*) FROM "' in " ".join(c)]
    for sql in count_cmds:
        assert "DROP TABLE" not in sql
        # every counted identifier is a plain safe name
        identifier = sql.split('FROM "')[1].split('"')[0]
        assert verify_restore.SAFE_TABLE_NAME.match(identifier)
    out = capsys.readouterr().out
    assert "alembic_version=1" in out
    assert "projects=7" in out
    # 1 catalog-reported unusual name + 2 hostile lines filtered client-side
    assert "3 unusual-name table(s) skipped" in out


def test_failed_informational_count_is_reported_not_fatal(dest, capsys):
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(count_fail_for={"projects"})
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 0, "an informational count failure must not fail verification"
    out = capsys.readouterr().out
    assert "projects=unavailable" in out
    assert "alembic_version=1" in out


def test_cleanup_failure_is_visible_alongside_unexpected_exception(dest, capsys):
    dump = _write_backup(dest)
    # Primary failure: docker cp raises an unexpected RuntimeError.
    # Cleanup failure: inspect reports a foreign container name, so the
    # ownership guard refuses removal.
    runner = FakeVerifyRunner(
        raise_on_cp=RuntimeError("docker daemon exploded"),
        inspect_name="arya-postgres-prod",
    )
    with pytest.raises(RuntimeError, match="docker daemon exploded"):
        verify_restore.run_verify([str(dump)], runner=runner)
    assert runner.removed == [], "foreign container must never be removed"
    assert "cleanup also failed" in capsys.readouterr().err


def test_rm_failure_after_successful_verification_fails_closed(dest, capsys):
    """`docker rm -f` failing after a fully successful verification must
    not be reported as success: rc 1, the removal attempt is visible,
    and the operator gets the container name + manual removal command."""
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(rm_rc=1, rm_stderr="cannot remove: device busy")
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1, "verification must not pass while required cleanup failed"
    assert runner.removed == [FakeVerifyRunner.CID], "removal was attempted once"
    err = capsys.readouterr().err
    assert "verification passed but cleanup failed" in err
    assert FakeVerifyRunner.NAME in err
    assert f"docker rm -f {FakeVerifyRunner.NAME}" in err
    assert "device busy" in err


def test_rm_failure_does_not_mask_primary_verification_failure(dest, capsys):
    """With a restore failure AND a cleanup failure, the restore error
    stays the headline ERROR; the rm failure is the secondary NOTE."""
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(restore_rc=1, rm_rc=1)
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    err = capsys.readouterr().err
    assert "ERROR: docker exec failed (pg_restore)" in err
    assert "NOTE: cleanup also failed" in err
    assert "could not remove disposable container" in err
    assert FakeVerifyRunner.NAME in err


@pytest.mark.parametrize(
    "bad_stdout",
    [
        "",
        "not-a-real-id",
        "deadbeef --privileged",
        "A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6E7F8A9B0C1D2E3F4A5B6C7D8E9F0A1B2",
    ],
)
def test_malformed_container_id_fails_safely_without_cleanup(dest, capsys, bad_stdout):
    """An empty or hostile docker-run stdout must never be used as a
    container id: the run fails closed with no further docker command
    (no inspect/exec/cp/rm), and the locally generated NAME is
    reported for manual removal instead."""
    dump = _write_backup(dest)
    runner = FakeVerifyRunner(run_stdout=bad_stdout)
    rc = verify_restore.run_verify([str(dump)], runner=runner)
    assert rc == 1
    post_run_calls = [c for c in runner.calls if c[:2] != ["docker", "run"]]
    assert post_run_calls == [], "no docker command may use an untrusted id"
    assert runner.removed == []
    err = capsys.readouterr().err
    assert "malformed container id" in err
    assert verify_restore.CONTAINER_NAME_PREFIX in err
    assert "docker rm -f" in err


def test_checksum_sidecar_write_failure_cleans_all_artifacts(
    dest, frozen_clock, monkeypatch, capsys
):
    real_write_text = Path.write_text

    def _fail_sha256(self, data, encoding=None, errors=None, newline=None):
        if self.name.endswith(".sha256"):
            raise OSError("disk full")
        return real_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_text", _fail_sha256)
    rc = pg_backup.run_backup(["--dest", str(dest)], runner=FakeBackupRunner())
    assert rc == 1
    assert not list(dest.glob("*.dump")), "unlabelled dump must not survive"
    assert not list(dest.glob("*.manifest.json")), "orphan manifest must not survive"
    assert not list(dest.glob("*.sha256"))
    assert "no partial backup kept" in capsys.readouterr().err
