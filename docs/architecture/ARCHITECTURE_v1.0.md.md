# Arya OS — Build Instructions (Start → First Published Video)

**Give this whole document to whoever/whatever is helping you next (ChatGPT or otherwise).** It contains everything about what this project is, what's already built and verified, and exactly what's left to do, in order, until a real video is published on your YouTube channel. You don't need to explain anything yourself — this file is the explanation.

---

## 1. What this project is

**Arya OS** — a self-hosted, open-source, AI-driven YouTube video pipeline. Not a simple "script → post" bot. It's a real production system with:
- A database of record (every script, image, video, decision — versioned, never silently overwritten)
- A state machine that tracks exactly where each video is in the pipeline (so a crash doesn't lose progress)
- Human approval checkpoints before anything publishes
- A cost-aware, swappable AI provider system (start cheap with fal.ai, move to RunPod or your own GPU later — without rewriting anything)
- n8n as the orchestrator that sequences everything; a FastAPI backend that does the actual thinking, tracking, and validating

**Everything must stay open-source-first.** Model choices already locked in: DeepSeek/Qwen/Llama for text, SDXL/Flux for images, ComfyUI/AnimateDiff for video — all open-weight, runnable on your own GPU eventually.

---

## 2. Non-negotiable rules for whoever builds the rest

These are hard-won and must not be violated, no matter how small a change seems:

1. **Never touch `app/models/`** unless a new field genuinely doesn't exist anywhere — check the model file first, most fields you'll need already exist.
2. **Every agent inherits `BaseAgent`** (`app/agents/base.py`) and implements `async def run(self, context: dict) -> AgentResult`. Agents contain ONLY business logic (what prompt to build, how to interpret the result) — they never call a provider directly and never implement their own retry loop. Every agent executes through the **Execution Engine** (see section 4, Step 1), which is the only thing allowed to call `app/providers/router.py`'s `call_with_fallback()`.
3. **Every provider gets one adapter file** under `app/providers/<name>.py` — a single function like `generate_text()`/`generate_image()` that takes raw inputs and returns `(result, cost_usd)`. It knows nothing about agents, workflows, or the database. See `app/providers/openrouter.py` as the reference example.
4. **Secrets only ever come from `SecretsManager`** (`app/core/secrets.py`) — never `os.environ` directly, never hardcoded.
5. **Every new agent capability needs a matching FastAPI route** under `app/api/routers/agents.py`, following the exact pattern already there for `/api/agents/script`: look up the WorkflowRun, run the agent, save a real DB row, bump `total_cost_usd`, return a structured response (never a raw 500 error — always a JSON body, using an `error` field on failure, because n8n depends on this).
6. **Every route's request/response shape must be written to match what the n8n workflow already sends** — the n8n JSON files (in `Arya OS/n8n/workflows/`) were built first and are the source of truth for field names. Check the relevant workflow's `HTTP Request`/`Receive Input`/`Return Output` nodes before writing a schema.
7. **Write real tests for every change** — unit tests (mocked provider, no real API key needed) AND integration tests (real Postgres, real HTTP round-trip through the FastAPI app, only the outbound provider call mocked). Every prior step in this project was verified this way — don't skip it. Run `pytest backend/tests/` and confirm passing before considering anything "done."
8. **Don't touch `pipeline_state.py`, `workflow_service.py`'s stage-transition logic, or `PipelineStage`** unless you fully understand the state-machine fix already applied (search this repo for "Issue 1" and "Issue 2" in code comments if you need the history — it's all documented inline).
9. **Format and lint before calling anything finished**: `black backend/` then `ruff check backend/`.

---

## 3. Current verified state (as of this handoff)

Confirmed working with **55 passing tests** against a real Postgres database:

| Piece | Status |
|---|---|
| Docker/Postgres/Redis/FastAPI scaffold | ✅ Working |
| Database schema + first migration | ✅ Applied, tested upgrade/downgrade |
| Workflow Run tracking (`POST/GET/PATCH /workflow-runs`) | ✅ Working, with a correct state machine |
| Provider Router (cost-aware fallback logic) | ✅ Working, framework only — most providers still need adapters |
| **OpenRouter text-generation adapter** | ✅ Working (needs your real `OPENROUTER_API_KEY` in `.env` to actually generate text — untested against the real API, only against a simulated response) |
| **Script Agent** (`POST /api/agents/script`) | ✅ Working — the FIRST real AI capability in this project |
| n8n workflows (Research, Script Gen, Storyboard, Image Gen, Video Gen, YouTube Upload, Main Orchestrator) | ✅ Built as importable JSON, but most still call placeholder/nonexistent backend endpoints — only Script Generation's endpoint is real now |
| CI/CD (GitHub Actions: lint, test, security, docker) | ✅ Working |
| Trend/Research Agent | ❌ Not built (stub only) |
| Storyboard Agent + Validator | ❌ Not built |
| Voice Agent + Validator | ❌ Not built |
| Image Agent | ❌ Not built (stub only) |
| Video Agent | ❌ Not built (stub only) |
| Music/SFX Agent | ❌ Not built (stub only) |
| Thumbnail Agent | ❌ Not built (stub only) |
| Title/Description/SEO/Policy checks | ❌ Not built |
| YouTube Upload (real OAuth2 credential) | ❌ n8n workflow exists but has no real Google/YouTube credential attached yet |
| Execution Engine (shared provider/retry/cost/logging infrastructure) | ❌ Not built — now Step 1, built before any new agent |
| Decision Engine (retry / switch provider / rewrite prompt / escalate policy) | ❌ Not built — now Step 2, shared infrastructure consulted after a validation failure, not a pipeline stage |
| Final QC Validation, Upload Verification | ❌ Not built — these are in your architecture chart but have no code yet |
| Post-publish analytics, competitor tracking, self-improvement loop | ❌ Not built at all |

---

## 4. Build order — do these one at a time, in this order

Each step below follows the same shape: **provider adapter (if needed) → agent (business logic only) → route → n8n endpoint wiring → tests → done.** Steps 1 and 2 are shared infrastructure, not pipeline stages — every agent from Step 3 onward is built to use them, not to duplicate their logic. Use the Script Agent (`app/agents/script.py`, `app/api/routers/agents.py`) as your reference for what a single agent's business logic should look like — but note it predates the Execution/Decision Engine split below, so don't copy its retry/provider-call plumbing verbatim.

### Step 1 — Execution Engine (shared infrastructure, not a pipeline stage)
Every future agent executes through this instead of each reimplementing its own provider call, retry loop, cost tracking, logging, and error handling. Build this **first** — before Storyboard, Voice, Image, or Video — because those five agents would otherwise each duplicate the same boilerplate Script Agent already had to write once.

**Execution Engine responsibilities:**
- Provider routing (calls `app/providers/router.py`'s `call_with_fallback()`)
- Provider execution (actually invoking the chosen adapter)
- Validation (calls the matching `BaseValidator` on the raw output)
- Cost tracking (accumulates `cost_usd` across attempts, checks the running total against `Settings.max_cost_per_video_usd`)
- Logging (structured events, same as `call_with_fallback()` already does today)
- Metrics (duration, attempt count, provider used)
- Retry loop (repeats provider/validation on failure, up to `Settings.max_retry_attempts`)
- Decision Engine integration (on a validation failure, asks Decision Engine what to do next — see Step 2 — instead of deciding itself)
- Persistence (writes the `GenerationAttempt` row and updates `VersionedAssetMixin.quality_score` on the artifact)

Agents should contain **only** business logic — building a prompt, shaping the output into the right DB fields. Everything in the list above belongs to the Execution Engine, not the agent.

**How to build it:** refactor Script Agent's existing retry/provider-call code out into `app/services/execution_engine.py`, rewrite Script Agent to call it, confirm all existing tests still pass, then build Storyboard Agent against it from scratch as the first clean example.

### Step 2 — Decision Engine (shared infrastructure, not a pipeline stage)
**This is not a pipeline stage that sits "between" two agents** — it's a shared service the Execution Engine consults, the same way every future validation gate (Storyboard, Voice, Image, Video, Thumbnail) will consult it identically.

- **Validators never decide retries.** A validator's `ValidationResult` (`app/validators/base.py` — this already exists, don't rebuild it) only reports `passed`, `score`, `issues`, `notes`. It has no opinion on what happens next.
- **Decision Engine decides what happens next**, once a `ValidationResult` comes back failed: Retry / Switch Provider / Rewrite Prompt / Human Approval / Escalate / Continue.
- It only runs *after* a Provider Router call and a Validator call have both already happened — it has nothing to decide about before that.
- `Settings.max_retry_attempts` already exists as a config value for exactly this — it just isn't enforced by any code yet. This is where it gets enforced.

### Step 3 — Research/Trend Agent
- **Input:** a topic string (or nothing — it can also discover topics itself)
- **What it does:** pulls trending topics/data through a small, extensible interface rather than one hardcoded source:

  ```python
  class TrendSource(ABC):
      async def fetch(self, topic_hint: str | None) -> list[RawTrendItem]: ...
  ```

  First implementation: **Google Trends** (via the `pytrends` library — no LLM needed for a first version). Future implementations plug in without touching the Research Agent itself: **Reddit, YouTube, RSS, News APIs**. Keep this lightweight — a plain dict registry of sources (same pattern as `AGENT_REGISTRY`), not a heavier "aggregator" framework, until you actually have two or more sources to justify one.
- **Output:** `research_data` — a list of `{title, summary, source, score}` dicts. This exact shape already matches what the Script Agent expects to receive.
- **Route:** `POST /api/agents/research` (new)
- **n8n:** `Arya OS - Research` workflow already exists and expects this contract — just point its HTTP node at the real backend host.
- **Done when:** a real research call returns real trend data, feeds correctly into a real Script Agent call, and both have passing tests.

### Step 4 — Storyboard Agent + Storyboard Validator
**This is the first agent built entirely on the new pattern** — the first real proof that Execution Engine + Decision Engine work end to end, not just in theory.
- **Input:** a `Script` (content + id)
- **What it does:** breaks the script into a shot list — `[{shot: 1, description: "...", shot_type: "close-up"}]`. This is an LLM call (use the same OpenRouter adapter, different prompt) — but the agent itself should only build the prompt and shape the result; the Execution Engine handles the actual call, retries, and cost tracking.
- **Output:** a `Storyboard` DB row (`shots` JSONB field already exists on the model)
- **Validator:** a cheap, fast check — does every shot have a non-empty description? Is the shot count reasonable? This should run before any image gets generated (image generation costs real money; storyboard validation should not). Returns a `ValidationResult` only — it does not decide what happens on failure (see Step 2).
- **Route:** `POST /api/agents/storyboard`
- **n8n:** `Arya OS - Storyboard` workflow already exists.

### Step 5 — Voice Agent + Voice Validator
- **Input:** script content
- **What it does:** text-to-speech. You'll need a TTS provider adapter — check what's cheap/open-source-friendly today (options include ElevenLabs' API for now, or an open-source TTS model on RunPod/local GPU later — matches your "start with fal.ai, move to RunPod" plan).
- **Output:** an audio file (stored via the existing storage layer, `app/storage/`), with its duration recorded — **this duration is important, it should be passed to the Video Agent next** so video length matches voice length (this is the fix you already made to your chart's stage order).
- **Route:** `POST /api/agents/voice`

### Step 6 — Image Agent
- **Input:** one shot from the storyboard
- **What it does:** calls fal.ai (per your stated plan) to generate an image per shot.
- **Provider adapter:** `app/providers/fal.py` — same shape as `openrouter.py`, different API.
- **Route:** `POST /api/agents/image` — **important:** this should be called from the backend, not directly from n8n like the current placeholder n8n workflow does. Update the Image Generation n8n workflow's HTTP node once this route exists, so cost tracking and fallback routing actually apply to image generation too.
- **Validator:** Image Validator — quality/consistency check, can start as a simple "did we get a real image back, non-corrupt, right dimensions" check before adding anything smarter.

### Step 7 — Video Agent
- Same pattern as Image Agent, using fal.ai's video model or image-to-video. Target duration comes from the Voice Agent's output (Step 5).

### Step 8 — Final QC Validation (new — from your updated chart)
- After video + voice + music are combined: audio sync check, corruption check, loudness check. This is a gate your chart added that has zero code yet.

### Step 9 — Thumbnail Agent + Title/Description/SEO/Policy checks
- Thumbnail: image generation again (reuse the Image Agent's provider adapter with a different prompt).
- Title/Description: another LLM call (reuse the OpenRouter adapter).
- Policy check: a rules-based check against YouTube's policies before anything uploads — start simple (banned word list, required disclosures), you don't need an AI model for this.

### Step 10 — YouTube Upload (real credentials)
- The n8n workflow (`Arya OS - YouTube Upload`) already has the correct logic — a human-approval polling loop, then a real YouTube upload node. **It just has no real credential.**
- **What you need to do (not code — an account setup task):** create a Google Cloud project, enable the YouTube Data API v3, create an OAuth2 credential, and attach it inside n8n's credential manager. Full guide: search "n8n YouTube OAuth2 credential setup."
- **Upload Verification** (new from your chart): after upload, poll YouTube's API to confirm the video actually processed successfully before marking the run complete.

### Step 11 — First real automated video
Once Steps 1–10 are done and every stage has passed real tests, run the full Main Orchestrator n8n workflow end to end, with a real topic, against your real accounts. Watch it go through every gate. When it reaches "Published," **that's your first video.**

### Step 12 (after your first video) — Analytics + Self-Improvement Loop
Not needed for video #1. Build this after you've seen the pipeline work at least once — it needs real published-video data to learn from anyway.

---

## 5. Workflow Execution Context (not a new database table)

While Steps 1–2 are being built, it's tempting to add a persisted "memory" table storing every run's retry count, provider used, execution time, accumulated cost, and validator scores in one place. **Don't** — that data already has a home, and a second copy of it will drift out of sync with the original:

- Retry count, provider used, duration, cost → already on `GenerationAttempt`, one row per attempt.
- Accumulated cost for the whole run → already on `WorkflowRun.total_cost_usd`.
- Validator score per artifact → already on `VersionedAssetMixin.quality_score`.
- "What happened to this run, in order" → already answerable via `/lineage/{workflow_run_id}`.

What's actually missing — and worth building inside the Execution Engine (Step 1), not as a new table — is a small **in-memory Execution Context**, scoped to a single execution attempt, so a retry loop doesn't need to re-query the database between tries to know what it already attempted:

```python
@dataclass
class ExecutionContext:
    workflow_run_id: uuid.UUID
    stage: str
    provider: str | None
    model: str | None
    attempt_number: int
    elapsed_time: float
    accumulated_cost: float
    validation_result: ValidationResult | None
```

This object lives and dies with one call to the Execution Engine — it is never written to the database directly. Once an attempt finishes, the Execution Engine persists the relevant pieces of it into `GenerationAttempt` (Step 1's "Persistence" responsibility) and the context itself is discarded. Long-term memory of what happened continues to live entirely in `WorkflowRun`, `GenerationAttempt`, `VersionedAsset`-based tables, and the lineage view — this object is scratch space, not storage.

---

## 6. Environment setup checklist (do this before Step 1)

- [ ] Copy `.env.example` to `.env`
- [ ] Fill in `OPENROUTER_API_KEY` (already wired, just needs the key)
- [ ] Decide and fill in a `FAL_API_KEY` for Steps 6–7
- [ ] Decide a TTS provider and add its key for Step 5
- [ ] Run `docker compose up` and confirm `/health`, `/ready` both return healthy
- [ ] Run `alembic upgrade head` to make sure the database schema is applied
- [ ] Run `pytest backend/tests/` — should show all existing tests passing before you add anything new

---

## 7. What "done" looks like, overall

**The end goal is one full run of the Main Orchestrator, unattended except for the human-approval step, that ends with a real video live (or approved-and-ready) on your YouTube channel — going through every validation gate in your architecture chart, with every stage's cost and decision recorded in the database.** That's the finish line for this build.
