# AryaOS V1 — Stage 14: Decision Option Model

## 1. Option Generation Principles
Decision options are generated deterministically from the operational context without fabricating speculative metrics. 

### Mandatory Fields
Every `DecisionOption` consists of:
* `optionId`: Canonical identifier.
* `title`: Concise functional summary.
* `description`: Explicit operational workflow.
* `reversibility`: Classification (`REVERSIBLE`, `PARTIALLY_REVERSIBLE`, `IRREVERSIBLE`).
* `requiredGoals`: List of orchestrated DAG sub-goals.
* `requiredResources`: Required agent types and gateway leases.
* `strategyReferences`: Links to Stage 13 validated strategies.
* `supportingEvidence`: Grounded evidence from experiences or facts.
* `assumptions`: Key operational hypotheses.
* `risks`: Associated risk assessments.
* `estimatedCost`: Empirical estimate or strictly `'UNKNOWN'`.
* `estimatedDuration`: Empirical estimate or strictly `'UNKNOWN'`.
* `confidence`: Confidence band (`HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`).
* `fingerprint`: Deterministic 32-bit hash of normalized operational traits.

---

## 2. Reversibility Taxonomy
Options must declare their rollback feasibility upfront:
* **REVERSIBLE**: Execution changes can be cleanly rewound via Stage 09 checkpoint recovery. Low operational blast radius.
* **PARTIALLY_REVERSIBLE**: Independent sub-actions can be halted or retried; external or shared resources require manual reconciliation.
* **IRREVERSIBLE**: Generates permanent state modifications, public writes, financial commitments, or external notifications. Enforces mandatory human operator review.

---

## 3. Diversity Invariant & Deduplication
To prevent option clutter, candidate options must differ materially along at least one key operational axis:
* Strategy archetype (Sequential validation vs Parallel dispatch vs Consensus synthesis).
* Reversibility grade.
* Assigned agent roles.
* Resource allocation profile.

Deduplication uses a deterministic fingerprint:
$$\text{FP} = \text{Hash}(\text{normalizedTitle} : \text{reversibility} : \text{strategies} : \text{resources})$$
Near-identical or cosmetic variations are purged before scenario simulation.
