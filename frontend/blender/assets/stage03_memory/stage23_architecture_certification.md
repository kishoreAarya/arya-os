# Stage 23 — Architecture Certification

**Stage**: AryaOS V1 — Stage 23: Governed Recovery & Self-Healing Control Plane  
**Phase**: Phase 13: Final Certification, Full Regression & Stage Freeze  
**Status**: CERTIFIED & FROZEN  

---

## 1. Architectural Boundary & Ownership Certification

Stage 23 integrates with existing authority and infrastructure layers strictly honoring established boundaries without redefining or duplicating domain ownership:

```
┌─────────────────────────────────────────────────────────────┐
│                      Stage 12 / Stage 19                    │
│             Mission Authority & Reaction Authority          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Stage 20 / Stage 21                    │
│           Policy Authority & Governance Authority           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                          Stage 22                           │
│                 Operational Truth & Causal Audit            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                          Stage 23                           │
│              Recovery Control & Self-Healing Plane          │
└──────────────────┬──────────────────────┬───────────────────┘
                   │                      │
                   ▼                      ▼
┌──────────────────────────────┐  ┌───────────────────────────┐
│           Stage 09           │  │    Stage 15 / Stage 07    │
│  Durable Persistence Layer   │  │   Execution Boundaries    │
│    & Execution Journal       │  │ (Action Bus & Providers)  │
└──────────────────────────────┘  └───────────────────────────┘
```

### Architectural Ownership Mapping

- **Stage 09 (Persistence & Crash Recovery)**:
  - Owns durable execution journal, disk/storage sync, and crash recovery mechanics.
  - Stage 23 integrates via `recoveryControlPersistenceService`, using `ExecutionPersistence` and `ExecutionJournal` without creating alternative storage layers.
- **Stage 15 (External Capability Execution / Action Bus)**:
  - Owns capability dispatch, handler execution, and action pipeline.
  - Stage 23 recovery actions (retries, reconciliation probes, compensations) route strictly through `ActionBusService.dispatchAction`.
- **Stage 07 (Provider Execution / Execution Gateway)**:
  - Owns provider adapter invocation and execution gateway dispatch.
  - Stage 23 communicates with provider capabilities strictly through `ExecutionGateway.dispatch`.
- **Stage 16 (Connector Permissions)**:
  - Owns connector registration, permission scopes, and token revocation.
  - Stage 23 checks connector status via `ConnectorRegistry` and revalidates post-restart.
- **Stage 20 (Policy Authority)**:
  - Owns declarative policy evaluation, constraints, and rule changes.
  - Stage 23 captures immutable `policySnapshotId` and hash, revalidating policies before dispatch.
- **Stage 21 (Governance Authority)**:
  - Owns approval requirements, operator identity checks, and token generation.
  - Stage 23 checks `GovernanceControlPlane` and revalidates approval tokens.
- **Stage 22 (Operational Truth & Causal Audit)**:
  - Owns ground-truth execution evidence, causal parentage tracking, and tamper-evident audit logging.
  - Stage 23 classifies failures based on Stage 22 evidence and outputs reconciliation records to Stage 22.

---

## 2. Singleton Engine Audit (Zero Duplication)

A static codebase audit confirms that exactly ONE engine instance exists for each core authority function:

| Subsystem Component | Registered Implementation | Duplicate Instances Found |
|---|---|---|
| Recovery Control Engine | `RecoveryControlPlane` (`recoveryControlPlaneService.ts`) | **0** (Verified unique) |
| Policy Registry | `PolicyRegistry` (`policyRegistry.ts`) | **0** (Verified unique) |
| Governance Control Plane | `GovernanceControlPlane` (`governanceAuthorityService.ts`) | **0** (Verified unique) |
| Operational Truth Service | `OperationalTruthService` (`operationalTruthService.ts`) | **0** (Verified unique) |
| Execution Persistence | `ExecutionPersistence` (`executionPersistence.ts`) | **0** (Verified unique) |
| Action Bus Dispatcher | `ActionBusService` (`actionBus.ts`) | **0** (Verified unique) |
| Execution Gateway | `ExecutionGateway` (`executionGateway.ts`) | **0** (Verified unique) |
| Connector Registry | `ConnectorRegistry` (`connectorRegistry.ts`) | **0** (Verified unique) |

---

## 3. Execution Pipeline Invariants

Stage 23 enforces the following end-to-end execution pipeline invariants:

1. **Failure Observation**: Stage 22 captures unvarnished facts (`DISPATCH_NOT_PERFORMED`, `UNKNOWN_EXTERNAL_STATE`, `DEFINITIVE_FAILURE`).
2. **Classification**: Stage 23 assigns recovery category without fabricating facts.
3. **Safety Assessment**: Idempotency and reversibility classification determine candidate recovery actions.
4. **Authority Intersection**: Authority is validated across Policy $\cap$ Connector $\cap$ ActionBus $\cap$ Human $\cap$ Mission.
5. **Execution Delegation**: Recovery actions execute solely through Stage 15 Action Bus or Stage 07 Gateway. Stage 23 contains zero direct transport logic (`fetch`, raw socket, or Axios).
6. **Audit & Closure**: Outcome is journaled to Stage 09 and recorded in Stage 22 causal graph.
