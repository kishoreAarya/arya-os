/**
 * AryaOS V1 — Stage 08: Goal Interpreter
 *
 * Transforms high-level natural language goals into structured Goal specifications,
 * grounding them in spatial memory context and existing project constraints.
 */

import { Goal, GoalStatus } from '../types/goalOrchestration';
import { memoryContextService } from './memoryContextService';
import { memoryArchiveService } from './memoryArchiveService';
import { resultNormalizer } from './resultNormalizer';

export class GoalInterpreter {
  /**
   * Interprets user intent into a formal Goal specification.
   */
  public interpret(
    userIntent: string,
    targetMemoryId?: string,
    operatorId: string = 'operator-primary'
  ): Goal {
    const timestamp = new Date().toISOString();
    const sanitizedIntent = resultNormalizer.sanitizeText(userIntent);
    const goalId = `GOAL-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

    // Resolve memory context if targeted or default to primary anchor
    const effectiveMemoryId = targetMemoryId || 'MEM-0001';
    const memory = memoryArchiveService.getMemoryById(effectiveMemoryId);
    const memoryContext = memoryContextService.buildContext(effectiveMemoryId);

    // Extract objective and constraints
    const { objective, constraints, completionCriteria, priority, requiresApproval } =
      this.analyzeIntent(sanitizedIntent, memory?.title);

    const goal: Goal = {
      goalId,
      userIntent: sanitizedIntent,
      objective,
      constraints,
      priority,
      status: 'PLANNING',
      createdAt: timestamp,
      updatedAt: timestamp,
      currentPlanVersion: 0,
      plans: [],
      completionCriteria,
      approvalPolicy: {
        requireApprovalForConsequential: requiresApproval,
        autoApproveReadOnly: true,
      },
      contextRequirements: {
        targetMemoryId: effectiveMemoryId,
        contextMemories: [
          effectiveMemoryId,
          ...(memoryContext?.directRelationships || []).map((r) => r.memory.id),
        ].slice(0, 5),
        entityNames: (memoryContext?.sharedEntities || []).map((e) => e.name),
      },
      provenance: {
        sourceMemoryId: effectiveMemoryId,
        sourceMemoryTitle: memory?.title || 'System Core Architecture',
        commandText: sanitizedIntent,
        operatorId,
        createdAt: timestamp,
      },
    };

    return goal;
  }

  /**
   * Deterministic semantic decomposition of natural language intents.
   */
  private analyzeIntent(
    intent: string,
    anchorTitle?: string
  ): {
    objective: string;
    constraints: string[];
    completionCriteria: string[];
    priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    requiresApproval: boolean;
  } {
    const lower = intent.toLowerCase();

    // 1. Research & Production Brief
    if (lower.includes('production brief') || lower.includes('concept') || lower.includes('brief')) {
      return {
        objective: `Formulate a production-ready architectural concept and brief grounded in ${anchorTitle || 'AryaOS core architecture'}.`,
        constraints: [
          'Maintain continuity with locked Stage 03 Memory Archive',
          'Strict ACESFilmic visual language and cinematic tone',
          'Uphold OpenMontage / AryaOS decoupled orchestration boundary',
        ],
        completionCriteria: [
          'Architectural context thoroughly researched and validated',
          'Structured concept brief compiled with timeline and dependency milestones',
          'Output verified with zero secret leakage and validated confidence',
        ],
        priority: 'HIGH',
        requiresApproval: true,
      };
    }

    // 2. Video / Media Generation
    if (lower.includes('video') || lower.includes('shot') || lower.includes('animation')) {
      return {
        objective: `Compile a cinematic multi-shot video production plan for ${anchorTitle || 'selected memory'}.`,
        constraints: [
          'Conform to 30 FPS camera timeline standards',
          'Preserve Stage 03 lighting distribution and shader assets',
        ],
        completionCriteria: [
          'Keyframe visual continuity verified',
          'Shot list and prompt envelope compiled',
        ],
        priority: 'MEDIUM',
        requiresApproval: true,
      };
    }

    // 3. General Research & Analysis
    return {
      objective: `Perform comprehensive architectural analysis and synthesis for: "${intent}".`,
      constraints: [
        'Reference active memory relationships and decision history',
        'Verify zero simulated output',
      ],
      completionCriteria: [
        'Complete context synthesis produced',
        'Downstream memory events registered',
      ],
      priority: 'MEDIUM',
      requiresApproval: false,
    };
  }
}

export const goalInterpreter = new GoalInterpreter();
