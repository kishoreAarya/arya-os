# AryaOS V1 Stage 21 — Policy Snapshot Immutability & Version Tracking

## 1. Overview

In distributed and concurrent operational environments, policy rules must not mutate underneath an in-flight operation. The `PolicySnapshotService` creates point-in-time, immutable snapshots of all active policies registered in the `PolicyRegistry`.

Every governance decision references a concrete `PolicySnapshot`, guaranteeing that:
1. Long-running evaluations see a uniform, un-skewed rule set.
2. Decisions are 100% reproducible and audit-verifiable.
3. Mid-flight policy updates trigger deterministic staleness detection rather than silent drift.

---

## 2. Snapshot Lifecycle & Structure

```typescript
export interface PolicySnapshot {
  snapshotId: string;
  capturedAt: number;
  registryVersion: number;
  activePolicyCount: number;
  policies: readonly PolicySnapshotEntry[];
  fingerprint: string;
}
```

### 2.1 Filtering Rules
A snapshot captures **ONLY** policies with `status === 'ACTIVE'`.
- Policies in `DRAFT`, `CANDIDATE`, `PAUSED`, or `REVOKED` states are omitted.
- Shadow-mode candidate policies are never captured in the enforced execution snapshot.

### 2.2 Deep Object Freezing (`Object.freeze`)
Upon capture, the entire snapshot graph is recursively deep-frozen using `Object.freeze()`. Any runtime attempt to mutate policy parameters, conditions, or effects throws a runtime type error in strict mode.

---

## 3. Deterministic Fingerprinting (SHA-256)

Each snapshot computes a deterministic fingerprint:
- Policies are sorted deterministically by `id` and `version`.
- Relevant semantic fields (`id`, `version`, `priority`, `scope`, `conditions`, `effect`) are canonicalized as a JSON string.
- A cryptographic SHA-256 hash or deterministic pseudo-hash is generated from the canonical string.
- If two snapshots contain identical policies in different registration orders, their fingerprints are mathematically identical.

---

## 4. Registry Version Tracking & Invalidation

The `PolicyRegistry` maintains a monotonically increasing integer `registryVersion`:
- Any policy registration, update, status transition, or rollback increments `registryVersion`.
- The snapshot records `registryVersion` at the instant of capture.
- When an operation is submitted for pre-execution verification, if:
  $$\text{currentRegistryVersion} \neq \text{snapshotRegistryVersion}$$
  the decision is marked `VERSION_MISMATCH` and fails closed until re-evaluated.

---

## 5. Storage & Replay

Snapshots are stored in `executionPersistence` under `savePolicySnapshot(snapshot)`.
Historical decisions can be replayed against their original snapshot to confirm bit-identical decision outputs across restarts.
