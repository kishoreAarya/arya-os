# AryaOS V1 — Stage 13: Strategic Decision Context & Explainable Ranking

## 1. Objectives & Context Window Bounding

Injecting unstructured knowledge graph dumps into runtime prompts or decision steps leads to context pollution, hallucinations, high inference costs, and latency degradation.

AryaOS introduces the **Bounded Strategic Context Engine**:
1. **Bounded Retrieval**: Strictly limits facts, strategies, and evidence returned for any decision (maximum 6 ranked facts, 4 strategies, and pertinent open contradictions).
2. **Multi-Dimensional Explainable Scoring**: Every retrieved item receives a transparent ranking score with an exact mathematical breakdown of component weights.
3. **Automated Governance Gating**: If retrieved context contains unresolved critical contradictions or strategies with significant risks, execution pauses for operator signoff.

---

## 2. Multi-Dimensional Ranking Formula

Implemented in `strategicContextService.ts`:

$$S_{\text{final}}(f) = 100 \times \sum_{i \in \mathcal{D}} w_i \cdot s_i(f)$$

### Dimensional Breakdown & Weights:

| Dimension ($\mathcal{D}$) | Weight ($w_i$) | Evaluation Method |
| :--- | :--- | :--- |
| **Semantic Relevance** | $0.25$ | Token overlap between query subject and fact subject/object |
| **Task Similarity** | $0.25$ | Predicate match against active task type |
| **Recency** | $0.15$ | Half-life decay: $s_{\text{rec}} = 2^{-\Delta t / 60 \text{ days}}$ |
| **Confidence Weight** | $0.15$ | $\text{HIGH} (1.0), \text{MEDIUM} (0.7), \text{LOW} (0.35), \text{UNKNOWN} (0.10)$ |
| **Outcome Relevance** | $0.10$ | $\text{VERIFIED} \land \text{ACTIVE} (1.0)$ vs $\text{DISPUTED} / \text{UNCERTAIN} (0.30)$ |
| **Mission Similarity** | $0.10$ | Originating from current or identical mission topology |

### Transparent Explanation Contract:
Every ranked item returns a `ContextRankingExplanation`:
```typescript
interface ContextRankingExplanation {
  semanticRelevance: number; // 0 to 1
  taskSimilarity: number;    // 0 to 1
  recency: number;           // 0 to 1
  confidenceWeight: number;  // 0 to 1
  outcomeRelevance: number;  // 0 to 1
  missionSimilarity: number; // 0 to 1
  finalScore: number;        // Composite score [0, 100]
  rationale: string;         // Human-readable summary of score factors
}
```

---

## 3. Human Governance & Gating Rules

The `KnowledgeDecisionContext` acts as a security boundary between strategic knowledge and autonomous execution:

```typescript
interface KnowledgeDecisionContext {
  contextId: string;
  targetGoalId?: string;
  targetMissionId?: string;
  strategicContext: KnowledgeContext;
  governanceThresholdExceeded: boolean;
  requiresHumanReview: boolean;
  governanceReasons: string[];
  createdAt: string;
}
```

### Mandatory Human Review Triggers:
1. **Critical Contradictions**: Any open or under-review contradiction with `severity: 'CRITICAL'` affecting the target decision facts.
2. **High-Risk Strategy Reference**: Any referenced strategy containing $>2$ known risks or explicit deprecation constraints.
3. **Material Autonomy or Financial Boundary Change**: Any fact suggesting an increase in agent autonomy or token spending limit.

When triggered, `requiresHumanReview` is set to `true`, and the action is held for operator approval in the Spatial Command Console.
