/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Recovery Operations Projection Panel
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: Zero retry, compensate, reconcile, rollback, or abort buttons.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - Proposed action is NEVER rendered as dispatched or completed action.
 *    - Required reconciliation is NEVER rendered as verified success.
 *    - Declarative compensation is NEVER rendered as executed compensation.
 *    - Unresolved recovery requirements highlighted truthfully.
 */

import React from 'react';
import { RecoverySummary } from '../../types/controlPlane';
import {
  LifecycleBadge,
  EpistemicBadge,
  SecretScrubbedText,
} from './EpistemicIndicators';

export interface RecoveryOperationsPanelProps {
  recovery?: readonly RecoverySummary[];
  className?: string;
}

export const RecoveryOperationsPanel: React.FC<RecoveryOperationsPanelProps> = ({
  recovery = [],
  className = '',
}) => {
  return (
    <div
      data-testid="recovery-operations-panel"
      className={`flex flex-col gap-3 font-mono ${className}`}
      style={{
        backgroundColor: 'rgba(11, 15, 23, 0.85)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '8px',
        padding: '1rem',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-200 tracking-wider">
            RECOVERY CONTROL DECISIONS & PLANS
          </span>
          <span
            data-testid="recovery-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {recovery.length} RECORDS
          </span>
        </div>
        <div className="text-[0.625rem] text-slate-500">
          OBSERVATIONAL PROJECTION (STAGE 23 RECOVERY CONTROL PLANE)
        </div>
      </div>

      {recovery.length === 0 ? (
        <div
          data-testid="recovery-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO RECOVERY PLANS OR DECISIONS RECORDED (SYSTEM IN NORMAL EQUILIBRIUM)
        </div>
      ) : (
        <div
          data-testid="recovery-records-list"
          className="flex flex-col gap-2.5 max-h-[500px] overflow-y-auto pr-1"
        >
          {recovery.map((rec) => {
            const isProposed =
              rec.lifecycleState === 'PROPOSED' ||
              rec.lifecycleState === 'PLANNED' ||
              rec.lifecycleState === 'DECIDED';

            const requiresApproval =
              typeof rec.approvalRequirement === 'object' &&
              rec.approvalRequirement.required;

            const requiresRecon =
              typeof rec.reconciliationRequirement === 'object' &&
              rec.reconciliationRequirement.required;

            const compAvailable =
              rec.compensationPlan !== undefined &&
              rec.compensationPlan !== null &&
              rec.compensationPlan !== 'UNKNOWN';

            return (
              <div
                key={rec.recoveryPlanId}
                data-testid={`recovery-card-${rec.recoveryPlanId}`}
                className="flex flex-col gap-2 p-3 rounded bg-slate-950/70 border border-slate-800/70"
              >
                {/* Header row */}
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold text-amber-400">
                      {rec.recoveryPlanId}
                    </span>
                    <LifecycleBadge state={rec.lifecycleState} />
                    <EpistemicBadge status={rec.currentTruthState} size="sm" />
                    <span
                      data-testid="recovery-failure-class"
                      className="text-[0.5625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700"
                    >
                      FAILURE: {rec.failureClassification}
                    </span>
                  </div>

                  <div className="text-[0.625rem] text-slate-400">
                    OP: <span className="text-slate-200">{rec.originalOperationId}</span>
                  </div>
                </div>

                {/* Proposed Recovery Action Banner */}
                <div
                  data-testid="proposed-action-banner"
                  className="p-2 rounded bg-slate-900/60 border border-slate-800/60 flex flex-col gap-1 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400 text-[0.625rem] font-bold">
                      PROPOSED RECOVERY ACTION (RECOMMENDATION ONLY):
                    </span>
                    <strong className="text-amber-400">
                      {rec.proposedRecoveryAction}
                    </strong>
                  </div>
                  {rec.expectedOutcome && (
                    <div className="text-[0.625rem] text-slate-300">
                      <span className="text-slate-500 mr-1">EXPECTED OUTCOME:</span>
                      <SecretScrubbedText text={rec.expectedOutcome} />
                    </div>
                  )}
                </div>

                {/* Safety Assessment & Requirements Matrix */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[0.5625rem] bg-slate-900/40 p-2 rounded border border-slate-800/40">
                  <div>
                    <span className="text-slate-500">IDEMPOTENCY:</span>
                    <div className="text-slate-300 font-bold">{rec.idempotencyAssessment}</div>
                  </div>
                  <div>
                    <span className="text-slate-500">APPROVAL REQUIRED:</span>
                    <div
                      data-testid="recovery-approval-req"
                      className={`font-bold ${requiresApproval ? 'text-amber-400' : 'text-slate-400'}`}
                    >
                      {requiresApproval ? 'YES (MANDATORY)' : 'NO'}
                    </div>
                  </div>
                  <div>
                    <span className="text-slate-500">RECONCILIATION:</span>
                    <div
                      data-testid="recovery-recon-req"
                      className={`font-bold ${requiresRecon ? 'text-cyan-400' : 'text-slate-400'}`}
                    >
                      {requiresRecon ? 'REQUIRED (PROBE PENDING)' : 'NOT REQUIRED'}
                    </div>
                  </div>
                  <div>
                    <span className="text-slate-500">COMPENSATION:</span>
                    <div
                      data-testid="recovery-comp-plan"
                      className={`font-bold ${compAvailable ? 'text-purple-400' : 'text-slate-400'}`}
                    >
                      {compAvailable ? 'AVAILABLE (DECLARATIVE)' : 'NONE'}
                    </div>
                  </div>
                </div>

                {/* Epistemic Safety Notice */}
                {isProposed && (
                  <div
                    data-testid="recovery-observational-notice"
                    className="text-[0.5625rem] text-slate-400 bg-slate-900/20 p-1.5 rounded border border-slate-800/30 flex items-center justify-between"
                  >
                    <span>
                      * Recommendation has not been dispatched. Execution requires authoritative governance approval.
                    </span>
                    <span className="text-slate-500">
                      RETRY: {rec.retryCount ?? 0} | DEPTH: {rec.recoveryDepth ?? 0}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
