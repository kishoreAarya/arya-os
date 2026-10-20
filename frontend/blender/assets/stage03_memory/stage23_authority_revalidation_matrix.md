# AryaOS V1 — Stage 23: Phase 11
## Authority Revalidation Matrix

**Authoritative Status:** FROZEN & VERIFIED  
**Stage:** Stage 23 — Recovery Control Plane & Autonomous Healing  
**Phase:** Phase 11 — Cold-Restart Continuity & Governed Recovery Resumption  

---

### 1. Cross-Stage Authority Intersection

Stage 23 does NOT maintain independent authority or credentials. Upon cold restart, authority is re-derived through the intersection of Stages 12, 16, 20, 21, and 22:

```
┌────────────────────────────────────────────────────────────────────────┐
│               STAGE 23 RECOVERY AUTHORITY INTERSECTION                │
├──────────────────────┬────────────────────────┬────────────────────────┤
│ AUTHORITY DOMAIN     │ RESPONSIBLE STAGE      │ REVALIDATION RULE      │
├──────────────────────┼────────────────────────┼────────────────────────┤
│ Policy Intel         │ Stage 20               │ Snapshot ID & version  │
│ Governance & Approvals│ Stage 21               │ Token TTL (<5m) & actor│
│ Connector Access     │ Stage 16               │ Status != ERROR, active│
│ Mission Constraints  │ Stage 12               │ State != PAUSED/CANCEL │
│ Operational Truth    │ Stage 22               │ Causal audit precedence│
│ Orchestration State  │ Stage 09               │ Lease & counter integrity│
└──────────────────────┴────────────────────────┴────────────────────────┘
```

---

### 2. Authority Check Precedence & Failure Routing

```
                     REVALIDATION REQUEST
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     1. EXPIRATION CHECK                    2. OPERATIONAL TRUTH
     `now >= decision.expiresAt`            `externalSuccess: true`
            │ YES                                 │ YES
            ▼                                     ▼
    Status: EXPIRED                        Status: ALREADY_COMPLETED
    Action: ESCALATE                       Action: WAIT
            │ NO                                  │ NO
            └──────────────────┬──────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     3. EPISTEMIC STATUS                    4. MISSION CONSTRAINT
     `externalStatusConfirmed: false`       `missionState === PAUSED`
            │ YES                                 │ YES
            ▼                                     ▼
    Status: UNCONFIRMED                    Status: CONSTRAINT_BLOCKED
    Action: RECONCILE                      Action: PAUSE
            │ NO                                  │ NO
            └──────────────────┬──────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     5. POLICY DRIFT                        6. CONNECTOR PERMISSIONS
     `version != current`                   `permissionRevoked: true`
            │ YES                                 │ YES
            ▼                                     ▼
    Status: POLICY_MISMATCH                Status: PERMISSION_MISSING
    Action: REQUIRE_APPROVAL               Action: REQUIRE_APPROVAL
            │ NO                                  │ NO
            └──────────────────┬──────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     7. HUMAN APPROVAL                      8. CASCADE CONTAINMENT
     `humanApprovalExpired: true`           `containment === ISOLATE`
            │ YES                                 │ YES
            ▼                                     ▼
    Status: APPROVAL_EXPIRED               Status: CASCADE_PRESERVED
    Action: REQUIRE_APPROVAL               Action: PRESERVE CONTAINMENT
            │ NO                                  │ NO
            └──────────────────┬──────────────────┘
                               │
                               ▼
                        9. FALLBACK VALID
                        Status: VALID
                        Action: PROCEED AS DECIDED
```

---

### 3. Detailed Boundary Validation Matrix

| Subsystem Domain | Invariant | Violation Behavior | Outcome Action | Causal Journal Code |
|------------------|-----------|--------------------|----------------|---------------------|
| **Stage 20 Policy** | Policy snapshot immutable and matches current active registry version | If version advances or snapshot ID diverges, fail closed | `REQUIRE_APPROVAL` | `POLICY_VERSION_MISMATCH` |
| **Stage 20 Policy** | Active DENY rule overrides any stored recovery authorization | Immediate termination of recovery path | `ABORT` | `GOVERNANCE_POLICY_DENIED` |
| **Stage 21 Governance** | Operator approval token valid strictly for 5 minutes (`300,000ms`) | Token expired across reboot fails closed | `REQUIRE_APPROVAL` | `APPROVAL_TOKEN_EXPIRED` |
| **Stage 21 Governance** | Approval token cryptographically bound to exact `requestId` & `policySnapshotId` | Token replay across operations rejected | `REQUIRE_APPROVAL` | `GOVERNANCE_STALE` |
| **Stage 16 Connectors** | Target connector online and permissions unrevoked | Missing permissions or connector in ERROR state halts execution | `REQUIRE_APPROVAL` | `CONNECTOR_PERMISSION_MISSING` |
| **Stage 12 Mission** | Parent mission running and constraints satisfied | Paused or cancelled mission suspends recovery | `PAUSE` | `MISSION_CONSTRAINT_BLOCKED` |
| **Stage 09 Persistence** | Lease lock held by exactly one worker per decision | Multi-worker concurrent execution blocked (409) | `REJECTED` | `LEASE_ACQUIRED` / `LEASE_HELD` |
| **Stage 22 Truth** | Empirical reality supersedes intent | Completed action never replayed; unconfirmed action probed | `WAIT` / `RECONCILE` | `ALREADY_COMPLETED` / `UNCONFIRMED_EXTERNAL_STATE` |
