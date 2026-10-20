# AryaOS V1 — Stage 13: Knowledge Graph Schema & Semantic Domain Model

## 1. Node Taxonomy & Schema

The AryaOS Strategic Knowledge Graph indexes 21 canonical node categories (`KnowledgeNodeType`):

| Node Category | Description | Primary Identifiers & Format |
| :--- | :--- | :--- |
| `MISSION` | Long-horizon operational business objective | `mission:<id>` |
| `GOAL` | Directed task node coordinated within a mission | `goal:<id>` |
| `ACTION` | Atomic executable unit dispatched to execution gateway | `act:<id>` |
| `AGENT` | Specialized intelligence persona or coordinator | `agent:<id>` |
| `PROVIDER` | Backing model provider (Gemini, Claude, GPT, Kling) | `provider:<id>` |
| `CAPABILITY` | Operational skill or domain specialization | `cap:<name>` |
| `PROJECT` | Creative project root | `proj:<id>` |
| `CHARACTER` | Creative character persona or consistency anchor | `char:<id>` |
| `ASSET` | Visual, audio, or 3D asset reference | `asset:<id>` |
| `WORKFLOW` | Creative assembly pipeline | `wf:<id>` |
| `ARTIFACT` | Tangible generated output or file | `artifact:<id>` |
| `DECISION` | Human approval or arbitration decision | `decision:<id>` |
| `OUTCOME` | Empirical evaluation outcome or milestone result | `outcome:<id>` |
| `PATTERN` | Discovered recurring behavioral or failure pattern | `pat:<type>:<id>` |
| `STRATEGY` | Evidence-backed reusable guidance approach | `strat:<id>` |
| `CONSTRAINT` | Operational or policy boundary | `constraint:<id>` |
| `RISK` | Empirical threat to mission completion | `risk:<id>` |
| `MEMORY` | Stage 04 Spatial memory archive reference | `mem:<id>` |
| `EXPERIENCE` | Stage 11 empirical execution log | `exp:<id>` |
| `EVALUATION` | Stage 11 quality/reliability score card | `eval:<id>` |
| `LEARNING_SIGNAL` | Derived empirical learning vector | `lsig:<id>` |

### Common Node Attributes:
Every `KnowledgeNode` contains:
```typescript
interface KnowledgeNode {
  id: string;                      // Canonical identifier (unique)
  type: KnowledgeNodeType;         // One of 21 canonical types
  label: string;                   // Human-readable title
  createdAt: string;               // ISO 8601 timestamp
  updatedAt: string;               // ISO 8601 timestamp
  provenance: KnowledgeProvenance; // Full audit trail
  confidence: KnowledgeConfidence; // UNKNOWN | LOW | MEDIUM | HIGH
  status: KnowledgeStatus;         // VERIFIED | CANDIDATE | UNCERTAIN | DEPRECATED | REJECTED
  validity?: KnowledgeValidity;    // ACTIVE | SUPERSEDED | OBSOLETE | DISPUTED
  metadata?: Record<string, any>;  // Sanitized attributes
}
```

---

## 2. Directed Typed Edge Schema

Edges represent directed, semantic relations between canonical nodes:

$$\text{Edge ID} = \text{edge}:\text{source}--\text{RELATION}-->\text{target}$$

### Core Semantic Predicates:
- `MISSION_CONTAINS_GOAL`: Decomposes mission into coordinated goals.
- `GOAL_DEPENDS_ON_GOAL`: Prerequisite relationship in mission DAG.
- `GOAL_USED_AGENT`: Agent assigned to execute goal tasks.
- `AGENT_USED_PROVIDER`: Intelligence provider leveraged by agent.
- `EXECUTION_PRODUCED_ARTIFACT`: Resulting file or visual asset.
- `EXECUTION_GENERATED_EXPERIENCE`: Runtime log captured in Stage 11.
- `EXPERIENCE_SUPPORTS_FACT`: Empirical proof backing a factual claim.
- `FACT_SUPPORTS_STRATEGY`: Validated insight informing a strategy.
- `FACT_CONTRADICTS_FACT`: Direct semantic conflict between two facts.
- `DECISION_AFFECTED_MISSION`: Human or automated choice impacting mission.
- `RISK_AFFECTED_GOAL`: Threat identified for specific task.
- `LEARNING_SIGNAL_SUPPORTS_FACT`: Stage 11 signal validating a claim.
- `MEMORY_REFERENCES_MISSION`: Stage 04 vitrine memory linked to mission.

---

## 3. The Explicit Fact Model

A `KnowledgeFact` is represented as an explicit subject-predicate-object triple with dual-sided provenance and dynamic evidence linkage:

$$\text{Fact ID} = \text{fact}:\text{subject}::\text{PREDICATE}::\text{object}$$

```typescript
interface KnowledgeFact {
  id: string;                      // Deterministic hash of (subject, predicate, object)
  subject: string;                 // Subject canonical node ID
  predicate: string;               // Relation or attribute predicate
  object: string;                  // Target canonical node ID or literal symbol
  evidence: string[];              // References to supporting KnowledgeEvidence IDs
  confidence: KnowledgeConfidence; // Computed from evidence volume, quality, recency
  validity: KnowledgeValidity;     // ACTIVE | SUPERSEDED | OBSOLETE | DISPUTED
  status: KnowledgeStatus;         // If evidence < threshold: UNCERTAIN
  validFrom: string;               // Start of temporal validity
  validUntil?: string;             // Expiry timestamp
  observedAt: string;              // Observation timestamp
  supersededAt?: string;           // Timestamp when superseded by newer evidence
  provenance: KnowledgeProvenance; // Origin source details
  contradictionIds?: string[];     // Conflicting contradiction records
  metadata?: Record<string, any>;
}
```

---

## 4. Creative Domain Lineage Model

AryaOS structures creative workflows through a hierarchical lineage model without coupling to external execution environments:

```
[PROJECT]
   │
   └──► [CHARACTER]
           │
           ├──► [ASSET (Mesh / Texture / Audio)]
           │       │
           │       └──► [SHOT]
           │              │
           │              └──► [WORKFLOW]
           │                     │
           │                     └──► [MISSION]
           │                            │
           │                            └──► [OUTCOME]
```

- **OpenMontage Isolation**: OpenMontage remains a standalone rendering system. AryaOS records immutable knowledge references to generated assets without directly importing or executing OpenMontage internals.
