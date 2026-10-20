# AryaOS V1 — Stage 14: Decision Governance & Human Authority Boundary

## 1. Prime Directive of Decision Governance
AryaOS is designed to make human decisions better informed, transparent, and reversible—never to replace human authority for consequential actions.

Recommendations remain strictly in `AWAITING_REVIEW` until an authenticated human operator explicitly approves or rejects them.

---

## 2. Consequential Action Categories
Autonomous agents and background tasks are strictly forbidden from authorizing or executing the following consequential operations:
1. **Financial Decisions**: Purchasing provider credits, increasing budget limits, or altering billing thresholds.
2. **Provider Policy Mutations**: Switching baseline provider routing policies or modifying safety filters.
3. **Agent Autonomy Escalation**: Elevating agent capabilities, permissions, or dispatch bounds.
4. **Protected Memory Modifications**: Purging, altering, or deprecating protected historical knowledge nodes.
5. **Publishing & External Communications**: Releasing assets, publishing datasets, or sending emails/webhooks externally.
6. **Irreversible Operations**: Executing actions classified as `IRREVERSIBLE`.
7. **Mission Alterations**: Cancelling active missions, expanding mission scope, or removing validation gates.

---

## 3. Immutable Versioning
Once approved, a `Decision` record is permanently immutable.

If operational realities diverge or new evidence emerges:
1. The existing decision is marked `SUPERSEDED`.
2. A new `Decision v2` is instantiated with:
   * `previousDecisionId`: Links to the superseded ancestor.
   * `changeReason`: Explicit rationale for superseding.
   * `newEvidence`: Empirical observations justifying the new decision.
   * `changedConstraints` & `changedRisks`.

This guarantees an unbroken, tamper-evident lineage of all system strategies and choices.
