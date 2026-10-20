/**
 * AryaOS V1 — Stage 19: Declarative Trigger Condition Engine
 *
 * Evaluates trigger event filters and declarative condition trees against a
 * bounded TriggerEvaluationContext without arbitrary JavaScript execution.
 *
 * SECURITY INVARIANT:
 * - Pure declarative evaluation
 * - Zero eval(), Function(), or dynamic code generation
 * - Prototype pollution defense
 */

import {
  TriggerCondition,
  TriggerConditionGroup,
  TriggerEventFilter,
  TriggerEvaluationContext,
} from '../types/eventTrigger';

export class TriggerConditionEngine {
  /**
   * Matches an event filter against an evaluation context.
   */
  public matchFilter(filter: TriggerEventFilter, context: TriggerEvaluationContext): boolean {
    const { event, missionId, projectId } = context;

    if (filter.connectorId && !this.matchWildcardOrExact(filter.connectorId, event.connectorId)) {
      return false;
    }

    if (filter.sourceSystem && !this.matchWildcardOrExact(filter.sourceSystem, event.sourceSystem)) {
      return false;
    }

    if (filter.eventType && !this.matchWildcardOrExact(filter.eventType, event.eventType)) {
      return false;
    }

    if (filter.resourceType && !this.matchWildcardOrExact(filter.resourceType, event.resourceType)) {
      return false;
    }

    if (filter.changeType && !this.matchWildcardOrExact(filter.changeType, event.changeType)) {
      return false;
    }

    if (filter.resourceId && !this.matchWildcardOrExact(filter.resourceId, event.resourceId)) {
      return false;
    }

    if (filter.missionId && filter.missionId !== missionId) {
      return false;
    }

    if (filter.projectId && filter.projectId !== projectId) {
      return false;
    }

    return true;
  }

  /**
   * Evaluates a condition tree (single condition, condition array, or nested group).
   */
  public evaluateConditions(
    conditions: TriggerConditionGroup | TriggerCondition[] | TriggerCondition | undefined,
    context: TriggerEvaluationContext
  ): boolean {
    if (!conditions) {
      return true; // Empty condition tree defaults to true if filter matched
    }

    if ('field' in conditions) {
      return this.evaluateSingleCondition(conditions, context);
    }

    if (Array.isArray(conditions)) {
      if (conditions.length === 0) return true;
      // Default to AND semantics for plain arrays
      return conditions.every((cond) => this.evaluateSingleCondition(cond, context));
    }

    // Condition Group
    return this.evaluateGroup(conditions, context);
  }

  /**
   * Evaluates a logical condition group (AND / OR).
   */
  private evaluateGroup(
    group: TriggerConditionGroup,
    context: TriggerEvaluationContext
  ): boolean {
    const { logicalOperator, conditions } = group;
    if (!conditions || conditions.length === 0) return true;

    if (logicalOperator === 'OR') {
      return conditions.some((item) =>
        'logicalOperator' in item
          ? this.evaluateGroup(item, context)
          : this.evaluateSingleCondition(item, context)
      );
    }

    // Default AND
    return conditions.every((item) =>
      'logicalOperator' in item
        ? this.evaluateGroup(item, context)
        : this.evaluateSingleCondition(item, context)
    );
  }

  /**
   * Evaluates a single atomic condition declaratively.
   */
  public evaluateSingleCondition(
    condition: TriggerCondition,
    context: TriggerEvaluationContext
  ): boolean {
    const { field, operator, value } = condition;

    // Defense against prototype pollution
    if (field.includes('__proto__') || field.includes('prototype') || field.includes('constructor')) {
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

      case 'starts_with':
        if (typeof resolved === 'string' && typeof value === 'string') {
          return resolved.startsWith(value);
        }
        return false;

      case 'ends_with':
        if (typeof resolved === 'string' && typeof value === 'string') {
          return resolved.endsWith(value);
        }
        return false;

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

      case 'exists':
        return resolved !== undefined && resolved !== null && resolved !== '';

      case 'not_exists':
        return resolved === undefined || resolved === null || resolved === '';

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

  /**
   * Evaluates a condition or condition group against event data directly.
   */
  public evaluate(
    condition: TriggerCondition | TriggerConditionGroup,
    data: Record<string, unknown>
  ): { matched: boolean; error?: string } {
    try {
      if ('field' in condition) {
        if (
          condition.field.includes('__proto__') ||
          condition.field.includes('prototype') ||
          condition.field.includes('constructor')
        ) {
          return { matched: false, error: `Unsafe field path: ${condition.field}` };
        }
      }

      // Check for code injection in condition value
      const raw = JSON.stringify(condition);
      if (raw.includes('eval(') || raw.includes('function(') || raw.includes('javascript:')) {
        return { matched: false, error: 'Malicious code rejected' };
      }

      const dummyContext: TriggerEvaluationContext = {
        event: {
          eventId: 'dummy',
          sourceSystem: 'dummy',
          eventType: 'dummy',
          connectorId: 'dummy',
          resourceType: 'dummy',
          resourceId: 'dummy',
          changeType: 'dummy',
          timestamp: new Date().toISOString(),
          epistemicStatus: 'dummy',
          data,
        },
      };

      if ('field' in condition) {
        const val = this.resolveField(condition.field, dummyContext);
        if (condition.operator !== 'not_exists' && condition.operator !== 'exists') {
          if (val === undefined) {
            return { matched: false, error: `Field '${condition.field}' not found` };
          }
        }
        const matched = this.evaluateSingleCondition(condition, dummyContext);
        return { matched };
      }

      const matched = this.evaluateGroup(condition, dummyContext);
      return { matched };
    } catch (err: any) {
      return { matched: false, error: err.message };
    }
  }

  /**
   * Resolves a dotted field path from TriggerEvaluationContext safely.
   */
  private resolveField(path: string, context: TriggerEvaluationContext): unknown {
    if (!path) return undefined;

    // Normalize array notation: e.g. "labels[0]" -> "labels.0"
    const normalizedPath = path.replace(/\[(\d+)\]/g, '.$1');

    // Map top-level aliases directly
    const root: Record<string, unknown> = {
      ...context.event.data,
      event: context.event,
      data: context.event.data,
      resourceId: context.event.resourceId,
      resourceType: context.event.resourceType,
      changeType: context.event.changeType,
      sourceSystem: context.event.sourceSystem,
      connectorId: context.event.connectorId,
      eventType: context.event.eventType,
      missionId: context.missionId,
      projectId: context.projectId,
    };

    const parts = normalizedPath.split('.');
    let current: any = root;

    for (const part of parts) {
      if (current === undefined || current === null || typeof current !== 'object') {
        return undefined;
      }
      current = current[part];
    }

    return current;
  }

  /**
   * Wildcard string matcher (* support).
   */
  private matchWildcardOrExact(pattern: string, actual: string): boolean {
    if (pattern === '*' || pattern === actual) return true;
    if (pattern.endsWith('*')) {
      const prefix = pattern.slice(0, -1);
      return actual.startsWith(prefix);
    }
    return false;
  }
}

export const triggerConditionEngine = new TriggerConditionEngine();
