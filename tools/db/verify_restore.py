#!/usr/bin/env python3
"""AryaOS backup restore verification — restores a backup into a
DISPOSABLE, network-isolated PostgreSQL 16 container and runs sanity
checks. Never touches production.

Safety contract (see docs/DATABASE_BACKUP_RESTORE_RUNBOOK.md):
- The only container it creates or removes is one IT created, with a
  unique `arya-restore-verify-*` name, NO volumes, NO published ports,
  `--network none`, the same digest-pinned postgres:16-alpine image as
  production, and NO password at all (disposable trust auth).
- The backup's SHA-256 is verified against its manifest BEFORE any
  restore; missing or malformed manifests fail closed with no docker
  side effects.
- Cleanup removes ONLY the container created by this run (verified by
  container id and name prefix before removal), on EVERY exit path —
  expected failure, unexpected exception, or interruption — unless
  --keep was requested. Pre-existing containers, volumes, and files
  are never touched. A removal that fails is REPORTED (with the
  container name) and never claimed successful; the container id
  returned by docker run is validated before any use, and an
  empty/malformed id fails closed with no cleanup attempted.
- pg_restore runs with --exit-on-error: the first restore error stops
  the restore instead of continuing with a partial dataset.
- Exit code 0 only when checksum, restore, and every sanity check
  (including the Alembic revision stamp) pass — and, unless --keep was
  requested, required container cleanup also succeeded. Table-count,
  revision, and row-count reporting establish the archive RESTORES and
  is schema-consistent — they do NOT prove business-data completeness
  or application-level recovery (see the runbook).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Same immutable digest pin as docker-compose.prod.yml's postgres
# service — bump deliberately, together with the compose pin.
IMAGE = "postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
CONTAINER_NAME_PREFIX = "arya-restore-verify-"
SCRATCH_DB = "arya_restore_check"
REQUIRED_MANIFEST_KEYS = {"schema_version", "created_at_utc", "source", "backup"}
READY_TIMEOUT_SECONDS = 90
# Informational row counts are only taken for table names that are
# provably safe to interpolate (no quotes, newlines, or other characters
# that could break or shape the generated SQL). Unusual names are
# counted and REPORTED as skipped — never silently mangled.
SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_TABLE_NAME_SQL = "^[A-Za-z_][A-Za-z0-9_]*$"
# `docker run --detach` prints the full 64-hexadecimal container id on
# stdout. Anything else (empty, truncated, uppercase, or characters
# that could reshape a docker command line) is treated as untrusted:
# the run fails closed and NO cleanup is attempted with that
# identifier — the generated container NAME (known locally) is given
# to the operator for manual removal instead.
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


class RestoreVerifyError(RuntimeError):
    """Operator-detectable verification failure (safe to print)."""


# ---------------------------------------------------------------------------
# Pure, testable helpers
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise RestoreVerifyError(f"manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RestoreVerifyError(f"manifest is malformed: {exc}") from None
    if not isinstance(manifest, dict) or not REQUIRED_MANIFEST_KEYS <= set(manifest):
        raise RestoreVerifyError(
            f"manifest is missing required fields {sorted(REQUIRED_MANIFEST_KEYS)}"
        )
    backup = manifest.get("backup")
    if not isinstance(backup, dict) or not {"filename", "sha256"} <= set(backup):
        raise RestoreVerifyError("manifest 'backup' section is missing filename/sha256")
    return manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(dump_path: Path, manifest: dict) -> str:
    expected = manifest["backup"]["sha256"]
    actual = sha256_file(dump_path)
    if actual != expected:
        raise RestoreVerifyError(
            "CHECKSUM MISMATCH: the backup file does not match its manifest "
            f"(expected {expected}, got {actual}). Do not use this backup; see "
            "the runbook's checksum-mismatch section."
        )
    return actual


def build_run_args(name: str) -> list[str]:
    """docker create/run arguments for the disposable verification
    container. Isolation properties asserted by assert_isolated_run_args."""
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "-e",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        IMAGE,
    ]


def assert_isolated_run_args(args: list[str]) -> None:
    """Fail closed unless the container invocation is provably isolated:
    no published ports, no volumes, no network attachment."""
    if "-p" in args or "--publish" in args:
        raise RestoreVerifyError("refusing to run verification container with published ports")
    if "-v" in args or "--volume" in args or "--mount" in args:
        raise RestoreVerifyError("refusing to run verification container with volumes/mounts")
    if "--network" not in args or args[args.index("--network") + 1] != "none":
        raise RestoreVerifyError("refusing to run verification container attached to a network")
    if IMAGE not in args:
        raise RestoreVerifyError("refusing to run a non-pinned verification image")


def container_name_of(cid: str, runner) -> str:
    proc = runner(["docker", "inspect", "--format", "{{.Name}}", cid], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RestoreVerifyError(f"cannot inspect verification container {cid[:12]}")
    return proc.stdout.strip().lstrip("/")


def safe_remove_container(cid: str, runner) -> None:
    """Remove ONLY a container whose live name carries our unique
    prefix — never a pre-existing container, even by id confusion.
    A removal that itself fails is RAISED (never silently ignored);
    the message carries the owned container name so an operator can
    remove it manually."""
    name = container_name_of(cid, runner)
    if not name.startswith(CONTAINER_NAME_PREFIX):
        raise RestoreVerifyError(
            f"refusing cleanup of container {name!r}: not created by this tool"
        )
    proc = runner(["docker", "rm", "-f", cid], capture_output=True, text=True)
    if proc.returncode != 0:
        message = (
            f"could not remove disposable container {name} "
            f"(docker rm exit {proc.returncode})"
        )
        detail = (proc.stderr or "").strip()
        if detail:
            message += f": {detail}"
        raise RestoreVerifyError(
            f"{message} — remove it manually: docker rm -f {name}"
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_verify(argv: list[str] | None = None, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="AryaOS backup restore verification")
    parser.add_argument("backup", help="path to the .dump file to verify")
    parser.add_argument(
        "--keep", action="store_true", help="keep the disposable container for debugging"
    )
    args = parser.parse_args(argv)

    dump_path = Path(args.backup)
    manifest_path = dump_path.with_name(dump_path.name + ".manifest.json")
    cid: str | None = None
    created = False
    tables = 0
    row_summary: list[str] = []

    # Pre-docker validation: fail closed with ZERO docker side effects.
    try:
        manifest = load_manifest(manifest_path)
        if not dump_path.is_file():
            raise RestoreVerifyError(f"backup file not found: {dump_path}")
        verify_checksum(dump_path, manifest)
    except RestoreVerifyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Random suffix: concurrent same-second invocations can never
    # collide on the disposable container name.
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = (
        f"{CONTAINER_NAME_PREFIX}{stamp}-{dump_path.stem[-8:]}"
        f"-{uuid.uuid4().hex[:6]}"
    )

    outcome_error: BaseException | None = None
    cleanup_error: RestoreVerifyError | None = None

    def cexec(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        full = ["docker", "exec", cid, *cmd]
        out = runner(full, capture_output=True, text=True)
        if check and out.returncode != 0:
            raise RestoreVerifyError(f"docker exec failed ({cmd[0]}): {out.stderr.strip()}")
        return out

    try:
        run_args = build_run_args(name)
        assert_isolated_run_args(run_args)
        proc = runner(run_args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RestoreVerifyError(
                f"could not start disposable verification container: {proc.stderr.strip()}"
            )
        cid = proc.stdout.strip()
        if not CONTAINER_ID.fullmatch(cid):
            # Untrusted identifier: never used for exec/cp/rm. Fail
            # closed with ZERO further docker side effects; the run
            # may still have created a container, so hand the operator
            # the (locally generated, trusted) NAME for manual removal.
            raise RestoreVerifyError(
                f"docker run returned a malformed container id ({cid[:24]!r}); "
                "refusing to operate on it and attempting no cleanup. If a "
                f"container was created it is named {name}; remove it "
                f"manually: docker rm -f {name}"
            )
        created = True

        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while True:
            if cexec("pg_isready", "-U", "postgres", check=False).returncode == 0:
                break
            if time.monotonic() > deadline:
                raise RestoreVerifyError("verification postgres did not become ready in time")
            time.sleep(1)

        cexec("psql", "-U", "postgres", "--command", f'CREATE DATABASE "{SCRATCH_DB}"')
        cp = runner(
            ["docker", "cp", str(dump_path), f"{cid}:/tmp/backup.dump"],
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            raise RestoreVerifyError(f"docker cp failed: {cp.stderr.strip()}")
        cexec(
            "pg_restore",
            "-U",
            "postgres",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            SCRATCH_DB,
            "/tmp/backup.dump",
        )

        tables = int(
            cexec(
                "psql",
                "-U",
                "postgres",
                "-d",
                SCRATCH_DB,
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'",
            ).stdout.strip()
        )
        if tables <= 0:
            raise RestoreVerifyError("restore produced zero public tables — backup unusable")

        expected_revision = manifest["source"].get("alembic_revision")
        if expected_revision:
            revision = (
                cexec(
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    SCRATCH_DB,
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT version_num FROM alembic_version",
                )
                .stdout.strip()
            )
            if revision != expected_revision:
                raise RestoreVerifyError(
                    f"alembic revision mismatch after restore: {revision!r} != {expected_revision!r}"
                )

        # INFORMATIONAL per-table row counts — best-effort by design:
        # - the catalog query itself only returns safe names (SQL-side
        #   regex filter), the client re-validates each parsed line, and
        #   unusual names are counted and reported as skipped;
        # - a count that fails is reported as unavailable and NEVER
        #   fails the verification (only restore/checksum/schema/
        #   revision failures do that).
        # A completeness PROOF this is not.
        raw_names = [
            row.strip()
            for row in cexec(
                "psql",
                "-U",
                "postgres",
                "-d",
                SCRATCH_DB,
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                f"AND table_name ~ '{SAFE_TABLE_NAME_SQL}' "
                "ORDER BY table_name",
            ).stdout.splitlines()
            if row.strip()
        ]
        unusual = int(
            cexec(
                "psql",
                "-U",
                "postgres",
                "-d",
                SCRATCH_DB,
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                f"AND table_name !~ '{SAFE_TABLE_NAME_SQL}'",
            ).stdout.strip()
        )
        table_names = [name for name in raw_names if SAFE_TABLE_NAME.match(name)]
        skipped_unusual = unusual + (len(raw_names) - len(table_names))
        for table_name in table_names[:30]:
            escaped = table_name.replace('"', '""')  # defense in depth
            count_out = cexec(
                "psql",
                "-U",
                "postgres",
                "-d",
                SCRATCH_DB,
                "--tuples-only",
                "--no-align",
                "--command",
                f'SELECT count(*) FROM "{escaped}"',
                check=False,
            )
            if count_out.returncode != 0:
                row_summary.append(f"{table_name}=unavailable")
            else:
                row_summary.append(f"{table_name}={count_out.stdout.strip()}")
        if skipped_unusual:
            row_summary.append(f"{skipped_unusual} unusual-name table(s) skipped")
        if len(table_names) > 30:
            row_summary.append(f"…and {len(table_names) - 30} more tables")
    except BaseException as exc:
        # ANY exit path — expected failures, programming errors, even
        # KeyboardInterrupt — records the primary failure and falls
        # through to the finally-guarded cleanup below.
        outcome_error = exc
    finally:
        # Cleanup runs whenever this invocation created a container and
        # --keep was not requested; the ownership guard inside
        # safe_remove_container can never remove an unrelated container.
        if created and cid and not args.keep:
            try:
                safe_remove_container(cid, runner)
                created = False
            except RestoreVerifyError as exc:
                cleanup_error = exc

    if outcome_error is not None:
        # Report a cleanup failure on EVERY failure path BEFORE the
        # primary error is printed or re-raised — the primary failure
        # always remains the headline, never the reverse.
        if cleanup_error is not None:
            print(f"NOTE: cleanup also failed: {cleanup_error}", file=sys.stderr)
        if isinstance(outcome_error, RestoreVerifyError):
            print(f"ERROR: {outcome_error}", file=sys.stderr)
            return 1
        # Unexpected exception: cleanup was attempted above; re-raise so
        # the original failure stays fully visible (traceback intact).
        raise outcome_error
    if cleanup_error is not None:
        # Required cleanup failed: verification may NOT be reported as
        # successful. The cleanup error itself names the container (and
        # the manual-removal command when removal was attempted and
        # failed); `name` is this run's generated name in every case.
        print(
            f"ERROR: verification passed but cleanup failed: {cleanup_error} "
            f"(this run's disposable container was named {name})",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK restore verified: {dump_path.name} -> disposable {SCRATCH_DB} "
        f"({tables} public tables, alembic "
        f"{manifest['source'].get('alembic_revision') or 'n/a'})"
    )
    print("  row counts (informational, NOT a completeness proof): " + ", ".join(row_summary))
    if args.keep:
        print(f"  container kept for debugging (--keep): {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_verify())
