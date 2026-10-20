/**
 * AryaOS V1 — Stage 06: Context Packaging Layer
 *
 * Selects, filters, compresses, and structures relevant spatial memory graph data
 * into provider-ready context packages without blindly dumping raw records.
 */

import { CommandContext, ActionProposal } from '../types/spatialCommand';
import { ContextPackage, ContextPackageItem } from '../types/intelligenceProvider';

export interface ContextPackageOptions {
  maxMemories?: number;
  maxSummaryChars?: number;
  customSystemPrompt?: string;
}

export const contextPackager = {
  /**
   * Packages a CommandContext into a structured ContextPackage tailored for an intelligence provider.
   */
  packageContext(
    context: CommandContext | undefined,
    proposal: ActionProposal,
    options: ContextPackageOptions = {}
  ): ContextPackage {
    const maxMemories = options.maxMemories || 8;
    const maxSummaryChars = options.maxSummaryChars || 280;

    // 1. System Context
    const systemContext =
      options.customSystemPrompt ||
      'You are AryaOS Spatial Intelligence, an autonomous cognitive orchestration platform. ' +
        'Operate strictly within verified memory context. Anchor conclusions to architectural history and causal graph lineage.';

    // 2. Task Context
    const taskContext = `Action: ${proposal.actionClass} | Title: ${proposal.title} | Objective: ${proposal.description}`;

    // 3. Relevant Memory Selection & Compression
    const selectedItems: ContextPackageItem[] = [];
    const seenIds = new Set<string>();

    // Priority 1: Active Memory
    if (context?.activeMemory) {
      selectedItems.push({
        id: context.activeMemory.id,
        title: context.activeMemory.title,
        summary: this.compressText(context.activeMemory.summary, maxSummaryChars),
        type: context.activeMemory.type,
        relevanceScore: 1.0,
      });
      seenIds.add(context.activeMemory.id);
    }

    // Priority 2: Direct Relationships
    if (context?.directRelationships) {
      for (const rel of context.directRelationships) {
        if (selectedItems.length >= maxMemories) break;
        if (!seenIds.has(rel.memory.id)) {
          selectedItems.push({
            id: rel.memory.id,
            title: rel.memory.title,
            summary: this.compressText(rel.memory.summary, maxSummaryChars),
            type: rel.memory.type,
            relevanceScore: 0.85,
          });
          seenIds.add(rel.memory.id);
        }
      }
    }

    // Priority 3: Predecessor Decisions (Critical for architectural reasoning)
    if (context?.predecessorDecisions) {
      for (const dec of context.predecessorDecisions) {
        if (selectedItems.length >= maxMemories) break;
        if (!seenIds.has(dec.id)) {
          selectedItems.push({
            id: dec.id,
            title: dec.title,
            summary: this.compressText(dec.summary, maxSummaryChars),
            type: dec.type,
            relevanceScore: 0.75,
          });
          seenIds.add(dec.id);
        }
      }
    }

    // Priority 4: Same Project / Same Workflow
    const contextualPool = [
      ...(context?.sameProjectMemories || []),
      ...(context?.sameWorkflowMemories || []),
    ];
    for (const mem of contextualPool) {
      if (selectedItems.length >= maxMemories) break;
      if (!seenIds.has(mem.id)) {
        selectedItems.push({
          id: mem.id,
          title: mem.title,
          summary: this.compressText(mem.summary, maxSummaryChars),
          type: mem.type,
          relevanceScore: 0.6,
        });
        seenIds.add(mem.id);
      }
    }

    // 4. Entity Context
    const entities: Array<{ name: string; type: string }> = [];
    if (context?.sharedEntities) {
      context.sharedEntities.forEach((e) => {
        entities.push({ name: e.name, type: e.type });
      });
    }
    if (context?.activeMemory?.entities) {
      context.activeMemory.entities.forEach((e) => {
        if (!entities.some((existing) => existing.name === e.name)) {
          entities.push({ name: e.name, type: e.type });
        }
      });
    }

    // 5. Timeline Context
    let timelineContext: { predecessor?: string; successor?: string } | undefined;
    if (context?.timelineNeighbors?.predecessor || context?.timelineNeighbors?.successor) {
      timelineContext = {
        predecessor: context.timelineNeighbors.predecessor
          ? `${context.timelineNeighbors.predecessor.id}: ${context.timelineNeighbors.predecessor.title}`
          : undefined,
        successor: context.timelineNeighbors.successor
          ? `${context.timelineNeighbors.successor.id}: ${context.timelineNeighbors.successor.title}`
          : undefined,
      };
    }

    // 6. User Input
    const userInput = proposal.title;

    // 7. Token Estimation
    const totalChars =
      systemContext.length +
      taskContext.length +
      selectedItems.reduce((acc, item) => acc + item.title.length + item.summary.length, 0) +
      entities.reduce((acc, ent) => acc + ent.name.length, 0) +
      userInput.length;
    const tokenEstimate = Math.ceil(totalChars / 4);

    return {
      systemContext,
      taskContext,
      memoryContext: selectedItems,
      entityContext: entities.slice(0, 10),
      timelineContext,
      userInput,
      tokenEstimate,
    };
  },

  /**
   * Compresses long summaries to fit within token boundaries.
   */
  compressText(text: string, maxChars: number): string {
    if (!text) return '';
    const clean = text.replace(/\s+/g, ' ').trim();
    if (clean.length <= maxChars) return clean;
    return clean.slice(0, maxChars - 3) + '...';
  },
};
