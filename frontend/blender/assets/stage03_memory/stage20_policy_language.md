# AryaOS V1 Stage 20 — Declarative Policy Language & AST Engine Specification

## 1. Specification Overview

The **Declarative Policy Language** defines the syntax, operators, and safety constraints for governing autonomous behaviors in AryaOS V1. In untrusted and multi-agent environments, policy condition evaluation must be provably bounded, deterministic, and impervious to code injection or prototype tampering.

### Threat Model & Language Constraints

| Attack Vector | Classical Vulnerability | Stage 20 Defense |
|---|---|---|
| **Arbitrary Code Execution** | Interpreters using `eval()`, `new Function()`, or dynamic scripting | **Pure AST Evaluator**. Zero code execution or scripting. Evaluates purely declarative JSON ASTs. |
| **Prototype Pollution** | Manipulating `__proto__`, `constructor`, or `prototype` via dot paths | **Path Traversal Sanitizer**. Explicitly disallows any path segment matching reserved prototype names. |
| **Type Confusion / Loose Equality** | JavaScript `==` coercion leading to unexpected truthy results | **Strict Equality (`===`) & Type Guards**. Operands must match expected runtime types or fail closed. |
| **Silent Missing-Field Faults** | Unhandled `undefined` references causing runtime exceptions | **Safe Nested Traversal**. Missing paths gracefully return `undefined` and evaluate to `false` (fail-closed). |
| **Denial of Service** | Unbounded regular expression backtracking | **Deterministic String Primitives**. Operators restricted to deterministic substring, prefix, and suffix matches. |

---

## 2. Supported Atomic Operators

All atomic conditions implement `PolicyCondition`:
```typescript
interface PolicyCondition {
  field: string;
  operator: PolicyOperator;
  value?: unknown;
}
```

### Operator Evaluation Semantics

| Operator | Supported Value Types | Evaluation Logic | Fail-Closed Rule |
|---|---|---|---|
| `equals` | `string`, `number`, `boolean`, `null` | Strict equality `resolved === value` | Fails closed on type mismatch |
| `not_equals` | `string`, `number`, `boolean`, `null` | Strict inequality `resolved !== value` | True if field is missing |
| `contains` | `string`, `Array` | Substring check or array containment | False if target is non-string/non-array |
| `exists` | any | Field presence `resolved !== undefined && resolved !== null` | False if path unresolvable |
| `not_exists` | any | Field absence `resolved === undefined || resolved === null` | True if path unresolvable |
| `greater_than` | `number` | Numeric comparison `resolved > value` | False if either operand is non-number |
| `less_than` | `number` | Numeric comparison `resolved < value` | False if either operand is non-number |
| `in` | any | Set inclusion `value.includes(resolved)` | False if `value` is not an array |
| `not_in` | any | Set exclusion `!value.includes(resolved)` | False if `value` is not an array |

---

## 3. Compound Conjunctions (`AND` / `OR`)

Conditions are structured as recursive trees using `PolicyConditionGroup`:
```typescript
interface PolicyConditionGroup {
  conjunction: 'AND' | 'OR';
  conditions: (PolicyCondition | PolicyConditionGroup)[];
}
```

- **`AND` Conjunction**: Requires every child condition and subgroup to evaluate to `true`. Short-circuits on first `false`.
- **`OR` Conjunction**: Requires at least one child condition or subgroup to evaluate to `true`. Short-circuits on first `true`.
- **Empty Group**: Defaults to `true` (unconditional policy match).

---

## 4. Allowlisted Policy Effects

Policies cannot execute arbitrary callbacks. Effects are strictly restricted to the following allowlisted set:

| Effect | Target Subsystem | Action Taken |
|---|---|---|
| `ALLOW` | General Runtime | Permits execution to proceed. |
| `DENY` | General Runtime | Aborts proposed execution with an explainable reason. |
| `LIMIT` | Stage 10 Resource Governor / Stage 19 Triggers | Applies quantitative constraints (concurrency, budget, rate limits). |
| `REQUIRE_APPROVAL` | Stage 10 / Stage 19 Approval Gates | Holds execution in `AWAITING_APPROVAL` pending human operator sign-off. |
| `REQUIRE_REVIEW` | Stage 11 / Stage 14 Review Queues | Flags execution for operator inspection without immediate blocking. |
| `PAUSE` | Stage 12 Mission Control | Halts mission execution branches safely. |
| `DEFER` | Stage 09 Scheduler | Delays execution pending resource availability or cooldown. |
| `ROUTE` | Stage 06 Provider Router | Reroutes task dispatch to preferred or alternative providers/agents. |

---

## 5. Verification Summary

Verified in `src/tests/PolicyIntelligenceStage20.test.tsx` (Tests 7–13):
- Verified equality, numeric ranges, existence, and set inclusion.
- Verified compound `AND` and `OR` boolean trees.
- Verified complete rejection of prototype pollution attempts (`__proto__`, `constructor`).
- Verified zero dynamic code execution and complete fail-closed behavior on invalid inputs.
