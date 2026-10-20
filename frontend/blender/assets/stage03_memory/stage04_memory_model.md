# ARYAOS V1 — STAGE 04: SEMANTIC MEMORY MODEL SPECIFICATION

## Domain Model & Architecture Reference

**Version:** 1.0.0-PROD  
**Domain Layer:** `frontend/src/types/memory.ts`  
**Service Implementation:** `frontend/src/services/memoryArchiveService.ts`  

---

## 1. Architectural Philosophy

The Stage 04 Semantic Memory Model is strictly decoupled from the Three.js spatial rendering pipeline. 

### Core Decoupling Principles
1. **Zero Spatial Pollution:** Three.js object nodes only know their spatial instance identifier (`vitrineId`). Semantic metadata, markdown bodies, agent entities, and graph relationships are never attached directly to `THREE.Mesh` or `THREE.Group` userData.
2. **Deterministic Registry:** Every spatial crystal in the 3D environment corresponds permanently and deterministically to a registered memory record. No random generation, dynamic shuffling, or UUID churn per mount.
3. **Graph-Driven Navigation:** Memory items are not isolated entries; they form a directed semantic graph with weighted relationships, predecessor/successor temporal anchors, and entity cross-references.
4. **Backend-Agnostic Abstraction:** The memory service API provides standard contract interfaces allowing seamless transition from static frontend registries to live persistent backend APIs without changing the Three.js scene assembly.

---

## 2. Type Definitions & Schemas

### 2.1 Memory Record (`MemoryRecord`)

```typescript
export interface MemoryRecord {
  id: string;                      // Unique identifier (e.g. 'MEM-0001')
  title: string;                   // Human-readable title
  summary: string;                 // Concise architectural summary
  type: MemoryType;                // Semantic category
  createdAt?: string;              // ISO 8601 timestamp (or undefined if Epoch Zero)
  updatedAt?: string;              // ISO 8601 timestamp
  importance: number;              // Float 0.0 to 1.0 (system priority/weight)
  tags: string[];                  // Searchable keywords
  entities: MemoryEntity[];        // Associated users, agents, and subsystems
  relationships: MemoryRelationship[]; // Outgoing directed semantic edges
  source: MemorySource;            // Origin provenance
  metadata?: Record<string, unknown>; // Domain-specific telemetry
  spatialObjectId?: string;        // Stage 03 Vitrine ID mapping
}
```

### 2.2 Memory Type Taxonomy (`MemoryType`)

```typescript
export type MemoryType =
  | 'project'       // Foundational charters, long-term system milestones
  | 'decision'      // Key technical choices, routing heuristics, arbitration
  | 'conversation'  // Multi-agent dialogue, user alignment sessions
  | 'workflow'      // Generation pipelines, procedural synthesis flows
  | 'artifact'      // Shader specs, topology models, keyframe anchors
  | 'event'         // Stage awakenings, reactor ignition, lifecycle shifts
  | 'knowledge';    // Theoretical models, acoustic profiles, embeddings
```

### 2.3 Associated Entities (`MemoryEntity`)

```typescript
export interface MemoryEntity {
  id: string;
  name: string;
  type: 'agent' | 'user' | 'model' | 'scene' | 'system' | 'shot';
  role?: string;
}
```

### 2.4 Semantic Relationships (`MemoryRelationship`)

```typescript
export type RelationshipType =
  | 'derived_from'      // Branch or specialization of an existing memory
  | 'related_to'        // General semantic correlation
  | 'predecessor'       // Direct chronological or causal precursor
  | 'successor'         // Direct chronological or causal follower
  | 'references'        // Cites or relies upon technical specification
  | 'collaborates_with' // Multi-agent or subsystem co-execution
  | 'anchored_in';      // Physically or spatially anchored to core monument

export interface MemoryRelationship {
  targetMemoryId: string;
  relationshipType: RelationshipType;
  label: string;
  strength?: number;    // Weighting factor 0.0 to 1.0
}
```

### 2.5 Origin Provenance (`MemorySource`)

```typescript
export interface MemorySource {
  type: 'agent' | 'user' | 'system' | 'pipeline' | 'external';
  identifier?: string;
  sessionRef?: string;
}
```

### 2.6 Spatial Vitrine Mapping (`VitrineMemoryMapping`)

```typescript
export interface VitrineMemoryMapping {
  vitrineId: string;
  memoryId: string;
  archetype: 'mountain' | 'neural' | 'city' | 'matrix' | 'chrono';
  sector: 'DAIS_FLANK' | 'PATHWAY' | 'ROTUNDA_INNER';
}
```

### 2.7 Temporal Continuity Context (`TimelineContext`)

```typescript
export interface TimelineContext {
  current: MemoryRecord;
  predecessor?: MemoryRecord;
  successor?: MemoryRecord;
  chronologicalIndex: number;
  totalInSequence: number;
  hasTimestamp: boolean;
}
```

---

## 3. Spatial Sector & Archetype Distribution

The 24 vitrines are partitioned into 3 distinct architectural sectors:

```
                      [ ROTUNDA INNER ]
                     (4 Central Vitrines)
                   MEM-0021 ... MEM-0024
                             |
                   +---------+---------+
                   |                   |
            [ DAIS FLANK ]      [ PATHWAY ]
          (8 Grand Vitrines) (12 Processional Vitrines)
         MEM-0001 ... MEM-0008  MEM-0009 ... MEM-0020
```

### 3.1 Dais Flank Sector (8 Vitrines)
- **Role:** High-importance architectural charters, system routing matrices, and fundamental decisions.
- **Vitrine IDs:** `Dais_Flank_Crystal_01` through `08`.
- **Primary Archetypes:** Mountain (2), Neural (2), City (2), Matrix (1), Chrono (1).

### 3.2 Pathway Sector (12 Vitrines)
- **Role:** Concrete workflows, synthesis pipelines, keyframe interpolations, and agent arbitration logs.
- **Vitrine IDs:** `Pathway_Memory_Crystal_01` through `12`.
- **Primary Archetypes:** Mountain (3), Neural (3), City (2), Matrix (2), Chrono (2).

### 3.3 Rotunda Inner Sector (4 Vitrines)
- **Role:** Genesis events, Epoch Zero, core kinetic reactor ignition, and orbital sanctuary horizons.
- **Vitrine IDs:** `Rotunda_Inner_Crystal_01` through `04`.
- **Primary Archetypes:** City (1), Matrix (1), Chrono (1), Mountain (1).

---

## 4. Graph Resolution Heuristics

The `memoryArchiveService.getRelatedMemories(memoryId)` algorithm operates bidirectionally:
1. **Direct Outgoing Traversal:** Evaluates origin's `relationships` array, fetching target records by ID.
2. **Reverse Incoming Traversal:** Scans the database for other records whose `relationships` point back to the origin, synthesizing the converse relationship (e.g. `predecessor` $\rightarrow$ `successor`, `derived_from` $\rightarrow$ `references`).
3. **De-duplication:** Tracks visited IDs via a Set to prevent circular graph self-references.

---

## 5. Future Backend Adapter Specification

When connecting live backend memory archives, the service contract remains identical:

```typescript
export interface IMemoryArchiveAdapter {
  fetchMemories(): Promise<MemoryRecord[]>;
  fetchMemoryById(id: string): Promise<MemoryRecord | null>;
  searchMemories(query: string, filter: MemoryFilterType): Promise<MemoryRecord[]>;
  createMemoryRecord(record: Omit<MemoryRecord, 'id'>): Promise<MemoryRecord>;
  linkSpatialVitrine(vitrineId: string, memoryId: string): Promise<VitrineMemoryMapping>;
}
```
Because the spatial presentation layer only depends on `memoryArchiveService`, substituting an HTTP/WebSocket client requires zero alterations to the Three.js scene assembly or shaders.
