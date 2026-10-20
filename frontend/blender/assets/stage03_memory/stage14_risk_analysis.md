# AryaOS V1 — Stage 14: Risk Analysis & Pre-Mortem Engine

## 1. Unified Risk Integration
Stage 14 does not build a redundant second risk engine. Instead, it tightly integrates:
* Stage 12 `MissionRiskService`: Ingests operational deadline risks, dependency risks, provider capacity constraints, and recovery histories.
* Stage 13 `KnowledgeContradictionService`: Ingests active contradictions between knowledge claims as operational risks.

### Risk Classification
Every material risk is explicitly classified:
* **KNOWN**: Backed by documented evidence records or active contradictions in the knowledge graph.
* **INFERRED**: Derived logically from operational policies, resource limits, or dependency graphs.
* **PROJECTED**: Modeled under specific environmental stress scenarios.
* **UNKNOWN**: Identified unknown parameters where data is currently insufficient.

---

## 2. Pre-Mortem Failure Mode Analysis
The `PreMortemService` stress-tests candidate plans by asking:
> *"Assume this plan has failed disastrously in production. What caused that failure?"*

### Failure Mode Taxonomy
* **EVIDENCE_BACKED**: Grounded in historical failed experiences from Stage 11 or unresolved Stage 13 contradictions (e.g., recurrence of tool timeout under concurrent dispatch).
* **SPECULATIVE**: Hypothesized failure modes when no empirical failure records exist (e.g., unintended divergence during an irreversible file write).

Every failure mode is accompanied by:
1. `potentialCause`: Root failure trigger.
2. `earlyWarningSignal`: Measurable telemetry anomaly preceding failure.
3. `preventativeAction`: Governed mitigation to be enacted prior to dispatch.
