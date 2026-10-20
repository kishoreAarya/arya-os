# AryaOS V1 Stage 20 — Policy Intelligence & Governed Adaptive Operations Architecture

## 1. Executive Overview

Stage 20 introduces the **Policy Intelligence & Governed Adaptive Operations** layer to AryaOS V1. As autonomous agents, long-horizon missions, external triggers, and connector transports operate across the system, recurring empirical experience generates learning signals. Stage 20 answers the foundational operational question:

> *"How should AryaOS govern recurring behavior across missions, agents, triggers, resources, connectors, and learned experience?"*

Stage 20 explicitly rejects autonomous self-modification. A learning signal or performance optimization never possesses ambient authority to alter system policies or execute privileged operations. Stage 20 implements an auditable, multi-stage governance pipeline separating observation, candidate generation, counterfactual simulation, human review, versioned activation, and runtime governance.

```
EXPERIENCE (Stage 11 ExperienceStore)
       │
       ▼
EVALUATION & LEARNING SIGNALS (Stage 11 AgentEvaluationService)
       │
       ▼
POLICY CANDIDATE GENERATION (PolicyProposalService)
       │
       ▼
IMPACT SIMULATION & SHADOW EVALUATION (PolicyImpactSimulator / PolicyShadowService)
  ├── Multi-dimensional Forecasting (Cost, Latency, Quality, Reliability, Risk)
  ├── Epistemic Certainty Labeling (OBSERVED, INFERRED, PROJECTED, UNKNOWN)
  └── Shadow Observation (Zero Runtime Mutation)
       │
       ▼
HUMAN OPERATOR REVIEW (PolicyProposalService.reviewProposal)
  ├── Cryptographic Operator Sign-off (user-*)
  └── Strict Prohibition of Autonomous Agent / Daemon Approvals
       │
       ▼
POLICY ACTIVATION (PolicyRegistry / PolicyActivationRecord)
  ├── Immutable Version Increment (v1 ➔ v2 ➔ ...)
  └── Conflict Check & Deterministic Hierarchy Enforcement
       │
       ▼
RUNTIME GOVERNANCE (PolicyEvaluationService)
  ├── Stage 10 Resource Governor (Budget, Concurrency Leases)
  ├── Stage 12 Mission Control (Mission Pausing, Replanning Bounds)
  ├── Stage 14 Decision Intelligence (Scenario Constraints)
  ├── Stage 16 Connector Fabric (Permission Ceilings)
  └── Stage 19 Reaction Engine (Trigger & Reaction Rate Limits)
```

---

## 2. Core Invariants

Stage 20 is governed by five absolute architectural axioms:

1. **`LEARNING ≠ AUTHORITY`**: The observation of empirical patterns or performance anomalies never grants authority to modify runtime policies or elevate execution privileges.
2. **`EXPERIENCE ≠ PERMISSION`**: Historical execution success does not waive permission checks or grant ambient authorization.
3. **`RECOMMENDATION ≠ POLICY`**: Advisory recommendations emitted by `AdaptiveRoutingAdvisor` or `PolicyRecommendationService` remain non-binding until approved and activated.
4. **`POLICY ≠ APPROVAL`**: Defining or proposing a policy does not grant human sign-off. Consequential policy changes strictly require human operator confirmation.
5. **`APPROVAL ≠ EXECUTION`**: Approving a policy transitions it to `ACTIVE`. Runtime execution of actions remains strictly governed by Stage 15 Universal Action Bus and Stage 07 Execution Gateway.

---

## 3. Strict Boundary Guarantees

| Subsystem | Stage Authority | Stage 20 Constraint |
|---|---|---|
| **AI / Inference** | Stage 07 Execution Gateway (`executionGateway.execute`) | **Zero LLM Calls**. Stage 20 contains zero LLM inference invocations. |
| **External Action** | Stage 15 Universal Action Bus (`actionBusService.execute`) | **Sole Outbound Gateway**. Policies can limit or deny, but never execute actions directly. |
| **Identity & Scope** | Stage 16 Connector Fabric (`connectorRegistry`, `connectorPermissionService`) | **Permission Authority**. A policy cannot grant a capability that Stage 16 denies. |
| **Outbound Transport** | Stage 17 Connector Activation | **Untouched**. Transports are invoked exclusively by Stage 15 Action Bus. |
| **Inbound Ingestion** | Stage 18 External Event Ingestion | **Untouched**. Ingests and validates inbound webhooks. |
| **Trigger Orchestration**| Stage 19 Reaction Engine | **Trigger Authority**. Policies govern trigger rate limits, but Stage 19 orchestrates matching. |
| **Spatial / WebGL** | Stage 03 Spatial Memory Environment | **0 Additional Draw Calls**. Policy telemetry is rendered exclusively via DOM HUD panels in `SpatialCommandConsole`. |

---

## 4. Policy Domain Contracts

The domain model is defined in `src/types/policyIntelligence.ts`:

- **`Policy`**: Complete policy contract containing identity (`id`, `version`, `name`), scope (`scope`), priority (`priority`), declarative conditions (`conditions`), effect (`effect`), provenance (`provenance`), and lifecycle status (`status`).
- **`PolicyStatus`**: Finite lifecycle states: `DRAFT`, `CANDIDATE`, `UNDER_REVIEW`, `APPROVED`, `ACTIVE`, `PAUSED`, `DEPRECATED`, `REVOKED`. Direct transition `DRAFT ➔ ACTIVE` is forbidden.
- **`PolicyScope`**: Explicit targets: `SYSTEM`, `AGENT`, `MISSION`, `TRIGGER`, `REACTION`, `RESOURCE`, `CONNECTOR`, `PROVIDER`, `WORKFLOW`. No implicit global side effects.
- **`PolicyConditionGroup`**: Declarative boolean evaluation tree supporting `AND` and `OR` conjunctions of atomic `PolicyCondition` rules.
- **`PolicyEffect`**: Pure allowlisted effects: `ALLOW`, `DENY`, `LIMIT`, `REQUIRE_APPROVAL`, `REQUIRE_REVIEW`, `PAUSE`, `DEFER`, `ROUTE`.
- **`PolicyProposal`**: Proposal container linking candidate policy, proposer identity, impact simulation, and operator review state.
- **`PolicyActivationRecord`**: Immutable audit record tracking activation timestamp, approving operator, previous version, and rationale.
- **`PolicyRollbackRecord`**: Immutable record documenting explicit rollback to a prior version configuration.
- **`PolicyShadowRecord`**: Zero-mutation evaluation trace recording what a candidate policy would have done.
- **`PolicyDriftRecord`**: Operational drift telemetry flagging `REVIEW_REQUIRED` without automatic self-mutation.

---

## 5. Verification Summary

The policy architecture was verified under `src/tests/PolicyIntelligenceStage20.test.tsx` across 60 automated tests, confirming strict adherence to all architectural invariants and security boundaries.
