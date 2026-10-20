# AryaOS V1 Stage 21 — Multi-Tier Authority Intersection & Fail-Closed Model

## 1. Architectural Theorem

The central invariant governing AryaOS V1 runtime execution is:

$$\text{Effective Authority} = \text{Policy Decision} \cap \text{Connector Permissions} \cap \text{Action Authorization} \cap \text{Human Approval} \cap \text{Mission Constraints}$$

$$\text{POLICY ALLOW} \neq \text{ACTION AUTHORIZATION} \neq \text{CONNECTOR PERMISSION} \neq \text{HUMAN APPROVAL}$$

A policy evaluation resulting in `ALLOW` indicates solely that *organizational policies do not prohibit the operation*. It does **not** grant execution authority, does **not** bypass connector access scopes, and does **not** waive human operator approval boundaries.

---

## 2. Granular Tier Definitions

| Authority Tier | Responsible Service | Description | Failure Result |
|---|---|---|---|
| **Tier 1: Policy Tier** | `policyEvaluationService` | Matches rules, resolves conflicts, and checks organisational governance. | `DENY` or `REQUIRE_APPROVAL` |
| **Tier 2: Connector Tier** | `connectorPermissionService` | Validates connector health, permission scopes, resource paths, and operation permissions. | `MISSING_PERMISSION` |
| **Tier 3: Action Tier** | `actionBusService` & `capabilityRegistry` | Verifies capability registration, availability status, schema validation, and risk limits. | `DENIED` |
| **Tier 4: Human Approval Tier** | `governanceAuthorityService` | Enforces human approval requirements on `CRITICAL` or policy-flagged operations. | `REQUIRES_APPROVAL` |
| **Tier 5: Mission Tier** | `missionControlService` | Validates mission constraints, budget caps, concurrency limits, and active lifecycle states (`ACTIVE` vs `PAUSED`/`CANCELLED`). | `MISSION_CONSTRAINT_BLOCKED` |

---

## 3. Fail-Closed Invariant

The intersection is evaluated by `GovernanceAuthorityService.evaluateAuthorityIntersection()`:
- If **any** required tier fails or evaluates to false, `failClosed` is set to `true`.
- The aggregate status is assigned the most restrictive blocking code:
  - `DENIED` takes absolute precedence.
  - `REQUIRES_APPROVAL` is returned if human approval is pending.
  - `MISSING_PERMISSION` is returned if connector grants are absent.
  - `MISSION_CONSTRAINT_BLOCKED` is returned if mission is paused or limits are exceeded.
- Execution cannot proceed unless `effectiveStatus === 'GRANTED'`.

---

## 4. Anti-Spoofing & Privilege Escalation Protection

To protect against rogue subagents, compromised tool outputs, or ambient authority escalation:
1. **Autonomous Agent Default Deny**: Autonomous agents (`AUTONOMOUS_AGENT-*`) possess zero ambient connector access. They require an explicit, unexpired `AgentCapabilityGrant` issued by a human `OPERATOR`.
2. **Rejection of Machine Approval**: Approval tokens signed by `AUTONOMOUS_AGENT-*` or `SYSTEM-*` actors are immediately rejected with status `FORGED_REJECTED`.
3. **Approval Token Binding**: Approval tokens must include an unexpired timestamp, operator ID, signature, and must reference the exact `policySnapshotId` and `requestId`.
4. **Connector Health Verification**: A connector in `UNAVAILABLE`, `ERROR`, or `DEGRADED` health state causes immediate fail-closed denial.
