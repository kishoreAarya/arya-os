# AryaOS V1 Stage 22 — Causal Graph Architecture & Graph Safety

## 1. Overview & Architectural Intent

Stage 22 establishes a structured **Causal Graph** representation of all operational activity across the AryaOS V1 runtime. Rather than treating logs as isolated strings or flat event streams, Stage 22 models the runtime as a directed causal dependency graph connecting requests, triggers, governance decisions, authorizations, dispatches, executions, and state observations.

The causal graph enables:
- Instant root-cause attribution for any observed failure or security violation.
- Full provenance tracing from external webhook to downstream physical state change.
- Detection of missing intermediate evidence (e.g., unauthorized dispatches).

---

## 2. Graph Model & Schema

The causal graph is represented by $G = (V, E)$, where $V$ is a set of operational nodes and $E$ is a set of directed causal edges.

### 2.1 Nodes ($V$)
Each node represents an atomic operational milestone:
```typescript
interface CausalNode {
  nodeId: string;
  operationId: string;
  stage: number;
  nodeType: 'REQUEST' | 'MISSION' | 'TRIGGER' | 'GOVERNANCE' | 'AUTHORITY' | 'ACTION' | 'EXECUTION' | 'RECONCILIATION' | 'OBSERVATION' | 'MISSING_EVIDENCE';
  label: string;
  timestamp: number;
  epistemicStatus: 'CONFIRMED' | 'OBSERVED' | 'INFERRED' | 'PROJECTED' | 'UNKNOWN';
  metadata: Record<string, unknown>;
}
```

### 2.2 Edges ($E$)
Each edge represents a typed, directed causal dependency:
```typescript
interface CausalEdge {
  fromNodeId: string;
  toNodeId: string;
  relation: 'CAUSED_BY' | 'TRIGGERED_BY' | 'GOVERNED_BY' | 'AUTHORIZED_BY' | 'DISPATCHED_BY' | 'EXECUTED_BY' | 'RECONCILED_BY' | 'EVIDENCED_BY';
  timestamp: number;
}
```

---

## 3. Mandatory Graph Safety & Resource Bounds

To prevent resource exhaustion, denial-of-service, or graph corruption during malicious or degraded execution, the causal graph builder enforces strict boundaries:

### 3.1 Self-Cycle Rejection
$$\forall e = (u, v) \in E \implies u \neq v$$
Any attempt to insert a self-referential causal edge ($u \to u$) is immediately rejected and flagged as a graph anomaly.

### 3.2 Cycle Detection & Acyclicity Enforcement
When building causal dependency chains, recursive cycle detection tracks visited node sets. If a circular reference ($A \to B \to C \to A$) is encountered:
1. Traversal halts immediately on that branch.
2. The graph is marked with `hasCycles: true`.
3. The circular edge is isolated to prevent infinite loops.

### 3.3 Traversal Depth Bound ($\text{MAX\_CAUSAL\_DEPTH} = 10$)
Causal traversal terminates at a maximum depth of 10 ancestry levels. Operations exceeding 10 ancestral hops are truncated with depth-limit indicators.

### 3.4 Node Count Bound ($\text{MAX\_CAUSAL\_NODES} = 100$)
A single operational causal graph can contain at most 100 nodes. If an operation branches excessively (e.g., fan-out triggering), node insertion ceases gracefully at 100, preventing DOM and memory exhaustion.

---

## 4. Explicit Representation of Missing Evidence

### The Non-Fabrication Principle
Traditional monitoring systems either invent plausible links or silently drop orphaned events. AryaOS V1 strictly forbids both:
- **Never Fabricate**: Do not insert a hypothetical governance approval if none exists in the audit registry.
- **Never Delete**: Do not discard an action dispatch just because its parent trigger cannot be found.

### The `MISSING_EVIDENCE` Synthetic Step
When an operation trace contains an action dispatch without a preceding governance evaluation:
```json
{
  "stepNumber": 2,
  "lifecycleState": "MISSING_EVIDENCE",
  "epistemicStatus": "UNKNOWN",
  "stageOrigin": 22,
  "description": "Missing governance evaluation prior to action dispatch 'act-isolated-dispatch-999'",
  "isMissingEvidence": true
}
```
This guarantees complete visibility into anomalous or rogue executions without corrupting historical records.
