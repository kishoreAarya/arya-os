# AryaOS V1 — Stage 12: Mission Control Architecture

## 1. Overview & Operating System Model

AryaOS V1 Stage 12 introduces **Long-Horizon Mission Control & Adaptive Execution**. While previous stages established individual capabilities—goal orchestration (Stage 08), durable execution and crash recovery (Stage 09), multi-agent coordination and resource governance (Stage 10), and collective intelligence and empirical evaluation (Stage 11)—Stage 12 unifies these systems into a durable, multi-goal, mission-level operating system.

A **Mission** represents an overarching business objective that spans multiple milestones, coordinated goals, execution horizons, and runtime constraints.

```
+-----------------------------------------------------------------------------------+
|                                 ARYAOS MISSION                                    |
|   (ID, Scope, Policy, Priority, Constraints, Risk, Milestones, Checkpoints)       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                             MISSION CONTROL LAYER                                 |
|                                                                                   |
|  +--------------------+   +-----------------------+   +------------------------+  |
|  |  Dependency Graph  |   |   Critical Path &     |   | Multi-Factor Priority  |  |
|  |     (DAG Engine)   |   |   Duration Bounds     |   |       Arbitrator       |  |
|  +--------------------+   +-----------------------+   +------------------------+  |
|            |                         |                            |               |
|  +--------------------+   +-----------------------+   +------------------------+  |
|  | Deterministic Risk |   |  Checkpoint Recovery  |   |   Adaptive Replanner   |  |
|  |    Assessment      |   |  & State Reconciliation|  | (Completed Work Guard) |  |
|  +--------------------+   +-----------------------+   +------------------------+  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  Coordinates Goal IDs
+-----------------------------------------------------------------------------------+
|                  STAGE 08 / 09 / 10 / 11 UNDERLYING RUNTIMES                      |
|                                                                                   |
|   * Stage 08 Goal Orchestrator (Decomposition, Action DAG, Execution Loop)       |
|   * Stage 09 Durable Persistence Journal & Replay                                 |
|   * Stage 10 Multi-Agent Coordinator & Resource Governor                          |
|   * Stage 11 Collective Intelligence, Agent Evaluation & Experience Store         |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  Single Execution Gate
+-----------------------------------------------------------------------------------+
|               STAGE 07 EXECUTION GATEWAY (executionGateway.execute)               |
|                                         |                                         |
|                                         v                                         |
|               STAGE 06 INTELLIGENCE PROVIDER ROUTER                               |
+-----------------------------------------------------------------------------------+
```

---

## 2. Architectural Boundaries & Non-Negotiable Guarantees

1. **No Second Orchestration Engine**: Mission Control does NOT create parallel task execution mechanisms. Missions strictly coordinate Goal references (`MissionGoalReference`). Goal execution is dispatched through Stage 08 `goalOrchestrator`, which schedules tasks through Stage 10 `agentCoordinator`, governed by `resourceGovernor`, and executed through Stage 07 `executionGateway.execute()`.
2. **Provider Isolation**: Mission Control never invokes AI provider APIs directly. All provider requests flow strictly through the Stage 07 Execution Gateway.
3. **Immutability of Spatial & Visual Foundations**:
   - `stage03_aryaos_memory_environment.blend` is locked (SHA256: `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`).
   - 14 Stage 03 GLB assets are immutable.
   - `STAGE03_CAMERAS` remain unmodified.
   - Zero additional WebGL draw calls; HUD rendered via clean DOM overlays.
4. **Preservation of Completed Work**: Replanning, recovery, or rescheduling never overwrites or re-executes goals marked `COMPLETED` or `SUCCEEDED`.
5. **Truthful Duration Estimates**: Unmeasured or unbounded durations are explicitly labeled `'UNKNOWN'` rather than displaying hallucinated or guessed estimates.

---

## 3. Core Lifecycle State Machine

A Mission moves deterministically through validated states:

```
[DRAFT] ---> [PLANNED] ---> [ACTIVE] <---> [PAUSED]
                |              |
                |              +---------> [WAITING_APPROVAL]
                |              |                  |
                |              +---------> [RECOVERY_REQUIRED]
                |              |                  |
                |              +---------> [REPLANNING]
                |              |
                v              v
           [CANCELLED]    [COMPLETED] / [FAILED]
```

- **DRAFT**: Mission definition assembled; milestones and dependencies defined.
- **PLANNED**: Valid DAG generated, critical path computed, initial resource envelope validated.
- **ACTIVE**: Goals dispatched in topological frontier order according to priority and governance.
- **PAUSED**: Execution temporarily suspended; in-flight tasks drain or yield safely at checkpoints.
- **WAITING_APPROVAL**: A milestone or policy constraint mandates human operator review.
- **RECOVERY_REQUIRED**: System crash or network fault detected; state reconciliation required.
- **REPLANNING**: A goal failed or constraints shifted; replanner generates plan version $N+1$ while preserving completed goals.
- **COMPLETED**: All terminal milestones and completion criteria satisfied.
- **FAILED**: Unrecoverable failure or budget breach occurred without viable replan path.
- **CANCELLED**: Operator requested termination.

---

## 4. Subsystem Interactions

### A. Stage 08 Integration
- Mission Control registers Goal IDs with `goalOrchestrator`.
- Listens to goal lifecycle events (`PENDING` -> `RUNNING` -> `SUCCEEDED` / `FAILED`).
- Dynamically resolves dependent goals when upstream milestones succeed.

### B. Stage 09 Integration
- Mission definitions, execution plans, and milestones persist in `executionPersistence`.
- Checkpoints capture exact mission state vector $(M, P_v, G_{states}, R_{usage}, t)$.
- On boot, `missionCheckpointService` inspects persistent storage to recover active missions.

### C. Stage 10 Integration
- Cross-mission resource arbitration delegates concurrency, tokens, and rate limits to `resourceGovernor`.
- Active missions negotiate token budgets without exceeding system-wide hard caps.

### D. Stage 11 Integration
- Mission risk assessment and prioritization query Stage 11 `agentEvaluationService` and `experienceStore` for agent failure rates and empirical task latencies.

### E. Spatial HUD Console
- `SpatialCommandConsole` renders `mission-control-hud` and `mission-timeline-hud`.
- Displays real-time mission status, critical path highlights, milestone completion bars, and live risk alerts.
