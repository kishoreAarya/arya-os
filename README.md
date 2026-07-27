# Project Arya OS — Sprint 1: Foundation

This is the foundation scaffold for the Personal AI Content Factory
described in the architecture doc. It is deliberately minimal — it
proves the plumbing works before any pipeline logic is added.

## What's here

- **FastAPI app** (`backend/app/main.py`) with a `/health` endpoint that
  checks both Postgres and Redis are reachable.
- **Centralized config** (`backend/app/core/config.py`) — all settings
  flow through one `Settings` object via dependency injection. No module
  reads `os.environ` directly.
- **Structured logging** (`backend/app/core/logging.py`) via structlog —
  JSON in production, readable console output in dev.
- **Async SQLAlchemy 2.x** session setup, ready for Sprint 2's models.
- **Alembic** wired to app settings, ready for the first migration once
  models exist.
- **Docker Compose** running Postgres, Redis, the backend, and n8n
  together — n8n stays the workflow orchestrator; this backend exposes
  services n8n calls into (see architecture note below).
- **One smoke test** confirming the app boots.

## Architecture note: n8n vs. backend

n8n remains the pipeline orchestrator (Trend Discovery → ... → Publish).
This FastAPI backend does **not** duplicate that — it exposes REST
endpoints n8n workflow nodes call for anything too complex for n8n's
built-in nodes: provider abstraction, validation logic, the learning
loop, artifact storage. Keep orchestration in n8n; keep business logic
and data integrity in this backend.

## Running it

```bash
cp .env.example .env
# edit .env with real Postgres/Redis passwords and provider keys as you get them

docker compose up --build
```

Then check:
- `http://localhost:8000/` → `{"service": "arya-os", "status": "running", "sprint": 1}`
- `http://localhost:8000/health` → confirms Postgres + Redis connectivity
- `http://localhost:5678` → n8n dashboard (login with N8N_BASIC_AUTH_USER/PASSWORD)

## Local dev (without Docker, for fast iteration)

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn app.main:app --reload --app-dir backend
```

## What's deliberately NOT here yet

Per the architecture review: `Users` table, circuit breakers, dead
letter queue, and rate-limiting middleware are deferred until a real
need shows up — building them now would be solving problems you don't
have yet, at the cost of shipping your first pipeline slower.

## Sprint 2 — Database (done)

All 15 tables from the architecture doc now exist as SQLAlchemy models
under `backend/app/models/`, verified to compile to valid Postgres DDL:

| File | Tables | Plain-language purpose |
|---|---|---|
| `core.py` | Project, WorkflowRun | A channel, and one full pipeline run for one video |
| `content.py` | Script, Storyboard, Prompt | The written script, its shot breakdown, and every exact prompt sent to a generator |
| `media.py` | Image, GeneratedVideo, Asset, Video | Raw generated shots, supporting audio/music, and the one final assembled video |
| `provider.py` | Provider, ProviderUsageLog | Registry of external services, and a cost/usage row for every single API or GPU call |
| `system.py` | Artifact, SystemLog | An index of every output produced, and workflow-level event history |
| `analytics.py` | Analytics, LearningFeedback | YouTube performance snapshots, and conclusions the Learning Agent draws from them |

**Cost-per-video tracking** (flagged in the architecture review) is
built in: `ProviderUsageLog.cost_usd` logs spend per call, rolling up
to `WorkflowRun.total_cost_usd`.

**Learning Loop** (also flagged as undefined) now has a concrete shape:
`Analytics` rows feed the Learning Agent (Sprint 10), which writes
`LearningFeedback` rows tagged by category (topic/script/thumbnail/
title), which future Trend/Script agents read before their next run.

### Generate and apply the first migration

This needs a live Postgres, so run it against your own Docker stack:

```bash
docker compose up -d postgres
docker compose run --rm backend uv run alembic revision --autogenerate -m "initial schema"
docker compose run --rm backend uv run alembic upgrade head
```

Check the generated file under `alembic/versions/` before applying —
autogenerate is a good draft, not a guarantee.

## Production Hardening (done)

Ten additions on top of Sprint 2, requested to close the gap between
"pipeline that works" and "pipeline you'd trust with real output."

### 1. Asset Versioning
`VersionedAssetMixin` (in `models/mixins.py`) adds `version`,
`parent_version_id`, `status` (Draft/Generated/Approved/Rejected),
`retry_reason`, and `quality_score` to Script, Storyboard, Prompt,
Image, GeneratedVideo, Video, and the new `Thumbnail` table. Rejected
drafts are never deleted — they're just rows with `status=REJECTED`
that the next attempt's `parent_version_id` points back at.
**Why:** so "Prompt V1 -> Image V1 -> Rejected, Prompt V2 -> Image V2
-> Approved" is a real queryable history, and the Learning Loop always
knows which version actually got published.

### 2. Human-in-the-Loop Approval
New `ApprovalCheckpoint` table + `/approvals` router (`api/routers/
approvals.py`). n8n creates a checkpoint after each stage (trend,
script, storyboard, prompt, image, video, thumbnail) and waits for a
decision (approve/reject/retry/manual_edit/continue) before proceeding.
**Why:** stops autonomous publishing until your validators have a track
record — the exact gap flagged in the first architecture review.
**Fits:** sits between an Agent's output and the next Agent's input;
n8n is still the one enforcing the pause, this backend just stores
the decision.

### 3. Quality Score System
`quality_score` (0-100) lives on every versioned asset for a single
overall number. The new `QualityScoreDetail` table holds dimension
breakdowns (Story, Consistency, Image, Prompt, Thumbnail, Overall
Video) that don't map cleanly to one table.
**Why:** lets Performance Learning later correlate specific dimensions
against YouTube results (e.g. "high Image Quality -> higher CTR").

### 4. Retry History
New `GenerationAttempt` table — one row per try, not just a final
success/failed flag. Tracks attempt number, failure reason, validation
failure, provider used, cost, and duration.
**Why:** "Attempt 1 failed, Attempt 2 failed, Attempt 3 passed" is now
a queryable fact, including what each failed attempt cost you.

### 5. Separate Learning Systems
`models/analytics.py` now has two independent tables:
- `GenerationLearningEvent` — pre-publish, validator-driven (e.g.
  "Image Validator flagged face inconsistency -> prompt rewritten").
- `PerformanceLearningFeedback` — post-publish, YouTube-analytics-
  driven (CTR, retention, watch time, drop-off, likes, shares,
  subscribers gained, all now on `Analytics`).
**Why:** these answer different questions and use different evidence —
merging them would blur "the validator didn't like it" with "the
audience didn't like it."

### 6. Independent Validators
`backend/app/validators/` — `StoryValidator`, `PromptValidator`,
`ImageValidator`, `ConsistencyValidator`, `VideoValidator`,
`ThumbnailValidator`, `BrandValidator`, all implementing one
`BaseValidator.validate()` contract, registered in `VALIDATOR_REGISTRY`.
**Why:** an agent must never grade its own output. Validators are
called by the pipeline, never imported by an agent.

### 7. One FastAPI Backend (confirmed, not changed)
Still a single app with multiple routers (`api/routers/approvals.py`,
more to come) sharing one database and one set of services/providers.
No microservices were introduced.

### 8. Agent Plugin Architecture
`backend/app/agents/` — `BaseAgent.run()` contract, 7 stub agents
(trend/script/prompt/image/video/thumbnail/music), registered in
`AGENT_REGISTRY` (a plain dict, not an auto-discovery framework — that
would be over-engineering here). Adding a new agent = one new file +
one registry line.

### 9. Simplified Data Access
The empty `repositories/` folder from Sprint 1 has been **removed**.
In its place, `services/workflow_service.py` shows the pattern going
forward: plain async functions taking a session, no per-table
wrapper classes. Add functions here as real query needs come up.

### 10. Redis Stays Minimal (confirmed, not changed)
No internal event bus was added. Redis is still only wired for
caching/temporary state; the flow remains n8n -> REST -> FastAPI ->
Database.

## Hardening Pass 3 — Providers, Config, Ops

This pass answers the 14-point final-architecture-hardening review.
Nothing was redesigned, no microservices/Kafka/service-mesh were
added, n8n is still the only orchestrator, and Postgres is still the
only database. Nine items were genuinely new code; five were mostly
already built in Sprint 2 and just got formalized.

### New folder structure (only additions shown)

```
backend/app/
├── core/
│   ├── config.py          # extended: global tunables + feature-flag defaults + storage config
│   └── secrets.py         # NEW — single chokepoint for every API key/secret
├── events/
│   └── log.py             # NEW — EventType enum + log_event(), writes to SystemLog
├── providers/
│   ├── capabilities.py    # NEW — Provider Capability Registry
│   └── router.py          # NEW — Provider Router with fallback + cost ceiling
├── storage/
│   ├── base.py             # NEW — StorageProvider interface
│   ├── local.py            # NEW — local disk backend (default)
│   ├── s3.py                # NEW — S3 / Cloudflare R2 backend (boto3, lazy import)
│   └── __init__.py          # NEW — get_storage_provider() factory, reads STORAGE_BACKEND
├── workers/
│   ├── scheduler.py         # NEW — APScheduler wrapper, internal maintenance only
│   └── jobs.py               # NEW — job stubs: analytics, cost rollup, learning update, cleanup
├── models/
│   ├── prompt_template.py    # NEW — PromptTemplate table (Prompt gained template_id + version FKs)
│   ├── feature_flag.py       # NEW — FeatureFlag table
│   └── enums.py               # extended: PipelineStage enum (the state machine)
├── services/
│   ├── feature_flags.py       # NEW — is_enabled()/set_flag(), DB override + Settings fallback
│   ├── pipeline_state.py      # NEW — STAGE_TRANSITIONS + advance_stage() + resume_stage()
│   └── lineage_service.py     # NEW — get_lineage(run_id): full artifact trace
└── api/routers/
    ├── health.py               # NEW — /health /ready /providers /database /storage /validators
    ├── feature_flags.py        # NEW — GET/PUT /feature-flags
    └── lineage.py               # NEW — GET /lineage/{workflow_run_id}
```

### Item-by-item

**1. Provider Capability Registry** — `providers/capabilities.py`. A
plain dict (`PROVIDER_CAPABILITIES`), same philosophy as
`AGENT_REGISTRY`: no plugin auto-discovery, just one entry per
provider declaring its `Capability` values, cost tier, latency, and
which `Settings` field holds its secret. `providers_for(capability)`
returns matches cheapest-first — that ordering *is* the default
fallback priority.

**2. Dynamic Provider Fallback** — `providers/router.py`.
`call_with_fallback(capability, call_fn, ...)` tries providers in
priority order, logs every attempt through the Event Log, stops at
the first success, and refuses to start a new call once
`WorkflowRun.total_cost_usd` hits `MAX_COST_PER_VIDEO_USD`. Agents
never hardcode a fallback chain — they call the router once.

**3. Global Configuration System** — extended the *existing*
`core/config.py` (it was already the single source of truth per its
own docstring) with `quality_threshold`, `max_retry_attempts`,
`api_timeout_seconds`, `image_resolution`, `video_fps`,
`max_cost_per_video_usd`, and the six feature-flag defaults. No new
file needed — this was 90% done already.

**4. Workflow State Machine** — `models/enums.py` gained
`PipelineStage` (Created → Trend Selected → ... → Learning Updated,
exactly the list from the brief) and `services/pipeline_state.py`
holds `STAGE_TRANSITIONS`, a fixed adjacency map. `advance_stage()` is
the *only* function allowed to write `WorkflowRun.current_stage` — it
raises `InvalidStageTransitionError` on any disallowed jump. No
migration needed: `current_stage` was already a free string column.

**5. Central Event Logging** — `events/log.py`. `SystemLog` already
existed (Sprint 2); this adds the `EventType` enum (workflow started,
provider called, validation failed, retry triggered, human approved,
publishing started/completed, analytics imported, learning updated,
etc.) and `log_event()`, a fire-and-forget async write that never
raises into the caller.

**6. Prompt Template Versioning** — `models/prompt_template.py`
(`PromptTemplate`: name, version, template_text, variables JSONB,
model_used, revision_notes, is_deprecated). `content.py`'s `Prompt`
gained nullable `prompt_template_id` + `template_version` so every
generated prompt can point back at the exact template revision that
produced it, without breaking hand-written/ad hoc prompts.

**7. Feature Flags** — `models/feature_flag.py` + `services/
feature_flags.py`. `is_enabled(name)` checks the DB first (30s
in-process cache), falls back to the matching `Settings` boolean.
`PUT /feature-flags/{name}` flips one at runtime, no redeploy.

**8. Background Job Scheduler** — `workers/scheduler.py` (APScheduler,
started/stopped in `main.py`'s lifespan) + `workers/jobs.py` (stubs:
`collect_analytics`, `aggregate_costs`, `run_learning_update`,
`cleanup_temp_files`). Explicitly **not** a second orchestrator — jobs
that need pipeline logic (agents/validators/approvals) stay in n8n.

**9. Storage Abstraction** — `storage/base.py` (`StorageProvider` ABC:
upload/download/delete/exists/get_url), `storage/local.py` (default,
zero external deps), `storage/s3.py` (covers both AWS S3 and
Cloudflare R2 — R2 speaks the S3 API, so it's just `boto3` pointed at
a different `endpoint_url`). `get_storage_provider()` factory reads
`STORAGE_BACKEND`. Azure/GCS are left as clear `NotImplementedError`
stubs, same convention as the agent stubs — no current need since
Google Drive is the asset store today.

**10. Secrets Management** — `core/secrets.py`. `SecretsManager.get()`
is the only sanctioned way to read a key; it wraps `Settings` today,
swappable for Vault/Cloud Secret Manager later without touching a
single provider file.

**11. Health Monitoring** — `api/routers/health.py`: `/health`
(Postgres+Redis, same check as before), `/ready` (liveness + a
storage round-trip), `/providers` (registry + which secrets are
actually configured), `/database` (row count sanity check),
`/storage` (write/read/delete smoke test), `/validators`
(`VALIDATOR_REGISTRY` keys).

**12. Pipeline Resume** — `services/pipeline_state.py`'s
`resume_stage()`. Since `current_stage` already persists per run, this
is just "read it back and log a `PIPELINE_RESUMED` event" — a crash
recovery script or an n8n Error Trigger node calls this instead of
restarting from `CREATED`, which is what actually saves the GPU time
and cost the item asked for.

**13. Artifact Relationships** — `services/lineage_service.py`'s
`get_lineage(run_id)`. `Artifact.reference_table/reference_id` already
indexed every output (Sprint 2); this walks every `Artifact` for a
run and joins in its `QualityScoreDetail`, `GenerationAttempt`
(provider + cost), and `ApprovalCheckpoint` rows — one call answers
"what produced this video, with what model, at what cost, who
approved it." Exposed at `GET /lineage/{workflow_run_id}`.

**14. Keep It Simple** — confirmed, not touched. No Kubernetes, no
Kafka/RabbitMQ/event bus, still one FastAPI app with routers (now 4:
approvals, health, feature-flags, lineage), still plain functions in
`services/` instead of a repository layer.

### Migration notes

No migrations exist yet in `alembic/versions/` — Sprint 2's models
were never applied to a live database. That means this pass needs
**one** migration, not an incremental patch:

```bash
docker compose up -d postgres
docker compose run --rm backend uv run alembic revision --autogenerate -m "sprint2 + hardening pass 3 baseline"
docker compose run --rm backend uv run alembic upgrade head
```

Review the generated file before applying (autogenerate is a draft).
It will create every Sprint 2 table plus the two new ones from this
pass (`prompt_templates`, `feature_flags`) and the two new nullable
columns on `prompts` (`prompt_template_id`, `template_version`) — all
additive, nothing destructive.

New dependency: `apscheduler` (added to core deps). `boto3` is an
**optional** extra (`storage-s3`) — only needed if you set
`STORAGE_BACKEND=s3` or `r2`; local storage has zero new deps.

### What's still a stub (by design)

Same Sprint 3+ scope as before this pass: the actual provider client
calls (OpenRouter/Gemini/fal.ai/ComfyUI HTTP wiring), the job bodies
in `workers/jobs.py`, and Azure/GCS storage backends. The *shape*
(registry, router, scheduler, storage interface) is now in place so
filling those in is additive work, not architecture work.

