# Database Backup & Restore Runbook (PostgreSQL)

Audience: the AryaOS operator. This runbook closes the backup/restore
gap flagged as NOT VERIFIED in
`docs/FIRST_PRODUCTION_DEPLOYMENT_CHECKLIST.md` §4.3. Everything here
is implemented by two helpers added in the same change:

* `tools/db/pg_backup.py` — takes a backup
* `tools/db/verify_restore.py` — proves a backup is restorable, in a
  disposable isolated PostgreSQL 16 container

Both were unit-tested with fully faked docker commands (see
`backend/tests/test_db_backup_helpers_unit.py`). **No real backup or
restore has been executed yet** — see "What remains unverified" below.

---

## 1. Scope — what a database backup does and does not cover

A `pg_dump` custom-format backup covers everything in the PostgreSQL
volume (`arya_postgres_data`): projects, videos/metadata rows,
approvals, publication attempts/manifests, audit events.

It does **NOT** cover:

* **Media artifacts** in the `arya_storage_data` volume (rendered
  videos, thumbnails, generated assets). Copy/sync that volume's
  backing directory separately (see §6).
* Redis state (`arya_redis_data`) — scheduler/cache state only;
  treated as expendable.

## 2. Taking a backup

From the repository root, with the production compose stack running:

```
uv run python tools/db/pg_backup.py --dest /path/to/backups
```

Defaults target `docker-compose.prod.yml`, service `postgres`
(override with `--compose-file` / `--service`). What the helper does,
and the safety properties it enforces:

* Runs `pg_dump --format=custom` **inside** the container; the
  username/database expand from the container's own environment, so
  **no credential ever appears in a host command line, log, the
  manifest, or a filename** (local-socket auth; no password used).
* Writes three files per backup, all in your `--dest` directory:
  * `arya_os_backup_<UTC-timestamp>.dump` — the dump
  * `arya_os_backup_<UTC-timestamp>.manifest.json` — metadata
  * `arya_os_backup_<UTC-timestamp>.sha256` — checksum sidecar
    (usable with `sha256sum -c`)
* The manifest records: UTC timestamp, database name, pg client and
  server versions, the source **Alembic revision**, file size, and
  SHA-256 — never credentials.
* Atomicity: the dump streams to a temporary file and is renamed only
  after success. Any failure (dump error, empty dump, preflight
  failure) exits non-zero, removes the temporary file, and writes
  **no** manifest — a partial dump is never labelled successful.
* Destination safety: refuses directories inside the repository
  worktree (dumps must not be accidentally committable), refuses
  non-directory paths, and refuses to overwrite an existing backup
  file unless you pass `--force`.

Consistency note (honest limitation): `pg_dump` is consistent per
transaction snapshot; for a guaranteed all-tables-consistent point,
run backups during a quiet window or with the backend stopped
(`docker compose -f docker-compose.prod.yml stop backend` — data-only
stop; postgres keeps running).

## 3. Verifying a backup is restorable (rehearsal)

**Never restore into production.** The verification helper restores
into a disposable container it creates itself:

```
uv run python tools/db/verify_restore.py /path/to/backups/arya_os_backup_<stamp>.dump
```

Before anything runs it: verifies the `.manifest.json` exists and is
well-formed, and re-computes the dump's SHA-256 (any mismatch aborts
with **zero** docker side effects). Then it:

1. Starts one disposable container — unique `arya-restore-verify-*`
   name (timestamp + filename + random suffix, so concurrent runs can
   never collide), the same digest-pinned `postgres:16-alpine` image
   as production, `--network none`, **no volumes, no published ports,
   no password at all**.
2. Creates a scratch database and `pg_restore`s the dump into it with
   `--exit-on-error` (the first restore error stops the restore — no
   partial datasets), `--no-owner --no-privileges`, capturing exit
   status.
3. Sanity checks: at least one public table restored, and the restored
   Alembic revision equals the manifest's.
4. Prints per-table row counts for **human review** (informational
   only; a completeness proof this is not). Tables with unusual names
   (anything outside plain `A-Za-z0-9_` identifiers — quotes,
   newlines, etc.) are skipped and reported as skipped rather than
   risked in generated SQL; an individual count that fails is
   reported as `unavailable` and does not fail the verification.
5. Cleans up **only the container it created** — on success AND on
   every failure or interruption path (the ownership guard verifies
   id and name prefix before removal; pre-existing containers are
   never touched). A removal that itself fails is **reported** with
   the container name (and the manual `docker rm -f` command) and
   fails the run — a leftover disposable container is never silently
   ignored or counted as success. `--keep` intentionally retains the
   container for debugging and prints its name.

Exit 0 = the backup is **restorable and schema-consistent**, and the
disposable container was removed (or `--keep` was requested). It does
NOT prove business-data completeness or that the application works
after recovery: a migrated-but-dataless backup also passes the
automated checks. Review the printed row counts against your
expectations before trusting a backup for recovery.

**Alembic-revision capture race:** the manifest's revision is read at
backup time (`pg_backup.py`). A migration committed between that read
and the dump can make the manifest's revision differ from the dump's
actual revision — the verifier then reports a mismatch and **fails
closed**. That direction is safe (a good backup may be questioned, a
bad one is never waved through); if it happens, take a fresh backup
rather than forcing anything.

## 4. Restoring (real recovery — manual, deliberate)

The automated tool is for *verification*. A real production restore is
a deliberate, engineering-supervised operation:

1. Stop the backend (`docker compose -f docker-compose.prod.yml stop
   backend`). Leave postgres running.
2. Verify the backup (§3) — never restore an unverified file.
3. Restore into a fresh database first, never over live data:

   ```
   docker compose -f docker-compose.prod.yml exec -T postgres \
     sh -c 'createdb --username "$POSTGRES_USER" arya_os_restore'
   cat backup.dmp | docker compose -f docker-compose.prod.yml exec -T postgres \
     sh -c 'pg_restore --username "$POSTGRES_USER" --no-owner \
            --no-privileges --dbname arya_os_restore'
   ```

4. Validate the restored database (table counts, Alembic revision =
   manifest, spot-check business rows).
5. Only then, with engineering support, plan the cutover (rename
   databases under `template1` maintenance, or repoint
   `POSTGRES_DB`). There is **no automated cutover** — do not
   hand-drop the live database without a second human present.
6. Restart the backend and follow the deployment checklist's smoke
   tests (§5 of the first-production checklist).

## 5. Checksum mismatch — what to do

If `verify_restore.py` or `sha256sum -c` reports a mismatch:

1. Do not use, move, or delete the file yet — preserve it as evidence.
2. Re-run verification once (transient read errors are possible).
3. Still mismatched: the file is corrupt (bad disk, truncated copy,
  interrupted transfer). Take a **fresh** backup, verify it, and only
   then delete the corrupt one. If multiple backups show mismatches,
   suspect the storage itself before trusting anything on it.
4. Record the incident (file, checksums, storage medium).

## 6. Retention, encryption, off-host copies, media storage

Recommended practice (operational policy — not automated by the repo):

* **Retention:** keep at least 3 verified backups spanning your risk
  window (e.g., daily × 7, weekly × 4) — adjust to change frequency.
  Backups are only useful once *verified* (§3).
* **Access control & encryption:** the dump contains all application
  data — treat it as production-sensitive. Store on encrypted media
  (FileVault/LUKS/encrypted object storage), restrict file
  permissions (`chmod 600`, dedicated backup user), never on shared
  scratch space.
* **Off-host copies:** a backup on the same disk as the database is
  not a backup. Copy verified backup sets to a second machine or
  object store (encrypted in transit and at rest). Re-verify the
  checksum after copying (`sha256sum -c <file>.sha256`).
* **Media storage (`arya_storage_data`):** back it up independently —
  for example rsync/restic of the volume's backing directory or your
  S3/R2 bucket (if `STORAGE_BACKEND=s3`, enable bucket versioning +
  lifecycle rules). A database restore without media restores
  metadata pointing at missing files.
* **Offline rehearsals / incidents:** `verify_restore.py` uses the
  digest-pinned `postgres:16-alpine` image. If the registry is
  unreachable when you need it (air-gapped host, incident during an
  outage), the image must already exist locally (`docker image ls` to
  confirm). Pre-pull it as part of deployment preparation.

## 7. Prohibited actions

* Never restore into the production database directly "to test".
* Never disable the checksum verification.
* Never store backups inside the repository (the helper refuses this).
* Never commit dumps, manifests, or `.env` material.
* Never run the verification helper with volumes, ports, or networks
  attached (the tool refuses; do not edit around it).

## 8. What remains unverified

* **A real end-to-end backup → verify cycle against a live stack**
  (the helpers are unit-tested against fakes only). First real use is
  itself the rehearsal: run §2 + §3 on the production database *before*
  the first production migration and record results in the deployment
  checklist §4.3.
* Real-restore performance/timing expectations (dataset is currently
  small; re-measure as it grows).
