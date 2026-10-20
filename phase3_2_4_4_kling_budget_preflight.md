# ARYAOS STAGE 25 — PHASE 3.2.4.4
## CONTROLLED SINGLE-SHOT KLING VIDEO SANDBOX
### BUDGET ALLOCATION & PRE-EXECUTION SECURITY PREFLIGHT REPORT

**AUTHORIZATION: BUDGET ALLOCATION & PREFLIGHT ONLY.**  
**NO EXTERNAL PROVIDER CALLS MADE — ZERO DOLLARS SPENT.**

---

## 1. EXACT BUDGET ALLOCATION

Following the security acceptance of the budget-ledger remediation in Phase 3.2.4.4.4.2.1, a narrowly bounded local test budget headroom has been allocated for exactly ONE controlled single-shot Kling video generation:

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Exact File Changed** | `OpenMontage/data/fal_spend.json` | Local OpenMontage test safety ledger |
| **Old Budget** | **$20.00** | Initial baseline ceiling |
| **Old Used Spend** | **$20.00** | Preserved historical usage (unaltered) |
| **Old Remaining Headroom** | **$0.00** | 100% exhausted |
| **Estimated Kling Test Cost** | **$0.1000** | `kling-video/v3/standard`, 5s text-to-video (`0.10 * (5 / 5)`) |
| **Authorized Safety Margin** | **$0.0100** | Strict minimal margin (authorized <= cost + $0.01) |
| **New Authorized Budget** | **$20.11** | $20.00 + $0.10 + $0.01 |
| **Resulting Remaining Headroom** | **$0.11** | Strictly allows exactly 1 single-shot test ($0.10) |
| **Historical Spend Altered?** | **NO** | `generations` list intact; historical entries preserved |

### Headroom Verification (`tools.fal_spend.check_budget`):
- `check_budget(0.10)`: **`(True, None)`** — Exactly authorizes proposed 5-second test ($0.10).
- `check_budget(0.15)`: **`(False, 'Local FAL budget exceeded: $20.15 > $20.11 (remaining: $0.11)')`** — Fails closed against second calls or oversized durations.

---

## 2. PROPOSED SINGLE-SHOT KLING TEST PARAMETERS

The smallest valid input contract supported by the current Kling adapter has been constructed:

```json
{
  "provider": "kling",
  "model": "kling-video/v3/standard",
  "operation": "text_to_video",
  "prompt": "Cinematic slow orbital sweep of an ancient brass astrolabe mechanism, photorealistic, 4k",
  "duration": "5",
  "aspect_ratio": "16:9",
  "output_path": "backend/storage/artifacts/phase3_2_4_4_kling_astrolabe.mp4",
  "first_frame": null,
  "last_frame": null,
  "first_and_last_frame": null
}
```

### Invariants:
- **Duration:** Strictly **5 seconds** (minimum supported increment; 10s costs $0.20 and would fail the $0.11 headroom check).
- **Operation Mode:** `text_to_video` (eliminates external image download dependencies and SSRF attack surface).
- **Conditioning Constraints:**
  - First-frame conditioning: **NONE**
  - Last-frame conditioning: **NONE** (dual-layer pre-dispatch rejection active)
  - First+last frame conditioning: **NONE** (dual-layer pre-dispatch rejection active)
- **Call Count:** Strictly **1 single provider request**.
- **Concurrency:** **0 concurrency** (single in-process execution task).
- **Retries / Fallback:** **0 retries**, **0 fallback providers**.

---

## 3. SECURITY & PREFLIGHT VERIFICATION

| Dimension | Verification Item | Status | Evidence |
| :--- | :--- | :---: | :--- |
| **Live Execution Gate** | `ENABLE_LIVE_PROVIDER_EXECUTION` defaults to `False` | **VERIFIED** | Default `Settings().enable_live_provider_execution == False`; fails closed with `LiveExecutionGateError`. |
| **Local Gate Isolation** | `enable_live_local_execution=True` cannot enable Kling | **VERIFIED** | Kling is explicitly classified as external (`is_external_tool("kling_video") == True`); local gate fails closed. |
| **Provider Profile** | `supports_idempotency_key = False` | **VERIFIED** | Confirmed in `idempotency.py:151`. |
| **Provider Profile** | `supports_status_lookup = False` | **VERIFIED** | Confirmed in `idempotency.py:152`. |
| **Consistency Guarantee** | `NO_LOOKUP` strictly enforced | **VERIFIED** | Confirmed in `idempotency.py:153`; reconciler issues `LOOKUP_UNSUPPORTED`, `can_safely_retry=False`. |
| **Ambiguity Protection** | Subprocess timeout (300s) maps to `UNKNOWN` | **VERIFIED** | `OpenMontageAdapter:714` returns `UNKNOWN_PENDING_RECONCILIATION` (`is_ambiguous=True`). |
| **Secret Presence** | `FAL_KEY` present server-side | **VERIFIED** | Length: 72 chars; sourced from server config. |
| **Secret Masking** | `FAL_KEY` never printed or leaked | **VERIFIED** | `repr(Settings)` masks secret; `sanitize_text()` masks stderr/exceptions; git ignores `.env`. |
| **Subprocess Security** | Environment isolation and safe cwd | **VERIFIED** | `SAFE_SYSTEM_ENV_ALLOWLIST` active; `cwd=OpenMontage`; database credentials stripped. |

---

## 4. EXPECTED ARTIFACT CONTRACT

Before execution is authorized, the target physical output artifact contract is verified:

- **Target Path:** `backend/storage/artifacts/phase3_2_4_4_kling_astrolabe.mp4`
- **File Format:** ISOBMFF / MP4 container with `ftyp` magic bytes (`b"\x00\x00\x00 ftypmp42"`).
- **Expected Video Codec:** H.264 / AVC (`h264`).
- **Expected Dimensions:** 16:9 aspect ratio (`1280x720` standard or `1920x1080`).
- **Expected Duration:** Approximately 5.0 seconds (within `4.8s - 5.5s`).
- **Expected Frame Rate:** ~25.0 or ~30.0 fps.
- **Physical Verification:** `validate_artifact_file(..., expected_type="video")` using `/opt/homebrew/bin/ffprobe` (version 8.1.2) stream analysis.
- **Path Security:** Confinement within `backend/storage/artifacts/`, symlink escape protection, directory traversal protection.
- **Size Bounds:** `100 KB < file_size <= 500 MB`.

---

## 5. BUDGET SAFETY & RECONCILIATION INVARIANTS

1. **Pre-Dispatch Safety:** If `check_budget()` fails, execution aborts before issuing network calls: call count = 0, external spend = $0.00, spend ledger unmutated.
2. **Post-Dispatch Execution Truth:** If Fal accepts the request and produces a valid artifact, but secondary ledger recording experiences disk or lock contention, the action remains `SUCCEEDED` with `accounting_warning` recorded. External success is never falsified.
3. **No Automatic Retry:** Neither adapter nor runner will trigger retry on failure.
4. **Authoritative Financial Ledger:** Incurred cost will be persisted to PostgreSQL `AutonomousActionNode.cost_usd = 0.1000`.

---

## 6. REGRESSION & ARCHITECTURAL INTEGRITY RESULTS

| Invariant Item | Required Baseline | Observed Preflight Value | Verification Status |
| :--- | :--- | :--- | :---: |
| **Alembic Migration Head** | `i9d0e1f2a3b4` | `i9d0e1f2a3b4 (head)` | **CONFIRMED** |
| **New Database Migrations** | Exactly 0 | 0 new files (10 total) | **CONFIRMED** |
| **Stage 03 Blender SHA-256** | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` | **CONFIRMED** |
| **Stage 03 GLB Assets** | Exactly 28 intact | 14 blender + 14 dist GLBs intact | **CONFIRMED** |
| **Git Working Tree Commits** | Exactly 0 new commits | HEAD remains `ba6ca58` | **CONFIRMED** |
| **Stages 03–24 Code** | Untouched | Untouched | **CONFIRMED** |
| **Frontend Code** | Untouched | Untouched | **CONFIRMED** |
| **Full Execution Bridge Suites** | 100% green | **220 passed, 0 failed in 20.89s** | **CONFIRMED** |
| **OpenMontage Unit Tests** | 100% green | **5 passed in 5.20s** | **CONFIRMED** |
| **Provider Calls Made** | Exactly 0 | 0 network requests | **CONFIRMED** |
| **External Spend Incurred** | Exactly $0.00 | $0.00 | **CONFIRMED** |

---

## 7. FINAL PREFLIGHT VERDICT

The budget allocation is complete, tightly bounded ($0.11 headroom), and verified. All preflight safety checks, capability introspections, gate boundaries, and artifact validation contracts are green.

### **`KLING PREFLIGHT: READY FOR EXPLICIT EXECUTION`**

---

## ABSOLUTE STOP

- **No Kling or Fal API calls were made.**
- **No video was generated.**
- **Zero dollars were spent.**

Awaiting explicit operator authorization to execute the single-shot Kling video generation in Phase 3.2.4.4.
