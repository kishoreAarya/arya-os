# AryaOS V1 — Stage 13: Strategic Pattern Detection & Anti-Overfitting Engine

## 1. Objectives & Behavioral Invariants

Operating systems accumulate patterns through repetitive execution. A system that overfits to single isolated anomalies risks producing premature generalizations or ungrounded policy penalties.

### Core Invariant:
> **Strict Anti-Overfitting Threshold**: A recurring operational trend must be corroborated by at least two (and for high-impact patterns, three or four) distinct, validated execution runs before promotion to a formal `KnowledgePattern`.

---

## 2. Strategic Pattern Taxonomy

| Pattern Type | Detection Criteria | Operational Meaning | Suggested System Action |
| :--- | :--- | :--- | :--- |
| `REPEATED_FAILURE` | $\ge 2$ task failures for same `(agent, taskType)` | Persistent capability gap or prompt degradation | Route task to alternate agent or alert operator |
| `AGENT_SPECIALIZATION` | $\ge 2$ consecutive high-quality successes | Proven mastery for domain/capability | Prefer agent in automated task scheduling |
| `PROVIDER_SPECIALIZATION` | $\ge 3$ tasks with lowest latency / cost | Provider optimal for specific modality | Bias provider routing during DAG generation |
| `RESOURCE_BOTTLENECK` | $\ge 2$ rate-limit or concurrency stalls | Chronic resource contention on model/service | Increase backoff or allocate dedicated quota |
| `QUALITY_BOTTLENECK` | $\ge 2$ quality gate failures on milestone | Pipeline stage consistently below threshold | Inject human review step or adjust prompts |
| `DEADLINE_PATTERN` | $\ge 2$ goals exceeding initial duration by $>50\%$ | Systemic time underestimation | Adjust CPM lower bounds to `'UNKNOWN'` |
| `RECURRING_CONFLICT` | $\ge 2$ collisions between same two agents | Parallel lease collisions on shared state | Stagger milestones or enforce strict queue |
| `RECURRING_REPLAN` | $\ge 2$ missions requiring multiple replans | Upstream execution plan instability | Insert intermediate verification checkpoints |

---

## 3. Mathematical Detection Model

Implemented in `strategicPatternService.ts`:

### A. Failure Clustering
Let $\mathcal{E}$ be the set of Stage 11 experience records. For every agent $a$ and task type $\tau$:

$$N_{\text{fail}}(a, \tau) = \sum_{e \in \mathcal{E}} \mathbb{I}(e.agentId = a \land e.taskType = \tau \land \neg e.success)$$

$$\text{Trigger Condition}: N_{\text{fail}}(a, \tau) \ge 2 \implies \text{Emit } \text{REPEATED\_FAILURE}(a, \tau)$$

$$\text{Confidence}: \begin{cases} \text{MEDIUM} & \text{if } 2 \le N_{\text{fail}} < 4 \\ \text{HIGH} & \text{if } N_{\text{fail}} \ge 4 \end{cases}$$

### B. Specialization Clustering
$$N_{\text{succ}}(a, \tau) = \sum_{e \in \mathcal{E}} \mathbb{I}(e.agentId = a \land e.taskType = \tau \land e.success \land e.quality \ge 0.85)$$

$$\text{Trigger Condition}: N_{\text{succ}}(a, \tau) \ge 2 \implies \text{Emit } \text{AGENT\_SPECIALIZATION}(a, \tau)$$

### C. Agent Contention Clustering
Let $\mathcal{C}$ be the set of Stage 10 resource conflict events. For each unique agent pair $(a_i, a_j)$:

$$N_{\text{conflict}}(a_i, a_j) = \sum_{c \in \mathcal{C}} \mathbb{I}(\{a_i, a_j\} \subseteq c.contendingAgentIds)$$

$$\text{Trigger Condition}: N_{\text{conflict}}(a_i, a_j) \ge 2 \implies \text{Emit } \text{RECURRING\_CONFLICT}(a_i, a_j)$$

---

## 4. Human Governance & Pattern Elevation

Patterns are purely **observational and advisory**:
- A pattern never autonomously executes code or alters user permissions.
- When a pattern suggests routing adjustments, it provides explainable evidence references to the operator.
- Consequential adjustments (e.g. permanently blacklisting an agent or altering token limits) require operator confirmation.
