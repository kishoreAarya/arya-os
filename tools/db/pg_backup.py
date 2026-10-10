#!/usr/bin/env python3
"""AryaOS PostgreSQL backup helper — pg_dump custom-format with atomic
output, SHA-256 checksum, and a metadata manifest.

Safety contract (see docs/DATABASE_BACKUP_RESTORE_RUNBOOK.md):
- Credentials NEVER appear in host command lines, logs, the manifest,
  or filenames. The dump runs INSIDE the compose postgres container;
  the username/database are expanded from the container's own
  environment by an in-container shell, and no password is used
  (local-socket auth inside the official postgres image).
- Output is atomic: the dump streams to a temporary file in the
  destination directory and is renamed only after success. A failed
  dump never leaves a *.dump, manifest, or checksum behind.
- Any failed step exits non-zero; a partial dump is never labelled
  successful.
- Destinations inside the repository worktree are refused (dumps must
  not be committable by accident); an existing target file is refused
  unless --force is passed explicitly.

NOT covered by a database dump: media artifacts stored in the
`arya_storage_data` volume (see the runbook's off-host copy section).

Usage (no production side effects beyond reading the database):
    uv run python tools/db/pg_backup.py --dest /backups/arya
        [--compose-file docker-compose.prod.yml] [--service postgres]
        [--force]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA_VERSION = 1
TOOL_VERSION = "1"


class BackupError(RuntimeError):
    """Operator-detectable backup failure (message is safe to print)."""


# ---------------------------------------------------------------------------
# Pure, testable helpers
# ---------------------------------------------------------------------------


def validate_dest_dir(dest: Path, worktree: Path = WORKTREE_ROOT) -> Path:
    """Refuse unsafe destinations: an existing non-directory, or any
    path inside the repository worktree (a dump must never be
    accidentally committable). Creates the directory when absent."""
    resolved = dest.expanduser().resolve()
    try:
        resolved.relative_to(worktree.resolve())
    except ValueError:
        pass
    else:
        raise BackupError(
            f"refusing backup destination inside the repository worktree: {resolved}"
        )
    if resolved.exists() and not resolved.is_dir():
        raise BackupError(f"backup destination exists and is not a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def build_dump_command(compose_file: Path, service: str) -> list[str]:
    """pg_dump --format=custom executed INSIDE the container. The
    username/database expand from the container's own environment;
    nothing credential-like is placed in the host command line."""
    return [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "exec",
        "-T",
        service,
        "sh",
        "-c",
        'exec pg_dump --format=custom --no-password --username "$POSTGRES_USER" '
        '--dbname "$POSTGRES_DB"',
    ]


def build_container_query(compose_file: Path, service: str, script: str) -> list[str]:
    """Run a short psql/printenv script inside the container (safe,
    read-only introspection; never touches POSTGRES_PASSWORD)."""
    return [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "exec",
        "-T",
        service,
        "sh",
        "-c",
        script,
    ]


def query_db_name(compose_file: Path, service: str, runner) -> str:
    out = _capture(build_container_query(compose_file, service, 'printf %s "$POSTGRES_DB"'), runner)
    value = out.strip()
    if not value:
        raise BackupError("could not read POSTGRES_DB from the container environment")
    return value


def query_pg_client_version(compose_file: Path, service: str, runner) -> str:
    return _capture(build_container_query(compose_file, service, "pg_dump --version"), runner).strip()


def query_pg_server_version(compose_file: Path, service: str, runner) -> str:
    script = (
        'exec psql --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" '
        "--tuples-only --no-align --command \"SHOW server_version\""
    )
    return _capture(build_container_query(compose_file, service, script), runner).strip()


def query_alembic_revision(compose_file: Path, service: str, runner) -> str | None:
    """Best-effort safe read; None when the table does not exist yet
    (never-migrated database) or the read fails."""
    script = (
        'exec psql --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" '
        "--tuples-only --no-align --command "
        '"SELECT version_num FROM alembic_version" 2>/dev/null'
    )
    try:
        return _capture(build_container_query(compose_file, service, script), runner).strip() or None
    except BackupError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture(cmd: list[str], runner) -> str:
    proc = runner(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise BackupError(
            f"container command failed (exit {proc.returncode}): "
            f"{' '.join(cmd[:3])}… {detail[-1] if detail else ''}"
        )
    return proc.stdout


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_backup(argv: list[str] | None = None, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="AryaOS PostgreSQL backup helper")
    parser.add_argument("--dest", required=True, help="backup directory (outside the repository)")
    parser.add_argument("--compose-file", default="docker-compose.prod.yml")
    parser.add_argument("--service", default="postgres")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacing an existing backup file with an identical timestamped name",
    )
    args = parser.parse_args(argv)

    compose_file = Path(args.compose_file)
    if not compose_file.is_file():
        print(f"ERROR: compose file not found: {compose_file}", file=sys.stderr)
        return 1

    def fail(message: str, tmp: Path | None = None) -> int:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"ERROR: {message}", file=sys.stderr)
        return 1

    try:
        dest = validate_dest_dir(Path(args.dest))
    except BackupError as exc:
        return fail(str(exc))

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_name = f"arya_os_backup_{stamp}.dump"
    final_path = dest / final_name
    if final_path.exists() and not args.force:
        return fail(
            f"backup target already exists: {final_path} (pass --force to replace it)"
        )

    db_name = client_version = server_version = revision = None
    try:
        db_name = query_db_name(compose_file, args.service, runner)
        client_version = query_pg_client_version(compose_file, args.service, runner)
        server_version = query_pg_server_version(compose_file, args.service, runner)
        revision = query_alembic_revision(compose_file, args.service, runner)
    except BackupError as exc:
        return fail(f"preflight failed: {exc}")

    fd, tmp_name = tempfile.mkstemp(prefix=".arya-backup-", suffix=".tmp", dir=dest)
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "wb") as tmp_fh:
            proc = runner(build_dump_command(compose_file, args.service), stdout=tmp_fh)
        if proc.returncode != 0:
            return fail(f"pg_dump failed (exit {proc.returncode}); no backup was written", tmp_path)
        tmp_fh_size = tmp_path.stat().st_size
        if tmp_fh_size == 0:
            return fail("pg_dump produced an empty dump; treating as failure", tmp_path)
        checksum = sha256_file(tmp_path)
        os.replace(tmp_path, final_path)
    except Exception as exc:  # never label a partial dump successful
        return fail(f"backup failed: {exc}", tmp_path)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "backup_id": uuid.uuid4().hex,
        "source": {
            "compose_file": str(compose_file),
            "service": args.service,
            "database": db_name,
            "pg_client_version": client_version,
            "pg_server_version": server_version,
            "alembic_revision": revision,
        },
        "backup": {
            "filename": final_name,
            "format": "pg_dump custom",
            "size_bytes": final_path.stat().st_size,
            "sha256": checksum,
        },
    }
    try:
        (dest / f"{final_name}.manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (dest / f"{final_name}.sha256").write_text(
            f"{checksum}  {final_name}\n", encoding="utf-8"
        )
    except OSError as exc:
        # A dump without its complete manifest+checksum sidecars can
        # never be verified; remove every artifact THIS RUN created
        # (os.replace already placed the dump; one sidecar may exist if
        # the other's write failed) so no partial backup survives.
        # Pre-existing user files are never touched — the only paths
        # removed are this run's timestamped outputs.
        for artifact in (
            final_path,
            dest / f"{final_name}.manifest.json",
            dest / f"{final_name}.sha256",
        ):
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
        print(
            f"ERROR: backup succeeded but writing the manifest/checksum failed "
            f"({exc}); the unlabelled dump and any partial sidecars were "
            f"removed — no partial backup kept",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK backup written: {final_path} "
        f"({manifest['backup']['size_bytes']} bytes, sha256 {checksum[:16]}…, "
        f"alembic {revision or 'n/a'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_backup())
