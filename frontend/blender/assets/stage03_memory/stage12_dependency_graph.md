# AryaOS V1 — Stage 12: Mission Dependency Graph & Critical Path Analysis

## 1. Mathematical DAG Model

A Mission execution plan is formalized as a finite Directed Acyclic Graph:

$$G = (V, E)$$

Where:
- $V = \{g_1, g_2, \dots, g_n\}$ is the set of vertices representing atomic Goal References (`MissionGoalReference`).
- $E \subseteq V \times V$ is the set of directed edges $(g_i, g_j)$ indicating that goal $g_j$ depends on the completion of goal $g_i$ ($g_i \to g_j$).

### Attributes per Vertex $g_i \in V$:
- $\text{status}(g_i) \in \{\text{PENDING}, \text{READY}, \text{RUNNING}, \text{COMPLETED}, \text{FAILED}, \text{BLOCKED}, \text{SKIPPED}\}$
- $\text{milestone}(g_i) \in \text{String}$ (Milestone ID)
- $\text{duration}(g_i) \in \mathbb{R}^+ \cup \{\text{UNKNOWN}\}$ (Empirical or upper-bound expected duration in milliseconds)
- $\text{priority}(g_i) \in [0, 100]$

---

## 2. Structural Graph Validation

Prior to plan execution or replanning, $G$ must satisfy strict structural invariants implemented in `missionDependencyGraph.ts`:

### A. Cycle Detection
Any directed cycle $C = (g_{k_1}, g_{k_2}, \dots, g_{k_m}, g_{k_1})$ represents an illegal deadlock.
- **Algorithm**: Depth-First Search with 3-color node labeling:
  - `WHITE` (Unvisited)
  - `GRAY` (Currently in recursion stack)
  - `BLACK` (Fully explored)
- If an edge $(u, v)$ targets a `GRAY` vertex, a cycle is identified.
- **Cycle Path Reporting**: The exact directed cycle path $[g_{k_1}, g_{k_2}, \dots, g_{k_m}, g_{k_1}]$ is reported in the diagnostic output.

### B. Missing Dependency Detection
Every dependency reference $d \in \text{dependencies}(g_j)$ must correspond to a valid $g_i \in V$. If $d \notin V$, the graph fails validation with `MissingDependencyError`.

### C. Self-Dependency Prohibition
An edge $(g_i, g_i)$ is strictly invalid and flagged immediately.

---

## 3. Topological Layering & Milestone Grouping

Valid DAGs are partitioned into topological layers:

$$L_0, L_1, L_2, \dots, L_k$$

Where:
- $L_0 = \{g \in V \mid \text{in-degree}(g) = 0\}$
- $L_m = \{g \in V \setminus \bigcup_{j < m} L_j \mid \forall (u, g) \in E, u \in \bigcup_{j < m} L_j\}$

Milestones group vertices logically. A Milestone $M_k$ is complete if and only if:

$$\forall g \in V \text{ where } \text{milestone}(g) = M_k \implies \text{status}(g) \in \{\text{COMPLETED}, \text{SKIPPED}\}$$

---

## 4. Critical Path Method (CPM) & Slack Analysis

Critical path computation determines the sequence of dependent goals that dictates the minimum theoretical duration of the mission.

### A. Forward Pass (Earliest Times)
For each node $g_j$ in topological order:

$$ES(g_j) = \begin{cases} 0 & \text{if } \text{Pred}(g_j) = \emptyset \\ \max_{g_i \in \text{Pred}(g_j)} EF(g_i) & \text{otherwise} \end{cases}$$

$$EF(g_j) = ES(g_j) + \text{duration}(g_j)$$

### B. Backward Pass (Latest Times)
Let $T = \max_{g \in V} EF(g)$. For each node $g_i$ in reverse topological order:

$$LF(g_i) = \begin{cases} T & \text{if } \text{Succ}(g_i) = \emptyset \\ \min_{g_j \in \text{Succ}(g_i)} LS(g_j) & \text{otherwise} \end{cases}$$

$$LS(g_i) = LF(g_i) - \text{duration}(g_i)$$

### C. Slack / Float Computation
$$\text{Slack}(g_i) = LS(g_i) - ES(g_i) = LF(g_i) - EF(g_i)$$

- **Critical Path Definition**: The set of nodes where $\text{Slack}(g_i) = 0$.
- Goals on the critical path are granted elevated scheduling priority (+15 score boost in `missionPriority.ts`).

---

## 5. Truthful Duration Estimates & Unbounded Time Handling

AryaOS strictly enforces honesty in execution planning:
- When a goal lacks empirical benchmark data from Stage 11 `experienceStore` and has no explicit timeout constraint, its duration is recorded as `'UNKNOWN'`.
- If any node on a path has duration `'UNKNOWN'`, the path duration is reported as `'UNKNOWN'`, with the explicit known lower bound $\sum_{g \in \text{known}} \text{duration}(g)$ documented in metadata.
- No artificial or hallucinated durations are inserted.

---

## 6. Dynamic Executable Frontier

At any instant $t$, the executable frontier $\mathcal{F}(t)$ represents all unblocked goals ready for dispatch:

$$\mathcal{F}(t) = \{g \in V \mid \text{status}(g) = \text{PENDING} \land \forall (u, g) \in E, \text{status}(u) = \text{COMPLETED}\}$$

The `missionManager` queries $\mathcal{F}(t)$ and passes ready goals to `missionResourceArbitrator` for prioritized scheduling.
