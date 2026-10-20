# AryaOS V1 Stage 20 — Policy Shadow Mode & Non-Intrusive Evaluation

## 1. Concept & Architectural Boundary

Policy Shadow Mode provides a completely non-intrusive evaluation mechanism allowing proposed candidate policies to be evaluated against real-time operational context without affecting runtime execution decisions.

### Core Architectural Guarantee:
```
Runtime Request
       ↓
PolicyEvaluationService (Evaluates Active Policies) ──────> Active Decision ──────> Execution
       │
       └───> PolicyShadowService (Evaluates Candidate Policies)
                     ↓
             Divergence Check (Active Decision vs Candidate Decision)
                     ↓
             PolicyShadowRecord (Persisted in Execution Persistence)
                     ↓
             Zero Mutation of Active Decision or Runtime State
```

---

## 2. Divergence Tracking & Comparative Analysis

`PolicyShadowService` compares the actual active evaluation decision with the hypothetical candidate policy outcome:

- **Identical Outcomes**:
  - `isDivergent: false`
  - Records alignment and adds statistical support for candidate safety.
- **Divergent Outcomes**:
  - `isDivergent: true`
  - Generates structured `differenceExplanation`:
    - Identifies condition differences (e.g., candidate condition matched while active policy had no condition).
    - Highlights effect variance (e.g., Active allowed request, but Candidate would have required `REQUIRE_APPROVAL` or enforced `LIMIT`).
    - Reports constraint differences (e.g., tighter rate limit or lower concurrency lease).

---

## 3. Privacy & Credential Scrubbing in Shadow Telemetry

Shadow records (`PolicyShadowRecord`) are written to `ExecutionPersistence` for retrospective analysis by human operators. To ensure zero secret leakage, `PolicyShadowService` applies strict context filtering:

- Strips authorization headers (`Authorization`, `Bearer`, `X-Api-Key`).
- Recursively scrubs fields matching sensitive key regex patterns (`/auth/i`, `/token/i`, `/key/i`, `/secret/i`, `/password/i`, `/credential/i`).
- Stores only primitive scalars (`string`, `number`, `boolean`) in `contextSummary`.

---

## 4. Sample Shadow Mode Execution Record

```json
{
  "shadowId": "shad-pol-rate-limit-prod-1727885000",
  "candidatePolicyId": "pol-rate-limit-prod",
  "activePolicyId": "pol-default-allow",
  "timestamp": "2026-10-02T21:45:00.000Z",
  "evaluatedContext": {
    "actionType": "external_connector_write",
    "connectorId": "conn-github-prod",
    "requestFrequency": 120
  },
  "activeDecision": {
    "appliedEffect": "ALLOW",
    "winningPolicyId": "pol-default-allow"
  },
  "candidateDecision": {
    "appliedEffect": "LIMIT",
    "constraint": { "rateLimitPerHour": 100 },
    "winningPolicyId": "pol-rate-limit-prod"
  },
  "isDivergent": true,
  "differenceExplanation": "Candidate policy 'pol-rate-limit-prod' would have enforced LIMIT (max 100/hr) on 'conn-github-prod', whereas active policy 'pol-default-allow' yielded ALLOW."
}
```

---

## 5. Operational Role in Human Review

Shadow mode records are presented in the **Spatial Command Console HUD** (`policy-shadow-hud`). Operators review empirical divergence reports over a trial observation window (e.g., 24–72 hours) prior to approving candidate promotion to `ACTIVE`.
