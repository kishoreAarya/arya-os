# AryaOS V1 Stage 23 — Evidence-Based Failure Classification Architecture

## 1. Purpose & Scope

The purpose of `FailureClassificationService` is to convert verified operational evidence into exactly one deterministic Stage 23 `FailureClassification`. 

$$\text{Stage 22 Operational Evidence} \longrightarrow \text{FailureClassificationService} \longrightarrow \text{Stage 23 FailureClassification}$$

### Absolute Architectural Separation
$$\text{CLASSIFICATION} \neq \text{RECOVERY DECISION}$$
Phase 2 answers exclusively: **"WHAT KIND OF FAILURE, INTERRUPTION, OR STATE DIVERGENCE OCCURRED?"**  
It strictly **DOES NOT** answer: **"WHAT SHOULD WE DO ABOUT IT?"**  
A classification of `TRANSIENT` does **not** mean `RETRY`. A classification of `UNKNOWN_EXTERNAL_STATE` does **not** itself trigger reconciliation. Action selection belongs exclusively to Phase 3 (`RecoveryAction` matrix routing).

---

## 2. Input Evidence Model

Classification consumes a strongly typed, structured evidence contract (`ClassificationEvidence`) rather than raw string parsing.

```typescript
export interface ClassificationEvidence {
  readonly operationId: string;
  readonly causationId: string;
  readonly correlationId: string;
  readonly lifecycleState?: string;
  readonly epistemicStatus?: string;
  readonly dispatchState: DispatchState;
  readonly httpStatus?: number;
  readonly providerErrorCategory?: string;
  readonly connectorStatus?: string;
  readonly authorizationResult?: { readonly authorized: boolean; readonly reason?: string };
  readonly permissionResult?: { readonly granted: boolean; readonly revoked?: boolean; readonly reason?: string };
  readonly policyResult?: { readonly decision: string; readonly matchedPolicyId?: string; readonly reason?: string };
  readonly staleStateEvidence?: { readonly isStale: boolean; readonly reason?: string };
  readonly timeoutEvidence?: { readonly timedOut: boolean; readonly timeoutMs?: number; readonly phase?: 'PRE_DISPATCH' | 'POST_DISPATCH' };
  readonly cancellationEvidence?: { readonly cancelled: boolean; readonly reason?: string };
  readonly dependencyState?: { readonly satisfied: boolean; readonly missingDependencies?: readonly string[] };
  readonly resourceExhaustionEvidence?: { readonly exhausted: boolean; readonly resourceType?: string };
  readonly partialExecutionEvidence?: { readonly completedSteps: readonly string[]; readonly failedStep?: string; readonly pendingSteps: readonly string[] };
  readonly reconciliationEvidence?: { readonly attempted: boolean; readonly matched: boolean; readonly discrepancies?: readonly string[] };
  readonly humanInterventionRequired?: boolean;
  readonly evidenceReferences?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}
```

---

## 3. The 13 Canonical Failure Categories

| Category | Definition | Triggering Evidence |
|---|---|---|
| **PARTIAL_EXECUTION** | A multi-step workflow where some steps completed before failure. | `partialExecutionEvidence.completedSteps.length > 0` and failed/pending steps present. |
| **UNKNOWN_EXTERNAL_STATE** | External action dispatched but outcome is unconfirmed, timed out, or unverified. | `dispatchState` is `DISPATCHED` / `EXECUTING` / `EXTERNAL_CONFIRMATION_ABSENT` with absent confirmation or `epistemicStatus === 'UNKNOWN'`. |
| **RECONCILIATION** | Observed physical environment contradicts intended state. | `reconciliationEvidence.matched === false` or `dispatchState === 'RECONCILIATION_FAILED'`. |
| **PERMISSION** | Connector revoked, token expired, or missing connector fabric scope. | `permissionResult.revoked === true` or `connectorStatus === 'REVOKED'`. |
| **AUTHORIZATION** | Capability authorization denied in Stage 15/21 authority intersection. | `authorizationResult.authorized === false`. |
| **POLICY** | Active policy evaluated to `DENY`. | `policyResult.decision === 'DENY'`. |
| **STALE_STATE** | Stale policy snapshot, TTL expired, or invalidated approval signature. | `staleStateEvidence.isStale === true`. |
| **RESOURCE** | Quota limit exceeded, rate limit hit, out of memory/disk. | `httpStatus === 429` or `resourceExhaustionEvidence.exhausted === true`. |
| **DEPENDENCY** | Missing prerequisite artifact, upstream task failure. | `dependencyState.satisfied === false` or `missingDependencies.length > 0`. |
| **PERMANENT** | Unrecoverable client error, bad request, schema rejection. | `httpStatus` 400–499 (except 429) or `INVALID_REQUEST`. |
| **SYSTEM_INTERRUPTION** | Cancellation, SIGTERM/SIGKILL, process crash before dispatch. | `cancellationEvidence.cancelled === true` or `PROCESS_TERMINATED`. |
| **TRANSIENT** | Network socket timeout before dispatch, 502/503/504 before dispatch. | Pre-dispatch network error or `timeoutEvidence.phase === 'PRE_DISPATCH'`. |
| **HUMAN_REQUIRED** | Mandatory human operator gate, safety policy hold. | `humanInterventionRequired === true` or `decision === 'REQUIRE_APPROVAL'`. |

---

## 4. Deterministic Precedence & Override Hierarchy

When multiple evidence signals are present, `failureClassificationService` applies strict deterministic precedence:

1. **`PARTIAL_EXECUTION`**: Completed side-effects must be accounted for first so subsequent recovery steps never duplicate completed actions.
2. **`UNKNOWN_EXTERNAL_STATE`**: Overrides any transient error. If a timeout or HTTP 500 occurs after dispatch, the outcome is unknown, not transient.
3. **`RECONCILIATION`**: Overrides permission or policy errors if the external change already occurred and produced a discrepancy.
4. **`PERMISSION`**: Overrides local authorization because missing connector credentials halt execution before authority checks can proceed.
5. **`AUTHORIZATION`**: Overrides policy evaluation if the agent has no capability grant.
6. **`POLICY`**: Overrides permanent/transient errors if the operation was blocked at governance.
7. **`STALE_STATE`**: Overrides resource/dependency errors if authority was stale.
8. **`RESOURCE`**: Overrides permanent errors if quota blocked execution.
9. **`DEPENDENCY`**: Overrides system interruption if prerequisites were missing.
10. **`PERMANENT`**: Overrides transient errors when input is syntactically invalid.
11. **`SYSTEM_INTERRUPTION`**: Overrides transient network errors when process was cancelled.
12. **`TRANSIENT`**: Evaluated when errors occur prior to external dispatch.
13. **`HUMAN_REQUIRED`**: Fallback for mandatory review gates not preempted by higher errors.

---

## 5. Epistemic Safety & Dispatch-State Boundaries

### The Non-Fabrication Rule
If `epistemicStatus === 'UNKNOWN'` and external dispatch was attempted or occurred:
$$\text{Classification} \equiv \text{UNKNOWN\_EXTERNAL\_STATE}$$
The system strictly prohibits:
- Silently upgrading `UNKNOWN` to `FAILED`.
- Silently upgrading `UNKNOWN` to `SUCCESS`.
- Treating client-supplied claims of success as authoritative evidence without Stage 22 cryptographic reconciliation.

### Pre-Dispatch vs Post-Dispatch Timeout Disambiguation
- **Timeout with `dispatchState === 'NOT_DISPATCHED'`**: Classified as `TRANSIENT` (safe to re-evaluate).
- **Timeout with `dispatchState === 'DISPATCHED'`**: Classified as `UNKNOWN_EXTERNAL_STATE` (unsafe to retry blindly).

---

## 6. Deterministic Reason Codes

Every classification result includes an immutable, strongly typed reason code:
- `TRANSIENT_NETWORK_FAILURE`
- `PERMANENT_CLIENT_REJECTION`
- `AUTHORIZATION_DENIED`
- `CONNECTOR_PERMISSION_REVOKED`
- `POLICY_DENIED`
- `STALE_AUTHORITY`
- `EXTERNAL_CONFIRMATION_ABSENT`
- `PARTIAL_WORKFLOW_COMPLETION`
- `RECONCILIATION_FAILED`
- `RESOURCE_EXHAUSTED`
- `DEPENDENCY_UNAVAILABLE`
- `SYSTEM_INTERRUPTION`
- `HUMAN_APPROVAL_REQUIRED`
- `AMBIGUOUS_EVIDENCE_SAFE_FALLBACK`

---

## 7. Security Defenses

- **Prototype Pollution**: Input evidence payloads are sanitized by `validateAndSanitizePayload()`, rejecting `__proto__`, `constructor`, and `prototype`.
- **Payload Bounding**: Nesting depth bounded to $\le 5$ levels, key count bounded to $\le 50$.
- **Zero LLM Tokens**: Pure deterministic TypeScript logic with zero hallucination.
- **Side-Effect Free**: Does not mutate goals, missions, policies, or historical audit records.
