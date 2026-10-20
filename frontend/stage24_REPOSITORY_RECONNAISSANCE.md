# AryaOS V1 Stage 24 — Repository Reconnaissance & Architecture Integration Audit
## Mission Operations Control Plane (Stage 24: Phase 0)

**Date**: October 3, 2026  
**Status**: PHASE 0 RECONNAISSANCE COMPLETE — PENDING ARCHITECTURAL APPROVAL  
**Baseline Verified**:
- 1,515 / 1,515 Tests Passing (100%)
- 45 / 45 Test Suites Passing
- Stage 23: 392 / 392 Tests Passing
- TypeScript: 0 Errors (`npx tsc --noEmit`)
- Production Build: PASS (10.89s)
- External Network Calls: 0 (No Axios, no raw sockets)
- LLM Tokens: 0
- Master Stage 03 Blender SHA256: `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`
- Stage 03 GLBs: 28 / 28 Intact
- WebGL Baseline: 53–54 Draw Calls, 86,842 Triangles

---

## 1. Executive Summary & Stage 24 Mandate

Stage 24 establishes the **Mission Operations Control Plane** of AryaOS V1. Its core objective is to unify the existing intelligence, mission, policy, governance, execution, operational-truth, recovery, persistence, and learning systems into **ONE coherent, operator-facing control surface**.

### Fundamental Architectural Axiom
AryaOS already possesses the requisite authorities:
- **WHAT should happen** $\to$ Goal / Intent / Planning (Stages 08, 10, 12)
- **WHY it should happen** $\to$ Mission / Decision Intelligence (Stages 12, 14)
- **WHAT is permitted** $\to$ Policy Intelligence (Stage 20)
- **WHETHER an action is authorized** $\to$ Governance Control Plane (Stage 21)
- **HOW it executes** $\to$ Action Bus & Execution Gateway (Stages 15, 07)
- **WHAT actually happened** $\to$ Operational Truth & Causal Audit (Stage 22)
- **WHAT to do when something fails** $\to$ Recovery Control Plane (Stage 23)
- **WHAT was learned** $\to$ Memory / Knowledge / Learning (Stages 11, 13)

**Strict Mandate**: Stage 24 is an **INTEGRATION / PROJECTION LAYER** over existing authoritative subsystems. It coordinates **VIEW + REQUEST + OBSERVE**. It **MUST NOT** create secondary engines, duplicate authority, bypass governance, or perform direct execution.

---

## 2. Inventory of Existing Control Surfaces & Architecture

### 2.1 Existing Backend Authority & Execution Fabric
1. **Stage 08 (Autonomous Task Orchestration)**:
   - `GoalOrchestrator` (`src/services/goalOrchestrator.ts`): Creates, parses, schedules, and monitors autonomous goals and ActionNode DAGs.
   - `goalInterpreter.ts`, `planGenerator.ts`, `planEvaluationService.ts`.
2. **Stage 09 (Persistence, Journaling & Crash Recovery)**:
   - `ExecutionPersistence` (`src/services/executionPersistence.ts`): Zero-secret persistence for goals, DAGs, missions, decisions, policies, governance decisions, recovery decisions, and audit events.
   - `ExecutionJournal` (`src/services/executionJournal.ts`): Append-only CRC32/SHA256 verified audit journal.
   - `RecoveryManager` (`src/services/recoveryManager.ts`): Boot-time goal/DAG frontier recovery.
3. **Stage 10 (Multi-Agent Coordination & Resource Governance)**:
   - `AgentCoordinator` (`src/services/agentCoordinator.ts`): Agent lifecycle, task assignment, conflict resolution (`agentConflictManager.ts`), and resource budgeting (`resourceGovernor.ts`).
4. **Stage 11 (Evaluation & Learning)**:
   - `AgentEvaluationService` (`src/services/agentEvaluationService.ts`): Evaluates task outcomes and generates experience records and learning signals (`learningSignalService.ts`).
5. **Stage 12 (Mission Control)**:
   - `MissionManager` (`src/services/missionManager.ts`): Coordinates multi-goal missions, dependencies (`missionDependencyGraph.ts`), plan versioning (`missionPlanner.ts`, `missionReplanner.ts`), checkpoints (`missionCheckpoint.ts`), observations (`missionObservationService.ts`), and risk evaluation (`missionRiskService.ts`).
6. **Stage 13 (Strategic Knowledge Graph)**:
   - `KnowledgeGraph` (`src/services/knowledgeGraph.ts`): Vector-adjacent factual, pattern, and strategy graph with contradiction detection (`knowledgeContradictionService.ts`).
7. **Stage 14 (Decision Intelligence)**:
   - `DecisionIntelligenceService` (`src/services/decisionIntelligenceService.ts`): Multi-option evaluation, trade-off analysis (`tradeoffEngine.ts`), pre-mortems (`premortemService.ts`), and consequence simulation (`consequenceSimulator.ts`).
8. **Stage 15 (Universal Action Bus)**:
   - `ActionBusService` (`src/services/actionBusService.ts`): Sole external capability execution boundary; action proposal, authorization check (`actionAuthorizationService.ts`), and normalization (`actionResultNormalizer.ts`).
9. **Stage 16 & 17 (Connector Fabric & Real Activation)**:
   - `ConnectorRegistry` (`src/services/connectorRegistry.ts`): Manages connector registration, permissions (`connectorPermissionService.ts`), lifecycle, and OAuth boundaries (`oauthBoundary.ts`).
   - Adapters: `githubConnectorAdapter.ts`, `googleDriveConnectorAdapter.ts`.
10. **Stage 18 & 19 (External Event Ingestion & Reaction Engine)**:
    - `EventIngressService` (`src/services/eventIngressService.ts`): Sanitizes, validates, and ingests external webhook events.
    - `ReactionExecutionEngine` (`src/services/reactionExecutionEngine.ts`): Evaluates triggers (`triggerRegistry.ts`, `triggerConditionEngine.ts`) and proposes governed reactions.
11. **Stage 20 (Policy Intelligence)**:
    - `PolicyRegistry` (`src/services/policyRegistry.ts`): Declarative AST policy management, simulation, conflict resolution (`policyConflictService.ts`), shadow mode (`policyShadowService.ts`), and drift monitoring (`policyDriftService.ts`).
12. **Stage 21 (Governed Policy Control Plane)**:
    - `GovernanceControlPlane` (`src/services/governanceControlPlane.ts`): 5-tier fail-closed authority intersection ($\text{Policy} \cap \text{Connector} \cap \text{ActionBus} \cap \text{Human} \cap \text{Mission}$), staleness verification (`governanceStalenessService.ts`), and operator token validation.
13. **Stage 22 (Operational Truth & Causal Audit)**:
    - `OperationalTruthService` (`src/services/operationalTruthService.ts`): Separates intent from observed truth. Enforces $\text{REQUESTED} \neq \text{PLANNED} \neq \text{AUTHORIZED} \neq \text{DISPATCHED} \neq \text{EXECUTED} \neq \text{OBSERVED} \neq \text{RECONCILED}$ and $\text{UNKNOWN} \neq \text{SUCCESS}$.
    - `CausalTraceService` (`src/services/causalTraceService.ts`): Constructs bounded causal DAGs linking operations, triggers, policies, governance decisions, and results (`MAX_CAUSAL_DEPTH = 10`, `MAX_CAUSAL_NODES = 100`).
    - `AuditEventRegistry` (`src/services/auditEventRegistry.ts`): Immutable audit event store.
14. **Stage 23 (Governed Recovery Control Plane)**:
    - `RecoveryControlPlane` (`src/services/recoveryControlPlane.ts`): Central recovery decision surface coordinating classification (`failureClassificationService.ts`), safety (`recoverySafetyService.ts`), planning (`recoveryPlanService.ts`), reconciliation (`recoveryReconciliationService.ts`), compensation (`recoveryCompensationService.ts`), and cascade protection (`recoveryCascadeService.ts`).

---

## 3. Existing Frontend Control Surfaces & Presentation Layers

### 3.1 Top Navigation & Root Views (`src/components/navigation/AppNav.tsx`, `src/App.tsx`)
The frontend currently routes between 6 top-level views via `AppView`:
- `'spatial'`: `SpatialWorld.tsx` — 3D memory environment with DOM overlay controls.
- `'creator'`: Creator Studio — Generation forms, presets, frame controls.
- `'pipelines'`: `PipelinesView.tsx` — Workflow runs, execution stages, and lineage.
- `'research'`: `ResearchView.tsx` — Trend research and content intelligence.
- `'publishing'`: `PublishingView.tsx` — Multi-channel distribution and scheduling.
- `'learning'`: `LearningView.tsx` — Feedback loops and model evaluation.

### 3.2 Spatial Command Deck & Overlays
- **`SpatialWorld.tsx`**: Renders the 3D scene (Three.js canvas) with Stage 03 GLBs, camera rig, and post-processing.
- **`MemoryArchiveOverlay.tsx`**: Houses the modal/docked console system over the 3D scene.
- **`SpatialCommandConsole.tsx`**: The primary operational DOM console (1,900+ lines). It currently hosts telemetry panels and mini-HUDs for Stages 05, 07, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, and 23.
- **`RecoveryControlHUD.tsx`**: Pure DOM telemetry component rendering Stage 23 recovery decisions, epistemic status, and safety bounds.

### 3.3 Existing Frontend APIs (`src/api/`)
- `creatorApi.ts`: Generation submissions, history, capabilities.
- `dashboardApi.ts`: Workflow runs (`fetchWorkflowRuns`), lineage (`fetchLineage`), pending approvals (`fetchPendingApprovals`), and decisions (`decideApproval`).
- `productionApi.ts`: Project trees, shots, jobs, remote sync status.

---

## 4. Reusable Services for Stage 24 Control Plane

Stage 24 can directly project state from these active singletons without instantiating new engines:

| Control Plane Domain | Authoritative Reusable Service | Method / Query Source |
|---|---|---|
| **Mission State** | `missionManager` & `executionPersistence` | `missionManager.listMissions()`, `missionManager.getMission(id)`, `executionPersistence.getMissions()` |
| **Operation State & DAGs** | `executionPersistence` & `operationalTruthService` | `executionPersistence.getGoals()`, `operationalTruthService.isObservedState()`, `operationalTruthService.reconcileOperationalTruth()` |
| **Governance & Policies** | `governanceControlPlane` & `policyRegistry` | `governanceControlPlane.evaluateGovernance()`, `policyRegistry.getActivePolicies()`, `executionPersistence.getGovernanceDecisions()` |
| **Pending Approvals** | `executionPersistence` & `governanceControlPlane` | `executionPersistence.getApprovals()`, `governanceControlPlane.getEvaluatedDecisions()` |
| **Recovery Proposals** | `recoveryControlPlane` & `recoveryControlPersistenceService` | `recoveryControlPlane.getActiveDecisions()`, `recoveryControlPersistenceService.loadRecoveryState()` |
| **Operational Truth & Audit** | `operationalTruthService` & `auditEventRegistry` | `auditEventRegistry.getEvents()`, `auditEventRegistry.getEventsByOperationId()` |
| **Causal Lineage Graphs** | `causalTraceService` | `causalTraceService.buildCausalGraph(operationId)` |
| **System Telemetry & Health** | `executionPersistence` | `executionPersistence.getTelemetry()`, `executionPersistence.isDurableStorageActive()` |

---

## 5. Duplicate-Risk Analysis & Hard Boundaries

| System Function | Risk of Duplication | Anti-Duplication Enforcement for Stage 24 |
|---|---|---|
| **Execution Dispatch** | Creating a second runner in UI | Stage 24 has **ZERO** execution dispatch logic; UI buttons only submit requests to existing backend services (`actionBusService`, `executionGateway`). |
| **Governance Evaluation**| Evaluating policies in React | All governance evaluation remains inside `governanceControlPlane.evaluateGovernance()`; UI only renders the returned decision. |
| **Human Approvals** | Approving locally without token | UI displays pending approvals, but approval submission must construct an authentic `OperatorApprovalToken` signed by a human operator and verified by Stage 21. |
| **Recovery Planning** | Retrying or compensating from UI | UI cannot trigger raw retries or compensations; it presents Stage 23 recovery proposals and routes decisions strictly through `recoveryControlPlane`. |
| **Mission Management** | Second mission planner | Missions are queried strictly from `missionManager` / `executionPersistence`; no new planning engine. |
| **Causal Graph Building**| Generating custom DAGs | Causal traces must be generated exclusively by `causalTraceService.buildCausalGraph()`. |
| **Epistemic Honesty** | Inferring success from dispatch | If an operation has dispatched but has no external confirmation, Stage 24 MUST project `UNKNOWN` (epistemic `UNKNOWN`); synthetic `SUCCESS` is prohibited. |

---

## 6. Proposed Stage 24 Integration Architecture

To fulfill the Stage 24 mandate without bloat or duplication, the proposed architecture consists of:

```
                                  OPERATOR (HUMAN)
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     STAGE 24: COMMAND DECK (DOM)      │
                     │  (Observational Multi-Panel Console)  │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │      controlPlaneSnapshotService      │
                     │  (Deterministic Read/Projection Façade)│
                     └───────────────────┬───────────────────┘
                                         │
     ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
     ▼                   ▼                               ▼                   ▼
┌──────────────┐  ┌──────────────┐                ┌──────────────┐   ┌──────────────┐
│   Stage 12   │  │ Stage 20/21  │                │   Stage 22   │   │   Stage 23   │
│MissionManager│  │  Governance  │                │Operational   │   │   Recovery   │
│              │  │Control Plane │                │    Truth     │   │Control Plane │
└──────────────┘  └──────────────┘                └──────────────┘   └──────────────┘
```

### Proposed New & Modified Components:
1. **`src/types/controlPlane.ts`**: Pure read-oriented projection types (`MissionSummary`, `OperationSummary`, `OperationTimeline`, `GovernanceSummary`, `ApprovalSummary`, `RecoverySummary`, `CausalTraceSummary`, `SystemHealthSummary`, `ControlPlaneSnapshot`).
2. **`src/services/controlPlaneSnapshotService.ts`**: Unified read/projection service querying existing services (`missionManager`, `governanceControlPlane`, `operationalTruthService`, `recoveryControlPlane`, `causalTraceService`, `executionPersistence`).
3. **`src/components/spatial/MissionOperationsControlDeck.tsx`**: Operator-facing pure DOM Command Deck component supporting tabbed operational panels:
   - `MISSIONS`: Multi-goal mission status, progress, checkpoints, risk.
   - `OPERATIONS`: Unified operation timeline preserving the 16 canonical states.
   - `APPROVALS`: Human approval queue with risk context, policy snapshot, and expiration.
   - `RECOVERY`: Stage 23 recovery proposals, failure classifications, and safety bounds.
   - `GOVERNANCE`: Policy snapshot inspector and 5-tier authority intersection explainer.
   - `CAUSAL TRACE`: Stage 22 causal graph projection with depth/node bounds.
   - `SYSTEM HEALTH`: Honest multi-subsystem observational health telemetry.
4. **Integration Mounts**:
   - Primary: Integrated into `SpatialCommandConsole.tsx` (as a dedicated Command Deck section/tab, maintaining 0 Three.js overhead).
   - Secondary / Alternative: Registered in `AppNav.tsx` or `App.tsx` as a dedicated operational view if needed, preserving existing view flows.
5. **`src/tests/MissionOperationsControlStage24.test.tsx`**: Exhaustive test suite covering all 25 adversarial and functional requirements specified in Phase 13.

---

## 7. File Classification: Permitted vs. Strictly Prohibited Changes

### 7.1 Files That MUST NOT Be Modified (Strict Freeze)
- `blender/stage03_aryaos_memory_environment.blend` / `blender/stage03_memory_v2.blend` (Master SHA256 `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`)
- `public/assets/stage03_memory/*.glb` (All 28 GLB visual assets)
- `src/stage03_assembly.ts`, `src/stage03_reflections.ts`, `src/stage03_validation.ts`
- Three.js camera rigs (`SpatialCameraRig.tsx`, camera FOVs, camera positions)
- Existing Stage 23 test file: `src/tests/RecoveryControlStage23.test.tsx` (392 tests must remain completely unmodified)
- All existing 44 other test suite files in `src/tests/` (Must not be modified or weakened)
- Backend authoritative services: `executionGateway.ts`, `actionBusService.ts`, `governanceControlPlane.ts`, `policyRegistry.ts`, `operationalTruthService.ts`, `recoveryControlPlane.ts`, `executionPersistence.ts`

### 7.2 Files That MAY Be Created / Modified (Stage 24 Scope)
- **Created**:
  - `src/types/controlPlane.ts` (Stage 24 projection contracts)
  - `src/services/controlPlaneSnapshotService.ts` (Projection aggregator)
  - `src/components/spatial/MissionOperationsControlDeck.tsx` (Pure DOM operational deck)
  - `src/tests/MissionOperationsControlStage24.test.tsx` (Dedicated Stage 24 tests)
  - Documentation artifacts in `blender/assets/stage03_memory/`
- **Modified (Minimal surgical integration only)**:
  - `src/components/spatial/SpatialCommandConsole.tsx` (Mounting the Stage 24 Control Deck in pure DOM without adding WebGL calls)
  - `src/types/dashboard.ts` & `src/components/navigation/AppNav.tsx` / `src/App.tsx` (Only if exposing an operator view tab)

---

## 8. Hard Stop Attestation & Readiness

In accordance with the Stage 24 specification:
- Phase 0 reconnaissance is complete.
- **Zero code changes have been executed.**
- All 1,515 baseline tests remain green across 45 suites.
- Architecture and boundary definitions are locked.
- We **STOP HERE** and await explicit architectural approval before beginning Phase 1.
