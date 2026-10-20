# AryaOS V1 — Stage 12: Cross-Mission Resource Arbitration & Multi-Factor Priority

## 1. Resource Governance Model & Contention Invariants

In an autonomous multi-mission operating environment, multiple long-horizon missions compete for finite execution resources:
- Concurrent active provider execution slots.
- Global token consumption ceilings (daily and per-minute).
- Rate limits per intelligence provider (requests per second / minute).
- Local agent memory and context buffer quotas.

### Strict Governance Invariant:
**No mission may bypass Stage 10 `resourceGovernor` or Stage 07 `executionGateway`.**
Mission Control does not allocate physical execution slots directly; instead, `missionResourceArbitrator` evaluates contending mission goals, assigns deterministic priority weights, and negotiates allocations with `resourceGovernor`.

---

## 2. Multi-Factor Priority Scoring Engine

The priority of a goal $g$ within a mission $M$ is computed transparently in `missionPriority.ts` using a multi-factor linear evaluation function:

$$S(g, M) = \text{clamp}_{[0, 100]}\Big( w_{\text{base}} P_{\text{base}}(M) + w_{\text{crit}} B_{\text{crit}}(g) + w_{\text{urg}} U_{\text{mile}}(g) + w_{\text{rel}} R_{\text{rel}}(g) + w_{\text{cost}} C_{\text{eff}}(g) \Big)$$

### Factor Breakdown:

1. **Base Mission Priority ($P_{\text{base}}$)**:
   - `CRITICAL`: 100
   - `HIGH`: 75
   - `MEDIUM`: 50
   - `LOW`: 25
   - Weight: $w_{\text{base}} = 0.40$

2. **Critical Path Bonus ($B_{\text{crit}}$)**:
   - If $g \in \text{CriticalPath}(M)$, $B_{\text{crit}} = 15$
   - Else, $B_{\text{crit}} = 0$
   - Weight: $w_{\text{crit}} = 1.0$ (direct additive boost)

3. **Milestone Urgency ($U_{\text{mile}}$)**:
   - Measures deadline proximity or downstream dependent milestones.
   - Range: $[0, 20]$
   - Weight: $w_{\text{urg}} = 0.20$

4. **Historical Reliability ($R_{\text{rel}}$)**:
   - Queried from Stage 11 `agentEvaluationService` and `experienceStore`.
   - If historical failure rate for this goal type $< 5\%$, bonus $+5$.
   - If historical failure rate $> 25\%$, penalty $-10$.

5. **Cost Efficiency ($C_{\text{eff}}$)**:
   - Prioritizes lightweight tasks when token budgets are constrained.
   - Range: $[-5, +5]$

---

## 3. Contention Detection & Deterministic Arbitration

When total requested concurrency across active missions exceeds the system limit $C_{\max}$ (or token demand exceeds $T_{\text{avail}}$):

1. **Frontier Aggregation**: Collect all ready goals $\bigcup_{M} \mathcal{F}_M(t)$.
2. **Deterministic Ranking**: Sort goals descending by score:
   $$\text{Rank}(g_i) > \text{Rank}(g_j) \iff S(g_i) > S(g_j) \lor (S(g_i) = S(g_j) \land t_{\text{ready}}(g_i) < t_{\text{ready}}(g_j))$$
   Ties are broken deterministically by earliest submission timestamp.
3. **Quota Allocation**: Dispatch goals up to available capacity.
4. **Audit Trail**: Every arbitration cycle generates an immutable `ResourceAllocationDecision` recording:
   - Contending goal IDs and parent missions.
   - Exact numerical scores and component factor breakdowns.
   - Outcome (`GRANTED`, `QUEUED`, `YIELDED`, `REJECTED`).
   - Justification string for full operator transparency.

---

## 4. Preemption & Cooperative Yielding Policy

AryaOS strictly forbids destructive preemption. If a `CRITICAL` mission arrives while capacity is fully occupied by `MEDIUM` or `LOW` tasks:

1. **No In-Flight Task Destruction**: Running tasks are never killed mid-call. This prevents token waste, corrupted state, and partial API side effects.
2. **Cooperative Yielding at Checkpoints**: The executing goal is allowed to reach its nearest atomic checkpoint or task boundary.
3. **Safe State Reconciliation**:
   - The yielding goal's current progress is captured in a `MissionCheckpoint`.
   - State transitions to `PAUSED` or `PENDING` (frontier).
   - Execution capacity is granted to the higher-priority mission goal.
