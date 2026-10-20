# ARYAOS STAGE 25 — PHASE 3.2.4.4.4.1
## OPENMONTAGE BUDGET LEDGER REMEDIATION DESIGN AUDIT
### ARCHITECTURAL REMEDIATION DESIGN TO PREVENT POST-CHARGE ACCOUNTING CORRUPTION OF EXECUTION TRUTH

**AUTHORIZATION: STRICTLY READ-ONLY AUDIT.**  
**NO CODE CHANGES — NO DATABASE MIGRATIONS — NO GIT COMMITS — NO PROVIDER CALLS.**

---

## EXECUTIVE SUMMARY

In Phase 3.2.4.4.4.0, the Kling Video Readiness Audit identified a critical execution blocker:
The OpenMontage local FAL budget ledger (`OpenMontage/data/fal_spend.json`) has a `$20.00` ceiling and is already exhausted with `$20.00` of historical spend. In `OpenMontage/tools/video/kling_video.py`, `tools.fal_spend.record()` is invoked **after** external video generation and download have completed. Under current conditions, `record()` raises an unhandled `RuntimeError: FAL budget exceeded: $20.10 > $20.00`, crashing the runner subprocess.

This causes AryaOS to classify a real, billed, downloaded, and physically valid media generation as `FAILED` (or `UNKNOWN`), falsely reporting failure after real money has been charged.

This audit presents the **Architectural Remediation Design** to resolve this blocker. The design decouples pre-dispatch budget authorization from post-dispatch spend recording, enforces execution truth across both systems, and guarantees that local bookkeeping anomalies can never corrupt confirmed external provider outcomes.

### Audit Verdict
**`REMEDIATION DESIGN READY`**

---

## 1. EXACT CURRENT FAILURE PATH

Tracing the end-to-end execution flow of a Kling generation request under the current code:

```
1. AryaOS AutonomousExecutionRunner.run_action_node()
   ├── Validates action state (QUEUED / SCHEDULED)
   ├── Acquires worker lease & fencing token
   ├── Persists pre-dispatch durable intent: DISPATCH_COMMITTED to PostgreSQL
   └── Transitions action to EXECUTING
2. LiveProviderDispatcher.dispatch(action)
   ├── Verifies fail-closed gate: is_live_provider_execution_enabled()
   ├── media_bridge.synthesize_job_package() (validates schema, SSRF, rejects last-frame)
   ├── VideoProviderRegistry resolves KlingVideoProvider
   └── Calls KlingVideoProvider.generate_video(pkg, output_path)
3. KlingVideoProvider.generate_video()
   ├── Validates credentials (FAL_KEY present)
   ├── Verifies OpenMontage directory availability
   └── Calls OpenMontageAdapter.execute_tool("kling_video", inputs, timeout=300s)
4. OpenMontageAdapter._run_subprocess()
   ├── Builds isolated environment (SAFE_SYSTEM_ENV_ALLOWLIST + FAL_KEY, strips DB secrets)
   ├── Spawns subprocess with cwd=OpenMontage, protocol v1.1 RUNNER_SCRIPT
   └── Passes JSON payload over stdin
5. OpenMontage Subprocess Execution (kling_video.py)
   ├── Loads KlingVideo tool
   ├── Dispatches HTTP POST to https://queue.fal.run/fal-ai/kling-video/v3/standard/text-to-video
   ├── ⚡ EXTERNAL BOUNDARY CROSSED: Fal accepts job, returns request_id, DEBITS USER ACCOUNT ($0.10)
   ├── Polling loop: waits for queue status COMPLETED
   ├── HTTP GET to data["video"]["url"]: downloads 5-second MP4 video bytes
   ├── Writes bytes to output_path on disk
   ├── Runs probe_output() (ffprobe stream analysis)
   └── ❌ FAILURE POINT: kling_video.py line 214 executes record(...)
       ├── tools/fal_spend.py loads data/fal_spend.json
       ├── Computes used = $20.00; evaluated used + 0.10 ($20.10) > budget ($20.00)
       ├── Raises RuntimeError("FAL budget exceeded: $20.10 > $20.00")
       └── 💥 CRASH: line 214 is OUTSIDE the inner try/except block (lines 151-193)
           Subprocess crashes with unhandled exception, exit code 1
           No protocol v1.1 JSON frame (__ARYA_OPENMONTAGE_RESULT_START__) is emitted
6. Back in AryaOS OpenMontageAdapter
   ├── Subprocess exited with code 1; no framed payload captured
   └── Returns OpenMontageToolResult(success=False, status="FAILED" / "UNKNOWN_PENDING_RECONCILIATION")
7. AutonomousExecutionRunner & Database State
   ├── Persists action status as FAILED in PostgreSQL
   └── ⚠️ CATASTROPHIC DIVERGENCE:
       - Real Fal account was debited $0.10
       - Valid MP4 artifact exists on disk
       - AryaOS records FAILED and marks goal blocked
       - Automatic or manual retry risks DOUBLE CHARGING the user.
```

---

## 2. FAILURE SEMANTICS ANALYSIS

| Component Stage | Actual Outcome | System Interpretation Under Current Code |
| :--- | :--- | :--- |
| **Provider Network Call** | **SUCCESS** | Provider accepted request, assigned queue ID, billed account. |
| **Provider Video Generation** | **SUCCESS** | GPU rendered 5-second cinematic clip. |
| **Artifact Download** | **SUCCESS** | MP4 bytes downloaded and written to storage disk. |
| **Artifact QC Probe** | **SUCCESS** | `ffprobe` verified non-empty playable MP4 container. |
| **Local Spend Recording** | **FAILED** | `record()` raised unhandled `RuntimeError` due to local ledger ceiling. |
| **AryaOS Observed State** | **FAILED / UNKNOWN** | Action marked `FAILED` with stderr exception trace. |

### Severity Assessment:
- The current implementation commits the classic **post-facto authorization error**: evaluating a spend ceiling *after* the spend has already permanently occurred.
- This produces a severe epistemic contradiction: the external physical reality (debited funds, generated MP4) is directly inverted by local software crash into a false failure.

---

## 3. REQUIRED ARCHITECTURAL INVARIANT

The proposed remediation establishes this formal security and execution invariant:

> **ARCHITECTURAL INVARIANT (EXECUTION TRUTH & ACCOUNTING ISOLATION):**  
> *"Once external provider execution has been durably evidenced (via provider request ID or validated physical artifact), a local post-charge accounting failure MUST NOT convert confirmed external execution into a false provider FAILED outcome. All budget checks MUST occur pre-dispatch; all post-dispatch accounting failures MUST be treated as non-fatal secondary warnings."*

### Two-Phase Invariant Decomposition:
1. **Pre-Dispatch Invariant (Zero-Spend Gate):**  
   Budget availability must be verified *prior* to crossing any external provider execution boundary. If authorized budget is exceeded, execution fails closed before dispatch. External spend must remain strictly **$0.00**.
2. **Post-Dispatch Invariant (External Truth Dominance):**  
   Once the provider has accepted the request and produced an artifact, local bookkeeping (e.g., updating a local JSON file) is an internal secondary effect. An IO error, lock contention, or ledger check failure during local recording must be captured as a diagnostic warning (`accounting_warning`), leaving the action's execution status strictly **`SUCCEEDED`**.

---

## 4. BUDGET AUTHORITY ANALYSIS

Boundary ownership across AryaOS and OpenMontage:

| Authority Scope | Sovereign Owner | Rationale |
| :--- | :--- | :--- |
| **Pre-Dispatch Budget Authorization** | **AryaOS** (Stage 20 Policy / Stage 21 Governance / Stage 25 Bridge) | AryaOS decides WHAT, WHY, and MAXIMUM BUDGET. Governs user permissions, project budgets, and approvals. |
| **Local Tool Spend Guard** | **OpenMontage** (`fal_spend.py` pre-flight check) | Serves as a local runtime safety clamp preventing runaway scripts inside OpenMontage. |
| **Provider-Reported Actual Spend** | **Provider API** (Fal/Kling telemetry) | The authoritative financial debit reported by the vendor. |
| **Authoritative Financial Ledger** | **AryaOS PostgreSQL** (`AutonomousActionNode.cost_usd`) | Stage 09 / Stage 22 persistent truth. Immutable, audited, queryable across the enterprise. |
| **Secondary Local File Ledger** | **OpenMontage** (`OpenMontage/data/fal_spend.json`) | Local cache/tracker for OpenMontage CLI tooling. Non-authoritative for enterprise governance. |
| **Accounting Failure Handling** | **OpenMontage Tool Boundary & AryaOS Dispatcher** | Logged to telemetry/audit; isolated from execution lifecycle state. |

---

## 5. PRE-DISPATCH VS. POST-DISPATCH SEQUENCING DESIGN

```
┌────────────────────────────────────────────────────────────────────────┐
│ PRE-DISPATCH PHASE (Zero External Spend)                              │
├────────────────────────────────────────────────────────────────────────┤
│ 1. AryaOS validates action, parameters, aspect ratio, duration.        │
│ 2. AryaOS verifies project budget ceiling (Stage 20 / Stage 25).       │
│ 3. OpenMontage KlingVideo.execute() performs PRE-FLIGHT budget check:  │
│    check_budget(cost) -> if exceeded:                                  │
│    RETURN ToolResult(success=False, error="Budget exceeded", ...)      │
│    [ABORT BEFORE DISPATCH — ZERO NETWORK CALLS — ZERO DOLLARS SPENT]   │
│ 4. AryaOS persists DISPATCH_COMMITTED pre-dispatch intent to database. │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ EXTERNAL DISPATCH PHASE (Single-Shot Boundary)                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Submit request to Fal queue API (requests.post).                    │
│ 2. Immediately capture authentic Provider Request ID.                  │
│ 3. Poll queue until completion.                                        │
│ 4. Download video artifact from provider CDN.                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ POST-DISPATCH PHASE (Execution Truth Dominance)                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Validate physical artifact (size bounds, magic bytes, ffprobe).     │
│ 2. Record spend in local ledger inside SAFE EXCEPTION BLOCK:           │
│    try:                                                                │
│        record_spend(...)                                               │
│    except Exception as ledger_err:                                     │
│        logger.warning("Local spend ledger update failed", ...)         │
│        data["accounting_warning"] = str(ledger_err)                    │
│ 3. Emit Protocol v1.1 ToolResult: success=True, status="COMPLETED".    │
│ 4. AryaOS validates physical artifact on disk via validate_artifact.   │
│ 5. AryaOS persists action as SUCCEEDED with durable cost_usd in DB.    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 6. LEDGER FAILURE SEMANTICS MATRIX

Explicit behavior specification for all six execution permutations:

| Scenario | Provider State | Artifact State | Ledger State | AryaOS Action Status | Safe to Retry? | Explanatory Truth |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| **A. Pre-dispatch budget failure** | Not called ($0) | None | Unchanged | `FAILED` / `REJECTED` | **YES** | Zero provider spend. Fails closed before API call. Safe to retry after budget allocation. |
| **B. Normal happy path** | Succeeded ($0.10) | Valid MP4 | Updated ($20.10) | `SUCCEEDED` | **NO** | Normal successful execution. Artifact linked, cost recorded. |
| **C. Post-dispatch ledger record fails** | Succeeded ($0.10) | Valid MP4 | Failed (write error) | `SUCCEEDED` | **NO** | External execution confirmed. Artifact valid. Ledger error logged as non-fatal warning. |
| **D. Ambiguous provider outcome + ledger error** | In-flight / Timeout | None | Failed / Skipped | `UNKNOWN_PENDING_RECONCILIATION` | **NO** | Epistemic status UNKNOWN. Leases fenced. Reconciler requires human intervention. |
| **E. Provider succeeds, download fails** | Billed ($0.10) | Missing / Corrupt | Recorded / Warned | `FAILED` (with Request ID) | **NO** (Manual recovery) | External money spent, artifact lost. Request ID preserved for CDN re-fetch without regeneration. |
| **F. Provider succeeds, artifact valid, ledger IO error** | Succeeded ($0.10) | Valid MP4 | Disk full / Perm error | `SUCCEEDED` | **NO** | Physical truth prevails. Primary financial truth recorded in PostgreSQL `cost_usd`. |

---

## 7. DUPLICATE CHARGE SAFETY VERIFICATION

The proposed remediation guarantees zero duplicate charges:
1. **No Automatic Retry:** Neither `OpenMontageAdapter` nor `AutonomousExecutionRunner` contains automatic retry logic for `EXTERNAL_API_TOOLS`.
2. **Pre-Dispatch Fencing:** Pre-flight budget rejection aborts execution *before* `DISPATCH_COMMITTED` can proceed to network transmission.
3. **No Fallback Provider:** `VideoProviderRegistry` does not implement silent fallbacks to alternative paid providers.
4. **No Double-Counting:** `check_budget()` is strictly read-only and does not mutate `fal_spend.json`. `record_spend()` runs at most once per execution.
5. **No Ambiguity Masking:** If a network timeout occurs during queue polling, the outcome remains `UNKNOWN_PENDING_RECONCILIATION`. The reconciler strictly reports `LOOKUP_UNSUPPORTED` with `can_safely_retry=False`.

---

## 8. MAPPING TO EXISTING STAGE 25 ARCHITECTURAL AUTHORITIES

The remediation reuses 100% existing Stage 25 architecture without introducing new daemons, tables, or microservices:

| Stage / Component | Existing Authority Responsibilities | Remediation Role |
| :--- | :--- | :--- |
| **Stage 07 Gateway** | Ingestion, initial payload validation | Untouched. Validates incoming goal schema. |
| **Stage 08 Orchestration** | DAG dependency management | Untouched. Manages action node dependencies. |
| **Stage 09 Persistence** | PostgreSQL state management | Untouched. Authoritative persistence for action status, artifact URI, and `cost_usd`. |
| **Stage 15 Action Bus** | Event publishing | Untouched. Emits execution transition events. |
| **Stage 20 Policy** | Enterprise quotas and safety limits | Defines global maximum budget ceilings. |
| **Stage 21 Governance** | Approvals & operator checkpoints | Operator review for actions requiring manual confirmation. |
| **Stage 22 Audit** | Immutable event ledger & causal traces | Records pre-dispatch intent, execution duration, and provider telemetry. |
| **Stage 23 Recovery** | Authoritative reconciliation engine | Resolves ambiguous timeouts without guessing or retry. |
| **Stage 25 Execution Bridge** | `AutonomousExecutionRunner`, `LiveProviderDispatcher` | Evaluates fail-closed gate, validates physical MP4 via `artifact_validator`. |
| **OpenMontage Adapter** | Subprocess sandbox & protocol v1.1 | Enforces process-group isolation, safe cwd, environment filtering. |
| **OpenMontage Tool Boundary** | Media synthesis & provider calling | Executes pre-flight budget check, dispatches Fal call, traps ledger IO errors. |

---

## 9. OPENMONTAGE FAL BUDGET LEDGER ANALYSIS

1. **Nature of `fal_spend.json`:**
   - It is a **local developer/test safeguard file** within the OpenMontage repository (`OpenMontage/data/fal_spend.json`).
   - It is NOT part of AryaOS core databases, does not survive container redeployments, and is not synchronized across multi-worker clusters.
2. **Tool Scope:**
   - Inspection proves `flux_image.py` does **NOT** use `fal_spend.py`.
   - `kling_video.py` is the **only tool** in the entire codebase referencing `fal_spend`.
3. **The Danger of Merely Raising the Budget:**
   - If an engineer simply changes `"budget": 50.0` in `fal_spend.json` without fixing the code:
     - The single test call in Phase 3.2.4.4.4 would pass.
     - BUT the architectural defect (evaluating budget post-charge with an unhandled exception) would remain.
     - As soon as the ledger reached $50.00, or if `fal_spend.json` suffered an IO error, the system would immediately crash again *after* charging the provider.
4. **Remediation Mandate:**
   - **Code Changes in OpenMontage:** Decouple `check_budget()` from `record_spend()`, call `check_budget()` pre-dispatch, wrap `record_spend()` in safe exception handling.
   - **Configuration / Ledger Reset:** Reset or increase the test budget in `fal_spend.json` to allow authorized test execution.

---

## 10. MINIMAL IMPLEMENTATION PLAN

### A. Mandatory Blocker Fix (Phase 3.2.4.4.4.2 Implementation Scope)

#### 1. `OpenMontage/tools/fal_spend.py`
Refactor into two distinct functions:
- `check_budget(cost: float) -> tuple[bool, str | None]`:
  Read-only pre-flight inspection. Checks `used + cost <= budget`. Returns `(True, None)` or `(False, "FAL budget exceeded: ...")`. Does NOT modify ledger.
- `record(*, model, cost, operation, project, asset) -> dict[str, Any]`:
  Appends generation record and writes JSON to disk. Does NOT raise budget exception if called post-execution.

#### 2. `OpenMontage/tools/video/kling_video.py`
- In `KlingVideo.execute(inputs)`:
  - **Pre-dispatch:** Call `check_budget(cost)` immediately after checking `api_key`. If false, return:
    ```python
    return ToolResult(
        success=False,
        error=f"Pre-dispatch budget check failed: {budget_error}",
        status=ToolStatus.FAILED,
    )
    ```
  - **Post-dispatch:** Wrap `record(...)` in safe error handling:
    ```python
    try:
        record(...)
    except Exception as ledger_err:
        # Non-fatal: do not abort successful generation
        logger.warning(f"Failed to record local spend: {ledger_err}")
    ```

#### 3. `OpenMontage/data/fal_spend.json`
- Update test budget headroom for authorized Stage 25 testing (e.g., set budget to `$25.00` or reset historical test usage).

### B. Optional Hardening (Post-Phase 3.2.4.4.4)
- Include `accounting_warning` in Protocol v1.1 `ToolResult.data` payload.
- In AryaOS `KlingVideoProvider.estimate_cost()`: verify against a configurable max single-shot ceiling ($0.15).

### C. Phase 4 Cleanup
- Migrate OpenMontage local spend tracking to report telemetry directly through AryaOS's unified database event bus, eliminating disk-based JSON ledgers entirely.

---

## 11. REGRESSION & ARCHITECTURAL INTEGRITY VERIFICATION

The read-only audit verified that zero system state was altered:

| Invariant Item | Required Baseline | Observed Audit State | Verification |
| :--- | :--- | :--- | :---: |
| **Alembic Migration Head** | `i9d0e1f2a3b4` | `i9d0e1f2a3b4 (head)` | **CONFIRMED** |
| **New Migrations** | Exactly 0 | 0 new migrations | **CONFIRMED** |
| **Stage 03 Blender SHA-256** | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | **CONFIRMED** |
| **Stage 03 GLB Assets** | Exactly 28 intact | 14 blender + 14 dist GLBs intact | **CONFIRMED** |
| **Git Working Tree Commits** | Exactly 0 new commits | HEAD remains `ba6ca58` | **CONFIRMED** |
| **Frontend Directory** | Untouched | Untouched | **CONFIRMED** |
| **Stages 03–24 Code** | Untouched | Untouched | **CONFIRMED** |
| **Execution Bridge Test Suite** | 100% green | 212 passed, 0 failed in 12.97s | **CONFIRMED** |
| **External Spend Incurred** | Exactly $0.00 | $0.00 (Zero network calls) | **CONFIRMED** |

---

## 12. FINDINGS BY SEVERITY

| Severity | Finding Title | Impact Summary | Remediation Requirement |
| :--- | :--- | :--- | :--- |
| **CRITICAL** | Post-Charge Accounting Crash in `kling_video.py` | `record()` evaluates budget post-charge outside try/except; crashes process after provider debits account and writes MP4. | Decouple `check_budget()` (pre-dispatch) from `record()` (post-dispatch safe block). |
| **HIGH** | OpenMontage Test Budget Ledger Exhaustion | `fal_spend.json` budget is $20.00; used is $20.00. Any call triggers `FAL budget exceeded`. | Increase budget ceiling or reset test entries in `fal_spend.json`. |
| **MEDIUM** | Architectural Sequencing Flaw (Combined Check & Record) | `record()` in `fal_spend.py` conflates read-only authorization with state mutation. | Split into read-only `check_budget()` and mutation `record()`. |
| **LOW** | Asymmetric Budget Ledger Usage Across Tools | `kling_video.py` enforces `fal_spend.json` but `flux_image.py` does not. | Document OpenMontage tool asymmetry; harmonize in Phase 4. |

---

## FINAL VERDICT

The failure mechanism has been comprehensively diagnosed, root cause established, boundary ownership delineated, and the minimal remediation design verified against all Stage 25 security invariants.

### **`REMEDIATION DESIGN READY`**

---

## ABSOLUTE STOP

This audit is strictly a design audit.
- No code was modified.
- No configuration was changed.
- No budget values were altered.
- No Fal, Kling, or external provider calls were made.
- External spend remains **$0.00**.

Awaiting operator instruction to proceed to Phase 3.2.4.4.4.2 implementation.
