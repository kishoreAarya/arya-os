# AryaOS V1 — Stage 13: Knowledge Contradiction & Conflict Resolution Design

## 1. Objectives & Non-Destructive Invariants

When an operating system aggregates distributed observations across multiple agents, providers, and execution runs, conflicting claims naturally occur. 

A naive system simply overwrites older data with newer data. This corrupts operational auditability and conceals system volatility.

### Non-Destructive Invariants:
1. **Never Silently Overwrite**: When a newly derived fact contradicts an existing fact, both facts are retained.
2. **Explicit Contradiction Entity**: The conflict is recorded as an immutable `KnowledgeContradiction` record linking both facts and their respective evidence arrays.
3. **Dual-Sided Evidence Preservation**: Resolving a contradiction NEVER deletes evidence from the weaker or superseded side. The losing fact's validity is updated to `SUPERSEDED` or `DISPUTED`, but remains fully queryable in historical audits.

---

## 2. Contradiction Taxonomy

| Contradiction Type | Definition | Example Scenario |
| :--- | :--- | :--- |
| `FACT_CONTRADICTION` | Direct semantic opposition on identical subject & object | "Agent X `PERFORMS_WELL_FOR` task Y" vs "Agent X `UNDERPERFORMS_FOR` task Y" |
| `TEMPORAL_CONTRADICTION` | Mutually exclusive active states overlapping in time | System marked `OFFLINE` and `ONLINE` during the same timestamp window |
| `SOURCE_CONFLICT` | Two reputable sources claim opposite findings | Memory archive states Provider A succeeded, but Execution Journal records 500 error |
| `OUTCOME_CONFLICT` | Identical task inputs yielding opposing deterministic outcomes | Milestone reported `SUCCESS` and `FAILURE` for same goal |
| `STRATEGY_CONFLICT` | Strategy recommends pattern prohibited by another strategy | "Always parallelize research" vs "Prohibit concurrent research on low memory" |

---

## 3. The KnowledgeContradiction Contract

```typescript
interface KnowledgeContradiction {
  contradictionId: string;                   // Canonical ID: contra:<type>:<factA>_vs_<factB>
  type: KnowledgeContradictionType;          // FACT_CONTRADICTION | TEMPORAL_CONTRADICTION | etc.
  factA: string;                             // Fact ID A
  factB: string;                             // Fact ID B
  evidenceA: string[];                       // Evidence supporting A
  evidenceB: string[];                       // Evidence supporting B
  detectedAt: string;                        // ISO 8601 timestamp
  severity: ContradictionSeverity;           // LOW | MEDIUM | HIGH | CRITICAL
  resolutionStatus: ContradictionResolutionStatus; // OPEN | UNDER_REVIEW | RESOLVED | SUPERSEDED
  resolutionStrategy?: ResolutionStrategy;   // TEMPORAL_RESOLUTION | EVIDENCE_WEIGHTING | etc.
  resolvedAt?: string;                       // ISO 8601 timestamp
  resolutionNote?: string;                   // Machine or human explanation
  resolvedBy?: string;                       // Rule name or Operator ID
}
```

---

## 4. Deterministic Resolution Strategies

When adjudication is required, `knowledgeResolutionService` evaluates five formal strategies:

### A. Temporal Resolution (`TEMPORAL_RESOLUTION`)
- **Trigger**: One fact was observed substantially later (>30 days) and reflects natural technological evolution or model updates.
- **Action**: Older fact validity transitions to `SUPERSEDED`; `supersededAt` timestamp recorded.

### B. Evidence Weighting (`EVIDENCE_WEIGHTING`)
- **Trigger**: Fact A has extensive supporting evidence (weight $\ge 2.0$ delta over Fact B).
- **Action**: Dominant fact remains `ACTIVE`; weaker fact transitions to `DISPUTED` with status `UNCERTAIN`. All evidence preserved.

### C. Source Priority (`SOURCE_PRIORITY`)
- **Trigger**: Distinct source tiers collide.
- **Deterministic Hierarchy**:
  $$\text{OPERATOR\_INPUT} (100) > \text{STAGE11\_EVALUATION} (85) > \text{STAGE12\_MISSION} (80) > \text{STAGE11\_EXPERIENCE} (70) > \text{STAGE09\_JOURNAL} (60) > \text{STAGE04\_MEMORY} (50)$$
- **Action**: Higher-tier source prevails. Lower-tier marked `DISPUTED`.

### D. Context Partitioning (`CONTEXT_PARTITION`)
- **Trigger**: Conflicting facts hold true under different environmental conditions (e.g. low-concurrency vs high-concurrency).
- **Action**: Both facts retained; domain applicability constraints scoped to respective metadata.

### E. Human Review (`HUMAN_REVIEW`)
- **Trigger**: `CRITICAL` severity contradictions, evenly matched evidence, or disputes impacting consequential operational policies.
- **Action**: Status set to `UNDER_REVIEW`; flagged in the Spatial Command Console for operator decision. Automated policy adoption is halted until operator signoff.
