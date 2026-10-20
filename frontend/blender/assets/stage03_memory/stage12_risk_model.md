# AryaOS V1 — Stage 12: Mission Quantitative Risk Model

## 1. Objectives & Risk Framework

Autonomous mission execution requires continuous, deterministic risk evaluation to protect against budget overruns, deadlocks, cascading failures, and timeline degradation.

The `missionRiskService` evaluates every active and planned mission against an empirical multi-factor risk model. Rather than relying on subjective heuristics, risk is computed mathematically from observable graph properties, resource telemetry, and Stage 11 historical evaluations.

---

## 2. Risk Taxonomy & Categorization

AryaOS identifies five canonical risk categories (`MissionRiskCategory`):

| Category | Indicator | Trigger Condition |
| :--- | :--- | :--- |
| `DEPENDENCY_CHAIN` | Graph topology & critical path depth | Critical path length $> 6$ or single-point-of-failure bottleneck node |
| `RESOURCE_STARVATION` | Token & concurrency burn rates | Mission tokens consumed $> 80\%$ of budget or concurrency blocked $> 3$ cycles |
| `GOAL_FAILURE_RATE` | Empirical execution outcomes | Failed goals $> 15\%$ of attempted goals or Stage 11 historical failure rate $> 20\%$ |
| `DEADLINE_BREACH` | Projected timeline vs. constraints | Earliest finish time ($EF_{\text{terminal}}$) $> 90\%$ of `maxDurationMs` |
| `APPROVAL_BLOCKED` | Latency in human review | Mission in `WAITING_APPROVAL` exceeding 3600 seconds without action |

---

## 3. Mathematical Risk Scoring Formula

For each risk category $c \in \mathcal{C}$, a normalized risk component score $r_c \in [0, 100]$ is computed:

### A. Dependency Chain Risk ($r_{\text{dep}}$)
$$r_{\text{dep}} = \min\left(100, \frac{|\text{CriticalPath}|}{L_{\max}} \times 60 + N_{\text{bottlenecks}} \times 20\right)$$
where $L_{\max} = 10$ and $N_{\text{bottlenecks}}$ is the count of nodes whose removal disconnects the remaining graph.

### B. Resource Starvation Risk ($r_{\text{res}}$)
$$r_{\text{res}} = \begin{cases} 
0 & \text{if } U_{\text{tokens}} \le 0.50 \\
\left(\frac{U_{\text{tokens}} - 0.50}{0.50}\right) \times 100 & \text{if } U_{\text{tokens}} > 0.50
\end{cases}$$
where $U_{\text{tokens}} = \frac{\text{tokensConsumed}}{\text{tokenBudget}}$.

### C. Goal Failure Risk ($r_{\text{fail}}$)
$$r_{\text{fail}} = \min\left(100, \left( \frac{N_{\text{failed}}}{N_{\text{attempted}} + 1} \times 0.70 + H_{\text{fail\_rate}} \times 0.30 \right) \times 100 \right)$$
where $H_{\text{fail\_rate}}$ is the empirical failure rate from Stage 11 `agentEvaluationService`.

### D. Deadline Breach Risk ($r_{\text{dead}}$)
$$r_{\text{dead}} = \begin{cases}
0 & \text{if duration is UNKNOWN or unbounded} \\
\min\left(100, \frac{\text{ProjectedDuration}}{\text{MaxDurationMs}} \times 100\right) & \text{otherwise}
\end{cases}$$

### Composite Mission Risk ($R_{\text{mission}}$):
$$R_{\text{mission}} = \max_{c \in \mathcal{C}} r_c \times 0.60 + \left( \frac{1}{|\mathcal{C}|} \sum_{c \in \mathcal{C}} r_c \right) \times 0.40$$

---

## 4. Severity Bands & Automated Responses

| Composite Score ($R_{\text{mission}}$) | Severity | Automated Action |
| :--- | :--- | :--- |
| $0 \le R < 25$ | `LOW` | Normal execution; background observation logging |
| $25 \le R < 50$ | `MEDIUM` | Elevated telemetry sampling; warn in Spatial HUD |
| $50 \le R < 75$ | `HIGH` | Pre-allocate recovery checkpoints; prioritize critical path tasks |
| $75 \le R \le 100$ | `CRITICAL` | Block new frontier dispatches; flag `requiresApproval`; alert operator |

---

## 5. Proactive Mitigation Suggestions

When a risk item exceeds `MEDIUM` severity, `missionRiskService` generates actionable mitigations:
- **Dependency Bottleneck**: Suggests parallelizing independent sub-tasks or splitting large monolithic goals.
- **Resource Exhaustion**: Proposes switching to lightweight models or requesting token quota expansion.
- **High Failure Rate**: Suggests routing tasks to alternative specialized agents with higher reliability scores in Stage 11.
- **Deadline Threat**: Suggests compressing non-critical milestones or skipping optional diagnostic goals.
