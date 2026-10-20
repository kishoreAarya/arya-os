/**
 * AryaOS V1 — Stage 10: Objective Quality Gate Engine
 *
 * Enforces concrete, deterministic verification of task outputs against explicit criteria.
 * Rejects subjective hand-waving; LLM evaluation scores are NEVER represented as ground truth.
 */

import { AgentTask, QualityRequirementLevel } from '../types/agentCoordination';

export interface QualityEvaluationResult {
  passed: boolean;
  level: QualityRequirementLevel;
  issues: string[];
  humanReviewRequired: boolean;
  evaluatorIdentity: string;
  evaluatedAt: string;
}

export const qualityGate = {
  /**
   * Evaluates task execution output against the declared quality requirement.
   */
  evaluate(
    task: AgentTask,
    output: string | undefined,
    structuredOutput?: Record<string, unknown>,
    latencyMs?: number
  ): QualityEvaluationResult {
    const issues: string[] = [];
    const level = task.qualityRequirement || 'QUALITY_STANDARD';
    const evaluatorIdentity = 'AryaOS-Deterministic-QualityGate-v1';
    const evaluatedAt = new Date().toISOString();

    // 1. Mandatory Baseline Check (Applies to all levels)
    if (!output || output.trim().length === 0) {
      issues.push('Output payload is empty or whitespace-only.');
      return {
        passed: false,
        level,
        issues,
        humanReviewRequired: false,
        evaluatorIdentity,
        evaluatedAt,
      };
    }

    // 2. Specific Level Rules
    switch (level) {
      case 'QUALITY_LOW': {
        // Just needs non-empty content
        break;
      }

      case 'QUALITY_STANDARD': {
        if (output.trim().length < 15) {
          issues.push('Output length is below standard threshold (minimum 15 characters).');
        }
        // Check for expected output contract fields if specified
        if (task.expectedOutputContract && Object.keys(task.expectedOutputContract).length > 0) {
          if (!structuredOutput) {
            issues.push('Task specifies an expected output contract but no structured output was delivered.');
          } else {
            for (const requiredKey of Object.keys(task.expectedOutputContract)) {
              if (structuredOutput[requiredKey] === undefined) {
                issues.push(`Structured output missing declared contract key '${requiredKey}'.`);
              }
            }
          }
        }
        break;
      }

      case 'QUALITY_HIGH': {
        if (output.trim().length < 40) {
          issues.push('Output length is below high-quality threshold (minimum 40 characters).');
        }
        if (latencyMs && latencyMs < 50) {
          issues.push('Suspiciously instantaneous execution (<50ms) for high-quality required task.');
        }
        if (task.expectedOutputContract && Object.keys(task.expectedOutputContract).length > 0) {
          if (!structuredOutput) {
            issues.push('High-quality task missing expected structured output schema.');
          } else {
            for (const requiredKey of Object.keys(task.expectedOutputContract)) {
              if (structuredOutput[requiredKey] === undefined) {
                issues.push(`Structured output missing declared contract key '${requiredKey}'.`);
              }
            }
          }
        }
        break;
      }

      case 'HUMAN_REVIEW': {
        return {
          passed: true,
          level,
          issues: ['Task is explicitly designated for human review before final acceptance.'],
          humanReviewRequired: true,
          evaluatorIdentity,
          evaluatedAt,
        };
      }
    }

    return {
      passed: issues.length === 0,
      level,
      issues,
      humanReviewRequired: false,
      evaluatorIdentity,
      evaluatedAt,
    };
  },
};
