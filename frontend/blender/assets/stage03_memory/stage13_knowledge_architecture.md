# AryaOS V1 — Stage 13: Strategic Knowledge Architecture & Long-Term Memory

## 1. Operating System Vision & Knowledge Layer Hierarchy

Stage 13 introduces the **Strategic Knowledge Graph & Long-Term Memory Layer** to AryaOS V1. 

While previous stages established distinct operational capabilities:
- **Stage 04–05**: Spatial semantic memory (vitrines, relationships, semantic anchors).
- **Stage 09**: Durable event-sourced execution state and crash recovery.
- **Stage 10**: Multi-agent coordination and resource governance.
- **Stage 11**: Agent evaluation, collective intelligence, and empirical learning signals.
- **Stage 12**: Long-horizon mission control, milestone DAGs, checkpoints, and adaptive replanning.

Stage 13 connects these operational signals into a structured, queryable, provenance-preserving semantic knowledge graph.

```
+-----------------------------------------------------------------------------------+
|                        STRATEGIC KNOWLEDGE GRAPH (STAGE 13)                       |
|   (Canonical Nodes, Typed Directed Edges, Explicit Facts, Provenance, Confidence) |
+-----------------------------------------------------------------------------------+
       ^                    ^                     ^                   ^
       |                    |                     |                   |
+---------------+   +------------------+   +---------------+   +--------------------+
|  Contradiction|   | Strategic Pattern|   | Strategy Model|   |  Strategic Decision|
|    Engine     |   |    Detection     |   |   Repository  |   |   Context Engine   |
+---------------+   +------------------+   +---------------+   +--------------------+
       ^                    ^                     ^                   ^
       |                    |                     |                   |
+-----------------------------------------------------------------------------------+
|                        KNOWLEDGE INGESTION & RELATION EXTRACTOR                   |
+-----------------------------------------------------------------------------------+
       ^                    ^                     ^                   ^
       |                    |                     |                   |
+--------------+    +----------------+    +---------------+    +--------------------+
|  Stage 04    |    |   Stage 09     |    |   Stage 11    |    |      Stage 12      |
|Spatial Memory|    |Execution State |    |  Evaluations  |    |Missions & Checkpts |
+--------------+    +----------------+    +---------------+    +--------------------+
```

---

## 2. Fundamental Architectural Invariants

1. **Not a Second Execution Engine**: Stage 13 does not execute tasks, spawn scheduler workers, or replace `goalOrchestrator` or `missionManager`.
2. **Provider Isolation**: Zero direct external provider calls. All AI execution remains strictly behind Stage 07 `executionGateway.execute()`.
3. **Evidence vs. Truth**: The system strictly separates historical observation from universal truth. A single observation never becomes `HIGH` confidence.
4. **Zero Secret Leakage**: All ingested knowledge, claims, facts, and metadata pass through automated credential scrubbers (`Bearer`, `sk-`, `ghp_`, API keys).
5. **No Independent Persistence System**: Extends Stage 09 `executionPersistence.ts` without creating disconnected databases.
6. **Immutable Spatial Foundations**: Stage 03 Blender scene (`c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`), 14 GLBs, and cameras are immutable. HUD extensions are pure DOM overlays with zero additional WebGL draw calls.

---

## 3. The Knowledge Flow Pipeline

Knowledge transitions deterministically through six pipeline phases:

```
RAW EVENTS (Stage 09 / 11 / 12)
    ↓
INGESTION & SANITIZATION (knowledgeIngestionService)
    ↓
RELATION EXTRACTION (knowledgeRelationExtractor)
    ↓
CANONICAL GRAPH MERGE (knowledgeGraph)
    ↓
CONTRADICTION & CONFIDENCE SCORING (knowledgeContradictionService & knowledgeConfidenceService)
    ↓
STRATEGIC CONTEXT & QUERY SUPPORT (strategicContextService & knowledgeQueryService)
```

1. **Ingestion & Sanitization**: Strips secrets, computes deterministic canonical IDs, and links source records.
2. **Relation Extraction**: Deterministically identifies structural edges (e.g. `MISSION_CONTAINS_GOAL`, `GOAL_USED_AGENT`, `AGENT_USED_PROVIDER`, `EXPERIENCE_SUPPORTS_FACT`).
3. **Graph Storage**: Multi-directed graph indexing canonical nodes and edges with deterministic lookup.
4. **Contradiction Detection**: Audits incoming facts against existing facts. If opposing claims are active, generates a `KnowledgeContradiction` record without overwriting history.
5. **Confidence & Decay**: Quantifies evidence count, recency, quality, and consistency using half-life decay.
6. **Decision Context**: Assembles bounded, explainable contexts for new goals and missions, highlighting relevant strategies, risks, and open contradictions.
