# AryaOS V1 — Stage 12: Adaptive Replanning Policy & Work Preservation

## 1. Objectives & Replanning Philosophy

Long-horizon missions inevitably encounter reality shifts: provider downtime, rate limits, schema changes, unexpected tool errors, or updated business requirements. 

A naive system either halts completely or restarts from scratch. AryaOS introduces **Adaptive Replanning with Strict Work Preservation**.

### Fundamental Invariant:
**Completed and verified work is immutable.**
When a replan is triggered:
- All completed goals remain marked `COMPLETED` in the new plan.
- Their generated outputs and memory vitrine records remain untouched.
- Only the unexecuted downstream subgraph is pruned, modified, or augmented.

---

## 2. Dynamic Replanning Triggers

The `missionReplanner` is deterministically invoked under five explicit conditions:

1. **Terminal Goal Failure**: A goal in the critical or non-critical path fails after exhausting all local retry attempts configured by Stage 08/09 policies.
2. **Resource Constraint Contraction**: Operator or governor reduces the mission token ceiling or concurrency allocation below the remaining plan's requirements.
3. **Milestone Schedule Breach**: Empirical task latencies indicate that a milestone deadline will be missed without path compression.
4. **External Dependency Invalidation**: An external API, tool, or credential dependency becomes unavailable.
5. **Human Operator Steering**: Operator submits an updated mission scope or prompts a structural change via the Spatial Command Console.

---

## 3. Plan Versioning & Audit Trail

Every replan produces a new, immutable `MissionExecutionPlan`:

$$P_{v} \xrightarrow{\text{replan}} P_{v+1}$$

### Plan Metadata Invariants:
- `planVersion`: Strictly monotonically increasing integer ($1, 2, 3, \dots$).
- `replanReason`: Human-readable and machine-classified trigger description.
- `supersededPlanId`: Reference to the preceding plan version.
- `preservedGoalIds`: Explicit array of completed goals carried forward without modification.
- `addedGoalIds`: Array of newly introduced alternative or corrective goals.
- `prunedGoalIds`: Array of abandoned pending goals removed from the DAG.

---

## 4. Step-by-Step Replanning Algorithm

Implemented in `missionReplanner.ts`:

```
+-----------------------------------------------------------------------------------+
| 1. Capture Pre-Replan Snapshot (Checkpoint)                                       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. Partition Existing DAG into Three Sets:                                        |
|    - C = { g in V | status(g) in {COMPLETED, SUCCEEDED} }  (IMMUTABLE)            |
|    - F = { g in V | status(g) == FAILED }                  (TARGET OF REPLAN)     |
|    - P = { g in V | status(g) in {PENDING, READY, BLOCKED} } (MUTABLE)            |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. Synthesize Alternative Subgraph:                                               |
|    - For failed goal f in F, consult Stage 11 Experience Store for alternatives.  |
|    - Generate replacement goal(s) R = {r_1, r_2, ...} with adjusted parameters.   |
|    - Connect dependencies: Pred(R) = Completed dependencies of f                  |
|    - Rewire downstream: For every p in P depending on f, replace edge (f, p)      |
|      with (r_last, p).                                                            |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. Validate Structural Invariants:                                                |
|    - Run cycle detection on new DAG: G_{v+1} = (C union R union P', E').          |
|    - Verify all dependencies resolve within G_{v+1}.                              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. Recompute Critical Path & Resource Requirements                                |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 6. Check Governance Thresholds (Approval Gating):                                 |
|    - If new plan cost delta > 20% or adds high-risk actions:                      |
|        Mission state -> WAITING_APPROVAL                                          |
|    - Else:                                                                        |
|        Mission state -> ACTIVE (Execution resumes automatically)                  |
+-----------------------------------------------------------------------------------+
```

---

## 5. Human Approval Gating

If the adaptive replan requires high-consequence operations (e.g. switching from local models to costly external providers, deleting resources, or modifying external production systems):
- The replanner sets `requiresApproval = true`.
- The mission enters `WAITING_APPROVAL`.
- The execution engine pauses until an operator explicitly clicks **Approve Replan** in the `mission-control-hud`.
