# AryaOS V1 Stage 20 — Policy Conflict Detection & Deterministic Resolution

## 1. Overview & Conflict Model

When multiple active policies match a single operational context (e.g. an agent initiating an external action during a long-horizon mission), policy directives may conflict. For example, an optimization policy might permit provider routing while a system safety policy mandates mission execution pause.

In classical rule engines, conflicts often lead to non-deterministic race conditions or silent suppression of rules. AryaOS Stage 20 strictly guarantees **lossless, deterministic, explainable conflict resolution**.

---

## 2. Deterministic 8-Tier Priority Hierarchy

Every policy declares a priority tier mapped to an immutable numeric weight:

```
+---------------------------------------------------------------------------------+
|                             POLICY PRIORITY HIERARCHY                           |
+----+--------------------+--------+----------------------------------------------+
|Rank| Tier               | Weight | Operational Scope                            |
+----+--------------------+--------+----------------------------------------------+
| 1  | SYSTEM_SAFETY      |  100   | Critical invariants, crash & deadlock defense|
| 2  | SECURITY           |   90   | Connector boundaries, scope isolation        |
| 3  | HUMAN_GOVERNANCE   |   80   | Operator approval requirements               |
| 4  | RESOURCE_LIMITS    |   70   | Financial budgets, action/agent lease bounds |
| 5  | MISSION_POLICY     |   60   | Mission milestone gates, branch constraints  |
| 6  | AGENT_POLICY       |   50   | Specialist agent concurrency & profiles      |
| 7  | TRIGGER_POLICY     |   40   | Event webhook ingestion & cooldown rules     |
| 8  | OPTIMIZATION_POLICY|   30   | Cost/latency routing preferences             |
+----+--------------------+--------+----------------------------------------------+
```

### Invariant Guarantee
A lower-ranked policy (e.g. `OPTIMIZATION_POLICY`) can **never** override a higher-ranked policy (e.g. `SYSTEM_SAFETY` or `SECURITY`), regardless of empirical learning confidence or agent seniority.

---

## 3. Conflict Classification Taxonomies

Stage 20 classifies policy overlaps into five distinct conflict types:

1. **`CONTRADICTORY_POLICY`**: Directly opposing effects (e.g. `ALLOW` vs `DENY` or `PAUSE`).
2. **`SCOPE_CONFLICT`**: Overlapping policies defined at different architectural boundaries (e.g. Agent vs Mission vs Connector).
3. **`PRIORITY_CONFLICT`**: Multiple matching policies competing at different priority tiers.
4. **`RESOURCE_CONFLICT`**: Divergent quantitative limits (e.g. max cost ceiling of $50 vs $20).
5. **`AUTHORIZATION_CONFLICT`**: A policy attempting to grant permissions that exceed external security ceilings.

---

## 4. Tie-Breaking & Effect Restrictiveness

When two policies share the exact same priority tier and weight, the resolution engine selects the **more restrictive effect** to ensure safety:

```
DENY (10)
  > PAUSE (8)
    > REQUIRE_APPROVAL (6)
      > REQUIRE_REVIEW (5)
        > LIMIT (4)
          > DEFER (3)
            > ROUTE (2)
              > ALLOW (1)
```

If effect restrictiveness is also identical, the higher policy version (`v2 > v1`) takes precedence.

---

## 5. Lossless Preservation & Auditing

Stage 20 **never** silently deletes or ignores a superseded policy. When a conflict occurs:
1. `PolicyConflictService` constructs a `PolicyConflictRecord`.
2. Both competing policies (`policyAId`, `policyBId`) and versions are preserved.
3. A detailed `precedenceReason` is generated explaining the resolution.
4. The record is permanently committed to `executionPersistence.savePolicyConflict(conflict)`.

### Sample Conflict Audit Record
```json
{
  "conflictId": "conflict-pol-deny-pol-allow-1790958100-3fa1",
  "policyAId": "pol-deny",
  "policyAVersion": 1,
  "policyBId": "pol-allow",
  "policyBVersion": 1,
  "conflictType": "CONTRADICTORY_POLICY",
  "precedenceReason": "Policy 'pol-deny' (Priority: SYSTEM_SAFETY, Weight: 100) takes precedence over Policy 'pol-allow' (Priority: OPTIMIZATION_POLICY, Weight: 30) due to hierarchical precedence rules.",
  "effectivePolicyId": "pol-deny",
  "detectedAt": 1790958100000
}
```

---

## 6. Verification Summary

Verified in `src/tests/PolicyIntelligenceStage20.test.tsx`:
- Test 14: Confirmed priority weights strictly descend across all 8 tiers.
- Test 15: Confirmed `CONTRADICTORY_POLICY` detection between `ALLOW` and `DENY`.
- Test 16: Confirmed both policies remain intact in the catalog with explainable precedence.
- Test 58: Confirmed conflict records are persisted to execution persistence.
