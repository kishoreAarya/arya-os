# AryaOS V1 Stage 22 — Failure Boundary Reconstruction & Root Cause Analysis

## 1. Overview

In complex autonomous systems, failures often manifest far downstream from their originating cause. A failed API call might be caused by an expired token, an unauthorized agent capability, a denied security policy, or a corrupted inbound webhook.

Stage 22 implements the **Failure Boundary Service**, which diagnoses the exact boundary where an operation halted, identifies the responsible stage, and produces deterministic root-cause diagnostics.

---

## 2. The Five Canonical Failure Boundaries

Stage 22 classifies all non-successful operational outcomes into five exhaustive boundaries:

```
REQUEST / TRIGGER
       │
       ▼
[Stage 21: Policy Evaluation] ──────► (1) POLICY_DENIED
       │
       ▼
[Stage 21: Human Gate] ─────────────► (2) HUMAN_APPROVAL_PENDING
       │
       ▼
[Stage 21: Authority Intersection] ──► (3) AUTHORIZATION_DENIED
       │
       ▼
[Stage 15: Action Dispatch]
       │
       ▼
[Stage 17: External Execution] ──────► (4) EXTERNAL_RESULT_UNKNOWN
       │
       ▼
[Stage 22: Reality Reconciliation] ─► (5) RECONCILIATION_FAILURE
```

### Detailed Boundary Characteristics

| Failure Boundary | Stopping Stage | Root Cause Trigger | Diagnostic Remediation |
|---|---|---|---|
| **POLICY_DENIED** | Stage 21 (Governance Plane) | Policy evaluated to `DENY` due to resource limit, security baseline, or safety critical rule. | Review policy violation details; adjust parameters to satisfy policy rules. |
| **HUMAN_APPROVAL_PENDING** | Stage 21 (Governance Plane) | Operation involves high risk or financial threshold; awaiting operator signature. | Review in Spatial Command Console and provide explicit approval token. |
| **AUTHORIZATION_DENIED** | Stage 21 (Authority Intersection) | Agent lacks capability grant, connector permission, or scope in Stage 16. | Grant required connector capability or scope to the requesting actor. |
| **EXTERNAL_RESULT_UNKNOWN** | Stage 15/17 (External Gateway) | Action dispatched but connector callback timed out or provider disconnected. | Poll external provider status or trigger verified compensation flow. |
| **RECONCILIATION_FAILURE** | Stage 22 (Truth Engine) | Execution reported success, but observed target environment contradicts intent. | Inspect environmental drift; resolve discrepancy before state synchronization. |

---

## 3. Failure Boundary Detail Schema

```typescript
export interface FailureBoundaryDetail {
  readonly boundary: FailureBoundary;
  readonly stoppingStage: string;
  readonly reason: string;
  readonly diagnosticMessage: string;
  readonly suggestedRemediation?: string;
  readonly timestamp: number;
}
```

---

## 4. Root Cause Reconstruction Methodology

When `operationalAudit.diagnoseFailure(operationId)` is called:
1. All chronological events for `operationId` are retrieved from `auditEventRegistry`.
2. The sequence is scanned in reverse from outcome to origin:
   - If an event contains `STATE_RECONCILED` with `lifecycleState === 'FAILED'`, it is classified as `RECONCILIATION_FAILURE`.
   - If the last event is `OPERATION_UNKNOWN`, it is classified as `EXTERNAL_RESULT_UNKNOWN`.
   - If an event contains `AUTHORITY_CHECKED` with `lifecycleState === 'DENIED'`, it is classified as `AUTHORIZATION_DENIED`.
   - If an event contains `GOVERNANCE_DECIDED` with `decision === 'REQUIRE_APPROVAL'`, it is classified as `HUMAN_APPROVAL_PENDING`.
   - If an event contains `GOVERNANCE_DECIDED` with `decision === 'DENY'`, it is classified as `POLICY_DENIED`.
3. If no failure conditions are detected, `diagnoseFailure` deterministically returns `undefined`.
