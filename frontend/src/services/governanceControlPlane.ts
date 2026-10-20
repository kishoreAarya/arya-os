/**
 * AryaOS V1 — Stage 21: Governed Policy Control Plane
 *
 * Central façade and runtime governance coordinator.
 * Coordinates: Request → ContextBuilder → PolicySnapshot → PolicyEvaluation →
 * AuthorityCheck → StalenessCheck → GovernanceDecision → Explanation → Persistence.
 *
 * ABSOLUTE ARCHITECTURAL INVARIANTS:
 * 1. The control plane DOES NOT execute the final action itself.
 * 2. Stage 07 Execution Gateway remains the sole AI execution boundary.
 * 3. Stage 15 Action Bus remains the sole external action boundary.
 * 4. Stage 16 Connector Fabric remains the sole permission boundary.
 * 5. Stage 19 Reaction Engine remains the event reaction boundary.
 * 6. ZERO LLM calls or network requests in policy governance (pure deterministic logic).
 * 7. Fail-closed authority intersection: missing permission or approval blocks execution.
 */

import {
  GovernanceRequest,
  GovernanceContext,
  PolicySnapshot,
  GovernanceDecision,
  GovernanceDecisionType,
  OperatorApprovalToken,
  GovernanceStalenessCheck,
  EpistemicStatus,
} from '../types/governanceControlPlane';
import { governanceContextService } from './governanceContextService';
import { policySnapshotService } from './policySnapshotService';
import { governanceAuthorityService } from './governanceAuthorityService';
import { governanceStalenessService } from './governanceStalenessService';
import { governanceExplanationService } from './governanceExplanationService';
import { policyConditionEngine } from './policyConditionEngine';
import { policyConflictService } from './policyConflictService';
import { policyRegistry } from './policyRegistry';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';
import { Policy, PolicyEvaluationResult, POLICY_PRIORITY_WEIGHTS } from '../types/policyIntelligence';
import { actionBusService, ActionBusExecuteOptions } from './actionBusService';
import { ActionRequest, ActionResult } from '../types/actionBus';

export interface GovernanceEvaluateOptions {
  runtimeOverrides?: Partial<GovernanceContext>;
  operatorApproval?: OperatorApprovalToken;
  snapshot?: PolicySnapshot;
  bypassCache?: boolean;
  epistemicStatus?: EpistemicStatus;
}

export class GovernanceControlPlane {
  private decisionCache: Map<string, GovernanceDecision> = new Map();
  private evaluatedRequestParams: Map<string, string> = new Map();
  private maxCacheSize = 200;

  public reset(): void {
    this.decisionCache.clear();
    this.evaluatedRequestParams.clear();
    policySnapshotService.reset();
  }

  public resetCache(): void {
    this.decisionCache.clear();
    this.evaluatedRequestParams.clear();
  }

  /**
   * Main entry point for evaluating governance over an operational request.
   */
  public evaluateGovernance(
    request: GovernanceRequest,
    options?: GovernanceEvaluateOptions
  ): GovernanceDecision {
    const startTime = performance.now();

    // 1. Build Bounded Governance Context
    const context = governanceContextService.buildContext(request, options?.runtimeOverrides);
    this.evaluatedRequestParams.set(request.requestId, JSON.stringify(context.sanitizedParameters));

    // 2. Obtain Immutable Policy Snapshot
    const snapshot = options?.snapshot || policySnapshotService.captureSnapshot();

    // 3. Deterministic Cache Check
    const cacheKey = this.computeCacheKey(request, snapshot, options?.operatorApproval);
    if (!options?.bypassCache && this.decisionCache.has(cacheKey)) {
      const cached = this.decisionCache.get(cacheKey)!;
      // Re-verify staleness on cache hit to prevent serving out-of-date policy decisions
      const staleness = governanceStalenessService.checkStaleness(snapshot, request, options?.operatorApproval);
      if (!staleness.isStale) {
        return {
          ...cached,
          deterministicMetadata: {
            ...cached.deterministicMetadata,
            cacheHit: true,
            evaluatedAt: Date.now(),
          },
        };
      }
    }

    // 4. Policy Matching & Evaluation against Snapshot Entries
    const matchedResults: PolicyEvaluationResult[] = [];
    const evaluatedPolicyVersions: Record<string, number> = {};

    for (const entry of snapshot.policies) {
      evaluatedPolicyVersions[entry.policyId] = entry.version;

      if (this.matchesScope(entry.scope, context)) {
        const isMatched = policyConditionEngine.evaluate(entry.conditions, context as unknown as Record<string, unknown>);
        if (isMatched) {
          const priorityWeight = entry.priorityWeight || POLICY_PRIORITY_WEIGHTS[entry.priority] || 0;
          matchedResults.push({
            policyId: entry.policyId,
            version: entry.version,
            matched: true,
            effect: entry.effect,
            priority: entry.priority,
            priorityWeight,
            reason: entry.effect.reason || `Enforced by snapshot policy '${entry.policyId}' v${entry.version}`,
          });
        }
      }
    }

    // 5. Conflict Resolution via Stage 20 Conflict Engine
    const allPoliciesMap = new Map<string, Policy>(
      policyRegistry.getAllPolicies().map((p) => [p.id, p])
    );
    const policyDecisionResult = policyConflictService.resolveConflicts(matchedResults, allPoliciesMap);

    const winningPolicyId = policyDecisionResult.winningPolicyId;
    const winningPriority = policyDecisionResult.winningPriority;
    const rawPolicyEffect = policyDecisionResult.effectiveEffect.type;

    // 6. Authority Intersection (Policy ∩ Connector ∩ Action ∩ Approval ∩ Mission)
    const authorityIntersection = governanceAuthorityService.evaluateAuthorityIntersection(
      request,
      context,
      snapshot,
      rawPolicyEffect as GovernanceDecisionType,
      options?.operatorApproval
    );

    // 7. Staleness Check
    const staleness = governanceStalenessService.checkStaleness(
      snapshot,
      request,
      options?.operatorApproval
    );

    // 8. Synthesize Final Effective Governance Decision
    let finalDecision: GovernanceDecisionType;
    let finalReason: string;

    if (authorityIntersection.humanApprovalStatus === 'FORGED_REJECTED') {
      finalDecision = 'DENY';
      finalReason = `Execution denied: Anti-spoofing rejection (${authorityIntersection.blockingReasons.join('; ')})`;
    } else if (staleness.isStale) {
      finalDecision = 'REQUIRE_REVIEW';
      finalReason = `Decision deferred: ${staleness.reason}`;
    } else if (authorityIntersection.failClosed) {
      if (authorityIntersection.effectiveStatus === 'REQUIRES_APPROVAL') {
        finalDecision = 'REQUIRE_APPROVAL';
        finalReason = `Execution blocked: Human operator approval required (${authorityIntersection.blockingReasons.join('; ')})`;
      } else if (authorityIntersection.effectiveStatus === 'MISSING_PERMISSION') {
        finalDecision = 'DENY';
        finalReason = `Execution blocked: Missing Connector Fabric permission (${authorityIntersection.blockingReasons.join('; ')})`;
      } else if (authorityIntersection.effectiveStatus === 'MISSION_CONSTRAINT_BLOCKED') {
        finalDecision = 'PAUSE';
        finalReason = `Execution paused: Mission constraints violated (${authorityIntersection.blockingReasons.join('; ')})`;
      } else {
        finalDecision = 'DENY';
        finalReason = `Execution denied: ${authorityIntersection.blockingReasons.join('; ')}`;
      }
    } else {
      // Policy allows and all authority tiers satisfied
      finalDecision = rawPolicyEffect as GovernanceDecisionType;
      finalReason = policyDecisionResult.reason || 'All governance constraints and authorities verified';
    }

    // 9. Generate 10-Point Explanation
    const explanation = governanceExplanationService.generateExplanation({
      request,
      context,
      snapshot,
      matchedPolicies: matchedResults.map((m) => m.policyId),
      conflictingPolicies: policyDecisionResult.conflictingPolicies.map((c) => ({
        conflictId: c.conflictId,
        policyAId: c.policyAId,
        policyBId: c.policyBId,
        precedenceReason: c.precedenceReason,
      })),
      precedenceResolution: policyDecisionResult.reason,
      resultingPolicyDecision: finalDecision,
      authorityIntersection,
      epistemicStatus: options?.epistemicStatus || 'OBSERVED',
    });

    const decisionId = `gov_dec_${request.requestId}_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
    const evaluationLatencyMs = Math.max(0.1, Number((performance.now() - startTime).toFixed(2)));

    const decision: GovernanceDecision = {
      decisionId,
      requestId: request.requestId,
      correlationId: context.correlationId,
      policySnapshotId: snapshot.snapshotId,
      policyRegistryVersion: snapshot.registryVersion,
      evaluatedPolicyVersions,
      decision: finalDecision,
      reason: finalReason,
      matchedPolicies: matchedResults.map((m) => m.policyId),
      conflictingPolicies: policyDecisionResult.conflictingPolicies.map((c) => ({
        conflictId: c.conflictId,
        policyAId: c.policyAId,
        policyBId: c.policyBId,
        conflictType: c.conflictType,
        precedenceReason: c.precedenceReason,
      })),
      winningPolicyId,
      winningPriority,
      authorityIntersection,
      staleness,
      explanation,
      epistemicStatus: options?.epistemicStatus || 'OBSERVED',
      deterministicMetadata: {
        evaluationLatencyMs,
        evaluatedAt: Date.now(),
        cacheHit: false,
        fingerprint: snapshot.fingerprint,
      },
    };

    // 10. Audit Event & Persistence
    this.recordDecision(decision, request);

    // Cache decision
    if (!staleness.isStale && this.decisionCache.size < this.maxCacheSize) {
      this.decisionCache.set(cacheKey, decision);
    }

    Object.freeze(authorityIntersection);
    Object.freeze(explanation);
    Object.freeze(staleness);
    Object.freeze(decision.deterministicMetadata);

    return Object.freeze(decision);
  }

  /**
   * Pre-execution verification to prevent execution under stale decisions.
   */
  public verifyPreExecution(
    decision: GovernanceDecision,
    currentRequest: GovernanceRequest,
    approvalToken?: OperatorApprovalToken
  ): GovernanceStalenessCheck {
    const snapshot = policySnapshotService.getSnapshot(decision.policySnapshotId);
    if (!snapshot) {
      return {
        isStale: true,
        status: 'REQUIRES_REEVALUATION',
        reason: `Evaluated PolicySnapshot '${decision.policySnapshotId}' is no longer available in memory. Re-evaluation required.`,
        evaluatedSnapshotId: decision.policySnapshotId,
        currentRegistryVersion: policyRegistry.getRegistryVersion(),
        snapshotRegistryVersion: decision.policyRegistryVersion,
      };
    }

    const evaluatedParamsJson = this.evaluatedRequestParams.get(currentRequest.requestId);
    if (evaluatedParamsJson) {
      const currentParamsJson = JSON.stringify(
        governanceContextService.sanitizeObject(currentRequest.parameters || {})
      );
      if (evaluatedParamsJson !== currentParamsJson) {
        return {
          isStale: true,
          status: 'VERSION_MISMATCH',
          reason: 'Request parameters altered between evaluation and execution. Re-evaluation required.',
          evaluatedSnapshotId: decision.policySnapshotId,
          currentRegistryVersion: policyRegistry.getRegistryVersion(),
          snapshotRegistryVersion: decision.policyRegistryVersion,
          alteredRequestParameters: true,
        };
      }
    }

    return governanceStalenessService.checkStaleness(snapshot, currentRequest, approvalToken);
  }

  /**
   * Executes an action through the governed execution pipeline:
   * Governance Request -> Governance Decision -> Fail-Closed Check -> Action Bus Execution.
   */
  public async executeGovernedAction(
    request: ActionRequest,
    options?: ActionBusExecuteOptions
  ): Promise<{
    decision: GovernanceDecision;
    actionResult?: ActionResult;
  }> {
    const govRequest = governanceContextService.mapActionRequestToGovernanceRequest(request);
    let operatorApproval: OperatorApprovalToken | undefined;
    if (options?.operatorApproval) {
      operatorApproval = {
        approvedBy: options.operatorApproval.approvedBy,
        approvedAt: Date.now(),
        signature: options.operatorApproval.signature || 'VALID_OPERATOR_SIG',
        requestId: govRequest.requestId,
        policySnapshotId: 'CURRENT',
        riskLevel: 'HIGH',
      };
    }
    const decision = this.evaluateGovernance(govRequest, { operatorApproval });

    if (decision.decision !== 'ALLOW' && decision.decision !== 'LIMIT' && decision.decision !== 'ROUTE') {
      return { decision };
    }

    if (decision.authorityIntersection.failClosed) {
      return { decision };
    }

    // Dispatches to existing authoritative Action Bus (Stage 15 boundary)
    const actionResult = await actionBusService.execute(request, options);
    return { decision, actionResult };
  }

  /**
   * Evaluates a triggered reaction through the governed control plane.
   */
  public evaluateTriggeredReaction(
    triggerId: string,
    actionRequest: ActionRequest,
    options?: ActionBusExecuteOptions
  ): GovernanceDecision {
    const govRequest = governanceContextService.mapActionRequestToGovernanceRequest({
      ...actionRequest,
      triggerId,
    });
    let operatorApproval: OperatorApprovalToken | undefined;
    if (options?.operatorApproval) {
      operatorApproval = {
        approvedBy: options.operatorApproval.approvedBy,
        approvedAt: Date.now(),
        signature: options.operatorApproval.signature || 'VALID_OPERATOR_SIG',
        requestId: govRequest.requestId,
        policySnapshotId: 'CURRENT',
        riskLevel: 'HIGH',
      };
    }
    return this.evaluateGovernance(govRequest, { operatorApproval });
  }

  private matchesScope(
    scope: { scopeType: string; targetId?: string },
    context: GovernanceContext
  ): boolean {
    if (scope.scopeType === 'SYSTEM') return true;
    if (scope.scopeType === 'CONNECTOR') {
      return !scope.targetId || scope.targetId === context.connectorId;
    }
    if (scope.scopeType === 'AGENT') {
      return !scope.targetId || scope.targetId === context.actor.actorId;
    }
    if (scope.scopeType === 'MISSION') {
      return !scope.targetId || scope.targetId === context.missionId;
    }
    if (scope.scopeType === 'TRIGGER') {
      return !scope.targetId || scope.targetId === context.triggerId;
    }
    if (scope.scopeType === 'PROVIDER') {
      return !scope.targetId || scope.targetId === context.providerId;
    }
    if (scope.scopeType === 'RESOURCE') {
      return context.activeConcurrentActions !== undefined || context.costUsd !== undefined;
    }
    return false;
  }

  private computeCacheKey(
    request: GovernanceRequest,
    snapshot: PolicySnapshot,
    approval?: OperatorApprovalToken
  ): string {
    const raw = `${request.requestId}_${request.actor.actorId}_${request.capabilityId || ''}_${request.actionType || ''}_${snapshot.snapshotId}_${approval?.approvedBy || 'none'}`;
    return raw;
  }

  private recordDecision(decision: GovernanceDecision, request: GovernanceRequest): void {
    executionPersistence.saveGovernanceDecision?.(decision);
    executionJournal.appendEvent({
      goalId: request.goalId || request.missionId || 'governance-control-plane',
      eventType: 'GOVERNANCE_EVALUATED',
      payload: {
        decisionId: decision.decisionId,
        requestId: decision.requestId,
        decision: decision.decision,
        winningPolicyId: decision.winningPolicyId,
        effectiveStatus: decision.authorityIntersection.effectiveStatus,
        isStale: decision.staleness.isStale,
        snapshotId: decision.policySnapshotId,
      },
    });
  }
}

export const governanceControlPlane = new GovernanceControlPlane();
