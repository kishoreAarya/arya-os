#!/usr/bin/env python3
"""AryaOS PostgreSQL backup helper — pg_dump custom-format with atomic
output, SHA-256 checksum, and a metadata manifest.

Safety contract (see docs/DATABASE_BACKUP_RESTORE_RUNBOOK.md):
- Credentials NEVER appear in host command lines, logs, the manifest,
  or filenames. The dump runs INSIDE the compose postgres container;
  the username/database are expanded from the container's own
  environment by an in-container shell, and no password is used
  (local-socket auth inside the official postgres image).
- Output: the dump AND both sidecars (manifest, checksum) are staged
  as temporary files in the destination directory; the final paths
  are then replaced by sequential renames (dump, manifest, checksum)
  only after every write has succeeded — the set is not
  transactional as a group. A failed run never leaves a *.dump,
  manifest, or checksum behind, and a staging failure never destroys
  a pre-existing backup set (--force collisions included); a rename
  failure after the dump replacement removes the partially replaced
  set and reports failure. No fsync durability is provided — see the
  runbook's atomicity limits.
- The source Alembic revision is recorded only when it can actually
  be read: a never-migrated database records None, while a failed or
  ambiguous revision read fails the whole backup (fail closed).
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
    """Return the source database's current Alembic revision, or None
    when the alembic_version table does not exist (a never-migrated
    database). Any OTHER failure — connection, auth, unexpected psql
    output or exit — raises BackupError so the backup fails closed
    instead of silently recording 'no revision'."""
    probe = (
        'exec psql --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" '
        "--tuples-only --no-align --command "
        '"SELECT to_regclass(\'public.alembic_version\') IS NOT NULL"'
    )
    present = _capture(build_container_query(compose_file, service, probe), runner).strip()
    if present not in ("t", "f"):
        raise BackupError(
            f"could not determine whether alembic_version exists (psql said {present!r})"
        )
    if present == "f":
        return None
    script = (
        'exec psql --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" '
        "--tuples-only --no-align --command "
        '"SELECT version_num FROM alembic_version"'
    )
    revision = _capture(build_container_query(compose_file, service, script), runner).strip()
    if not revision:
        raise BackupError("alembic_version exists but version_num is empty")
    return revision


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
        dump_size = tmp_path.stat().st_size
        if dump_size == 0:
            return fail("pg_dump produced an empty dump; treating as failure", tmp_path)
        checksum = sha256_file(tmp_path)
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
            "size_bytes": dump_size,
            "sha256": checksum,
        },
    }
    manifest_path = dest / f"{final_name}.manifest.json"
    sidecar_path = dest / f"{final_name}.sha256"
    manifest_tmp: Path | None = None
    sidecar_tmp: Path | None = None
    committed = False
    try:
        # Stage BOTH sidecars as temp files first: with --force an
        # existing backup set must survive any staging failure, so no
        # final path is replaced until every write has succeeded. The
        # renames then commit the new set (dump first, sidecars after).
        m_fd, m_name = tempfile.mkstemp(prefix=".arya-backup-", suffix=".tmp", dir=dest)
        os.close(m_fd)
        manifest_tmp = Path(m_name)
        s_fd, s_name = tempfile.mkstemp(prefix=".arya-backup-", suffix=".tmp", dir=dest)
        os.close(s_fd)
        sidecar_tmp = Path(s_name)
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest_tmp.write_text(manifest_json, encoding="utf-8")
        sidecar_tmp.write_text(f"{checksum}  {final_name}\n", encoding="utf-8")
        os.replace(tmp_path, final_path)
        committed = True
        os.replace(manifest_tmp, manifest_path)
        os.replace(sidecar_tmp, sidecar_path)
    except OSError as exc:
        # A backup without its complete manifest+checksum sidecars can
        # never be verified. Remove every artifact THIS RUN created:
        # the staged temps always, and the final paths only once the
        # dump rename already committed them (before that, the final
        # paths may hold a PRE-EXISTING backup set, which stays
        # untouched).
        for artifact in (tmp_path, manifest_tmp, sidecar_tmp):
            if artifact is not None:
                try:
                    artifact.unlink(missing_ok=True)
                except OSError:
                    pass
        if committed:
            for artifact in (final_path, manifest_path, sidecar_path):
                try:
                    artifact.unlink(missing_ok=True)
                except OSError:
                    pass
        if committed:
            outcome = "the partially replaced backup set was removed"
        else:
            outcome = (
                "no final artifact was touched — any pre-existing backup "
                "set is intact"
            )
        print(
            f"ERROR: backup succeeded but staging the manifest/checksum failed "
            f"({exc}); no partial backup kept — {outcome}",
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
