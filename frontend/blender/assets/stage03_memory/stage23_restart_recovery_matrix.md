# AryaOS V1 — Stage 23: Phase 11
## Cold-Restart Recovery & Resumption Decision Matrix

**Authoritative Status:** FROZEN & VERIFIED  
**Stage:** Stage 23 — Recovery Control Plane & Autonomous Healing  
**Phase:** Phase 11 — Cold-Restart Continuity & Governed Recovery Resumption  
**Master Blender SHA256:** `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`  
**Test Suite:** 1,437 / 1,437 Passed (45 suites) | Stage 23: 314 tests | Phase 11: 46 tests  

---

### 1. Architectural Principle: "No Trust-by-Persistence"

A core architectural invariant governs cold-restart continuity in AryaOS:
> **Persistence proves prior existence, NOT current authority.**
> When AryaOS restarts, no persisted recovery decision may execute without authoritative revalidation from Stage 20 (Policy), Stage 21 (Governance), and Stage 22 (Operational Truth).

```
                      COLD RESTART EVENT
                              │
                              ▼
            LOAD PERSISTED RECOVERY DECISION
              (Stage 09 executionPersistence)
                              │
                              ▼
                   STRUCTURAL INTEGRITY CHECK
           (Prototype pollution, secret, size guard)
                              │
                              ▼
                 DECISION REVALIDATION PIPELINE
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
    STAGE 22 TRUTH      STAGE 20 POLICY     STAGE 21 GOVERNANCE
   - External success? - Policy version?   - Operator approval TTL?
   - Unknown state?    - Snapshot ID?      - Connector permissions?
   - Completed steps?  - Deny rules?       - Mission state?
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                              ▼
                 REVALIDATION RESULT DETERMINATION
            (VALID, REQUIRE_APPROVAL, PAUSE, WAIT, ESCALATE)
```

---

### 2. Cold-Restart Resumption Matrix

| # | Interruption Point | Persisted State | Revalidation Input | Epistemic Status | Revalidated Outcome | Recommended Action | Reason Code |
|---|-------------------|-----------------|-------------------|------------------|---------------------|--------------------|-------------|
| 1 | Pre-dispatch | `retryCount: 2`, `NOT_DISPATCHED` | Authority intact | `OBSERVED` | `RETRY` | `RETRY` | `VALID` |
| 2 | Pre-dispatch (Max) | `retryCount: 3`, `NOT_DISPATCHED` | Authority intact | `OBSERVED` | `ESCALATE` | `ESCALATE` / `WAIT` | `VALID` |
| 3 | In-flight (Post-dispatch) | `DISPATCHED` | Remote unconfirmed | `UNKNOWN` | `RECONCILE` | `RECONCILE` | `UNCONFIRMED_EXTERNAL_STATE` |
| 4 | In-flight (Offline completion) | `DISPATCHED` | `externalSuccess: true` | `CONFIRMED` | `NO_RECOVERY_REQUIRED` | `WAIT` | `ALREADY_COMPLETED` |
| 5 | Multi-step recovery | Step 1 done, step 2 failed | Authority intact | `OBSERVED` | `RESUME` | `RESUME` | `VALID` |
| 6 | High-risk multi-step | Step 1 done, step 2 failed | Human required | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` / `WAIT` | `VALID` |
| 7 | Active compensation | `COMPENSATE` | Not yet compensated | `OBSERVED` | `COMPENSATE` | `COMPENSATE` | `VALID` |
| 8 | Active compensation | `COMPENSATE` | `observed: COMPENSATED` | `CONFIRMED` | `WAIT` | `WAIT` | `COMPENSATION_ALREADY_EXECUTED` |
| 9 | Active reconciliation | `reconcileAttempts: 1` | Ambiguous state | `UNKNOWN` | `RECONCILE` | `RECONCILE` | `UNCONFIRMED_EXTERNAL_STATE` |
| 10 | Max reconciliation | `reconcileAttempts: 3` | Ambiguous state | `UNKNOWN` | `ESCALATE` | `ESCALATE` | `MAX_RECONCILIATION_ATTEMPTS_EXCEEDED` |
| 11 | Approved decision | Token fresh (<5m TTL) | Signed operator token | `OBSERVED` | `RETRY` | `RETRY` | `VALID` |
| 12 | Expired approval | Token stale (>5m TTL) | `humanApprovalExpired` | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `APPROVAL_TOKEN_EXPIRED` |
| 13 | Policy version drift | `policyVersion: 1` | `currentPolicyVersion: 2` | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `POLICY_VERSION_MISMATCH` |
| 14 | Policy snapshot drift | `snapshotId: old-uuid` | `currentSnapshotId: new-uuid` | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `POLICY_SNAPSHOT_MISMATCH` |
| 15 | Active Policy DENY | Matching rule active | Stage 20 DENY rule | `OBSERVED` | `ABORT` | `ABORT` | `GOVERNANCE_POLICY_DENIED` |
| 16 | Revoked permission | Connector capability | `permissionRevoked: true` | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `CONNECTOR_PERMISSION_MISSING` |
| 17 | Connector ERROR | Connector capability | `connectorStatus: 'ERROR'` | `OBSERVED` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `CONNECTOR_PERMISSION_MISSING` |
| 18 | Paused mission | `missionId: active` | `missionState: 'PAUSED'` | `OBSERVED` | `PAUSE` | `PAUSE` | `MISSION_CONSTRAINT_BLOCKED` |
| 19 | Cancelled mission | `missionId: active` | `missionState: 'CANCELLED'` | `OBSERVED` | `PAUSE` | `PAUSE` | `MISSION_CONSTRAINT_BLOCKED` |
| 20 | Cascade ISOLATE | `containment: ISOLATE` | Restart reboot | `OBSERVED` | `ISOLATE` | Preserved | `CASCADE_CONTAINMENT_PRESERVED` |
| 21 | Cascade ABORT | `containment: ABORT` | Crash reboot | `OBSERVED` | `ABORT` | Preserved | `CASCADE_CONTAINMENT_PRESERVED` |
| 22 | Expired recovery lease | Worker A lease expired | Worker B request | `OBSERVED` | Expired invalidated | Null lease | `LEASE_EXPIRED` |
| 23 | Active recovery lease | Worker A lease valid | Worker B request | `OBSERVED` | Locked (409) | Rejected | `LEASE_HELD_BY_OTHER` |
| 24 | Tampered payload | Malformed record | Storage load | `UNKNOWN` | Null record | Dropped | `SECURITY_VIOLATION` |

---

### 3. Fail-Closed Guarantees

1. **Unknown External State Cannot Progress to Action:**
   If an interrupted operation was dispatched but remote outcome is unconfirmed, epistemic status remains `UNKNOWN`. No blind retries or replays are permitted.
2. **Ambient Authority is Zero:**
   No historical execution approval or connector grant is grandfathered across reboot without explicit cryptographic and timestamp verification.
3. **Immutability of Historical Decisions:**
   Superseding an invalid or stale decision across restart writes a new immutable record with state `SUPERSEDED` / `EXPIRED`; historical causal logs are preserved for Stage 22 audit.
