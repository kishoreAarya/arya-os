# AryaOS V1 Stage 19 — Declarative Condition Engine Specification

## 1. Engine Objective & Threat Model

The **Trigger Condition Engine** (`TriggerConditionEngine`) evaluates whether an incoming normalized event matches the semantic preconditions of a trigger. In untrusted or multi-tenant event processing, condition evaluation is a primary attack vector for arbitrary code execution (ACE), prototype pollution, and denial-of-service (ReDoS / infinite loops).

### Threat Model & Countermeasures

| Vulnerability Vector | Classical Failure Mode | Stage 19 Hardening |
|---|---|---|
| **Arbitrary Code Execution** | Use of `eval()`, `new Function()`, or scripting interpreters | **Zero dynamic execution**. The engine is a strict, pure AST matcher operating on typed JSON values. |
| **Prototype Pollution** | Dot-paths containing `__proto__`, `constructor`, or `prototype` | **Path Traversal Sanitizer**. Explicitly rejects any field path containing reserved prototype tokens. |
| **Denial of Service** | Complex regular expressions with catastrophic backtracking | **Zero dynamic regex**. String matching is restricted to deterministic `contains`, `starts_with`, `ends_with`. |
| **Silent Faults / Flawed Coercion** | JavaScript loose equality `==` causing unexpected truthiness | **Strict equality (`===`) and strict type guards**. Mismatched types fail closed. |
| **Missing Path Crashes** | `TypeError: Cannot read property of undefined` | **Safe nested traversal**. Unresolved paths gracefully return `undefined` and evaluate to `false`. |

---

## 2. Supported Atomic Operators

All atomic conditions implement `TriggerCondition`:
```typescript
interface TriggerCondition {
  field: string;
  operator: TriggerOperator;
  value?: unknown;
}
```

### Operator Semantics

| Operator | Supported Types | Semantics | Fail-Closed Rule |
|---|---|---|---|
| `equals` | `string`, `number`, `boolean`, `null` | Strict deep/primitive equality (`a === b`) | Returns `false` on type mismatch |
| `not_equals` | `string`, `number`, `boolean`, `null` | Strict inequality (`a !== b`) | Returns `true` if field missing |
| `contains` | `string`, `Array` | Substring inclusion or array member inclusion | Returns `false` if target is not string/array |
| `starts_with` | `string` | Prefix check via `String.prototype.startsWith` | Returns `false` if target is not string |
| `ends_with` | `string` | Suffix check via `String.prototype.endsWith` | Returns `false` if target is not string |
| `greater_than` | `number` | Numeric comparison `a > b` | Returns `false` if either operand is non-number |
| `less_than` | `number` | Numeric comparison `a < b` | Returns `false` if either operand is non-number |
| `exists` | any | Field presence check (`a !== undefined && a !== null`) | Returns `false` if path unresolvable |
| `not_exists` | any | Field absence check (`a === undefined || a === null`) | Returns `true` if path unresolvable |
| `in` | any | Membership check in expected array (`value.includes(target)`) | Returns `false` if `value` is not array |
| `not_in` | any | Non-membership in expected array | Returns `false` if `value` is not array |

---

## 3. Nested Field Resolution & Array Indexing

Field paths support nested dot notation and zero-indexed array indexing:
- `data.issue.title` -> Resolves to property `title` of object `issue` in `data`.
- `data.labels[0]` -> Resolves to first item in `labels` array.
- `metadata.metrics.severity` -> Resolves nested hierarchy.

### Path Traversal Implementation
```typescript
private resolveField(path: string, event: NormalizedExternalEvent): unknown {
  if (!path || typeof path !== 'string') return undefined;

  // Prototype pollution defense
  if (path.includes('__proto__') || path.includes('constructor') || path.includes('prototype')) {
    return undefined;
  }

  const parts = path.split(/\.|\[(\d+)\]/).filter(Boolean);
  let current: unknown = event;

  for (const part of parts) {
    if (current === null || current === undefined) {
      return undefined;
    }
    if (typeof current === 'object') {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }

  return current;
}
```

---

## 4. Compound Condition Trees (Boolean Conjunctions)

Conditions are structured as recursive groups using `TriggerConditionGroup`:
```typescript
interface TriggerConditionGroup {
  conjunction: 'AND' | 'OR';
  conditions: (TriggerCondition | TriggerConditionGroup)[];
}
```

### Evaluation Algorithm
- **Empty Group**: Defaults to `true` (unconditional match).
- **`AND` Conjunction**: Short-circuits on first `false`. Requires all child conditions or sub-groups to evaluate to `true`.
- **`OR` Conjunction**: Short-circuits on first `true`. Requires at least one child condition or sub-group to evaluate to `true`.

---

## 5. Test Suite Verification

The condition engine was verified in `src/tests/EventReactionStage19.test.tsx`:
- Tests 10–13: Verified equality, substring, numeric range, and existence operators.
- Tests 14–15: Verified compound `AND` and `OR` conjunction logic.
- Tests 16–18: Verified nested dot paths, array indexing (`labels[0]`), and fail-closed behavior on missing fields and type mismatches.
- Test 19: Verified rejection of prototype pollution attempts (`__proto__`, `constructor`).
- Test 20: Verified complex nested boolean trees combining `AND` with nested `OR` conditions.
