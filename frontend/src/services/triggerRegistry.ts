/**
 * AryaOS V1 — Stage 19: Trigger Registry
 *
 * Deterministic registration, versioning, security sanitization, and lifecycle catalog
 * for event-driven triggers.
 *
 * INVARIANTS:
 * - Deterministic: rejects duplicate IDs
 * - Immutable versions: updates to ACTIVE triggers increment version
 * - Strict lifecycle transitions: DRAFT cannot execute; REVOKED is terminal
 * - Sanitization: rejects embedded credentials, tokens, or executable script injection
 */

import {
  Trigger,
  TriggerId,
  TriggerStatus,
  TriggerCondition,
  TriggerConditionGroup,
} from '../types/eventTrigger';
import { executionPersistence } from './executionPersistence';

export class TriggerRegistry {
  private triggers: Map<TriggerId, Trigger> = new Map();
  private triggerVersions: Map<TriggerId, Trigger[]> = new Map();

  constructor() {
    this.loadFromStorage();
  }

  /**
   * Registers a new trigger in DRAFT or specified status.
   */
  public registerTrigger(trigger: Trigger): { success: boolean; trigger?: Trigger; errors: string[] } {
    try {
      if (!trigger || typeof trigger !== 'object') {
        return { success: false, errors: ['Trigger payload is required.'] };
      }
      const errors: string[] = [];
      if (!trigger.triggerId) errors.push("Missing required field 'triggerId'");
      if (!trigger.name) errors.push("Missing required field 'name'");
      if (!trigger.eventFilter) errors.push("Missing required field 'eventFilter'");
      if (!trigger.reaction) errors.push("Missing required field 'reaction'");

      const validRisks = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
      if (trigger.riskLevel && !validRisks.includes(trigger.riskLevel)) {
        errors.push(`Invalid riskLevel '${trigger.riskLevel}'. Must be one of: ${validRisks.join(', ')}.`);
      }
      if (trigger.reaction && !trigger.reaction.reactionType) {
        errors.push("Missing required field 'reactionType' in reaction.");
      }

      if (errors.length > 0) {
        return { success: false, errors };
      }

      if (this.triggers.has(trigger.triggerId)) {
        return { success: false, errors: [`Duplicate trigger registration: '${trigger.triggerId}' is already registered.`] };
      }

      // 1. Scrub secrets in reaction parameters before storing/checking
      if (trigger.reaction?.parameters) {
        const scrubbedParams: Record<string, unknown> = {};
        const secretKeys = ['apikey', 'api_key', 'token', 'secret', 'password', 'bearer', 'credential', 'private_key'];
        for (const [k, v] of Object.entries(trigger.reaction.parameters)) {
          if (secretKeys.some((sk) => k.toLowerCase().includes(sk))) {
            scrubbedParams[k] = '[REDACTED]';
          } else {
            scrubbedParams[k] = v;
          }
        }
        trigger.reaction.parameters = scrubbedParams;
      }

      // 2. Security & code injection validation
      this.validateTriggerSecurity(trigger);

      const initial: Trigger = {
        ...trigger,
        version: trigger.version || 1,
        status: trigger.status || 'DRAFT',
        createdAt: trigger.createdAt || new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };

      this.triggers.set(initial.triggerId, initial);
      this.triggerVersions.set(initial.triggerId, [{ ...initial }]);
      executionPersistence.saveTrigger(initial);

      return { success: true, trigger: initial, errors: [] };
    } catch (err: any) {
      return { success: false, errors: [err.message] };
    }
  }

  /**
   * Updates an existing trigger. If trigger is ACTIVE, increments version to preserve history.
   */
  public updateTrigger(
    triggerId: TriggerId,
    updates: Partial<Omit<Trigger, 'triggerId' | 'version' | 'createdAt'>>,
    changeReason?: string
  ): { success: boolean; trigger?: Trigger; error?: string } {
    try {
      const existing = this.triggers.get(triggerId);
      if (!existing) {
        return { success: false, error: `Cannot update non-existent trigger '${triggerId}'` };
      }

      if (existing.status === 'REVOKED') {
        return { success: false, error: `Cannot update trigger '${triggerId}' because it has been REVOKED.` };
      }

      // Validate security of updates
      if (updates.conditions) {
        this.validateConditionSecurity(updates.conditions);
      }

      const isVersionBump = existing.status === 'ACTIVE' || updates.status === 'ACTIVE';
      const nextVersion = isVersionBump ? existing.version + 1 : existing.version;

      const updated: Trigger = {
        ...existing,
        ...updates,
        version: nextVersion,
        updatedAt: new Date().toISOString(),
        provenance: existing.provenance
          ? {
              ...existing.provenance,
              source: updates.provenance?.source || existing.provenance.source,
              changeReason: changeReason || updates.provenance?.changeReason,
            }
          : (updates.provenance || { createdBy: 'system' }),
      };

      this.triggers.set(triggerId, updated);

      // Record historical version
      const history = this.triggerVersions.get(triggerId) || [];
      history.push({ ...updated });
      this.triggerVersions.set(triggerId, history);

      executionPersistence.saveTrigger(updated);
      return { success: true, trigger: updated };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Updates trigger lifecycle status following strict state machine rules.
   */
  public transitionStatus(
    triggerId: TriggerId,
    newStatus: TriggerStatus,
    reason?: string
  ): Trigger {
    const res = this.transitionState(triggerId, newStatus, reason);
    if (!res.success) {
      throw new Error(res.error || 'Transition failed');
    }
    return res.trigger!;
  }

  public transitionState(
    triggerId: TriggerId,
    newStatus: TriggerStatus,
    reason?: string
  ): { success: boolean; trigger?: Trigger; error?: string } {
    const trigger = this.triggers.get(triggerId);
    if (!trigger) {
      return { success: false, error: `Trigger '${triggerId}' not found.` };
    }

    const currentStatus = trigger.status;
    if (currentStatus === newStatus) {
      return { success: true, trigger };
    }

    // State machine transition validation
    if (currentStatus === 'REVOKED') {
      return { success: false, error: `Trigger '${triggerId}' is REVOKED and cannot undergo state transitions: Invalid state transition.` };
    }

    if (currentStatus === 'DRAFT' && newStatus !== 'ACTIVE' && newStatus !== 'DISABLED' && newStatus !== 'REVOKED') {
      return { success: false, error: `Illegal lifecycle transition: DRAFT triggers can only transition to ACTIVE, DISABLED, or REVOKED (attempted: ${newStatus}).` };
    }

    return this.updateTrigger(triggerId, { status: newStatus }, reason);
  }

  public getTrigger(triggerId: TriggerId): Trigger | null {
    return this.triggers.get(triggerId) || null;
  }

  public getTriggerVersion(triggerId: TriggerId, version: number): Trigger | null {
    const versions = this.triggerVersions.get(triggerId) || [];
    return versions.find((v) => v.version === version) || null;
  }

  public listTriggers(filter?: { status?: TriggerStatus }): Trigger[] {
    let list = Array.from(this.triggers.values());
    if (filter?.status) {
      list = list.filter((t) => t.status === filter.status);
    }
    return list;
  }

  public listActiveTriggers(): Trigger[] {
    return this.listTriggers({ status: 'ACTIVE' });
  }

  public getTriggerVersions(triggerId: TriggerId): Trigger[] {
    return this.triggerVersions.get(triggerId) || [];
  }

  public loadFromPersistence(): void {
    this.loadFromStorage();
  }

  public clear(): void {
    this.triggers.clear();
    this.triggerVersions.clear();
  }

  /**
   * Validates trigger definition against security policies and forbidden constructs.
   */
  public validateTriggerSecurity(trigger: Trigger): void {
    const raw = JSON.stringify(trigger);

    // 1. Secret scrubbing check
    const secretKeywords = ['bearer ', 'ghp_', 'client_secret', 'password', 'private_key'];
    for (const kw of secretKeywords) {
      if (raw.toLowerCase().includes(kw)) {
        throw new Error(`Security Violation: Trigger '${trigger.triggerId}' contains forbidden secret or credential references ('${kw}').`);
      }
    }

    // 2. Code injection check
    const injectionKeywords = ['eval(', 'function(', 'javascript:', '<script', '__proto__'];
    for (const kw of injectionKeywords) {
      if (raw.toLowerCase().includes(kw)) {
        throw new Error(`Code injection violation: Trigger '${trigger.triggerId}' contains forbidden executable code or prototype tampering pattern ('${kw}').`);
      }
    }

    // 3. Condition safety
    if (trigger.conditions) {
      this.validateConditionSecurity(trigger.conditions);
    }
  }

  private validateConditionSecurity(conditions: TriggerConditionGroup | TriggerCondition[] | TriggerCondition): void {
    if ('field' in conditions) {
      const field = (conditions.field || '').toLowerCase();
      if (field.includes('eval') || field.includes('prototype') || field.includes('__proto__') || field.includes('constructor')) {
        throw new Error(`Security Violation: Condition field '${conditions.field}' violates safety constraints.`);
      }
      return;
    }
    const items = Array.isArray(conditions) ? conditions : conditions.conditions;
    for (const item of items) {
      if ('logicalOperator' in item) {
        this.validateConditionSecurity(item);
      } else {
        const field = (item.field || '').toLowerCase();
        if (field.includes('eval') || field.includes('prototype') || field.includes('__proto__') || field.includes('constructor')) {
          throw new Error(`Security Violation: Condition field '${item.field}' violates safety constraints.`);
        }
      }
    }
  }

  private loadFromStorage(): void {
    try {
      const persisted = executionPersistence.getAllTriggers();
      persisted.forEach((t) => {
        this.triggers.set(t.triggerId, t);
        const versions = this.triggerVersions.get(t.triggerId) || [];
        versions.push(t);
        this.triggerVersions.set(t.triggerId, versions);
      });
    } catch {
      // Safe fallback
    }
  }
}

export const triggerRegistry = new TriggerRegistry();
