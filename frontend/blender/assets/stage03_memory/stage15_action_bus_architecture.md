# AryaOS V1 Stage 15 — Universal Action Bus Architecture

## 1. Overview & Architectural Role

The **Universal Action Bus** introduces a unified, capability-neutral runtime interface through which AryaOS coordinates, authorizes, executes, and audits external interactions.

Prior to Stage 15, AryaOS possessed comprehensive cognitive faculties:
* **Stage 04-05**: Spatial Semantic Memory
* **Stage 07**: Real Intelligence Execution Gateway (`executionGateway.execute()`)
* **Stage 08**: Goal Orchestration & DAG Scheduling
* **Stage 09**: Durable Execution Persistence & Recovery
* **Stage 10**: Multi-Agent Coordination & Resource Governance
* **Stage 11**: Evaluation, Experience & Collective Learning
* **Stage 12**: Long-Horizon Missions & Checkpoint Operations
* **Stage 13**: Strategic Knowledge Graph & Provenance
* **Stage 14**: Decision Intelligence, Strategy Planning & Consequence Simulation

Stage 15 provides the critical missing physical interface: **EXTERNAL CAPABILITY ORCHESTRATION**.

---

## 2. Invariant: Absolute Boundary Separation

The most critical architectural boundary in AryaOS V1 is the strict bifurcation between LLM intelligence and external world manipulation:

```
+-----------------------------------------------------------------------------------+
|                                     AryaOS                                        |
+-----------------------------------------------------------------------------------+
          |                                                               |
          v                                                               v
+-------------------------------+                               +-------------------+
|   Stage 07 Execution Gateway  |                               | Stage 15 ActionBus|
|   `executionGateway.execute()`|                               | `actionBus.execute`|
+-------------------------------+                               +-------------------+
          |                                                               |
  [LLM / AI Model APIs]                                           [External Actions]
  * anthropic.claude-3-5-sonnet                                   * filesystem.read
  * openai.gpt-4o                                                 * filesystem.write
  * google.gemini-1-5-pro                                         * web.search
  * deepseek.chat                                                 * external.http
                                                                  * github.read_issue
                                                                  * github.create_issue
                                                                  * notification.send
```

### Guarantees:
1. **No External Mutation via Gateway**: `executionGateway` cannot execute filesystem, HTTP, GitHub, or notification actions.
2. **No Model Inference via Action Bus**: `actionBusService` does not connect to LLM endpoints, generate completions, or alter prompts.
3. **No Direct UI Invocation**: Spatial UI components trigger neither directly; all requests flow through governed orchestrators.
4. **Sandboxed Mock Isolation**: In test and offline environments, adapters run completely within deterministic, in-memory sandboxes without live network credentials.

---

## 3. Action Bus Execution Pipeline

Every action request passing through `actionBusService.execute()` undergoes a 10-stage synchronous lifecycle:

```
ActionRequest
      │
      ▼
1. Idempotency Check ──────── (Cache Hit) ──► Return Cached ActionResult
      │ (Cache Miss)
      ▼
2. Capability Lookup ──────── (Not Found) ──► FAILED (Category: NOT_FOUND)
      │
      ▼
3. Availability Check ─────── (OFFLINE) ────► FAILED (Category: UNAVAILABLE)
      │
      ▼
4. Schema Validation ──────── (Invalid) ────► FAILED (Category: VALIDATION)
      │
      ▼
5. Authorization & Sandbox ── (Denied) ─────► DENIED / REQUIRES_APPROVAL
      │ (Authorized)
      ▼
6. Adapter Dispatch ───────── (No Adapter) ─► FAILED (Category: NOT_FOUND)
      │
      ▼
7. Execution Race (Timeout & Retries)
      │ (Success)
      ├────────────────────── (Error / Timeout)
      │                               │
      ▼                               ▼
8. Output Normalization         Reconciliation (State Check)
      │                               │
      │                               ▼
      ├────────────────────── Failure Normalization
      │
      ▼
9. Audit Logging & State Persistence (Zero Secret Leakage)
      │
      ▼
10. Knowledge Graph Ingestion & Journal Event Emission
```

---

## 4. Key Contracts & Types

```typescript
export interface ActionRequest {
  actionId: string;
  capabilityId: string;
  operation: string;
  parameters: Record<string, unknown>;
  idempotencyKey?: string;
  timeoutMs?: number;
  context: ActionExecutionContext;
}

export interface ActionResult {
  actionId: string;
  capabilityId: string;
  success: boolean;
  status: ActionExecutionStatus; // 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'DENIED' | 'REQUIRES_APPROVAL' | 'STATE_UNKNOWN'
  data: unknown;
  metadata: Record<string, unknown>;
  error?: ActionError;
  provenance: ActionProvenance;
  durationMs: number;
}
```

---

## 5. Architectural Verification & Zero Overhead

* **Zero Direct Provider Calls**: Verified by automated architecture checks.
* **Deterministic Sandboxing**: All reference mock adapters operate in memory without network leaks.
* **Zero 3D Overhead**: Spatial Command Console overlays (`action-bus-hud`, `capability-status-hud`, `action-trace-hud`) render exclusively as DOM HUD elements, adding 0 WebGL draw calls.
