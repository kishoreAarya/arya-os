# ARYAOS STAGE 25 — PHASE 3.2.4.4.4.0
## CONTROLLED KLING VIDEO EXECUTION READINESS AUDIT
### READ-ONLY EVALUATION OF KLING VIDEO EXECUTION BOUNDARY & PRE-DISPATCH INVARIANTS

**AUTHORIZATION: STRICTLY READ-ONLY AUDIT.**  
**NO CODE CHANGES — NO DATABASE MIGRATIONS — NO GIT COMMITS — NO PROVIDER CALLS.**

---

## EXECUTIVE SUMMARY

Phase 3.2.4.4.3 successfully proved live external-provider execution across the AryaOS boundary (via a single-shot Flux image call costing $0.0300), and Phase 3.2.4.4.3.1 established independent security acceptance.

This audit performs a strict, read-only readiness evaluation for the next proposed external execution boundary:
**Phase 3.2.4.4.4 — Controlled Single-Shot Kling Video Sandbox**.

### Key Audit Findings
1. **AryaOS Architecture Readiness:** The AryaOS video abstraction, `LiveProviderDispatcher`, `VideoProviderRegistry`, `KlingVideoProvider`, durable idempotency engine (`DISPATCH_COMMITTED`), fail-closed gate evaluation, SSRF protection, and physical artifact validator (`ffprobe` stream analysis) are fully implemented, structurally hardened, and covered by 212 green unit and integration tests.
2. **First-Frame / Last-Frame Safety:** Conditioning invariants are strictly enforced across two independent layers (`media_bridge.py` and `video_provider.py`). Last-frame and first+last-frame conditioning are deterministically rejected *before* any provider call or subprocess spawn.
3. **CRITICAL EXECUTION BLOCKER IDENTIFIED (OpenMontage Internal Budget Limit):**
   Inspection of `OpenMontage/tools/video/kling_video.py` and `OpenMontage/data/fal_spend.json` reveals that after generating and downloading a Kling video, `kling_video.py` invokes `tools.fal_spend.record()`. The budget ledger in `OpenMontage/data/fal_spend.json` is set to `$20.00` and already contains `$20.00` of historical spend. Any new call will cause `record()` to raise an unhandled `RuntimeError: FAL budget exceeded: $20.10 > $20.00`.
   Crucially, this occurs **after** Fal has already accepted the generation and billed the user's account, causing the job to crash and report failure despite funds being spent.

### Final Readiness Verdict
**`PHASE 3.2.4.4.4.0 KLING READINESS: READY WITH BLOCKERS`**  
*(Execution must not proceed until the OpenMontage budget ledger blocker is remediated in Phase 3.2.4.4.4).*

---

## A. CURRENT KLING IMPLEMENTATION

The Kling video integration is implemented as a dual-system bridge between AryaOS and OpenMontage:

| Property | Implementation Detail | Source Location |
| :--- | :--- | :--- |
| **AryaOS Provider Class** | `KlingVideoProvider` (subclass of `VideoGenerationProvider`) | `backend/app/services/video_provider.py:86` |
| **Provider ID** | `"kling"` | `backend/app/services/video_provider.py:93` |
| **Default Model ID** | `"kling-video/v3/standard"` | `backend/app/services/video_provider.py:94` |
| **Registry Resolution** | `VideoProviderRegistry.resolve_provider_for_package()` | `backend/app/services/video_provider.py:349` |
| **OpenMontage Tool** | `KlingVideo` (`name = "kling_video"`, version `0.1.0`) | `OpenMontage/tools/video/kling_video.py:29` |
| **External API Backend** | Fal.ai hosted Kling queue API | `https://queue.fal.run/fal-ai/kling-video/{variant}/{operation_path}` |
| **Execution Protocol** | Protocol v1.1 via framed JSON over subprocess stdio | `backend/app/services/openmontage_adapter.py:49` |
| **Credentials** | Server-side `FAL_KEY` / `FAL_API_KEY` | Injected into subprocess environment only |

---

## B. PROVIDER CAPABILITY MATRIX

Capability determination based strictly on repository source inspection:

| Dimension | Supported? | Details / Constraints | Source Reference |
| :--- | :---: | :--- | :--- |
| **Text-to-Video** | **YES** | Supported via `operation="text_to_video"` | `kling_video.py:69` |
| **Image-to-Video (First Frame)** | **YES** | Supported via `operation="image_to_video"` with `image_url` | `kling_video.py:88` |
| **Last-Frame Conditioning** | **NO** | Strictly unsupported; rejected before dispatch | `video_provider.py:150`, `media_bridge.py:260` |
| **First + Last Frame Conditioning** | **NO** | Strictly unsupported; rejected before dispatch | `video_provider.py:150`, `media_bridge.py:260` |
| **Durations Supported** | **YES** | Discrete durations: `"5"` or `"10"` seconds (defaults to `"5"`) | `kling_video.py:77` |
| **Aspect Ratios Supported** | **YES** | `"16:9"`, `"9:16"`, `"1:1"` (defaults to `"16:9"`) | `kling_video.py:83` |
| **Model Variants** | **YES** | `"v3/standard"`, `"v2.1/master"`, `"v2.1/pro"`, `"v2.1/standard"` | `kling_video.py:72` |
| **Provider Request ID** | **YES** | Captured from queue submission (`queue_data.get("request_id")`) | `kling_video.py:163` |
| **Provider-Side Idempotency** | **NO** | Fal queue does not accept client idempotency keys | `idempotency.py:149` (`supports_idempotency_key=False`) |
| **Provider Status Lookup** | **NO** | Out-of-band lookup is unsupported (`consistency_guarantee=NO_LOOKUP`) | `idempotency.py:153` (`supports_status_lookup=False`) |
| **Cancellation** | **NO** | No out-of-band cancellation endpoint implemented | Verified via provider contract |
| **Timeout Handling** | **YES** | 300s subprocess timeout; maps to `UNKNOWN_PENDING_RECONCILIATION` | `openmontage_adapter.py:714` |

---

## C. GOVERNED EXECUTION PATH

The governed execution path strictly adheres to the Stage 25 architecture without backdoors or direct SDK imports:

```
[AryaOS Goal Orchestration]
             │
             ▼
[AutonomousExecutionRunner] (Enforces Lease, Fencing, Status Transitions)
             │
             ▼
[Pre-Dispatch Intent] (Persists DISPATCH_COMMITTED & Cryptographic Action Fingerprint to PostgreSQL)
             │
             ▼
[LiveProviderDispatcher] (Enforces fail-closed gate: ENABLE_LIVE_PROVIDER_EXECUTION=True)
             │
             ▼
[Job Package Synthesis (media_bridge)] (Validates schema, checks SSRF, rejects last-frame conditioning)
             │
             ▼
[VideoProviderRegistry] (Resolves KlingVideoProvider)
             │
             ▼
[KlingVideoProvider] (Validates configuration, checks last-frame conditioning, maps duration/aspect)
             │
             ▼
[OpenMontageAdapter] (Spawns isolated subprocess with cwd=OpenMontage, sanitized env, protocol v1.1)
             │
             ▼
[OpenMontage Tool: kling_video] (Calls https://queue.fal.run/fal-ai/..., downloads MP4 artifact)
             │
             ▼
[Protocol v1.1 Framing] (__ARYA_OPENMONTAGE_RESULT_START__ / __END__)
             │
             ▼
[Physical Artifact Validation] (Validates MP4 magic bytes, ffprobe streams, codec, resolution, duration)
             │
             ▼
[AryaOS Persistence] (Action marked SUCCEEDED with durable evidence, cost, and telemetry)
```

**Verification:** No direct Fal SDK or requests calls exist inside AryaOS backend code for Kling. All generation flows strictly through the `OpenMontageAdapter` subprocess boundary.

---

## D. CREDENTIAL / SECURITY AUDIT

1. **Source of Truth:** Provider credentials (`FAL_KEY` / `FAL_API_KEY`) are sourced strictly from server-side environment (`backend/.env`) via Pydantic `Settings`.
2. **No Client Overrides:** Client payloads, action inputs, and `inputs_json` cannot supply, override, or substitute credentials. Any client input attempting to inject keys is ignored or rejected by secret scanners.
3. **No Leakage in Logging or Telemetry:**
   - In Pydantic models, `fal_key` is marked with `repr=False`.
   - Logging formatters pass strings through `sanitize_text()` and `sanitize_payload()`, which regex-mask keys matching `(?:key-)?[a-f0-9]{8,}(?:-[a-f0-9]{4,}){3,}` and API key formats.
   - Credentials are never returned in HTTP responses, SSE streams, or database error traces.
4. **Subprocess Environment Isolation:**
   - In `backend/app/services/openmontage_adapter.py:578` (`build_subprocess_env`), `os.environ.copy()` is strictly forbidden.
   - An explicit allowlist (`SAFE_SYSTEM_ENV_ALLOWLIST`) passes only runtime necessities (`PATH`, `HOME`, `LANG`, etc.).
   - Only `FAL_KEY` / `FAL_API_KEY` is injected for `kling_video` (an external tool).
   - Core backend secrets (`DATABASE_URL`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `MASTER_API_KEY`, `JWT_SECRET`) are explicitly stripped via `FORBIDDEN_SECRET_KEYS`.
5. **Git Protection:** `.env` is ignored by Git; zero credentials appear in source code or commits.

---

## E. IDEMPOTENCY / DUPLICATE-CHARGE ANALYSIS

Because Kling is an external paid provider without native idempotency keys, duplicate-charge prevention is enforced entirely by AryaOS:

1. **Pre-Dispatch Durable Intent:**
   Before any subprocess or network request is initiated, `AutonomousExecutionRunner` writes a `DISPATCH_COMMITTED` intent to the database within a transaction.
2. **Action Identity & Cryptographic Fingerprinting:**
   Actions are fingerprinted via SHA-256 over canonicalized inputs (excluding volatile fields like lease tokens and timestamps). Redispatching an already executing action is rejected with `409 Conflict`.
3. **Fencing & Worker Leases:**
   Executions require an active worker lease. A stale worker attempting to commit results with an expired lease is rejected.
4. **No Hidden Automatic Retries:**
   The runner, dispatcher, and adapter contain **zero automatic retries** for external API tools. If an execution fails, it is marked `FAILED` or `UNKNOWN_PENDING_RECONCILIATION`.
5. **Subprocess Crash / Network Interruption:**
   If a network drop occurs after Fal accepts the queue request, AryaOS does NOT retry. The failure is classified as ambiguous (`is_ambiguous=True`) to prevent double-billing.

---

## F. UNKNOWN / RECONCILIATION ANALYSIS

When an external provider execution experiences an ambiguous failure (timeout, network disconnect, or process termination):

1. **Epistemic Truth:**
   In `openmontage_adapter.py:714`, any timeout or abnormal exit on `EXTERNAL_API_TOOLS` returns:
   `status="UNKNOWN_PENDING_RECONCILIATION"`, `phase="IN_FLIGHT"`, `is_ambiguous=True`.
2. **Provider Profile in Idempotency Engine:**
   In `idempotency.py:149-155`:
   ```python
   "kling": ProviderCapabilityProfile(
       provider_id="kling",
       supports_idempotency_key=False,
       supports_status_lookup=False,
       consistency_guarantee=ProviderConsistencyGuarantee.NO_LOOKUP,
       lookup_terminal_states=set(),
   )
   ```
3. **Reconciliation Behavior:**
   Because `supports_status_lookup=False` and `consistency_guarantee=NO_LOOKUP`:
   - `ReconciliationService` issues a verdict of `LOOKUP_UNSUPPORTED` with `can_safely_retry=False`.
   - The action transitions to `RECOVERY_REQUIRED`.
   - The system **never** invents synthetic polling and **never** assumes the job failed to safely retry.
   - Operator human intervention is strictly required to unblock the goal.

---

## G. ARTIFACT VALIDATION ANALYSIS

Video artifact validation is implemented in `backend/app/services/artifact_validator.py` (`validate_artifact_file` with `expected_type="video"`):

1. **Physical File Verification:**
   Validation is performed directly against the generated file on disk before the action can transition to `SUCCEEDED`.
2. **Security & Path Confinement:**
   - Verifies filename against safe alphanumeric regex (`^[a-zA-Z0-9_\-\.]+$`).
   - Resolves symlinks and ensures the file is strictly contained within `storage/artifacts`.
   - Traversal attempts (`../`) and absolute paths outside storage are rejected.
3. **Magic Byte / Header Checks:**
   - Checks for `b"ftyp"` magic bytes in the first 32 bytes of the file.
   - Explicitly rejects HTML/text masquerading as MP4 (`<!DOCTYPE`, `<html`, `{"error"`, etc.).
4. **Deep Stream Inspection via `ffprobe`:**
   - Local `ffprobe` is verified available at `/opt/homebrew/bin/ffprobe` (version 8.1.2).
   - Executes `ffprobe -v error -print_format json -show_format -show_streams` with a 15-second timeout.
   - Extracts: container format (`mp4`), duration, video stream codec (`h264`), resolution (`width` x `height`), and frame rate (`r_frame_rate`).
   - Rejects files with missing video streams or zero dimensions.
5. **Size Bounds:** Enforces `0 < file_size <= 500 MB`.

---

## H. OPENMONTAGE SUBPROCESS SECURITY

The subprocess execution boundary in `OpenMontageAdapter` adheres to strict security invariants:

1. **Explicit CWD:** Subprocess explicitly sets `cwd=str(self.openmontage_path)`. The AryaOS backend root can never become the subprocess working directory.
2. **No Shell Execution:** Executed via `asyncio.create_subprocess_exec()` with `shell=False`.
3. **Process Group Isolation:** Spawns with `start_new_session=True` (setsid), isolating the process tree from AryaOS.
4. **Bounded Stream Buffering:** Stdout and stderr are read via chunked readers capped at `2 MB` (`MAX_STREAM_BYTES`) to prevent memory exhaustion attacks.
5. **Process Tree Termination:** On timeout (300s), sends `SIGTERM` to the process group (`os.killpg`), allows a bounded grace period, and escalates to `SIGKILL` to prevent orphan worker processes.
6. **No Code Imports:** Zero OpenMontage modules are imported into the AryaOS Python process memory.

---

## I. FIRST-FRAME / LAST-FRAME CAPABILITY MATRIX

The audit conducted an explicit, line-by-line inspection of frame conditioning handling:

| Conditioning Mode | Implemented Status | Pre-Dispatch Behavior | Bypass Prevention |
| :--- | :---: | :--- | :--- |
| **First-Frame Only** (`image_to_video`) | **SUPPORTED** | Allowed. URL validated against SSRF blocklist. Passes `image_url` to Kling. | SSRF checked via `validate_reference_url` |
| **Last-Frame Only** | **UNSUPPORTED** | **Strictly Rejected.** Dual-layer rejection in `media_bridge.py` and `video_provider.py`. | Fails before subprocess spawn |
| **First + Last Frame** | **UNSUPPORTED** | **Strictly Rejected.** Rejection triggers whenever `last_frame` candidate exists. | Fails before subprocess spawn |

### Proof of Dual-Layer Rejection:
1. **Layer 1 (`backend/app/services/media_bridge.py:260`):**
   ```python
   last_frame_candidate = (
       inputs.get("last_frame") or inputs.get("lastFrame")
       or inputs.get("end_frame_url") or inputs.get("endFrameUrl")
       or inputs.get("last_frame_url")
   )
   if last_frame_candidate:
       raise UnsupportedCapabilityError(
           "Unsupported capability: Provider 'kling' does not support last-frame conditioning..."
       )
   ```
2. **Layer 2 (`backend/app/services/video_provider.py:150`):**
   ```python
   last_frame = getattr(pkg.references, "lastFrame", None) or pkg.references.endFrameUrl
   if last_frame:
       return OpenMontageToolResult(
           success=False, status="FAILED",
           error="Unsupported generation mode: Kling provider on fal.ai does not support last-frame conditioning..."
       )
   ```

Clients cannot bypass validation through `inputs_json`.

---

## J. PROPOSED CONTROLLED SINGLE-SHOT TEST SPECIFICATION (PHASE 3.2.4.4.4)

When Phase 3.2.4.4.4 is authorized and blockers are resolved, the controlled single-shot execution must adhere to this exact specification:

1. **Target Capability:** `VIDEO_GENERATION`
2. **Provider & Model:** `provider="kling"`, `model="kling-video/v3/standard"`
3. **Operation Mode:** `text_to_video` (deterministic baseline, avoids external image dependencies)
4. **Prompt:** `"Cinematic slow orbital sweep of an ancient brass astrolabe mechanism, photorealistic, 4k"`
5. **Duration:** Strictly **5 seconds** (minimum supported increment)
6. **Aspect Ratio:** `16:9`
7. **Concurrency:** Strictly **1 single call**; zero parallel requests
8. **Retries / Fallbacks:** Zero automatic retries; zero fallback providers
9. **Execution Gate:** Temporarily activate `ENABLE_LIVE_PROVIDER_EXECUTION=True` in-process for this single action only.
10. **Evidence Capture Requirements:**
    - Fal Request ID (e.g., UUID from queue API)
    - OpenMontage protocol v1.1 framed JSON result
    - Physical MP4 artifact saved in `backend/storage/artifacts/`
    - Full `ffprobe` telemetry (duration ~5.0s, codec `h264`, container `mp4`, dimensions, fps)
    - SHA-256 hash and byte size of artifact
    - PostgreSQL durable action status `SUCCEEDED`

---

## K. COST / BUDGET PROPOSAL

1. **Kling Pricing Structure:**
   - Fal Kling v3 Standard: `$0.10` per 5 seconds of generated video (`0.10 * (duration / 5)`).
   - Minimum single-shot cost: **$0.1000 USD**.
2. **Hard Spend Ceiling:**
   - Propose an authorization ceiling of **$0.1500 USD** for Phase 3.2.4.4.4.
   - Any cost calculation exceeding $0.15 must fail closed prior to dispatch.
3. **Spend Safety Invariants:**
   - Exactly 1 provider request.
   - Zero synthetic polling or re-dispatch.
   - Provider-reported and estimated cost captured in durable database records.

---

## L. REGRESSION / INTEGRITY RESULTS

| Invariant Item | Baseline Requirement | Observed Value | Verification Status |
| :--- | :--- | :--- | :---: |
| **Alembic Migration Head** | `i9d0e1f2a3b4` | `i9d0e1f2a3b4 (head)` | **CONFIRMED** |
| **New Migrations Created** | Exactly 0 | 0 new migrations | **CONFIRMED** |
| **Stage 03 Blender SHA-256** | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | **CONFIRMED** |
| **Stage 03 GLB Assets** | Exactly 28 intact | 14 blender + 14 dist GLBs intact | **CONFIRMED** |
| **Git Working Tree Commits** | Exactly 0 new commits | HEAD remains `ba6ca58` | **CONFIRMED** |
| **Frontend Code Modified** | Exactly 0 modifications | Untouched | **CONFIRMED** |
| **Stages 03–24 Code** | Untouched | Untouched | **CONFIRMED** |
| **Test Suite Baseline** | 100% green | **212 passed, 0 failed** across all 15 suites in 12.97s | **CONFIRMED** |

---

## M. FINDINGS BY SEVERITY

### 1. BLOCKER (HIGH): OpenMontage Budget Ledger Exhaustion (`fal_spend.json`)
- **Location:** `OpenMontage/tools/video/kling_video.py:214` and `OpenMontage/data/fal_spend.json`
- **Description:**
  `kling_video.py` calls `tools.fal_spend.record()` upon completing video generation and download.
  In `OpenMontage/data/fal_spend.json`:
  ```json
  {
    "budget": 20.0,
    "generations": [
      {
        "timestamp": "2026-08-20T00:00:00Z",
        "model": "historical",
        "operation": "historical_spend",
        "project": "initialization",
        "asset": "historical_usage",
        "cost": 20.0
      }
    ]
  }
  ```
  The budget is `$20.00`, and `used` is already `$20.00`.
  In `OpenMontage/tools/fal_spend.py:40-43`:
  ```python
  if used + cost > float(data["budget"]):
      raise RuntimeError(
          f"FAL budget exceeded: ${used + cost:.2f} > ${float(data['budget']):.2f}"
      )
  ```
- **Consequence:** Calling Kling ($0.10) will trigger `RuntimeError: FAL budget exceeded: $20.10 > $20.00`. Because this occurs **after** Fal has already processed the request and charged the account, the subprocess will crash, the MP4 will not be emitted via protocol v1.1, and AryaOS will mark the action `FAILED` after real money has been spent.
- **Required Remediation (in Phase 3.2.4.4.4):** The budget ledger in `OpenMontage/data/fal_spend.json` must be increased or reset before triggering live execution.

### 2. OBSERVATION (LOW): OpenMontage Adapter `get_tool_status()` Normalization
- **Location:** `backend/app/services/openmontage_adapter.py:528`
- **Description:** OpenMontage tools return `ToolStatus.AVAILABLE` (value `"available"`). The adapter checks `res.status in ("available", "AVAILABLE")`, but protocol v1.1 status normalization converts lowercase statuses. This does not affect live tool generation (`execute_tool`), which evaluates tool output rather than status probes.

### 3. OBSERVATION (LOW): Known Image Container Observation
- **Description:** Phase 3.2.4.4.3 noted JPEG bytes within a `.png` filename from Fal. For video, `validate_artifact_file` strictly validates the MP4 container via `ffprobe` stream metadata, eliminating format confusion risks for video files.

---

## N. FINAL VERDICT

All AryaOS core governance, provider abstraction, gate enforcement, credential isolation, and artifact validation mechanisms are verified and ready for video execution.

However, due to the exhausted `$20.00` budget ledger in OpenMontage's `fal_spend.json`, a live call will immediately fail post-payment.

Therefore, the formal audit verdict is:

### **`PHASE 3.2.4.4.4.0 KLING READINESS: READY WITH BLOCKERS`**

---

## ABSOLUTE STOP

This audit is strictly read-only.
- No code was modified.
- No migrations were created.
- No git commits were generated.
- No Fal or Kling API calls were made.
- Zero dollars spent.

Awaiting operator instruction to proceed to Phase 3.2.4.4.4 blocker remediation and subsequent controlled single-shot execution.
