# Arya OS Implementation Status

**Audit date:** 2026-07-27
**Audit type:** Engineering gap analysis (no code, workflows, or backend changed)
**Scope:** FastAPI backend, SQLAlchemy models, providers, agents, validators, services, database/migrations, API routes, GitHub Actions, n8n workflow suite.

## Overall completion: ~28%

This is a rough, weighted estimate, not a precise metric — treat it as directional. It's low primarily because the two things that actually make videos (agents and providers) are still 100% stub/contract-only, while everything *around* them (schema, plumbing, CI, orchestration skeleton) is comparatively far along.

| Area | Estimated completion | Basis |
|---|---|---|
| Infrastructure (Docker/DB/Redis/FastAPI/CI) | ~60% | Runs, but no migrations applied yet; CI has no real tests to run |
| Database schema & models | ~70% | Models are thorough; zero migrations exist to actually create the tables |
| Backend API routes | ~40% | 4 routers fully implemented; zero agent/generation-facing routes exist |
| Agents | ~5% | All 6 stub files raise `NotImplementedError`; only the base contract exists |
| Validators | ~5% | All 7 stub files return hardcoded `passed=True`; no real scoring logic |
| Providers | ~10% | Capability registry + fallback router logic exist; zero provider adapters (no HTTP client for OpenRouter, Gemini, ComfyUI, FAL, or RunPod actually calls anything) |
| n8n orchestration | ~45% | 6 of 12 pipeline stages exist as real, importable workflows; all still call placeholder/nonexistent endpoints by design |
| YouTube Upload / distribution | ~30% | Real workflow shape exists (approval gate, upload, thumbnail) but zero OAuth2 credentials configured |

---

## 1. Infrastructure

| Component | Status | Notes |
|---|---|---|
| Docker | PARTIAL | `docker-compose.yml` builds and runs Postgres, Redis, backend, n8n. The compose file bind-mounts source over the built image (dev pattern), and there's no separate prod compose file yet. |
| PostgreSQL | PARTIAL | Container runs and is reachable, but **no Alembic migrations exist** (`alembic/versions/` is empty except `.gitkeep`) — the database has no tables today. |
| Redis | PARTIAL | Container runs, connection is established at FastAPI startup, and `/health` pings it — but nothing in the codebase actually uses Redis for caching, queues, or pub/sub yet. |
| FastAPI | DONE (for what exists) | App boots, structured logging, health-check suite (`/health`, `/ready`, `/providers`, `/database`, `/storage`, `/validators`) is thorough and working. |
| GitHub Actions | DONE (for current scope) | `lint.yml` (Ruff + Black + YAML), `test.yml` (pytest + Postgres/Redis services), `security.yml` (Bandit + pip-audit), `docker.yml` (build + Hadolint) all exist and are valid. Coverage gate intentionally set to 0% since there's almost nothing to cover yet. |
| n8n | PARTIAL | n8n container is defined in compose and reachable at `n8n.somasekhar.dev` per existing infra notes. 6 of 12 pipeline-stage workflows are built and importable; 6 do not exist yet. |
| Configuration | PARTIAL | Centralized `Settings`/`SecretsManager` pattern is solid. `DEBUG` defaults to `True` (should default `False` in production). No `.env` is populated with real values — every provider API key is blank. |

---

## 2. Backend API Status

Every route that exists in the FastAPI app today, verified directly against the router source files.

| Route | Purpose | Implemented | Used by n8n | Missing |
|---|---|---|---|---|
| `GET /` | Root status/sprint marker | Yes | No | — |
| `GET /health` | Liveness check | Yes | No | — |
| `GET /ready` | Readiness check (DB/Redis/storage) | Yes | No | — |
| `GET /providers` | Provider capability/health snapshot | Yes | No | — |
| `GET /database` | DB connectivity check | Yes | No | — |
| `GET /storage` | Storage backend check | Yes | No | — |
| `GET /validators` | Validator registry snapshot | Yes | No | — |
| `POST /approvals/` | Create an approval checkpoint | Yes | **Yes** — YouTube Upload workflow | — |
| `GET /approvals/{checkpoint_id}` | Fetch a checkpoint's decision status | Yes | **Yes** — YouTube Upload workflow polling loop | — |
| `POST /approvals/{checkpoint_id}/decide` | Record a human decision on a checkpoint | Yes | No (would be called by a dashboard, not n8n) | Dashboard UI doesn't exist yet to call this |
| `GET /approvals/pending/{workflow_run_id}` | List pending checkpoints for a run | Yes | No | — |
| `GET /feature-flags/` | List all feature flags | Yes | No | — |
| `GET /feature-flags/{name}` | Get one flag's value | Yes | No | — |
| `PUT /feature-flags/{name}` | Update a flag's value | Yes | No | — |
| `GET /lineage/{workflow_run_id}` | Full lineage/history for a run | Yes | No | — |

**Every agent/generation-facing route referenced by the n8n workflows is missing** — these are listed in Section 6, not this table, since they don't exist in the codebase at all.

---

## 3. Agents

All agent files live in `backend/app/agents/`. Every one currently raises `NotImplementedError` or contains only a class skeleton — there is no real provider-calling logic in any of them.

| Agent | Current implementation | Missing work | Priority |
|---|---|---|---|
| **Trend Agent** (`trend.py`) | Stub — inherits `BaseAgent`, raises `NotImplementedError` | Real trend-source integration (YouTube Data API / news API / Google Trends proxy), normalization, ranking logic | High — first stage, everything downstream depends on it |
| **Script Agent** (`script.py`) | Stub | Prompt construction, call to `ProviderRouter` for `TEXT_GENERATION`, response parsing into `Script` model, word-count/quality metadata | High — second stage |
| **Prompt Agent** (`prompt.py`) | Stub | Purpose in the pipeline isn't fully pinned down yet — likely shot-prompt construction for image/video providers (storyboard → per-shot prompt). Needs a decision on whether this *is* the Storyboard agent or a helper the Storyboard stage calls. | Medium — blocks Storyboard, but scope needs clarifying first |
| **Image Agent** (`image.py`) | Stub | Real ComfyUI/FAL/RunPod HTTP client, per-shot prompt → image call, storage write, `Image` row creation | High — blocks Video Agent |
| **Video Agent** (`video.py`) | Stub | Image-to-video provider client (FAL `ltx-video` or ComfyUI), per-shot clip generation, plus the separate clip-merge/stitch step (`GeneratedVideo` → `Video`) | High |
| **Thumbnail Agent** (`thumbnail.py`) | Stub | Thumbnail generation/selection logic, likely reusing the Image Agent's provider client with different framing/prompt | Medium |
| **Music Agent** (`music.py`) | Stub | Not currently represented anywhere in the n8n pipeline or the Main Orchestrator's 12 stages — scope is undefined. Needs a product decision on whether background music is in scope at all before building this. | Low — unscoped |
| **Metadata Agent** | **Does not exist as a file.** No `metadata.py` in `backend/app/agents/`. The Main Orchestrator's "Metadata Generation" stage has no corresponding agent at all yet — not even a stub. | Everything: title/description/tags generation logic, and the file itself | High — blocks YouTube Upload's `title`/`description` inputs |
| **Storyboard Agent** | **Does not exist as a file.** No `storyboard.py`. Unclear whether this is meant to be `prompt.py` under a different name, or a genuinely separate agent. | Needs a naming/scope decision before anything else | High — blocks Image Agent |
| **Upload Agent** | **Does not exist as a backend agent** — YouTube upload is implemented entirely inside the n8n workflow (native YouTube node + direct Data API call for thumbnails), not as a backend agent. This may be intentional (upload is a distribution action, not a generation step), but is worth confirming explicitly. | N/A if intentional | N/A |
| **Validator Agents** (`validators/*.py`) | All 7 files (`base`, `brand_validator`, `consistency_validator`, `image_validator`, `prompt_validator`, `script_story_validator`, `thumbnail_validator`, `video_validator`) are stubs returning hardcoded `passed=True`, `score=None`, or similar placeholder results | Real scoring logic per validator type — brand-safety checks, shot-to-shot visual consistency, image/thumbnail quality scoring, script/story structure checks | Medium — pipeline can run end-to-end without these actually validating anything, but they're currently rubber-stamps |

---

## 4. n8n Workflow Status

| Workflow | State |
|---|---|
| **Main Orchestrator** | **Blocked** — 6 of its 12 Execute Workflow nodes point at a `TODO_NOT_YET_BUILT` sentinel ID (Script Validation, Image Validation, Video Validation, Thumbnail, Metadata Generation, Human Approval). The other 6 are correctly wired to real, imported workflows. `continueOnFail` is set on the 6 missing stages so the pipeline doesn't hard-crash, but a full run cannot complete end-to-end today. |
| **Research** | **Waiting for provider** — workflow itself is complete and correctly wired (Execute Workflow Trigger → HTTP → normalize → return). Calls a placeholder trend-source URL; no real provider has been chosen yet. |
| **Script Generation** | **Waiting for backend** — workflow is complete and correctly wired. Calls `POST /api/agents/script`, which does not exist on the backend yet (and Script Agent behind it is a stub either way). |
| **Storyboard** | **Waiting for backend** — same situation: calls `POST /api/agents/storyboard`, which doesn't exist; no Storyboard agent exists behind it either. |
| **Image Generation** | **Waiting for provider** — workflow correctly loops over shots and calls a placeholder ComfyUI-style endpoint directly (bypassing the backend entirely — see Section 7). No real self-hosted or cloud image provider is reachable yet. |
| **Video Generation** | **Waiting for provider + backend** — per-shot clip generation calls a placeholder image-to-video provider directly; the separate merge/stitch step calls `POST /api/agents/video-merge`, which doesn't exist. Blocked on both fronts. |
| **YouTube Upload** | **Blocked on credential** — workflow logic is complete: real approval-checkpoint polling loop against `POST /approvals/` + `GET /approvals/{id}` (both real, working endpoints), then a native YouTube upload node and a direct Data API thumbnail call. Both YouTube-related nodes have an unconfigured `youTubeOAuth2Api` credential slot — no Google Cloud project/OAuth2 credential has been created yet. |

---

## 5. Provider Status

| Provider | Configured (API key present) | Implemented (adapter code exists) | Tested |
|---|---|---|---|
| OpenRouter | No — `.env.example` has `OPENROUTER_API_KEY=` blank | No — no `app/providers/openrouter.py` or equivalent adapter exists; only a registry entry in `capabilities.py` | No |
| Gemini | No — blank in `.env.example` | No adapter | No |
| Anthropic | No — blank in `.env.example` | No adapter | No |
| OpenAI | No — blank in `.env.example` | No adapter | No |
| ComfyUI | N/A — self-hosted, no API key by design (`secret_name: None`), no tunnel URL configured yet | No adapter — n8n calls a placeholder ComfyUI URL directly, bypassing the backend's `ProviderRouter` | No |
| FAL | No — blank in `.env.example` | No adapter | No |
| RunPod | No — blank in `.env.example` | No adapter (registry entry exists for `GPU_EXECUTION` capability only) | No |
| Replicate | No — blank in `.env.example` | No adapter | No |
| YouTube | No — no OAuth2 credential created in n8n yet | Partial — n8n's native YouTube node + a direct Data API `thumbnails.set` call are wired, but unusable without credentials | No |

**Important architectural note:** `backend/app/providers/router.py` (the fallback/cost-ceiling logic) and `capabilities.py` (the provider registry) are real and reasonably complete on their own — but nothing calls them yet. The Image Generation and Video Generation n8n workflows currently call external provider URLs directly, which means the backend's fallback/cost-ceiling logic is entirely bypassed for those two stages as things stand today.

---

## 6. Missing Backend Endpoints

Every endpoint the n8n workflow suite currently calls that does not exist in the FastAPI backend today, verified against the actual router files (Section 2):

1. `POST /api/agents/script` — called by Script Generation workflow
2. `POST /api/agents/storyboard` — called by Storyboard workflow
3. `POST /api/agents/video-merge` — called by Video Generation workflow (clip-stitching step)

Additionally, these don't exist and aren't yet called by any n8n workflow, but are implied by the gaps above:

4. `POST /api/agents/image` — Image Generation currently calls an external provider directly; no backend route brokers it
5. `POST /api/agents/video` (per-shot clip generation) — same situation as image generation
6. `POST /api/agents/thumbnail` — Thumbnail stage has no sub-workflow or backend route yet
7. `POST /api/agents/metadata` — Metadata Generation stage has no sub-workflow, backend route, or agent file yet
8. `POST /workflow-runs` — no endpoint exists to formally create/register a `WorkflowRun` row; the Main Orchestrator currently generates `workflow_run_id` locally in n8n as a timestamp-based string rather than from the backend

None of these should be built reactively just to unblock a workflow — each should be built alongside its corresponding agent, per the priority order in Section 8.

---

## 7. Current Blockers

Highest priority first:

1. **No database migrations exist.** `alembic/versions/` is empty. Nothing in this system can persist real data until the first migration is generated and applied — this blocks every other item on this list from being end-to-end testable, even with stub agents.
2. **Storyboard and Metadata agent scope is undefined.** There's no `storyboard.py` or `metadata.py` agent file at all (not even a stub), and it's unclear whether `prompt.py` is meant to serve as the Storyboard agent. This ambiguity blocks writing real implementations for two of the six missing backend endpoints.
3. **Zero provider adapters exist.** Every agent, once implemented, needs something to actually call. Without at least one working text-generation adapter (OpenRouter or Gemini), Script Agent cannot be completed even if its own logic is written.
4. **No YouTube OAuth2 credential configured.** Blocks the final pipeline stage entirely, independent of everything else being finished.
5. **Image/Video Generation bypass the backend's ProviderRouter.** Not a hard blocker to running today, but a decision needs to be made before more logic is built on top of the current (direct-call) pattern, or it becomes expensive to unwind later.
6. **No `POST /workflow-runs` endpoint.** Workflow runs aren't tracked as real database rows yet — `workflow_run_id` is a locally-generated string in n8n with nothing backing it in Postgres.

---

## 8. Recommended Build Order

Smallest/lowest-effort tasks first, only remaining work included.

1. Generate and apply the first Alembic migration against the existing SQLAlchemy models (no code changes required — the models already exist).
2. Create a Google Cloud project + YouTube Data API v3 OAuth2 credential and attach it in n8n (unblocks final stage independent of everything else).
3. Decide and document the scope split between `prompt.py`, a possible `storyboard.py`, and a possible `metadata.py` — this is a decision/design task, not code.
4. Implement one working provider adapter for `TEXT_GENERATION` (OpenRouter, since it's `cost_tier=1`) — a single HTTP client class under `app/providers/`.
5. Implement `POST /workflow-runs` to create a real `WorkflowRun` row and return a real `workflow_run_id`, replacing n8n's locally-generated placeholder.
6. Implement Script Agent using the OpenRouter adapter from step 4, plus `POST /api/agents/script`.
7. Implement the Storyboard agent (per the scope decided in step 3) plus `POST /api/agents/storyboard`.
8. Implement one working provider adapter for `IMAGE_GENERATION` (ComfyUI, since it's self-hosted/cheapest) and route Image Agent through the backend's `ProviderRouter` instead of n8n calling it directly.
9. Implement Image Agent plus `POST /api/agents/image`; update the Image Generation n8n workflow to call the new backend route instead of ComfyUI directly.
10. Implement one working provider adapter for `VIDEO_GENERATION` (FAL `ltx-video` or ComfyUI) and Video Agent, plus `POST /api/agents/video` and `POST /api/agents/video-merge`; update the Video Generation n8n workflow similarly.
11. Implement the Thumbnail agent plus `POST /api/agents/thumbnail`, and build the Thumbnail n8n sub-workflow.
12. Implement the Metadata agent plus `POST /api/agents/metadata`, and build the Metadata Generation n8n sub-workflow.
13. Build the Script Validation, Image Validation, and Video Validation n8n sub-workflows, wiring them to the (already-stub) validator classes — even rubber-stamp validators are enough to unblock the orchestrator's remaining `TODO_NOT_YET_BUILT` stages.
14. Resolve the Human Approval duplication flagged in the workflow review (orchestrator-level stage vs. the gate already built into YouTube Upload) — likely by removing or repurposing one of the two.
15. Replace hardcoded/rubber-stamp validator logic with real scoring, one validator at a time, starting with whichever is cheapest to get real signal from (likely `script_story_validator`, since it can reuse the text-generation adapter already built in step 4).
16. Add authentication (at minimum a shared-secret header) to the FastAPI backend before any of this is exposed beyond localhost — carried over from the earlier engineering review, still unresolved.

---

## 9. Milestones

**Milestone 1 — First working script generation**
Build order items 1, 4, 5, 6. Done when: a manually-triggered Main Orchestrator run produces a real, persisted `Script` row via a real OpenRouter call, with a real `workflow_run_id` tracked in Postgres.

**Milestone 2 — Storyboard generation**
Build order item 7 (plus the scope decision in item 3). Done when: a run produces a real `Storyboard` row with a genuine shot list, not a placeholder.

**Milestone 3 — Image generation**
Build order items 8–9. Done when: a run produces real `Image` rows with files actually written to storage, generated by a real ComfyUI (or equivalent) call routed through the backend's `ProviderRouter`.

**Milestone 4 — Video generation**
Build order item 10. Done when: a run produces real per-shot `GeneratedVideo` clips and one assembled `Video` row with a playable file.

**Milestone 5 — YouTube upload**
Build order items 2, 11–12 (thumbnail + metadata feed the upload stage). Done when: a run results in a real, unlisted/private YouTube video with a real thumbnail, title, and description — approved through the existing human-approval gate.

**Milestone 6 — First automated video**
All of the above, plus build order items 13–16. Done when: a single Main Orchestrator execution goes from a topic to a published (or approved-and-ready) YouTube video with no manually-run sub-workflows, no `TODO_NOT_YET_BUILT` stages remaining, and at least rubber-stamp validation at every gate.
