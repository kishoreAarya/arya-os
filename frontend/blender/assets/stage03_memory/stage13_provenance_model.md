# AryaOS V1 — Stage 13: Knowledge Provenance & Security Model

## 1. Provenance Invariant & Auditability

In an enterprise-grade AI operating system, ungrounded assertions are hazardous. AryaOS enforces the **Strict Provenance Invariant**:

> **No Orphan Facts**: Every node, fact, edge, and strategy must trace directly to an observable runtime execution, structured evaluation, spatial memory vitrine, or explicit operator action.

For every knowledge entity, the system records:
1. **Who/What produced it**: Source agent, provider, evaluation service, or operator.
2. **When it occurred**: Precise ISO 8601 observation and extraction timestamps.
3. **From which execution context**: Canonical identifiers linking `executionId`, `missionId`, `goalId`, `actionId`, or `evaluationId`.
4. **Supporting evidence**: Array of immutable evidence references.
5. **Confidence level**: Mathematical evaluation of certainty (`UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`).

```typescript
interface KnowledgeProvenance {
  source: KnowledgeSource;
  extractedAt: string;
  derivedBy: string;
  executionId?: string;
  missionId?: string;
  goalId?: string;
  actionId?: string;
  evaluationId?: string;
  memoryId?: string;
  confidenceScore?: number;
}
```

---

## 2. Zero-Secret Leakage Guarantee

Knowledge graphs accumulate data across external APIs, execution payloads, and agent tool calls. Without strict redaction, credentials could leak into persistent memory.

### Sanitization Policy:
All ingestion flows through `knowledgeIngestionService.sanitizeSecret()`, which applies recursive object scanning and regular expression redaction:

- **Bearer Tokens**: `Bearer [A-Za-z0-9\-_\.=]+` $\to$ `Bearer [REDACTED_TOKEN]`
- **OpenAI/Vendor Keys**: `sk-[A-Za-z0-9\-_]{20,}` $\to$ `sk-[REDACTED_KEY]`
- **Generic API Keys**: `key-[A-Za-z0-9\-_]{20,}` $\to$ `key-[REDACTED_KEY]`
- **GitHub / Personal Tokens**: `ghp_[A-Za-z0-9]{20,}` $\to$ `ghp-[REDACTED_TOKEN]`
- **Sensitive Object Keys**: `apikey`, `api_key`, `token`, `secret`, `password`, `authorization`, `auth`, `bearer`, `credential`, `privatekey` are automatically scrubbed to `[REDACTED_SECRET]`.

---

## 3. Snapshot Versioning & Cryptographic Fingerprinting

Strategic knowledge evolves as missions execute. Rather than mutating historical snapshots, AryaOS introduces **Monotonic Versioned Knowledge Snapshots**:

$$\text{Snapshot}_{v} \xrightarrow{\text{ingest new missions}} \text{Snapshot}_{v+1}$$

### Snapshot Contract:
```typescript
interface KnowledgeSnapshot {
  version: number;             // Monotonically increasing (1, 2, 3...)
  timestamp: string;           // ISO 8601 creation time
  nodeCount: number;           // Total active nodes
  edgeCount: number;           // Total active edges
  factCount: number;           // Total active facts
  contradictionCount: number;  // Open and resolved contradictions
  strategyCount: number;       // Candidate and validated strategies
  stateHash: string;           // SHA-256 fingerprint of canonical knowledge state
}
```

Historical snapshots are immutable records of organizational understanding at a specific point in time.
