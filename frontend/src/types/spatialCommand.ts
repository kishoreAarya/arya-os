/**
 * AryaOS V1 — Stage 05: Spatial Intelligence Command Layer Types
 *
 * Defines the operational interface evolving Memory Archive from:
 * MEMORY -> CONTEXT -> DECISION -> ACTION -> RESULT -> MEMORY
 *
 * Fully decoupled from the Three.js spatial rendering pipeline.
 */

import {
  MemoryRecord,
  MemoryRelationship,
  MemoryEntity,
  MemoryType,
} from './memory';

export type CommandIntentType =
  | 'QUERY_MEMORY'
  | 'SHOW_RELATED'
  | 'TRACE_HISTORY'
  | 'RECENT_CHANGES'
  | 'FIND_DECISIONS'
  | 'SHOW_WORKFLOWS'
  | 'SHOW_ARTIFACTS'
  | 'SHOW_UNRESOLVED'
  | 'OPEN_MEMORY'
  | 'INSPECT_DEPENDENCIES'
  | 'CREATE_RESEARCH_TASK'
  | 'GENERATE_PRODUCTION_PLAN'
  | 'ORCHESTRATE_GOAL'
  | 'SWITCH_CAMERA'
  | 'CLEAR_FILTERS'
  | 'UNKNOWN';

export interface CommandEntity {
  id: string;
  name: string;
  type: 'memory' | 'vitrine' | 'agent' | 'user' | 'system' | 'sector' | 'tag' | 'type' | 'camera';
  resolvedRecord?: MemoryRecord;
}

export interface CommandContext {
  activeMemory: MemoryRecord | null;
  activeVitrineId: string | null;
  directRelationships: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }>;
  reverseRelationships: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }>;
  timelineNeighbors: {
    predecessor?: MemoryRecord;
    successor?: MemoryRecord;
    index: number;
    total: number;
  };
  sharedEntities: MemoryEntity[];
  sharedTags: string[];
  sameProjectMemories: MemoryRecord[];
  sameWorkflowMemories: MemoryRecord[];
  relatedArtifacts: MemoryRecord[];
  predecessorDecisions: MemoryRecord[];
  successorEvents: MemoryRecord[];
  unresolvedRelationships: Array<{
    memory: MemoryRecord;
    relationship: MemoryRelationship;
    reason: string;
  }>;
}

export type ActionClass =
  | 'RESEARCH'
  | 'CREATE_WORKFLOW'
  | 'CREATE_ARTIFACT'
  | 'OPEN_MEMORY'
  | 'TRACE_MEMORY'
  | 'FILTER_MEMORY'
  | 'NAVIGATE_MEMORY'
  | 'CREATE_TASK'
  | 'SWITCH_CAMERA';

export type ExecutionType = 'FRONTEND_DIRECT' | 'BACKEND_ADAPTER';

export type ActionStatus =
  | 'PROPOSED'
  | 'CONFIRMED'
  | 'CANCELLED'
  | 'PLANNED'
  | 'EXECUTED'
  | 'FAILED';

export interface ActionProposal {
  id: string;
  actionClass: ActionClass;
  title: string;
  description: string;
  sourceMemoryId?: string;
  sourceMemoryTitle?: string;
  targetMemoryId?: string;
  targetVitrineId?: string;
  targetCamera?: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail';
  contextSummary: {
    relatedCount: number;
    entitiesCount: number;
    decisionsCount: number;
    notes?: string;
  };
  executionType: ExecutionType;
  status: ActionStatus;
  createdAt: string;
  payload?: Record<string, unknown>;
}

export interface MemoryEvent {
  id: string;
  type: string;
  sourceMemoryId?: string;
  sourceMemoryTitle?: string;
  action: ActionClass;
  timestamp: string;
  status: 'EXECUTED' | 'PLANNED' | 'RECORDED';
  resultSummary: string;
  relatedEntities: string[];
  metadata?: Record<string, unknown>;
}

export interface ActionResult {
  actionId: string;
  success: boolean;
  status: 'EXECUTED' | 'PLANNED' | 'CANCELLED' | 'FAILED';
  message: string;
  outputData?: Record<string, unknown>;
  memoryEvent?: MemoryEvent;
  timestamp: string;
}

export interface Command {
  id: string;
  rawInput: string;
  timestamp: string;
  intent: CommandIntentType;
  entities: CommandEntity[];
  targetMemoryId?: string;
  targetVitrineId?: string;
  targetSector?: 'DAIS_FLANK' | 'PATHWAY' | 'ROTUNDA_INNER' | 'ALL';
  targetCamera?: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail';
  explanation: string;
  context?: CommandContext;
  actionProposal?: ActionProposal;
}

export type SpatialCommandState =
  | 'IDLE'
  | 'HOVERED'
  | 'SELECTED'
  | 'INSPECTING'
  | 'RELATED_MEMORY'
  | 'COMMANDING'
  | 'PROPOSING_ACTION'
  | 'CONFIRMING'
  | 'EXECUTING'
  | 'RESULT'
  | 'MEMORY_UPDATED'
  | 'RETURN';
