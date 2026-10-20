/**
 * AryaOS V1 — Stage 05: Memory Context Engine
 *
 * Computes deterministic multi-dimensional contextual graphs for active memories:
 * direct & reverse relationships, timeline neighbors, shared entities,
 * predecessor decisions, successor events, workflows, artifacts, and unresolved items.
 */

import {
  MemoryRecord,
  MemoryRelationship,
  MemoryEntity,
} from '../types/memory';
import { CommandContext } from '../types/spatialCommand';
import {
  memoryArchiveService,
  STAGE04_MEMORY_DATABASE,
} from './memoryArchiveService';

export const memoryContextService = {
  /**
   * Constructs a comprehensive deterministic context object for a given memory.
   */
  buildContext(memoryId: string | null): CommandContext {
    if (!memoryId) {
      return this.buildSystemGlobalContext();
    }

    const activeMemory = memoryArchiveService.getMemoryById(memoryId) || null;
    if (!activeMemory) {
      return this.buildSystemGlobalContext();
    }

    const activeVitrineId = memoryArchiveService.getVitrineIdByMemoryId(memoryId) || null;

    // 1. Direct Outgoing Relationships
    const directRelationships: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }> = [];
    activeMemory.relationships.forEach((rel) => {
      const target = memoryArchiveService.getMemoryById(rel.targetMemoryId);
      if (target) {
        directRelationships.push({ memory: target, relationship: rel });
      }
    });

    // 2. Reverse Incoming Relationships
    const reverseRelationships: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }> = [];
    STAGE04_MEMORY_DATABASE.forEach((other) => {
      if (other.id !== memoryId) {
        const incoming = other.relationships.find((r) => r.targetMemoryId === memoryId);
        if (incoming) {
          reverseRelationships.push({
            memory: other,
            relationship: {
              targetMemoryId: other.id,
              relationshipType:
                incoming.relationshipType === 'predecessor'
                  ? 'successor'
                  : incoming.relationshipType === 'derived_from'
                  ? 'references'
                  : incoming.relationshipType,
              label: `Referenced by ${other.title}`,
              strength: incoming.strength,
            },
          });
        }
      }
    });

    // 3. Timeline Neighbors
    const timeline = memoryArchiveService.getTimelineContext(memoryId);
    const timelineNeighbors = {
      predecessor: timeline?.predecessor,
      successor: timeline?.successor,
      index: timeline?.chronologicalIndex ?? -1,
      total: timeline?.totalInSequence ?? 0,
    };

    // 4. Shared Entities across the archive
    const entityIds = new Set(activeMemory.entities.map((e) => e.name.toLowerCase()));
    const sharedEntities: MemoryEntity[] = [...activeMemory.entities];

    // 5. Shared Tags
    const sharedTags: string[] = [...activeMemory.tags];

    // 6. Connected Workflows
    const sameWorkflowMemories = STAGE04_MEMORY_DATABASE.filter(
      (m) =>
        m.id !== memoryId &&
        m.type === 'workflow' &&
        (m.tags.some((t) => activeMemory.tags.includes(t)) ||
          activeMemory.relationships.some((r) => r.targetMemoryId === m.id) ||
          m.relationships.some((r) => r.targetMemoryId === memoryId))
    );

    // 7. Related Artifacts
    const relatedArtifacts = STAGE04_MEMORY_DATABASE.filter(
      (m) =>
        m.id !== memoryId &&
        m.type === 'artifact' &&
        (activeMemory.relationships.some((r) => r.targetMemoryId === m.id) ||
          m.relationships.some((r) => r.targetMemoryId === memoryId) ||
          m.tags.some((t) => activeMemory.tags.includes(t)))
    );

    // 8. Predecessor Decisions
    const predecessorDecisions = STAGE04_MEMORY_DATABASE.filter(
      (m) =>
        m.id !== memoryId &&
        m.type === 'decision' &&
        (activeMemory.relationships.some(
          (r) => r.targetMemoryId === m.id && (r.relationshipType === 'derived_from' || r.relationshipType === 'references')
        ) ||
          (activeMemory.createdAt && m.createdAt && new Date(m.createdAt) < new Date(activeMemory.createdAt)))
    ).slice(0, 3);

    // 9. Successor Events
    const successorEvents = STAGE04_MEMORY_DATABASE.filter(
      (m) =>
        m.id !== memoryId &&
        m.type === 'event' &&
        (activeMemory.relationships.some((r) => r.targetMemoryId === m.id && r.relationshipType === 'successor') ||
          (activeMemory.createdAt && m.createdAt && new Date(m.createdAt) > new Date(activeMemory.createdAt)))
    ).slice(0, 3);

    // 10. Same Project memories
    const sameProjectMemories = STAGE04_MEMORY_DATABASE.filter(
      (m) =>
        m.id !== memoryId &&
        (m.tags.includes('horizon') || m.tags.includes('core') || m.tags.includes('genesis')) &&
        (activeMemory.tags.includes('horizon') ||
          activeMemory.tags.includes('core') ||
          activeMemory.tags.includes('genesis'))
    );

    // 11. Unresolved Relationships (strength < 0.85 or tagged as conflict / arbitration)
    const unresolvedRelationships: Array<{
      memory: MemoryRecord;
      relationship: MemoryRelationship;
      reason: string;
    }> = [];

    directRelationships.forEach(({ memory: target, relationship: rel }) => {
      if (rel.strength !== undefined && rel.strength < 0.85) {
        unresolvedRelationships.push({
          memory: target,
          relationship: rel,
          reason: `Relationship strength (${Math.round(rel.strength * 100)}%) below high-confidence threshold (85%)`,
        });
      }
    });

    if (activeMemory.tags.includes('arbitration') || activeMemory.tags.includes('conflict')) {
      directRelationships.forEach(({ memory: target, relationship: rel }) => {
        if (!unresolvedRelationships.some((u) => u.memory.id === target.id)) {
          unresolvedRelationships.push({
            memory: target,
            relationship: rel,
            reason: 'Active arbitration boundary between generative agents',
          });
        }
      });
    }

    return {
      activeMemory,
      activeVitrineId,
      directRelationships,
      reverseRelationships,
      timelineNeighbors,
      sharedEntities,
      sharedTags,
      sameProjectMemories,
      sameWorkflowMemories,
      relatedArtifacts,
      predecessorDecisions,
      successorEvents,
      unresolvedRelationships,
    };
  },

  /**
   * System-wide global context when no specific memory record is selected.
   */
  buildSystemGlobalContext(): CommandContext {
    const unresolved = this.findUnresolvedItems();
    return {
      activeMemory: null,
      activeVitrineId: null,
      directRelationships: [],
      reverseRelationships: [],
      timelineNeighbors: { index: -1, total: STAGE04_MEMORY_DATABASE.length },
      sharedEntities: [],
      sharedTags: [],
      sameProjectMemories: STAGE04_MEMORY_DATABASE.filter((m) => m.type === 'project'),
      sameWorkflowMemories: STAGE04_MEMORY_DATABASE.filter((m) => m.type === 'workflow'),
      relatedArtifacts: STAGE04_MEMORY_DATABASE.filter((m) => m.type === 'artifact'),
      predecessorDecisions: STAGE04_MEMORY_DATABASE.filter((m) => m.type === 'decision').slice(0, 3),
      successorEvents: STAGE04_MEMORY_DATABASE.filter((m) => m.type === 'event').slice(0, 3),
      unresolvedRelationships: unresolved.map((u) => ({
        memory: u.memory,
        relationship: u.relationship,
        reason: u.reason,
      })),
    };
  },

  /**
   * Returns all memories in the archive that have unresolved items, active arbitration,
   * or low-confidence edges.
   */
  findUnresolvedItems(): Array<{
    memory: MemoryRecord;
    relationship: MemoryRelationship;
    reason: string;
  }> {
    const items: Array<{ memory: MemoryRecord; relationship: MemoryRelationship; reason: string }> = [];

    STAGE04_MEMORY_DATABASE.forEach((rec) => {
      // Check for arbitration / conflict tags
      if (rec.tags.includes('arbitration') || rec.tags.includes('conflict')) {
        rec.relationships.forEach((rel) => {
          const target = memoryArchiveService.getMemoryById(rel.targetMemoryId);
          if (target) {
            items.push({
              memory: rec,
              relationship: rel,
              reason: `Unresolved multi-agent arbitration on ${rec.title}`,
            });
          }
        });
      }

      // Check for weak relationship strength
      rec.relationships.forEach((rel) => {
        if (rel.strength !== undefined && rel.strength < 0.85) {
          if (!items.some((i) => i.memory.id === rec.id && i.relationship.targetMemoryId === rel.targetMemoryId)) {
            items.push({
              memory: rec,
              relationship: rel,
              reason: `Confidence weight ${Math.round(rel.strength * 100)}% requires review`,
            });
          }
        }
      });
    });

    return items;
  },

  /**
   * Returns memories associated with unresolved items.
   */
  getUnresolvedMemories(): MemoryRecord[] {
    const unresolved = this.findUnresolvedItems();
    const ids = new Set(unresolved.map((u) => u.memory.id));
    return STAGE04_MEMORY_DATABASE.filter((m) => ids.has(m.id));
  },
};
