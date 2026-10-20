/**
 * AryaOS V1 — Stage 14: Pre-Mortem Analysis Service
 *
 * Conducts structured pre-mortem failure mode discovery:
 * "What could cause this plan to fail?"
 *
 * Discovers failure modes from historical failures, known risks, dependencies,
 * resource constraints, provider reliability, and agent performance.
 *
 * Enforces strict distinction:
 * Failure modes backed by empirical evidence vs SPECULATIVE failure modes.
 */

import {
  DecisionOption,
  DecisionContext,
  PreMortemAnalysis,
  PreMortemFailureMode,
} from '../types/decisionIntelligence';
import { executionPersistence } from './executionPersistence';

export class PreMortemService {
  /**
   * Conducts an evidence-backed pre-mortem analysis on a selected decision option.
   */
  public conductPreMortem(
    option: DecisionOption,
    context: DecisionContext
  ): PreMortemAnalysis {
    const failureModes: PreMortemFailureMode[] = [];

    // 1. Evidence-backed failure modes from historical failed experiences (Stage 11)
    const experiences = executionPersistence.getExperiences();
    const failedExperiences = experiences.filter((e) => e.status === 'FAILED');

    for (const failedExp of failedExperiences.slice(0, 3)) {
      failureModes.push({
        id: `pm_fail_${failedExp.experienceId}`,
        failureMode: `Historical failure mode recurrence in task pattern '${failedExp.taskType}'`,
        type: 'EVIDENCE_BACKED',
        evidenceIds: [failedExp.experienceId],
        potentialCause: 'Transient provider timeout or tool parameter mismatch',
        earlyWarningSignal: 'Repeated tool execution retries or latency exceeding 4000ms',
        preventativeAction: 'Enforce pre-flight schema validation and enable Stage 09 exponential backoff',
      });
    }

    // 2. Failure modes from active strategic contradictions (Stage 13)
    for (const contra of context.openContradictions.slice(0, 2)) {
      failureModes.push({
        id: `pm_contra_${contra.id}`,
        failureMode: `Strategic contradiction collision: ${contra.description}`,
        type: 'EVIDENCE_BACKED',
        evidenceIds: [contra.id],
        potentialCause: 'Conflicting assertions about system dependencies or agent capabilities',
        earlyWarningSignal: 'Divergent agent execution assertions during DAG scheduling',
        preventativeAction: 'Resolve contradiction via knowledgeResolutionService prior to final dispatch',
      });
    }

    // 3. Known risk-derived failure modes
    for (const risk of option.risks.slice(0, 2)) {
      failureModes.push({
        id: `pm_risk_${risk.id}`,
        failureMode: `Manifestation of known operational risk: ${risk.title}`,
        type: 'EVIDENCE_BACKED',
        evidenceIds: risk.evidenceIds,
        potentialCause: risk.description,
        earlyWarningSignal: `Risk severity escalates to ${risk.severity}`,
        preventativeAction: risk.mitigation || 'Engage human operator review checkpoint',
      });
    }

    // 4. Speculative failure modes (hypothetical failure modes when no empirical evidence exists)
    if (option.reversibility === 'IRREVERSIBLE') {
      failureModes.push({
        id: 'pm_spec_irreversible',
        failureMode: 'Irreversible state modification diverges from operator intent',
        type: 'SPECULATIVE',
        evidenceIds: [],
        potentialCause: 'Misunderstood requirement or undetected hallucination in final asset generation',
        earlyWarningSignal: 'Operator feedback diff differs from expected milestone output',
        preventativeAction: 'Mandate explicit operator confirmation with diff preview before commit',
      });
    }

    if (option.title.includes('Parallel')) {
      failureModes.push({
        id: 'pm_spec_concurrency',
        failureMode: 'Cascading rate-limit exhaustion across concurrent agent workers',
        type: 'SPECULATIVE',
        evidenceIds: [],
        potentialCause: 'Sub-agent workers hit simultaneous provider token spikes',
        earlyWarningSignal: 'Gateway lease requests throttled by ResourceGovernor',
        preventativeAction: 'Throttle parallel agent pool size and apply staggered scheduling',
      });
    }

    // Determine resilience rating
    const highRiskCount = failureModes.filter(
      (fm) => fm.type === 'EVIDENCE_BACKED'
    ).length;
    const resilienceRating =
      highRiskCount === 0 && option.reversibility === 'REVERSIBLE'
        ? 'HIGH'
        : highRiskCount <= 2
        ? 'MEDIUM'
        : 'LOW';

    const worstCaseScenario =
      option.reversibility === 'IRREVERSIBLE'
        ? 'Permanent unrecoverable state divergence requiring human manual rollback.'
        : 'Execution aborts with transient error; clean checkpoint recovery restores safe state.';

    return {
      id: `pm_analysis_${option.optionId}_${Date.now()}`,
      optionId: option.optionId,
      failureModes,
      worstCaseScenario,
      resilienceRating,
      analyzedAt: new Date().toISOString(),
    };
  }
}

export const premortemService = new PreMortemService();
