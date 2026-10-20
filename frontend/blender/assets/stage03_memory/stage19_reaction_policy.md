# AryaOS V1 Stage 19 — Governed Reaction Policy & Risk Classification Framework

## 1. Governing Policy Overview

In AryaOS V1, the receipt of an event does not confer authorization to alter system state or execute external side effects. The Reaction Policy defines how potential responses to incoming events are categorized, risk-elevated, authorized, and gated.

```
+---------------------------------------------------------------------------------+
|                               REACTION POLICY MATRIX                           |
+-------------------+----------------+---------------------+----------------------+
| Intent Type       | Intrinsic Risk | Approval Gate       | Execution Target     |
+-------------------+----------------+---------------------+----------------------+
| CREATE_OBSERVATION| LOW            | Automated           | Memory/Knowledge     |
| REQUEST_ANALYSIS  | LOW/MEDIUM     | Automated           | Decision Support     |
| CREATE_GOAL       | MEDIUM         | Automated (Scoped)  | Goal Orchestrator    |
| UPDATE_GOAL       | MEDIUM         | Automated (Scoped)  | Goal Orchestrator    |
| PAUSE_MISSION     | HIGH           | Human Signoff       | Mission Manager      |
| REPLAN_MISSION    | HIGH           | Human Signoff       | Mission Replanner    |
| EXTERNAL_ACTION   | CRITICAL       | Human Signoff       | Stage 15 Action Bus  |
+-------------------+----------------+---------------------+----------------------+
```

---

## 2. Risk Classification Levels

AryaOS classifies reaction intents into four discrete risk categories:

### LOW
- **Definitions**: Passive state ingestion, telemetry logging, internal observation recording, read-only status queries.
- **Side Effect Footprint**: Zero external mutations, zero mission disruptions.
- **Authorization**: Automated upon validating connector registration and basic identity.

### MEDIUM
- **Definitions**: Internal goal generation, analytical report queuing, priority recalculation within pre-authorized mission bounds.
- **Side Effect Footprint**: Internal computational and goal queue changes; no irreversible external actions.
- **Authorization**: Automated if target connector scopes are active and goal budget is within limits.

### HIGH
- **Definitions**: Mission pause, mission branch invalidation, replanning triggers, resource de-allocation, external read-write of non-critical data.
- **Side Effect Footprint**: Affects multi-agent workflows, long-horizon schedules, or external read-write sync.
- **Authorization**: Gated under `AWAITING_APPROVAL`. Requires human operator confirmation.

### CRITICAL
- **Definitions**: External state mutations (`POST`, `PUT`, `DELETE`), financial or resource expenditure, repository commits/merges, webhook dispatch, permission modifications.
- **Side Effect Footprint**: Irreversible external state mutations or monetary implications.
- **Authorization**: Strictly gated under `AWAITING_APPROVAL`. Cryptographic human signoff mandatory.

---

## 3. Dynamic Risk Elevation Engine

A trigger author cannot bypass safety controls by declaring an artificial `LOW` risk level on a consequential action. The `TriggerRiskService` applies dynamic risk elevation:

1. **Declared vs Operational Baseline**:
   ```typescript
   const intrinsicRisk = this.getIntrinsicRisk(trigger.reaction.intentType);
   let finalRisk = this.maxRisk(trigger.riskLevel, intrinsicRisk);
   ```
2. **Payload Mutation Inspection**:
   If `intentType === 'EXTERNAL_ACTION'`:
   - Inspects action capability or HTTP method.
   - If payload involves `write`, `update`, `delete`, `publish`, `send`, `POST`, `PUT`, `PATCH`, or `DELETE`, risk is elevated to `CRITICAL`.
3. **Connector Scope Elevation**:
   If required scopes include administrative or write grants (`write:*`, `admin:*`, `repo:write`, `payments:*`), the proposal is forced to `CRITICAL`.

---

## 4. Proposal State Machine

```
              ┌───────────────┐
              │   PROPOSED    │
              └───────┬───────┘
                      │
         ┌────────────┴────────────┐
         │ Risk Evaluation & Auth  │
         ▼                         ▼
   [Risk == LOW]            [Risk >= HIGH]
         │                         │
         ▼                         ▼
   ┌───────────┐         ┌───────────────────┐
   │AUTHORIZED │         │ AWAITING_APPROVAL │
   └─────┬─────┘         └─────────┬─────────┘
         │                         │
         │                ┌────────┴────────┐
         │                ▼                 ▼
         │          Human Approves    Human Rejects
         │                │                 │
         │                ▼                 ▼
         │          ┌───────────┐     ┌───────────┐
         └─────────►│AUTHORIZED │     │ REJECTED  │
                    └─────┬─────┘     └───────────┘
                          │
                          ▼
                    ┌───────────┐
                    │ EXECUTED  │
                    └───────────┘
```

---

## 5. Test Suite Verification

Verified in `src/tests/EventReactionStage19.test.tsx`:
- Tests 27–30: Verified intrinsic risk classification across all intent types.
- Test 31: Verified dynamic risk elevation when trigger declares `LOW` but reaction performs external mutation.
- Test 32: Verified consequential triggers are flagged as requiring human approval.
- Tests 33–35: Verified proposal generation and state assignment based on risk level.
