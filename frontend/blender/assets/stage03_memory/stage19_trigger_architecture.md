# AryaOS V1 Stage 19 — Trigger Architecture & Controlled Event Reaction Engine

## 1. Executive Overview

Stage 19 introduces the **Controlled Event-Driven Reaction Engine** to AryaOS V1. In Stage 18, inbound events, webhooks, and callbacks were authenticated, normalized, deduplicated, and committed to the immutable event journal. Stage 19 answers the critical architectural question:

> *"When an external event occurs, what — if anything — should AryaOS do?"*

Stage 19 explicitly rejects direct event-to-action dispatch. An incoming webhook or external state mutation does not possess execution authority. Stage 19 implements a formal, multi-stage governance pipeline separating matching, proposal, risk elevation, authorization, human gating, and bus dispatch.

```
EXTERNAL EVENT (Stage 18 Normalized)
         │
         ▼
TRIGGER MATCHING (TriggerEvaluationService)
  ├── Filter by Source, Resource, Change Type
  └── Declarative Condition Evaluation (TriggerConditionEngine)
         │
         ▼
REACTION PROPOSAL (ReactionProposalService)
  ├── Semantic Risk Classification (TriggerRiskService)
  ├── Dynamic Risk Elevation
  └── Authorization Gating
         │
         ├── LOW Risk ──► Automatic Authorization
         └── HIGH / CRITICAL ──► AWAITING_APPROVAL (Human Signoff Required)
                                      │
                                      ▼
REACTION EXECUTION ENGINE (ReactionExecutionEngine)
  ├── Causal Loop & Depth Enforcement (maxDepth = 3, Cycle Detection)
  ├── Idempotency Check & Concurrency Throttling
  └── Governed Dispatch:
        ├── EXTERNAL_ACTION ──► Stage 15 Action Bus (actionBusService.execute)
        ├── MISSION OPS     ──► Stage 12 Mission Manager / Replanner
        └── GOAL CREATION   ──► Stage 08 Goal Orchestrator
```

---

## 2. Core Invariants

Stage 19 is governed by five absolute architectural axioms:

1. **`EVENT ≠ ACTION`**: Receipt and ingestion of an external event never implies or causes immediate invocation of an external capability or code block.
2. **`EVENT ≠ AUTHORITY`**: An event carries data and payload provenance, but zero ambient authority. It cannot bypass permission boundaries or elevate privileges.
3. **`TRIGGER ≠ PERMISSION`**: Registering a trigger definition does not grant permission to execute its configured reactions. Permissions are checked dynamically at proposal time against Stage 16 Connector Fabric grants.
4. **`TRIGGER ≠ HUMAN APPROVAL`**: High and Critical risk reactions (external writes, destructive mutations, workflow triggers, spends) strictly require human operator cryptographic signoff. Autonomous agents and system Daemons are forbidden from granting approval.
5. **`REACTION PROPOSAL ≠ EXECUTION`**: A matched trigger emits a `ReactionProposal` record. Execution occurs only after authorization, validation, loop verification, and explicit dispatch via Stage 15 Action Bus.

---

## 3. Strict Boundary Guarantees

| Subsystem | Stage Authority | Stage 19 Constraint |
|---|---|---|
| **AI / Inference** | Stage 07 Execution Gateway (`executionGateway.execute`) | **Zero LLM Calls**. Stage 19 contains zero autonomous LLM calls or prompt generation. |
| **External Action** | Stage 15 Universal Action Bus (`actionBusService.execute`) | **Sole Outbound Gateway**. Stage 19 never contacts connector transports directly. |
| **Identity & Scope** | Stage 16 Connector Fabric (`connectorRegistry`, `connectorPermissionService`) | **Authorization Authority**. Every action intent is verified for active connector registration and granted scopes. |
| **Outbound Transport** | Stage 17 Connector Activation | **Untouched**. Transports are invoked exclusively by Stage 15 Action Bus. |
| **Inbound Ingestion** | Stage 18 External Event Ingestion | **Inbound Source**. Ingests, authenticates, deduplicates, and normalizes before passing to Stage 19. |
| **Scene & Visuals** | Stage 03 Spatial Memory Environment | **0 Additional Draw Calls**. Reaction telemetry is rendered strictly via DOM HUD panels in `SpatialCommandConsole`. |

---

## 4. Trigger Domain Contracts

The domain model is defined in `src/types/eventTrigger.ts`:

- **`Trigger`**: Complete trigger specification containing identity (`id`, `version`, `name`), event filter pattern (`eventFilter`), declarative conditions (`conditions`), reaction template (`reaction`), declared risk (`riskLevel`), authorization metadata (`targetConnectorId`, `requiredScopes`), and audit timestamps.
- **`TriggerStatus`**: Finite lifecycle states: `DRAFT`, `ACTIVE`, `PAUSED`, `DISABLED`, `REVOKED`.
- **`TriggerEventFilter`**: Source system pattern matching supporting wildcards (`*`), e.g., `sourceSystem: 'github'`, `resourceType: 'issue'`, `changeType: 'created'`.
- **`TriggerConditionGroup`**: Pure declarative boolean evaluation trees supporting `AND` and `OR` conjunctions of atomic `TriggerCondition` rules.
- **`TriggerReaction`**: Configured intent type (`EXTERNAL_ACTION`, `CREATE_GOAL`, `UPDATE_GOAL`, `PAUSE_MISSION`, `RESUME_MISSION`, `REPLAN_MISSION`, `CREATE_OBSERVATION`, `REQUEST_ANALYSIS`), payload template, idempotency key template, and retry parameters.
- **`ReactionProposal`**: Immutable governed proposal containing unique proposal ID, trigger reference, triggering event reference, evaluated risk level, approval status (`PROPOSED`, `AUTHORIZED`, `AWAITING_APPROVAL`, `REJECTED`, `EXPIRED`, `EXECUTED`, `FAILED`), and audit trail.
- **`ReactionExecutionResult`**: Final execution audit record containing execution status (`SUCCESS`, `FAILED`, `BLOCKED`, `CHAIN_LIMIT`, `THROTTLED`), execution duration, output, and causal tracking fields (`causationId`, `correlationId`, `depth`, `visitedTriggerIds`).

---

## 5. Pipeline Lifecycle Walkthrough

### Step A: Event Ingestion (Stage 18)
The external system (e.g. GitHub, Stripe, Discord) emits a webhook. Stage 18 verifies the cryptographic signature (HMAC SHA-256), validates the schema, deduplicates by delivery ID and payload hash, and normalizes the payload into a `NormalizedExternalEvent`.

### Step B: Trigger Evaluation (Stage 19)
`TriggerEvaluationService.evaluateEvent(event)` queries `TriggerRegistry.getActiveTriggers()`. For each active trigger:
1. Matches event against `trigger.eventFilter` (supporting exact match and `*` wildcard).
2. Evaluates declarative condition group via `TriggerConditionEngine.evaluate(trigger.conditions, event)`.
3. If matched, triggers proposal generation.

### Step C: Reaction Proposal & Risk Evaluation
`ReactionProposalService.createProposal(trigger, event)` is invoked:
1. `TriggerRiskService.evaluateReactionRisk(trigger, event)` evaluates intrinsic intent risk and dynamically elevates risk if external writes or state mutations are requested.
2. Checks connector registration and permission scopes via Stage 16 `connectorPermissionService.hasPermission()`.
3. If risk is `LOW` and permission is granted: auto-authorizes (`status: 'AUTHORIZED'`).
4. If risk is `HIGH` or `CRITICAL`: sets `status: 'AWAITING_APPROVAL'`.

### Step D: Human Approval Gate
For proposals awaiting approval, only an authenticated human operator (`user-*`) can grant approval via `ReactionProposalService.grantApproval()`.
Attempts by autonomous agents (`AUTONOMOUS_AGENT-*`) or system daemons (`SYSTEM-*`) are immediately rejected with security violations.

### Step E: Governed Execution (ReactionExecutionEngine)
When authorized:
1. Causal context is verified: `depth <= maxDepth (default: 3)`.
2. Cycle detection: `visitedTriggerIds` is inspected; if current trigger was already visited in the causal chain, execution is aborted with `status: 'CHAIN_LIMIT'` and a `REACTION_CHAIN_LIMIT` event is appended to the journal.
3. Concurrency throttle: In-flight executions are bounded (`maxConcurrentReactions: 10`).
4. Dispatch:
   - For `EXTERNAL_ACTION`: dispatches via `actionBusService.execute(...)`.
   - For `PAUSE_MISSION` / `REPLAN_MISSION`: dispatches via `missionManager` / `missionReplanner`.
   - For `CREATE_GOAL`: dispatches via `goalOrchestrator`.
5. Journaling: `TRIGGER_EXECUTED` or `TRIGGER_BLOCKED` event is committed to `executionPersistence`.

---

## 6. Verification Summary

The trigger architecture was verified under `src/tests/EventReactionStage19.test.tsx` across 60 automated tests, confirming strict adherence to all architectural invariants and security boundaries.
