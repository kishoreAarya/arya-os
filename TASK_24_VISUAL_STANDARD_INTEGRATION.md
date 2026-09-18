# ARYA OS — TASK 24: VISUAL STANDARD V2 INTEGRATION REPORT
## No-Credit Architecture Integration, Declarative Profiles & Dry-Run Verification

**Author:** Antigravity Autonomous Agent  
**Date:** September 14, 2026  
**Status:** **REAL PROVIDER VALIDATION PENDING — REPLICATE CREDITS EXHAUSTED**  
**Final Verdict:** **PASS — INTEGRATION READY, REAL VALIDATION PENDING**  

---

## 1. Executive Summary & Context

Task 22 established a Pareto frontier for production video, but direct operator human review rejected the resulting visuals as waxy, artificial, and lacking cinematic depth.

Task 23 conducted a targeted visual generation investigation (evaluating FLUX Schnell, FLUX Dev, and FLUX 1.1 Pro across 3 prompting strategies and 2 video generation models). Task 23 discovered:
1. **FLUX Schnell 4-Step Distillation was the root cause of failure:** Latent distillation compresses facial anatomy into waxy, plastic skin textures and creates hallucinated spatial logic (e.g. ghostly printed faces on black wool cassocks).
2. **FLUX 1.1 Pro produced superior keyframe fidelity (9.53/10 score):** Yielded lifelike skin pores, physically coherent shadows, and authentic atmospheric depth.
3. **Kling Standard v1.6 delivered stable cinematic camera push:** Exhibited rigid physical geometry and grounded kinetic movement with zero latent boil or wobbly warping (unlike LTX-Video).
4. **Concrete optical directives outperform generic AI buzzwords:** Specifying anamorphic focal lengths, motivated color temperatures (Kelvin), and three-plane depth staging drastically improved compositional weight.

**Current Operational Condition:**  
Replicate credits are exhausted (HTTP 402 Payment Required). Therefore, Task 24 is strictly an **IMPLEMENTATION, DRY-RUN, AND REGRESSION TASK**. No paid provider credits were expended ($0.00 spent). Production defaults remain strictly preserved on `current_legacy`, and all new V2 capabilities are safely integrated behind declarative profiles, feature flags, and dry-run safety gates.

---

## 2. Declarative Visual Model Profiles

Arya OS now features declarative visual model profiles in `backend/app/services/visual_profiles.py`, allowing seamless switching between baseline legacy behavior and advanced cinematic visual standards:

| Profile Identifier | Display Name | Image Generation Engine | Steps | Cost / Img | Video Engine | Cost / Vid | Target Quality |
| :--- | :--- | :--- | :---: | :---: | :--- | :---: | :---: |
| `current_legacy` *(Default)* | Current Legacy (FLUX Schnell / Fixed) | `black-forest-labs/flux-schnell` | 4 | $0.0030 | Kling Standard v1.6 | $0.25 | 7.0 / 10.0 |
| `visual_v2_lean` | Visual Standard V2 Lean (FLUX Dev) | `black-forest-labs/flux-dev` | 28 | $0.0250 | Kling Standard v1.6 | $0.25 | 8.5 / 10.0 |
| `visual_v2_flagship` | Visual Standard V2 Flagship (FLUX 1.1 Pro) | `black-forest-labs/flux-1.1-pro` | 30 | $0.0400 | Kling Standard v1.6 | $0.25 | 9.5 / 10.0 |

### Profile Characteristics:
- **`current_legacy`:** Preserved for 100% backward compatibility and zero-risk rollback. Production default (`visual_profile="current_legacy"`). Generates 1 candidate per shot, uses standard prompt formatting, and maintains hybrid 1-Kling / rest FFmpeg motion allocation.
- **`visual_v2_lean`:** Balanced cost-quality profile. Utilizes 28-step FLUX Dev, generates 3 candidates on key visual beats / Class A shots and 1 on atmospheric shots, applies Prompt Policy V2, and pairs kinetic beats with Kling Standard while utilizing deterministic FFmpeg for atmospheric drifts.
- **`visual_v2_flagship`:** Uncompromised cinematic standard. Utilizes FLUX 1.1 Pro with multi-candidate keyframe selection (3 on key beats, 2 on secondary, 1 on tertiary), incorporates Visual Continuity Bible anchors, applies full Prompt Policy V2 with Kelvin lighting and three-plane staging, and reserves Kling Standard for narrative-critical kinetic beats.

---

## 3. Provider Availability Status Granularity

Arya OS now explicitly distinguishes provider states to prevent confusing billing exhaustion with configuration or authentication failures:

```python
class ProviderAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"              # Provider operational, credentials valid
    UNAVAILABLE = "UNAVAILABLE"          # Network / service outage
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"# Missing API key or HTTP 401 Unauthorized
    CREDIT_EXHAUSTED = "CREDIT_EXHAUSTED"# Balance 0.00 / HTTP 402 Payment Required
    TIMEOUT = "TIMEOUT"                  # Request / poll deadline exceeded
    RATE_LIMITED = "RATE_LIMITED"        # HTTP 429 Too Many Requests
```

In `backend/app/providers/replicate.py`, HTTP 402 and API error messages citing "insufficient credits", "payment required", or "unpaid balance" are cleanly caught and raised as explicit `Replicate credits exhausted (402 Payment Required)` errors, preventing spurious retries and immediate categorization as `CREDIT_EXHAUSTED`.

---

## 4. Prompt Policy V2 Enforcement

Prompt Policy V2 eliminates empty AI buzzwords and replaces them with concrete physical cinematography physics:

### A. Strict Buzzword Ban List
The following terms are stripped by `sanitize_prompt_v2()`:
`8k`, `8k uhd`, `masterpiece`, `best quality`, `photorealistic`, `hyperrealistic`, `ultra realistic`, `trending on artstation`, `unreal engine`, `octane render`, `award winning`, `stunning`, `epic`, `breathtaking`, `intricate details`, `highly detailed`, `cinematic lighting`.

### B. Cinematography Directives
V2 prompts inject concrete optics and lighting parameters:
- **Lens & Optics:** Focal lengths, aperture, and distortion (e.g. `35mm anamorphic prime lens, f/2.0, shallow depth of field`).
- **Motivated Lighting Temperatures:** Specific Kelvin temperatures and sources (e.g. `2400K warm practical candlelight against 5600K slate moonlight fill`).
- **Three-Plane Depth Staging:** Intentional foreground framing, midground subject clarity, and atmospheric background falloff.
- **Tactile Material Textures:** Physical surfaces with weight (e.g. `coarse woven wool cassock, damp porous limestone, cold condensation`).
- **Emotional Narrative Intent:** Micro-behaviors (e.g. `caught mid-breath, tension in shoulders, wide pupillary response`).
- **Bible Section 30 Negative Prompts:** Mandatory prohibition of text, subtitles, captions, buttons, and user interface elements.

---

## 5. Smart Allocation V2 & Quality Floor Override

In `backend/app/services/smart_allocator.py`:
1. **Dynamic Candidate Allocation:**
   - Lean Policy: Key visual beat / Class A: **3 candidates**, Class B: **1 candidate**, Class C: **1 candidate**.
   - Flagship Policy: Key visual beat / Class A: **3 candidates**, Class B: **2 candidates**, Class C: **1 candidate**.
   - Legacy Policy: **1 candidate** fixed across all shots.
2. **Quality Floor Override:**
   - In accordance with production standards, Quality Floor ($\ge 8.5$) **strictly overrides budget limits**.
   - If a kinetic shot's motion score $\ge 0.75$, it is promoted to generative video (Kling) even if `max_kling_shots` has been reached, with explicit overrun logging:
     `Shot X promoted to Kling (motion_score=0.85) to prevent quality floor breach (<8.5)`.
3. **Itemized Accounting:**
   - Itemizes accepted vs rejected candidate costs, Kling video generation costs, and zero-cost FFmpeg motion.

---

## 6. Deterministic Dry-Run Mode (`VISUAL_DRY_RUN=true`)

When `VISUAL_DRY_RUN=true` (or `context["visual_dry_run"]=True`):
- `ImageAgent` and `VideoAgent` simulate deterministic results (`dry_run://...`) without making outbound network requests to paid APIs.
- Full shot plans, continuity contexts, Prompt Policy V2 transformations, and candidate selection rankings are generated deterministically.
- Cost accounting records:
  - **`OBSERVED COST`**: **$0.00** (Zero credits consumed)
  - **`EXPECTED COST`**: Accurately calculated from profile unit rates ($0.04/image, $0.25/video)

### Standardized 3-Shot Horror Benchmark ("The Crypt of Saint Jude")

| Metric | `current_legacy` | `visual_v2_lean` | `visual_v2_flagship` |
| :--- | :---: | :---: | :---: |
| **Image Model** | FLUX Schnell (4 steps) | FLUX Dev (28 steps) | FLUX 1.1 Pro (30 steps) |
| **Keyframe Candidates** | 3 candidates (1/1/1) | 9 candidates (3/3/3) | 9 candidates (3/3/3) |
| **Kling Generative Video** | 1 shot (Shot 3) | 1 shot (Shot 3) | 1 shot (Shot 3) |
| **FFmpeg Image-Motion** | 2 shots (Shots 1, 2) | 2 shots (Shots 1, 2) | 2 shots (Shots 1, 2) |
| **Expected Image Cost** | $0.0090 | $0.2250 | $0.3600 |
| **Expected Video Cost** | $0.2500 | $0.2500 | $0.2500 |
| **Total Expected Cost** | **$0.2590** | **$0.4750** | **$0.6100** |
| **Observed Real Cost** | **$0.0000** | **$0.0000** | **$0.0000** |
| **Visual Budget ($0.80)** | Passed ($0.541 under) | Passed ($0.325 under) | Passed ($0.190 under) |

---

## 7. Artifact Manifest & Directory Mirroring

All dry-run and profile artifacts were generated into `/tmp/arya-task24-visual-integration/` and mirrored to `~/Desktop/arya-task24-visual-integration/`:

1. [`visual_profiles.json`](file:///tmp/arya-task24-visual-integration/visual_profiles.json): Declarative schema and configuration parameters for all 3 visual profiles.
2. [`dry_run_plan.json`](file:///tmp/arya-task24-visual-integration/dry_run_plan.json): Complete deterministic 3-shot execution plan comparing all profiles.
3. [`expected_costs.json`](file:///tmp/arya-task24-visual-integration/expected_costs.json): Comparative itemized cost breakdown across profiles.
4. [`dry_run_report.md`](file:///tmp/arya-task24-visual-integration/dry_run_report.md): Formatted dry-run report.

---

## 8. Real Validation Script & Credit Safety Guard

A dedicated validation script was created at `scratch/run_task24_real_validation.py`:
- Validates provider credit readiness before any API invocation.
- If credits are exhausted, execution is safely refused with exit code 2 and a high-visibility diagnostic alert.
- CLI supports dry-run verification across all profiles:
  ```bash
  python scratch/run_task24_real_validation.py --profile visual_v2_flagship
  python scratch/run_task24_real_validation.py --profile visual_v2_lean
  python scratch/run_task24_real_validation.py --profile current_legacy
  ```

---

## 9. Test Verification & Zero Regression

- **Baseline Test Suite:** 506 / 506 passing
- **New Task 24 Unit Suite (`backend/tests/test_visual_profiles_unit.py`):** 11 / 11 passing
- **Total Test Suite:** **517 / 517 tests passing (100% green, 0 failures)**

---

## 10. Conclusion & Final Verdict

Task 24 successfully completes the architectural integration of the Task 23 cinematic visual standard into Arya OS without spending provider credits during the Replicate credit outage. Production defaults remain protected on `current_legacy`, and the system stands fully prepared for real-world validation the instant provider credits become available.

**FINAL VERDICT:**  
# PASS — INTEGRATION READY, REAL VALIDATION PENDING
