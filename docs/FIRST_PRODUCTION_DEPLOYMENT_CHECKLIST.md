# First-Production-Deployment Checklist

Audience: the AryaOS project owner/operator. Every item states where
the requirement comes from in the repository. Mark each item's outcome
as **PASS / FAIL / NOT VERIFIED** during your deployment; anything not
PASS must be resolved or explicitly accepted by you before going live.

Conventions: commands reference the repo root and
`docker-compose.prod.yml` (the hardened production composition).
Placeholders like `<value>` are for YOU to fill — never write real
secrets into this document.

---

## 1. Pre-deployment review

| # | Item | How to check | Source |
|---|---|---|---|
| 1.1 | Release commit identified & PR merged | Record the exact commit SHA you deploy; confirm the PR (v2 → main) merge state on GitHub | git / GitHub PR page |
| 1.2 | All 8 CI checks green on THAT exact commit | PR "Checks" tab: Pytest + Coverage, Ruff, Black --check, YAML Validation, Bandit, pip-audit, Validate Dockerfile, Build Image | `.github/workflows/*` |
| 1.3 | Known residual risks reviewed | Read the final review notes: approval-rotation window (narrow, follow-up), Black debt ratchet (223 files), B904/F541 deferred lint findings | `pyproject.toml` lint-policy comments |
| 1.4 | UNKNOWN runbook reviewed & reachable by the operator | `docs/UNKNOWN_PUBLICATION_RUNBOOK.md` exists; operator has API key + host access and has read §4/§7 | this repo |
| 1.5 | `.github/SECURITY.md` reporting route known | Read it | `.github/SECURITY.md` |

Outcome 1: ___

## 2. Environment and secrets

Required for production (verified in `backend/app/core/config.py`
`Settings`, `.env.example`, and the compose files):

| # | Variable | Requirement | Source |
|---|---|---|---|
| 2.1 | `APP_ENV=production` | mandatory; with it, API auth is strictly enforced and an unset key fails closed (HTTP 500) | `config.py`; README "Production Enforcement" |
| 2.2 | `ARYA_API_KEY` | REQUIRED — generate with `openssl rand -hex 32`; empty + production = all authenticated endpoints dead | `.env.example`; `config.py` |
| 2.3 | `POSTGRES_PASSWORD` | REQUIRED by prod compose — the file refuses to start without it (`:?` syntax) | `docker-compose.prod.yml` |
| 2.4 | `REDIS_PASSWORD` | REQUIRED — Redis runs authenticated everywhere; compose builds `REDIS_URL` from it | `docker-compose*.yml`, `.env.example` |
| 2.5 | `DATABASE_URL` | set by compose from the internal service name/credentials; app + Alembic both read it (`alembic/env.py` imports app settings) | `alembic/env.py`, `config.py` |
| 2.6 | `STORAGE_BACKEND` / `STORAGE_LOCAL_PATH` | default `local` + `/app/data/storage` (persistent volume); S3/R2 possible via the `storage-s3` extra | `config.py`, compose volumes |
| 2.7 | Provider keys as needed | optional per function: `POSTIZ_API_KEY`/`POSTIZ_BASE_URL`/`POSTIZ_DEFAULT_INTEGRATION_ID` for publishing; LLM/media keys (`OPENROUTER_API_KEY`, `ELEVENLABS_API_KEY`, `REPLICATE_API_KEY`, …) only for the providers you use | `config.py` |

Checks:

* [ ] 2.8 Secrets generated (not reused from dev), stored in the
  deployment environment / `.env` with restricted file permissions,
  and never committed (`git status` clean of secret files).
* [ ] 2.9 Rotation expectation recorded (owner decision — the repo
  defines no automated rotation; NOT VERIFIED capability).
* [ ] 2.10 TLS in front of the API (reverse proxy) so Bearer headers
  are encrypted in transit — README "Production Deployment
  Recommendations".
* [ ] 2.11 `API_AUTH_ENABLED` left at default `true` (it is ignored in
  production anyway).

Outcome 2: ___

## 3. Infrastructure and network

Verified against `docker-compose.prod.yml` / `docker-compose.yml`:

* [ ] 3.1 PostgreSQL and Redis are **not published** to the host in
  prod compose (internal `arya-net` only); dev compose binds any
  published ports to `127.0.0.1` only.
* [ ] 3.2 Containers hardened: `no-new-privileges`, `cap_drop: ALL`,
  non-root users, `read_only` where applicable, `pids_limit` on
  postgres — confirm no local overrides weaken these.
* [ ] 3.3 Images pinned by digest (postgres, redis, backend base, uv)
  — confirm the digest pins are unchanged from the reviewed commit.
* [ ] 3.4 Persistent volumes exist and are backed up-or-accepted:
  `arya_postgres_data`, `arya_redis_data`, `arya_storage_data` (names
  per compose `volumes:` blocks). Redis data is cache/scheduler state
  — losing it is an operational inconvenience, not data loss.
* [ ] 3.5 The backend container's Docker `HEALTHCHECK`
  (`curl -f http://localhost:8000/health`) is visible to your
  orchestrator; `/health` and `/ready` are unauthenticated by design,
  `/providers`, `/database`, `/storage` require the Bearer key
  (`backend/app/api/routers/health.py`).
* [ ] 3.6 Production-specific overrides reviewed: restart policy
  (`unless-stopped`), resource limits you add yourself (none are
  predefined — NOT VERIFIED capacity planning).

Outcome 3: ___

## 4. Database migration

Facts: Alembic is wired to the app's `DATABASE_URL`
(`alembic/env.py`); the container entrypoint runs
`alembic upgrade head` **automatically at startup** and aborts startup
if it fails (`docker/entrypoint.sh`, `AUTO_RUN_MIGRATIONS` default
`true`). Current revision chain (verified with `uv run alembic
history`): base `5faa0b6b68f1` → … → `f6a7b8c9d0e1` (publication
attempts) → **`a7b8c9d0e1f2` (head, publication manifests)**.

> Note: README's "Stability qualification" section references Alembic
> head `f6a7b8c9d0e1` — that text predates the manifest migration and
> is stale; the actual head is `a7b8c9d0e1f2`.

Steps (DO NOT run these against production during documentation
review — this section is the procedure for deployment day):

* [ ] 4.1 **PASS/FAIL:** current production revision known — IMPORTANT:
  under the default configuration the container entrypoint applies
  migrations BEFORE running any command
  (`docker/entrypoint.sh` runs `alembic upgrade head` first unless
  `AUTO_RUN_MIGRATIONS=false`; prod compose pins it to `"true"`), so a
  plain `docker compose … run --rm backend uv run alembic current`
  always reports the POST-migration state. To inspect the current
  revision WITHOUT migrating:

  `docker compose -f docker-compose.prod.yml run --rm -e AUTO_RUN_MIGRATIONS=false backend uv run alembic current`

  (verified: `docker compose run -e` overrides the service's
  `environment:` value; the entrypoint then logs "Automated migrations
  skipped" and runs your command. `POSTGRES_PASSWORD` must still be
  set for compose interpolation.) On a fresh, never-migrated database
  this prints nothing (no `alembic_version` row yet); on a migrated
  one it prints the revision stamp.
* [ ] 4.2 **PASS/FAIL:** migration preview reviewed —
  `uv run alembic upgrade head --sql` (offline SQL render; supported
  by `alembic/env.py`'s offline branch) or read each file under
  `alembic/versions/` — all five newest migrations are ADDITIVE (new
  tables `publication_attempts`, `publication_manifests`,
  `approval_decisions`, `approval_ttl_policies`; new columns). The
  `downgrade()` branches DROP those tables — never run them against a
  database with real data.
* [ ] 4.3 **PASS/FAIL:** verified database backup + **tested
  restore** exist before the first production migration. The repo
  provides **no backup/restore tooling or procedure** (NOT VERIFIED —
  you must establish one, e.g. `pg_dump`/`pg_restore` against the
  `arya_postgres_data` volume, and prove the restore works on a
  scratch database).
* [ ] 4.4 Migration execution (deployment day): normal path is simply
  starting the backend (`docker compose -f docker-compose.prod.yml up
  -d backend`) — the entrypoint applies migrations and **exits
  non-zero, refusing to serve, if they fail**. To apply manually
  first: `docker compose -f docker-compose.prod.yml run --rm backend
  uv run alembic upgrade head`.
* [ ] 4.5 **PASS/FAIL:** post-migration verification —
  `alembic current` shows `a7b8c9d0e1f2 (head)`; startup log shows
  `[entrypoint] Database migrations applied successfully.`
* [ ] 4.6 Failure handling: if the entrypoint aborts, the service did
  NOT start (safe state — no code runs on a half-migrated schema).
  Recovery = restore the backup (4.3) or fix forward with engineering;
  do **not** hand-edit schema; do **not** downgrade after real data
  exists.

Outcome 4: ___

## 5. Deployment and smoke tests (staged, all read-only or dry-run)

Stop conditions: any step FAILs, any unexpected log line
(`ERROR`/`CRITICAL`/traceback), or any endpoint answers
unauthenticated that should not — stop and investigate before
continuing.

* [ ] 5.1 Start infrastructure first:
  `docker compose -f docker-compose.prod.yml up -d postgres redis`;
  wait until healthy (`docker compose -f docker-compose.prod.yml ps`).
* [ ] 5.2 Start the backend: `docker compose -f docker-compose.prod.yml
  up -d backend` — watch logs for the entrypoint's migration success
  line and Uvicorn start (`docker compose -f docker-compose.prod.yml
  logs -f backend`).
* [ ] 5.3 **PASS/FAIL:** liveness — `curl -s
  http://<host>:<port>/health` → top-level
  `{"status": "healthy" | "degraded", "checks": {"postgres": "ok",
  "redis": "ok"}}` — the top-level `status` is `"healthy"` only when
  every dependency check is `"ok"`, otherwise `"degraded"`; each
  dependency's own result lives under `checks` (shape from
  `backend/app/api/routers/health.py`). PASS requires
  `"status": "healthy"` with both `checks` values `"ok"`.
* [ ] 5.4 **PASS/FAIL:** readiness incl. storage round-trip —
  `curl -s http://<host>:<port>/ready` (writes/deletes a test key via
  the configured storage backend).
* [ ] 5.5 **PASS/FAIL:** authentication actually enforced —
  `curl -s -o /dev/null -w '%{http_code}\n'
  http://<host>:<port>/publishing/status` must be **401** (and
  `WWW-Authenticate: Bearer`); the same call with
  `-H "Authorization: Bearer $ARYA_API_KEY"` must be **200**.
* [ ] 5.6 **PASS/FAIL:** database status —
  `curl -s -H "Authorization: Bearer $ARYA_API_KEY"
  http://<host>:<port>/database` → `status: ok`.
* [ ] 5.7 **PASS/FAIL:** dry-run publish validation (ZERO external
  calls — adapters short-circuit on `dry_run`):
  `curl -s -X POST -H "Authorization: Bearer $ARYA_API_KEY" -H
  "Content-Type: application/json" -d '{"asset_storage_path":
  "<a real asset path in your storage>", "dry_run": true, "platform":
  "postiz"}' http://<host>:<port>/publishing/publish` → expect a
  validation response, `is_dry_run: true`, no provider traffic.
  **Never** validate against real social accounts.
* [ ] 5.8 **PASS/FAIL:** Hermes source verification passed in logs
  (the runtime verifies the vendored submodule SHAs at job time;
  `backend/app/hermes/source.py`).

Outcome 5: ___

## 6. First live publication gate

An explicit HUMAN decision (you) is required before the first real
publish. Prerequisites the system itself enforces — confirm you
understand each:

* [ ] 6.1 The publish request carries a real `workflow_run_id` +
  `video_id` (mandatory for non-dry-run; the API returns 422
  otherwise — `backend/app/api/routers/publishing.py`).
* [ ] 6.2 A human **approval checkpoint** exists and is APPROVE, and
  it is **content-bound to a publication manifest** (the immutable
  fingerprint of exactly what will be dispatched) — the dispatch
  refuses otherwise (`backend/app/services/publish_gate.py`,
  `publication_manifest_service.py`).
* [ ] 6.3 Destination (`platform`, `social_platform`,
  `integration_id`) matches the approved manifest; mismatches are
  denied as parameter drift.
* [ ] 6.4 `enable_autonomous_publishing` is at its default `false`
  unless you deliberately enable automation (`config.py`).
* [ ] 6.5 Operator is ready to monitor: during/after the first
  publish, watch `GET /publishing/attempts?video_id=<uuid>`; if the
  attempt lands UNKNOWN, follow `docs/UNKNOWN_PUBLICATION_RUNBOOK.md`
  — do not retry.
* [ ] 6.6 Sign-off: "I approve the first live publication of video
  <video_id> to <platform>/<integration>" — signed ____, date ____.

Outcome 6: ___

## 7. Rollback and recovery

* **Code rollback** = redeploy the previous backend image tag (the
  compose setup expects an explicitly built/tagged image; keep the
  last-known-good tag before deploying the new one). Application code
  rollback is safe with the database schema left at head — the
  migrations are additive and older code ignores newer tables/columns.
* **Database rollback** (`alembic downgrade`) **DROPS the publication
  tables** — after real publication/approval data exists it destroys
  data. **No safe automated database rollback exists.** Recovery from
  a bad migration = restore the pre-migration backup (4.3) with
  engineering support.
* If neither code rollback nor restore is viable: stop the backend
  (containers down), preserve the volumes, escalate.

Escalation (placeholders — fill in before deployment day):

* Engineering: `__ENGINEER_NAME__ / __CHANNEL__`
* Owner: `__OWNER_NAME__ / __CHANNEL__`
* Security: `.github/SECURITY.md`

Outcome 7: ___

## 8. Sign-off table

| # | Item | Evidence (attach/link) | Owner | Status | Notes |
|---|---|---|---|---|---|
| 1 | Pre-deployment review (§1) | | | | |
| 2 | Environment & secrets (§2) | | | | |
| 3 | Infrastructure & network (§3) | | | | |
| 4 | Backup/restore verified (§4.3) | | | | |
| 5 | Migration applied & verified (§4.4-4.5) | | | | |
| 6 | Smoke tests (§5) | | | | |
| 7 | First-publication gate (§6) | | | | |
| 8 | Rollback plan rehearsed/understood (§7) | | | | |

Final deployment approval: signature ____________ date ________

---

## Known NOT VERIFIED capabilities (must be established or accepted)

1. **Database backup + tested restore** — no tooling/procedure in the
   repo (§4.3). Blocker for the first production migration until you
   create and prove one.
2. **Secret rotation automation** — none defined (§2.9).
3. **Resource/capacity limits** — no predefined CPU/memory limits
   (§3.6).
4. **Monitoring/alerting** — health endpoints exist; no alerting
   pipeline is configured in the repo.
5. **Provider-side media cleanup API** — orphaned uploads must be
   removed via the provider console (see the UNKNOWN runbook §6).
