# AryaOS V1 Stage 22 — Audit Event Schema & Event Immutability

## 1. Canonical Audit Event Schema

Every consequential operation in AryaOS V1 is recorded as an immutable `OperationalAuditEvent`. The schema provides comprehensive cross-stage correlation, epistemic categorization, failure diagnostics, and provenance tracking:

```typescript
export interface OperationalAuditEvent {
  // Identity & Monotonic Ordering
  readonly eventId: string;
  readonly sequenceNumber: number;
  readonly timestamp: number;
  readonly operationId: string;
  readonly correlationId: string;
  readonly causationId?: string;
  readonly parentOperationId?: string;

  // Lifecycle & Epistemic Certainty
  readonly eventType: OperationalAuditEventType;
  readonly lifecycleState: OperationalLifecycleState;
  readonly epistemicStatus: EpistemicStatus;
  readonly stageOrigin: number; // 1 to 22

  // Actor & Origin Context
  readonly actor: {
    readonly actorId: string;
    readonly actorType: 'USER' | 'AUTONOMOUS_AGENT' | 'SYSTEM' | 'EXTERNAL_SYSTEM';
  };
  readonly sourceSystem: string;

  // Cross-Stage Correlation References
  readonly actionId?: string;
  readonly connectorId?: string;
  readonly triggerId?: string;
  readonly triggerVersion?: number;
  readonly policyId?: string;
  readonly policyVersion?: number;
  readonly policySnapshotId?: string;
  readonly governanceDecisionId?: string;
  readonly governanceDecision?: 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL' | 'LIMIT' | 'DEFER' | 'PAUSE';
  readonly goalId?: string;
  readonly missionId?: string;

  // Diagnostic & Integrity Metadata
  readonly riskLevel?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly failureBoundary?: FailureBoundaryDetail;
  readonly evidenceReferences?: readonly string[];
  readonly reason?: string;
  readonly parameters?: Readonly<Record<string, unknown>>;
  readonly output?: Readonly<Record<string, unknown>>;

  // Cryptographic & Integrity Proofs
  readonly fingerprint: string;
  readonly isDuplicate?: boolean;
}
```

---

## 2. Event Types & Lifecycle Progression

The schema defines 12 strongly-typed event types representing operational milestones:

1. `REQUEST_RECEIVED`: External request or event entered the runtime.
2. `REQUEST_VALIDATED`: Syntactic and schema validation passed.
3. `MISSION_BOUND`: Tied to long-horizon mission or goal.
4. `TRIGGER_EVALUATED`: Matched against Stage 19 trigger rule.
5. `GOVERNANCE_DECIDED`: Evaluated by Stage 21 Governed Policy Control Plane.
6. `AUTHORITY_CHECKED`: 5-tier authority intersection evaluated.
7. `ACTION_DISPATCHED`: Dispatched to Stage 15 Universal Action Bus.
8. `ACTION_EXECUTED`: Connector or provider returned execution result.
9. `STATE_RECONCILED`: Direct observation compared with expected intent.
10. `OPERATION_SUCCEEDED`: Successful terminal completion.
11. `OPERATION_FAILED`: Terminal failure with diagnosed boundary.
12. `OPERATION_UNKNOWN`: Terminal state when external confirmation is missing.

---

## 3. Cryptographic Fingerprinting & Immutability

### 3.1 Canonical Serialization
To ensure deterministic hashing regardless of object key order, `auditIntegrityService.computeFingerprint()` performs recursive key sorting before hashing:
$$\text{Fingerprint} = \text{SHA256}(\text{CanonicalJSON}(\text{Payload}))$$

### 3.2 Deep Object Freezing
Once instantiated, audit events and all nested payload dictionaries are recursively frozen via `Object.freeze()`. Any runtime attempt to mutate an existing audit event throws a `TypeError`.

### 3.3 Monotonic Sequence Generation
Every event registered in `auditEventRegistry` receives a strictly increasing, gapless sequence number:
$$\text{seq}_{n+1} = \text{seq}_n + 1$$
This guarantees global chronological ordering across all asynchronous threads.

---

## 4. Cross-Stage Correlation Indexes

The `AuditEventRegistry` maintains multi-dimensional indexes for constant-time ($O(1)$) lookups:
- `indexByOperationId`: All events within an operational lifecycle.
- `indexByCorrelationId`: All operations within a distributed workflow.
- `indexByCausationId`: Ancestor-descendant causal edge queries.
- `indexByActionId`: Cross-reference to Stage 15 Action Bus dispatch.
- `indexByConnectorId`: Observability across Stage 16/17 connectors.
- `indexByTriggerId`: Telemetry for Stage 18/19 reactive rules.
- `indexByPolicyId`: Auditability for Stage 20/21 policy evaluations.
- `indexByGovernanceDecisionId`: Decision provenance lookup.
- `indexByMissionId`: Long-horizon mission checkpoint correlation.
