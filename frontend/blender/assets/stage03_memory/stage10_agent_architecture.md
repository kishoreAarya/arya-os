# ARYAOS V1 — STAGE 10: AGENT ARCHITECTURE SPECIFICATION

## 1. Architectural Philosophy: Workers vs. Providers

In AryaOS V1, a fundamental invariant governs autonomous intelligence:

> **An Agent is a logical worker persona with specialized capabilities, trust, and autonomy.**  
> **A Provider is an execution backend (runtime model/API) with cost, latency, and context limits.**

Agents must NEVER be conflated with providers. No agent profile in AryaOS contains vendor names (`openai`, `anthropic`, `gemini`), and no agent directly invokes an LLM API. All execution flows strictly from the logical worker through the Stage 06 `providerRouter` and Stage 07 `executionGateway`.

```
┌────────────────────────────────────────────────────────┐
│                   AryaOS Goal Engine                   │
└──────────────────────────┬─────────────────────────────┘
                           │ DAG Actions
                           ▼
┌────────────────────────────────────────────────────────┐
│               Multi-Agent Coordinator                  │
│  - Selects specialized worker from Agent Registry      │
│  - Binds ActionNode to AgentTask                       │
│  - Enforces per-agent and global concurrency limits    │
└────────────┬─────────────────────────────┬─────────────┘
             │                             │
             ▼                             ▼
  ┌─────────────────────┐       ┌──────────────────────┐
  │   Logical Worker    │       │  Resource Governor   │
  │   (e.g., RESEARCHER,│       │  & Memory Locks      │
  │    ANALYST, CODER)  │       └──────────┬───────────┘
  └──────────┬──────────┘                  │
             │                             │ Leases & Locks
             ▼                             ▼
┌────────────────────────────────────────────────────────┐
│                 Stage 06 Provider Router               │
│  (Selects optimal model/provider based on policy)      │
└──────────────────────────┬─────────────────────────────┘
                           │ Execution Plan
                           ▼
┌────────────────────────────────────────────────────────┐
│             Stage 07 Execution Gateway                 │
│  (Single truth boundary, idempotency, auth, fallbacks) │
└────────────────────────────────────────────────────────┘
```

---

## 2. Specialized Logical Worker Profiles

The `agentRegistry` maintains 10 default worker profiles:

| Agent ID | Persona Name | Role | Primary Capabilities | Concurrency | Trust Level | Autonomy Level | Scopes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `agent-researcher` | Archival Researcher | `RESEARCHER` | `RESEARCH`, `SUMMARIZATION`, `STRUCTURED_EXTRACTION` | 3 | `VERIFIED` | `HIGH` | `archive`, `vitrines`, `docs` |
| `agent-analyst` | Contextual Analyst | `ANALYST` | `REASONING`, `CLASSIFICATION`, `SUMMARIZATION` | 2 | `VERIFIED` | `HIGH` | `archive`, `analytics`, `telemetry` |
| `agent-planner` | Strategic Planner | `PLANNER` | `REASONING`, `STRUCTURED_EXTRACTION` | 2 | `AUTONOMOUS` | `HIGH` | `plans`, `goals`, `dag` |
| `agent-writer` | Narrative Synthesizer | `WRITER` | `SUMMARIZATION`, `REASONING` | 2 | `VERIFIED` | `HIGH` | `scripts`, `prompts`, `narratives` |
| `agent-coder` | Pipeline Engineer | `CODER` | `CODE_GENERATION`, `REASONING`, `STRUCTURED_EXTRACTION` | 2 | `VERIFIED` | `MEDIUM` | `code`, `workflows` |
| `agent-vision` | Visual Inspector | `VISION_ANALYST` | `VISION`, `IMAGE_GENERATION` | 1 | `VERIFIED` | `MEDIUM` | `visual`, `keyframes`, `vitrines` |
| `agent-video-director` | Spatial Video Director | `VIDEO_DIRECTOR` | `VIDEO_GENERATION`, `VISION` | 1 | `VERIFIED` | `LOW` *(Requires Approval)* | `video`, `shots`, `timeline` |
| `agent-quality` | Auditing Gatekeeper | `QUALITY_REVIEWER` | `REASONING`, `CLASSIFICATION` | 2 | `AUTONOMOUS` | `HIGH` | `qa`, `reviews`, `rubrics` |
| `agent-metadata` | Ontology Indexer | `METADATA_AGENT` | `CLASSIFICATION`, `STRUCTURED_EXTRACTION`, `EMBEDDING` | 4 | `AUTONOMOUS` | `HIGH` | `tags`, `entities`, `metadata` |
| `agent-publisher` | Distribution Gateway | `PUBLISHING_AGENT` | `REASONING`, `SUMMARIZATION` | 1 | `VERIFIED` | `LOW` *(Requires Approval)* | `channels`, `social`, `exports` |

---

## 3. AgentTask Contract & Lifecycle

When an `ActionNode` is ready for execution, `agentCoordinator.assignAgentForAction()` transforms it into an `AgentTask`:

```typescript
export interface AgentTask {
  taskId: string;
  goalId: string;
  planId: string;
  planVersion: number;
  parentActionId: string;
  assignedAgentId?: string;
  capability: ProviderCapabilityType;
  contextReferences: string[];
  inputContract: Record<string, unknown>;
  expectedOutputContract: Record<string, unknown>;
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  riskLevel: ActionRiskLevel;
  estimatedCost: { minUsd: number | null; maxUsd: number | null; currency: 'USD' };
  estimatedLatency: number;
  deadline?: string;
  status: AgentTaskStatus;
  qualityRequirement: QualityRequirementLevel;
  memoryAccessDeclarations: TaskMemoryAccessDeclaration[];
  createdAt: string;
  updatedAt: string;
}
```

### State Machine Transitions
1. `IDLE` $\rightarrow$ Initialized before assignment.
2. `ASSIGNED` $\rightarrow$ Bounded to a specific worker, pending resource lease and memory locks.
3. `RUNNING` $\rightarrow$ Dispatched to Stage 07 Execution Gateway with active lease.
4. `WAITING` $\rightarrow$ Paused for dependency unblocking or external rate limit backoff.
5. `BLOCKED` $\rightarrow$ Suspended due to concurrency saturation, budget exhaustion, or memory lock conflict.
6. `SUCCEEDED` $\rightarrow$ Completed execution and verified by Objective Quality Gate.
7. `FAILED` $\rightarrow$ Execution error or quality gate rejection.
8. `CANCELLED` $\rightarrow$ Operator aborted or superseded by replan.

---

## 4. End-to-End Operational Provenance

AryaOS preserves an unbroken chain of attribution for every autonomous operation:

$$\text{Goal} \longrightarrow \text{Plan} \longrightarrow \text{Action} \longrightarrow \text{Agent} \longrightarrow \text{Provider} \longrightarrow \text{Execution} \longrightarrow \text{Result} \longrightarrow \text{Observation} \longrightarrow \text{Memory Event}$$

- **Agent Identity**: Captures `agentId`, `agentRole`, and `agentTrustLevel`.
- **Backend Identity**: Captures `providerId`, `modelId`, and `executionId`.
- **Audit Logging**: Recorded in Stage 04 spatial memory events and Stage 09 event-sourced journal.
- **Zero Secret Leakage**: API tokens or raw credentials never enter the provenance payload.
