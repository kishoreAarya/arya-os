/**
 * AryaOS V1 — Stage 04: Spatial Memory & Intelligence Domain Types
 *
 * Defines the semantic intelligence layer for the Stage 03 Memory Archive,
 * decoupling Three.js spatial representations from semantic memory content.
 */

export type MemoryType =
  | 'project'
  | 'decision'
  | 'conversation'
  | 'workflow'
  | 'artifact'
  | 'event'
  | 'knowledge';

export type MemoryInteractionState =
  | 'IDLE'
  | 'HOVERED'
  | 'SELECTED'
  | 'INSPECTING'
  | 'RELATED_MEMORY'
  | 'RETURN';

export type MemoryFilterType =
  | 'ALL'
  | 'PROJECTS'
  | 'DECISIONS'
  | 'CONVERSATIONS'
  | 'WORKFLOWS'
  | 'ARTIFACTS'
  | 'EVENTS'
  | 'KNOWLEDGE';

export type RelationshipType =
  | 'derived_from'
  | 'related_to'
  | 'predecessor'
  | 'successor'
  | 'references'
  | 'collaborates_with'
  | 'anchored_in';

export interface MemoryEntity {
  id: string;
  name: string;
  type: 'agent' | 'user' | 'model' | 'scene' | 'system' | 'shot';
  role?: string;
}

export interface MemoryRelationship {
  targetMemoryId: string;
  relationshipType: RelationshipType;
  label: string;
  strength?: number; // 0.0 to 1.0
}

export interface MemorySource {
  type: 'agent' | 'user' | 'system' | 'pipeline' | 'external';
  identifier?: string;
  sessionRef?: string;
}

export interface MemoryRecord {
  id: string;
  title: string;
  summary: string;
  type: MemoryType;
  createdAt?: string; // ISO 8601 string or undefined if historical/untimed
  updatedAt?: string;
  importance: number; // 0.0 (low) to 1.0 (critical core)
  tags: string[];
  entities: MemoryEntity[];
  relationships: MemoryRelationship[];
  source: MemorySource;
  metadata?: Record<string, unknown>;
  spatialObjectId?: string; // Maps deterministically to Stage 03 Vitrine ID (e.g. "Dais_Flank_Crystal_01")
}

export interface VitrineMemoryMapping {
  vitrineId: string;
  memoryId: string;
  archetype: 'mountain' | 'neural' | 'city' | 'matrix' | 'chrono';
  sector: 'DAIS_FLANK' | 'PATHWAY' | 'ROTUNDA_INNER';
}

export interface TimelineContext {
  current: MemoryRecord;
  predecessor?: MemoryRecord;
  successor?: MemoryRecord;
  chronologicalIndex: number;
  totalInSequence: number;
  hasTimestamp: boolean;
}
