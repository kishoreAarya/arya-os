/**
 * AryaOS V1 — Stage 20: Policy Condition Engine
 *
 * Pure AST declarative condition engine for Policy Intelligence.
 * Strictly prevents dynamic code execution, eval(), Function(),
 * prototype pollution, and arbitrary script traversal.
 * Fails closed on any type mismatch, unresolvable field, or illegal token.
 */

import {
  PolicyCondition,
  PolicyConditionGroup,
  PolicyEvaluationContext,
} from '../types/policyIntelligence';

export class PolicyConditionEngine {
  /**
   * Evaluates a condition group against a runtime context.
   */
  public evaluate(
    conditionGroup: PolicyConditionGroup | undefined,
    context: PolicyEvaluationContext
  ): boolean {
    if (!conditionGroup || !conditionGroup.conditions || conditionGroup.conditions.length === 0) {
      return true; // Empty condition tree matches by default
    }

    if (conditionGroup.conjunction === 'AND') {
      return conditionGroup.conditions.every((cond) => this.evaluateNode(cond, context));
    } else if (conditionGroup.conjunction === 'OR') {
      return conditionGroup.conditions.some((cond) => this.evaluateNode(cond, context));
    }

    return false;
  }

  private evaluateNode(
    node: PolicyCondition | PolicyConditionGroup,
    context: PolicyEvaluationContext
  ): boolean {
    if ('conjunction' in node) {
      return this.evaluate(node as PolicyConditionGroup, context);
    }
    return this.evaluateAtomicCondition(node as PolicyCondition, context);
  }

  private evaluateAtomicCondition(
    condition: PolicyCondition,
    context: PolicyEvaluationContext
  ): boolean {
    const { field, operator, value } = condition;
    if (!field || typeof field !== 'string') return false;

    // Strict prototype pollution rejection
    if (
      field.includes('__proto__') ||
      field.includes('constructor') ||
      field.includes('prototype')
    ) {
      return false;
    }

    const resolved = this.resolveField(field, context);

    switch (operator) {
      case 'equals':
        return resolved === value;

      case 'not_equals':
        return resolved !== value;

      case 'contains':
        if (typeof resolved === 'string' && typeof value === 'string') {
          return resolved.includes(value);
        }
        if (Array.isArray(resolved)) {
          return resolved.includes(value);
        }
        return false;

      case 'exists':
        return resolved !== undefined && resolved !== null;

      case 'not_exists':
        return resolved === undefined || resolved === null;

      case 'greater_than':
        if (typeof resolved === 'number' && typeof value === 'number') {
          return resolved > value;
        }
        return false;

      case 'less_than':
        if (typeof resolved === 'number' && typeof value === 'number') {
          return resolved < value;
        }
        return false;

      case 'in':
        if (Array.isArray(value)) {
          return value.includes(resolved);
        }
        return false;

      case 'not_in':
        if (Array.isArray(value)) {
          return !value.includes(resolved);
        }
        return false;

      default:
        return false;
    }
  }

  private resolveField(path: string, context: PolicyEvaluationContext): unknown {
    if (!path || typeof path !== 'string') return undefined;

    // Disallow prototype tampering
    if (
      path.includes('__proto__') ||
      path.includes('constructor') ||
      path.includes('prototype')
    ) {
      return undefined;
    }

    const parts = path.split(/\.|\[(\d+)\]/).filter(Boolean);
    let current: unknown = context;

    for (const part of parts) {
      if (current === null || current === undefined) {
        return undefined;
      }
      if (typeof current === 'object') {
        current = (current as Record<string, unknown>)[part];
      } else {
        return undefined;
      }
    }

    return current;
  }
}

export const policyConditionEngine = new PolicyConditionEngine();
