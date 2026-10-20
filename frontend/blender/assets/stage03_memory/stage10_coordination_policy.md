# ARYAOS V1 — STAGE 10: MULTI-AGENT COORDINATION POLICY

## 1. Executive Summary

The Multi-Agent Coordinator (`agentCoordinator.ts`) functions as the operational dispatcher for AryaOS V1. It translates dependency-aware DAG actions into governed units of execution assigned to specialized logical workers.

The coordinator is strictly deterministic:
- **No LLM-controlled free-for-all.**
- **No arbitrary "best agent" magic numbers.**
- **Explicit constraint evaluation and deterministic scoring.**

```
       ┌────────────────────────┐
       │   DAG Action Node      │
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │  Candidate Filtering   │  (Capabilities, Availability, Concurrency)
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │ Deterministic Scoring  │  (Primary Match + Trust + Workload + History)
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │   Task Assignment      │  (AgentTask Bound to Worker)
       └───────────┬────────────┘
                   │
       ┌───────────┴────────────┐
       ▼                        ▼
┌──────────────┐         ┌──────────────┐
│ Memory Locks │         │  Lease Grant │
└──────┬───────┘         └──────┬───────┘
       │                        │
       └───────────┬────────────┘
                   ▼
       ┌────────────────────────┐
       │ Stage 07 Gateway Exec  │
       └───────────┬────────────┘
                   ▼
       ┌────────────────────────┐
       │  Quality Gate Check    │
       └───────────┬────────────┘
                   ▼
       ┌────────────────────────┐
       │ Observation Synthesis  │
       └────────────────────────┘
```

---

## 2. Deterministic Agent Selection Algorithm

When selecting a worker for an action requiring capability $C$:

### Step 1: Candidate Filtering
An agent $A$ is eligible if and only if:
1. $C \in A.\text{allowedCapabilities}$
2. $A.\text{status} \neq \text{'UNAVAILABLE'}$
3. $A.\text{currentWorkload} < A.\text{concurrencyLimit}$

If no candidates satisfy these constraints, assignment fails cleanly with `failureReason`, and the action is either queued or evaluated by the orchestrator.

### Step 2: Scoring Formula
Eligible candidates are scored deterministically:

$$\text{Score}(A) = S_{\text{primary}} + S_{\text{trust}} + S_{\text{workload}} + S_{\text{history}}$$

Where:
- $S_{\text{primary}} = 10$ if $C \in A.\text{capabilities}$ (primary role match), else $0$.
- $S_{\text{trust}} = 5$ for `AUTONOMOUS`, $3$ for `VERIFIED`, $0$ for `PROVISIONAL`.
- $S_{\text{workload}} = \text{round}\left(4 \times \left(1 - \frac{A.\text{currentWorkload}}{A.\text{concurrencyLimit}}\right)\right)$.
- $S_{\text{history}} = \text{round}\left(3 \times \frac{\text{Successes}}{\text{Successes} + \text{Failures}}\right)$.

The candidate with the highest score is selected. Ties are broken deterministically by alphabetical `agentId`.

---

## 3. Concurrency Limits & Resource Contention

The coordinator coordinates with the `ResourceGovernor`:
1. **Global Concurrency**: A goal will never execute more than `maxConcurrentActions` (default 3) simultaneous tasks.
2. **Distinct Worker Concurrency**: A goal will never deploy more than `maxConcurrentAgents` (default 4) simultaneous workers.
3. **Per-Agent Saturation**: An agent will never exceed its individual `concurrencyLimit`.

If limits are saturated:
- The task remains in `WAITING` or `BLOCKED` status.
- Once an active task finishes, leases are released and queued tasks are unblocked automatically.

---

## 4. Human Approval Escalation Boundaries

The coordinator automatically suspends task execution and triggers an approval gate when:
1. **Consequential Action**: Risk level is `CONSEQUENTIAL` or `EXTERNAL_SIDE_EFFECT` (e.g. video rendering, social publishing, destructive memory write).
2. **Low Agent Autonomy**: The assigned agent has `autonomyLevel: 'LOW'`.
3. **Budget Violation**: Estimated task cost would exceed the goal's remaining budget ceiling.
4. **Unresolvable Conflict**: Memory lock collision or contradictory outputs require operator arbitration.
5. **Quality Gate Requirement**: The task explicitly specifies `qualityRequirement: 'HUMAN_REVIEW'`.
