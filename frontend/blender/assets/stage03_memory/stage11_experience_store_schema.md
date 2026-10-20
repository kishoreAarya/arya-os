# ARYAOS V1 — STAGE 11: EXPERIENCE STORE SCHEMA SPECIFICATION

## 1. Overview

The `ExperienceStore` provides a durable, sanitized archive of task execution experiences. It bridges runtime task execution, multi-dimensional evaluation records, and long-term learning signals while guaranteeing zero secret leakage.

---

## 2. ExperienceRecord Schema Definition

```typescript
export interface ExperienceRecord {
  /** Unique primary identifier (e.g. 'exp-1790910504116-x9z4p') */
  experienceId: string;
  /** Associated goal identifier */
  goalId: string;
  /** Action node identifier within the plan DAG */
  actionId: string;
  /** Assigned agent identifier */
  agentId: string;
  /** Target intelligence provider */
  providerId: string;
  /** Provider capability invoked */
  capability: ProviderCapabilityType;
  /** Specific task class (e.g. 'MEMORY_SYNTHESIS', 'SECURITY_AUDIT') */
  taskType: string;
  /** Execution gateway execution identifier */
  executionId: string;
  /** Plan version at execution time (e.g. 1, 2) */
  planVersion: number;
  /** 64-character deterministic hex fingerprint of sanitized input */
  inputFingerprint: string;
  /** 64-character deterministic hex fingerprint of sanitized output */
  outputFingerprint: string;
  /** Complete multi-dimensional evaluation record */
  evaluation: EvaluationRecord;
  /** Verified USD cost or 'UNKNOWN' */
  cost: number | 'UNKNOWN';
  /** Total latency in milliseconds */
  latencyMs: number;
  /** Execution outcome status ('SUCCEEDED', 'FAILED', 'CANCELLED') */
  status: string;
  /** Human operator review decision if required ('APPROVED', 'REJECTED') */
  humanDecision?: 'APPROVED' | 'REJECTED';
  /** Downstream outcome status ('SUCCESS', 'FAILURE', 'SKIPPED') */
  downstreamOutcome?: string;
  /** ISO 8601 recording timestamp */
  timestamp: string;
  /** Scrubbed execution provenance */
  provenance: Record<string, unknown>;
}
```

---

## 3. Fingerprinting & Secret Sanitization

### Deterministic 64-Character Hex Hash
Inputs and outputs are fingerprinted using a non-cryptographic 64-character deterministic folding algorithm:
```typescript
function computeFingerprint(input: unknown): string {
  // Serializes and produces 64-character hex hash
  // Guarantees stable identical fingerprints across test and production runtimes
}
```

### Zero-Secret Leakage Guarantee
Before any experience is saved or fingerprinted, all inputs, outputs, and provenance dictionaries pass through `executionPersistence.sanitizeForPersistence()`:
- `Bearer [token]` $\longrightarrow$ `Bearer [REDACTED_TOKEN]`
- `sk-[key]`, `AIza[key]` $\longrightarrow$ `[REDACTED_KEY]`
- Keys matching `apikey`, `secret`, `password`, `auth`, `credential` $\longrightarrow$ `[REDACTED_SECRET]`

Raw API keys and tokens never enter localStorage, memory buffers, or evidence graphs.

---

## 4. Integration with Stage 09 Persistence

The Experience Store integrates directly into the Stage 09 `PersistedOrchestrationEnvelope`:

```typescript
export interface PersistedOrchestrationEnvelope {
  schemaVersion: number;
  savedAt: string;
  goals: Record<string, Goal>;
  activeGoalId: string | null;
  observations: Record<string, Observation[]>;
  approvals: Record<string, PersistedApprovalRecord>;
  telemetry: OperationalTelemetry;
  agentTasks?: Record<string, unknown>;
  conflictRecords?: Record<string, unknown>;
  // Stage 11 extensions
  experiences?: Record<string, ExperienceRecord>;
  evaluations?: Record<string, EvaluationRecord>;
  learningSignals?: Record<string, LearningSignal>;
  policyRecommendations?: Record<string, PolicyRecommendation>;
  planEvaluations?: Record<string, PlanEvaluation>;
}
```
Experiences survive application restarts, page reloads, and browser crashes through the established Stage 09 journal storage pipeline.
