/**
 * AryaOS V1 — Stage 05: Command Parser
 *
 * Interprets natural language operator commands, resolves semantic entities,
 * and formulates structured Command objects for action orchestration.
 */

import {
  Command,
  CommandIntentType,
  CommandEntity,
} from '../types/spatialCommand';
import {
  memoryArchiveService,
  STAGE04_MEMORY_DATABASE,
  VITRINE_MAPPING_REGISTRY,
} from './memoryArchiveService';
import { memoryContextService } from './memoryContextService';

export const commandParser = {
  /**
   * Parses natural language input into a structured Command with resolved entities and intent.
   */
  parse(rawInput: string, activeMemoryId?: string | null): Command {
    const trimmed = (rawInput || '').trim();
    const timestamp = new Date().toISOString();
    const id = `CMD-${Date.now()}`;

    if (!trimmed) {
      return {
        id,
        rawInput: '',
        timestamp,
        intent: 'UNKNOWN',
        entities: [],
        explanation: 'Command input is empty. Type a command or question to interact with the Memory Archive.',
      };
    }

    const lower = trimmed.toLowerCase();

    // 1. Resolve Entities from archive
    const entities = this.resolveEntities(lower);

    // 2. Identify Intent & Directives
    let intent: CommandIntentType = 'UNKNOWN';
    let explanation = '';
    let targetMemoryId: string | undefined = activeMemoryId || undefined;
    let targetVitrineId: string | undefined;
    let targetSector: 'DAIS_FLANK' | 'PATHWAY' | 'ROTUNDA_INNER' | 'ALL' | undefined;
    let targetCamera: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail' | undefined;

    // Direct entity reference override
    const memoryEntity = entities.find((e) => e.type === 'memory');
    if (memoryEntity && memoryEntity.resolvedRecord) {
      targetMemoryId = memoryEntity.resolvedRecord.id;
      targetVitrineId = memoryEntity.resolvedRecord.spatialObjectId;
    }

    const vitrineEntity = entities.find((e) => e.type === 'vitrine');
    if (vitrineEntity) {
      targetVitrineId = vitrineEntity.name;
      const mem = memoryArchiveService.getMemoryByVitrineId(targetVitrineId);
      if (mem) targetMemoryId = mem.id;
    }

    // Orchestrate Goal (Highest precedence for autonomous multi-step goals)
    if (
      lower.startsWith('goal:') ||
      lower.startsWith('orchestrate:') ||
      lower.includes('orchestrate goal') ||
      lower.includes('autonomous goal') ||
      lower.includes('execute goal')
    ) {
      intent = 'ORCHESTRATE_GOAL';
      explanation = targetMemoryId
        ? `Initiating autonomous goal orchestration engine anchored to ${targetMemoryId}.`
        : 'Initiating autonomous goal orchestration engine from current memory context.';
    }

    // Camera Switch Commands
    else if (
      lower.includes('camera') ||
      lower.includes('hero view') ||
      lower.includes('monumental view') ||
      lower.includes('detail view')
    ) {
      intent = 'SWITCH_CAMERA';
      if (lower.includes('monumental') || lower.includes('low angle')) {
        targetCamera = 'CAM_MonumentalLowAngle';
        explanation = 'Transitioning spatial viewport to CAM_MonumentalLowAngle colonnade perspective.';
      } else if (lower.includes('detail') || lower.includes('close')) {
        targetCamera = 'CAM_ArchiveDetail';
        explanation = 'Transitioning spatial viewport to CAM_ArchiveDetail vitrine perspective.';
      } else {
        targetCamera = 'CAM_CinematicHero';
        explanation = 'Transitioning spatial viewport to CAM_CinematicHero master establishing view.';
      }
    }

    // Create Research Task (High precedence)
    else if (
      lower.includes('research task') ||
      lower.includes('create a research') ||
      lower.includes('research this') ||
      lower.includes('create research')
    ) {
      intent = 'CREATE_RESEARCH_TASK';
      explanation = targetMemoryId
        ? `Formulating research task proposal anchored to ${targetMemoryId}.`
        : 'Formulating research task proposal from current memory context.';
    }

    // Generate Production Plan (High precedence)
    else if (
      lower.includes('production plan') ||
      lower.includes('generate a production') ||
      lower.includes('generate plan') ||
      lower.includes('production sequence')
    ) {
      intent = 'GENERATE_PRODUCTION_PLAN';
      explanation = targetMemoryId
        ? `Synthesizing production shot plan based on decision constraints in ${targetMemoryId}.`
        : 'Synthesizing production shot plan based on memory archive.';
    }

    // Inspect Dependencies (High precedence)
    else if (
      lower.includes('depend') ||
      lower.includes('dependencies') ||
      lower.includes('what depends on') ||
      lower.includes('predecessor') ||
      lower.includes('predecessors') ||
      lower.includes('successor')
    ) {
      intent = 'INSPECT_DEPENDENCIES';
      explanation = targetMemoryId
        ? `Resolving upstream predecessors and downstream successors for ${targetMemoryId}.`
        : 'Resolving global dependency graph for core charter and routing matrix.';
    }

    // Trace History
    else if (
      lower.includes('trace history') ||
      lower.includes('trace the history') ||
      lower.includes('history of this') ||
      lower.includes('timeline trace')
    ) {
      intent = 'TRACE_HISTORY';
      explanation = targetMemoryId
        ? `Tracing chronological causal chain and dependencies for ${targetMemoryId}.`
        : 'Tracing overall system lineage from Genesis to Astrolabe Core.';
    }

    // Show Related
    else if (
      lower.includes('show related') ||
      lower.includes('everything related to') ||
      lower.includes('related memories') ||
      lower.includes('show connections')
    ) {
      intent = 'SHOW_RELATED';
      explanation = targetMemoryId
        ? `Highlighting all semantic edges and associated vitrines connected to ${targetMemoryId}.`
        : 'Highlighting interconnected clusters across the spatial archive.';
    }

    // Recent Changes
    else if (
      lower.includes('recent') ||
      lower.includes('what changed') ||
      lower.includes('latest events') ||
      lower.includes('newest')
    ) {
      intent = 'RECENT_CHANGES';
      explanation = 'Retrieving the most recently anchored architectural decisions, events, and milestones.';
    }

    // Show Workflows
    else if (
      lower.includes('workflow') ||
      lower.includes('workflows connected') ||
      lower.includes('show workflows') ||
      lower.includes('pipelines')
    ) {
      intent = 'SHOW_WORKFLOWS';
      explanation = 'Extracting procedural generation workflows and execution pipelines.';
    }

    // Show Artifacts
    else if (
      lower.includes('artifact') ||
      lower.includes('artifacts generated') ||
      lower.includes('show artifacts')
    ) {
      intent = 'SHOW_ARTIFACTS';
      explanation = 'Filtering for concrete topological, material, and keyframe artifacts.';
    }

    // Show Unresolved Items
    else if (
      lower.includes('unresolved') ||
      lower.includes('unresolved items') ||
      lower.includes('pending') ||
      lower.includes('conflicts')
    ) {
      intent = 'SHOW_UNRESOLVED';
      explanation = 'Isolating memories with active multi-agent arbitration, conflict tags, or confidence < 85%.';
    }

    // Open Memory
    else if (
      lower.startsWith('open ') ||
      lower.includes('open memory') ||
      lower.includes('inspect memory') ||
      lower.includes('view memory') ||
      lower.includes('open the most recent')
    ) {
      intent = 'OPEN_MEMORY';
      if (!targetMemoryId) {
        // If not specified, pick most recent or first matching
        targetMemoryId = memoryEntity?.resolvedRecord?.id || 'MEM-0021';
      }
      explanation = `Opening semantic inspection drawer for memory record ${targetMemoryId}.`;
    }

    // Find Decisions (Evaluated after specific actions on decisions)
    else if (
      lower.includes('decision') ||
      lower.includes('decisions related') ||
      lower.includes('find decisions')
    ) {
      intent = 'FIND_DECISIONS';
      explanation = 'Filtering archive to architectural and autonomous arbitration decisions.';
    }

    // Clear Filters / Show All
    else if (
      lower.includes('clear') ||
      lower.includes('reset') ||
      lower.includes('show all') ||
      lower === 'all'
    ) {
      intent = 'CLEAR_FILTERS';
      explanation = 'Clearing spatial highlights and category filters to show the entire 24-vitrine archive.';
    }

    // General Query Memory (Fallback search)
    else if (entities.length > 0 || trimmed.length > 2) {
      intent = 'QUERY_MEMORY';
      explanation = `Searching spatial memory records matching "${trimmed}".`;
    } else {
      intent = 'UNKNOWN';
      explanation = `Command "${trimmed}" could not be recognized. Try "Show related memories", "Trace history", "Show unresolved", or "Switch camera".`;
    }

    // Build context
    const context = memoryContextService.buildContext(targetMemoryId || null);

    return {
      id,
      rawInput: trimmed,
      timestamp,
      intent,
      entities,
      targetMemoryId,
      targetVitrineId: targetVitrineId || (targetMemoryId ? memoryArchiveService.getVitrineIdByMemoryId(targetMemoryId) : undefined),
      targetSector,
      targetCamera,
      explanation,
      context,
    };
  },

  /**
   * Resolves mentioned entities (records, vitrines, agents, sectors, cameras) from raw text.
   */
  resolveEntities(rawInput: string): CommandEntity[] {
    const lower = (rawInput || '').toLowerCase();
    const results: CommandEntity[] = [];

    // 1. Check exact memory IDs (MEM-0001 .. MEM-0024)
    const memIdMatch = lower.match(/\bmem-\d{4}\b/);
    if (memIdMatch) {
      const idUpper = memIdMatch[0].toUpperCase();
      const rec = memoryArchiveService.getMemoryById(idUpper);
      if (rec) {
        results.push({
          id: rec.id,
          name: rec.title,
          type: 'memory',
          resolvedRecord: rec,
        });
      }
    }

    // 2. Check Memory Record Title keywords
    STAGE04_MEMORY_DATABASE.forEach((rec) => {
      const titleLower = rec.title.toLowerCase();
      // Match key distinctive terms
      const keyTerms = ['horizon', 'lineage', 'astrolabe', 'epoch zero', 'awakening', 'arbitration', 'acoustic', 'obsidian', 'terrain', 'lighting'];
      for (const term of keyTerms) {
        if (titleLower.includes(term) && lower.includes(term)) {
          if (!results.some((e) => e.id === rec.id)) {
            results.push({
              id: rec.id,
              name: rec.title,
              type: 'memory',
              resolvedRecord: rec,
            });
          }
          break;
        }
      }
    });

    // 3. Check Vitrine IDs
    VITRINE_MAPPING_REGISTRY.forEach((v) => {
      if (lower.includes(v.vitrineId.toLowerCase())) {
        const mem = memoryArchiveService.getMemoryById(v.memoryId);
        results.push({
          id: v.vitrineId,
          name: v.vitrineId,
          type: 'vitrine',
          resolvedRecord: mem,
        });
      }
    });

    // 4. Check Agents & Users
    const agents = ['orchestrator agent', 'script agent', 'video agent', 'sound resolver', 'continuity engine', 'arbitration gateway', 'director persona', 'lead architect', 'arya core'];
    agents.forEach((agent) => {
      if (lower.includes(agent)) {
        results.push({
          id: agent.replace(/\s+/g, '-'),
          name: agent.toUpperCase(),
          type: agent.includes('persona') || agent.includes('architect') ? 'user' : 'agent',
        });
      }
    });

    // 5. Check Camera mentions
    if (lower.includes('hero')) {
      results.push({ id: 'CAM_CinematicHero', name: 'Cinematic Hero Camera', type: 'camera' });
    }
    if (lower.includes('monumental')) {
      results.push({ id: 'CAM_MonumentalLowAngle', name: 'Monumental Low Angle Camera', type: 'camera' });
    }
    if (lower.includes('detail')) {
      results.push({ id: 'CAM_ArchiveDetail', name: 'Archive Detail Camera', type: 'camera' });
    }

    return results;
  },
};
