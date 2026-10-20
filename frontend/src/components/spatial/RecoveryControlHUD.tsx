/**
 * AryaOS V1 — Stage 23: Minimal DOM-Only Recovery Operational HUD
 *
 * Phase 12: Pure DOM telemetry overlay providing real-time visibility into the
 * Recovery Control Plane, Failure Classification, Safety Assessments,
 * and Stage 20/21/22 Governance and Operational Truth states.
 *
 * STRICT ARCHITECTURAL CONSTRAINTS:
 * 1. DOM-ONLY: Zero Three.js, WebGL, Canvas, Blender scene, or GLB interaction.
 * 2. OBSERVATIONAL ONLY: No execution triggers, no authorization bypasses, no policy mutations.
 * 3. EPISTEMIC SAFETY: Explicitly tags truth claims as UNKNOWN, OBSERVED, CONFIRMED, INFERRED, or PROJECTED.
 *    - UNKNOWN is never rendered as SUCCESS.
 *    - Recommendations are never rendered as executed actions.
 *    - Authorization is never rendered as execution.
 *    - Dispatch is never rendered as external success.
 */

import React from 'react';
import {
  RecoveryControlDecision,
  MAX_RECOVERY_DEPTH,
  MAX_AUTOMATIC_RETRIES,
  MAX_RECONCILIATION_ATTEMPTS,
} from '../../types/recoveryControl';

export type EpistemicStatus = 'UNKNOWN' | 'OBSERVED' | 'CONFIRMED' | 'INFERRED' | 'PROJECTED';

export interface RecoveryControlHUDProps {
  /** Target operation identifier */
  operationId?: string;
  /** Current recovery lifecycle progression or terminal state */
  recoveryState?: string;
  /** Failure classification (13 canonical types) */
  failureClassification?: string;
  /** Recovery decision outcome */
  recoveryDecision?: string;
  /** Stage 20 Policy snapshot & evaluation state */
  policyState?: string;
  /** Stage 21 Governance decision state */
  governanceState?: string;
  /** Effective multi-layer authority intersection state */
  authorityState?: string;
  /** Stage 22 Operational Truth empirical state */
  operationalTruth?: string;
  /** Active reconciliation state and probes */
  reconciliationState?: string;
  /** Whether human operator approval is mandatory */
  approvalRequired?: boolean;
  /** Current recovery recursion depth */
  recoveryDepth?: number;
  /** Maximum allowable recovery depth */
  maxRecoveryDepth?: number;
  /** Current automatic retry count */
  retryCount?: number;
  /** Maximum allowable automatic retries */
  maxRetries?: number;
  /** Current reconciliation probe count */
  reconciliationAttempts?: number;
  /** Maximum allowable reconciliation probe attempts */
  maxReconciliationAttempts?: number;
  /** Stage 22 Epistemic status tag */
  epistemicStatus?: EpistemicStatus;
  /** Optional pre-computed decision object for auto-population */
  decision?: Partial<RecoveryControlDecision>;
  /** Visibility toggle */
  isOpen?: boolean;
  /** Optional close callback (DOM presentation only) */
  onClose?: () => void;
  /** Custom wrapper CSS class */
  className?: string;
}

const EPISTEMIC_BADGE_STYLES: Record<
  EpistemicStatus,
  { bg: string; text: string; border: string; label: string }
> = {
  UNKNOWN: {
    bg: 'rgba(239, 68, 68, 0.18)',
    text: '#f87171',
    border: 'rgba(239, 68, 68, 0.5)',
    label: 'UNKNOWN (UNVERIFIED)',
  },
  OBSERVED: {
    bg: 'rgba(56, 189, 248, 0.18)',
    text: '#38bdf8',
    border: 'rgba(56, 189, 248, 0.5)',
    label: 'OBSERVED',
  },
  CONFIRMED: {
    bg: 'rgba(16, 185, 129, 0.18)',
    text: '#34d399',
    border: 'rgba(16, 185, 129, 0.5)',
    label: 'CONFIRMED (EMPIRICAL)',
  },
  INFERRED: {
    bg: 'rgba(168, 85, 247, 0.18)',
    text: '#c084fc',
    border: 'rgba(168, 85, 247, 0.5)',
    label: 'INFERRED (MODEL)',
  },
  PROJECTED: {
    bg: 'rgba(6, 182, 212, 0.18)',
    text: '#22d3ee',
    border: 'rgba(6, 182, 212, 0.5)',
    label: 'PROJECTED (SIMULATION)',
  },
};

export const RecoveryControlHUD: React.FC<RecoveryControlHUDProps> = ({
  operationId: propOpId,
  recoveryState: propRecState,
  failureClassification: propFailClass,
  recoveryDecision: propRecDecision,
  policyState: propPolicyState,
  governanceState: propGovState,
  authorityState: propAuthState,
  operationalTruth: propOpTruth,
  reconciliationState: propReconState,
  approvalRequired: propApprovalReq,
  recoveryDepth: propRecDepth,
  maxRecoveryDepth = MAX_RECOVERY_DEPTH,
  retryCount: propRetryCount,
  maxRetries = MAX_AUTOMATIC_RETRIES,
  reconciliationAttempts: propReconAttempts,
  maxReconciliationAttempts = MAX_RECONCILIATION_ATTEMPTS,
  epistemicStatus: propEpistemicStatus,
  decision,
  isOpen = true,
  onClose,
  className = '',
}) => {
  if (!isOpen) return null;

  // Resolve values from decision object or fallback to direct props
  const opId = decision?.operationId || propOpId || 'OP-UNKNOWN';
  const recState = decision?.lifecycleState || propRecState || 'DETECTED';
  const failClass = decision?.classification || propFailClass || 'SYSTEM_INTERRUPTION';
  const recDecision = decision?.recoveryOutcome || propRecDecision || 'WAIT';
  const policyState = propPolicyState || 'ACTIVE / v42';
  const govState =
    propGovState ||
    (decision?.governanceRequirement?.humanOperatorRequired ? 'APPROVAL REQUIRED' : 'GOVERNED');
  const authState =
    propAuthState ||
    (decision?.governanceRequirement?.humanOperatorRequired ? 'BLOCKED' : 'PERMITTED');
  const opTruth = propOpTruth || (decision?.epistemicStatus === 'CONFIRMED' ? 'CONFIRMED' : 'UNKNOWN');
  const recDepth = decision?.recoveryDepth ?? propRecDepth ?? 1;
  const retryCount = decision?.retryCount ?? propRetryCount ?? 0;
  const reconAttempts = decision?.reconciliationAttempts ?? propReconAttempts ?? 0;
  const reconState = propReconState || (reconAttempts > 0 ? `PROBING (${reconAttempts}/${maxReconciliationAttempts})` : 'IDLE');
  const approvalRequired =
    propApprovalReq !== undefined
      ? propApprovalReq
      : decision?.governanceRequirement?.humanOperatorRequired ?? false;

  const rawEpistemic = (decision?.epistemicStatus as EpistemicStatus) || propEpistemicStatus || 'UNKNOWN';
  const epistemicConfig = EPISTEMIC_BADGE_STYLES[rawEpistemic] || EPISTEMIC_BADGE_STYLES.UNKNOWN;

  // Epistemic Safety Guarantees
  // Invariant 1: UNKNOWN must never display as SUCCESS
  const safeOperationalTruth =
    rawEpistemic === 'UNKNOWN' && (opTruth === 'SUCCESS' || opTruth === 'CONFIRMED')
      ? 'UNKNOWN (EVIDENCE PENDING)'
      : opTruth;

  // Invariant 2: Recommendation must not display as executed
  const safeRecoveryState =
    recState === 'PROPOSED'
      ? 'PROPOSED (RECOMMENDATION ONLY)'
      : recState;

  // Invariant 3: Blocked authority when approval required
  const safeAuthorityState =
    approvalRequired && authState === 'PERMITTED'
      ? 'BLOCKED (REQUIRES APPROVAL)'
      : authState;

  return (
    <div
      data-testid="recovery-control-hud"
      className={`recovery-control-hud-root ${className}`}
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        width: '380px',
        backgroundColor: 'rgba(8, 12, 20, 0.94)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(56, 189, 248, 0.35)',
        borderRadius: '8px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.65)',
        color: '#f8fafc',
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        fontSize: '0.75rem',
        zIndex: 9999,
        pointerEvents: 'auto',
        overflow: 'hidden',
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderBottom: '1px solid rgba(56, 189, 248, 0.2)',
          backgroundColor: 'rgba(15, 23, 42, 0.8)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: approvalRequired ? '#f59e0b' : '#38bdf8',
              boxShadow: approvalRequired
                ? '0 0 8px #f59e0b'
                : '0 0 8px #38bdf8',
            }}
          />
          <span
            style={{
              fontWeight: 700,
              fontSize: '0.8125rem',
              letterSpacing: '0.05em',
              color: '#e2e8f0',
            }}
          >
            ARYAOS RECOVERY CONTROL
          </span>
        </div>
        {onClose && (
          <button
            type="button"
            data-testid="hud-close-btn"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              fontSize: '1rem',
              lineHeight: 1,
              padding: '2px 6px',
            }}
            aria-label="Close HUD"
          >
            ✕
          </button>
        )}
      </div>

      {/* Epistemic Safety Badge */}
      <div
        style={{
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: epistemicConfig.bg,
          borderBottom: `1px solid ${epistemicConfig.border}`,
        }}
      >
        <span style={{ fontSize: '0.6875rem', color: '#94a3b8', textTransform: 'uppercase' }}>
          Epistemic Status
        </span>
        <span
          data-testid="hud-epistemic-status"
          style={{
            fontSize: '0.6875rem',
            fontWeight: 700,
            color: epistemicConfig.text,
            letterSpacing: '0.04em',
          }}
        >
          {epistemicConfig.label}
        </span>
      </div>

      {/* Telemetry Matrix Grid */}
      <div
        style={{
          padding: '12px 14px',
          display: 'grid',
          gridTemplateColumns: '120px 1fr',
          rowGap: '6px',
          columnGap: '8px',
          fontSize: '0.6875rem',
        }}
      >
        <span style={{ color: '#94a3b8' }}>Operation</span>
        <span data-testid="hud-operation-id" style={{ fontWeight: 600, color: '#f1f5f9' }}>
          {opId}
        </span>

        <span style={{ color: '#94a3b8' }}>Operational Truth</span>
        <span
          data-testid="hud-operational-truth"
          style={{
            fontWeight: 600,
            color: rawEpistemic === 'UNKNOWN' ? '#fbbf24' : '#34d399',
          }}
        >
          {safeOperationalTruth}
        </span>

        <span style={{ color: '#94a3b8' }}>Recovery State</span>
        <span
          data-testid="hud-recovery-state"
          style={{
            fontWeight: 600,
            color: recState === 'COMPLETED' ? '#34d399' : recState === 'ABORTED' ? '#f87171' : '#38bdf8',
          }}
        >
          {safeRecoveryState}
        </span>

        <span style={{ color: '#94a3b8' }}>Failure Class</span>
        <span data-testid="hud-failure-class" style={{ fontWeight: 600, color: '#e2e8f0' }}>
          {failClass}
        </span>

        <span style={{ color: '#94a3b8' }}>Recovery Decision</span>
        <span
          data-testid="hud-recovery-decision"
          style={{
            fontWeight: 700,
            color:
              recDecision === 'ABORT'
                ? '#f87171'
                : recDecision === 'REQUIRE_APPROVAL'
                ? '#f59e0b'
                : recDecision === 'RECONCILE'
                ? '#c084fc'
                : '#38bdf8',
          }}
        >
          {recDecision}
        </span>

        <span style={{ color: '#94a3b8' }}>Policy State</span>
        <span data-testid="hud-policy-state" style={{ color: '#cbd5e1' }}>
          {policyState}
        </span>

        <span style={{ color: '#94a3b8' }}>Governance</span>
        <span
          data-testid="hud-governance-state"
          style={{
            fontWeight: 600,
            color: approvalRequired ? '#f59e0b' : '#34d399',
          }}
        >
          {govState}
        </span>

        <span style={{ color: '#94a3b8' }}>Authority</span>
        <span
          data-testid="hud-authority-state"
          style={{
            fontWeight: 600,
            color: safeAuthorityState === 'BLOCKED' || safeAuthorityState.startsWith('BLOCKED') ? '#f87171' : '#34d399',
          }}
        >
          {safeAuthorityState}
        </span>

        <span style={{ color: '#94a3b8' }}>Approval Req</span>
        <span
          data-testid="hud-approval-required"
          style={{
            fontWeight: 600,
            color: approvalRequired ? '#f59e0b' : '#94a3b8',
          }}
        >
          {approvalRequired ? 'YES (MANDATORY)' : 'NO'}
        </span>

        <span style={{ color: '#94a3b8' }}>Recovery Depth</span>
        <span data-testid="hud-recovery-depth" style={{ color: '#cbd5e1' }}>
          {recDepth} / {maxRecoveryDepth}
        </span>

        <span style={{ color: '#94a3b8' }}>Retries</span>
        <span data-testid="hud-retry-count" style={{ color: '#cbd5e1' }}>
          {retryCount} / {maxRetries}
        </span>

        <span style={{ color: '#94a3b8' }}>Reconciliation</span>
        <span data-testid="hud-reconciliation-state" style={{ color: '#cbd5e1' }}>
          {reconState}
        </span>
      </div>

      {/* Safety Notice Footer */}
      <div
        data-testid="hud-epistemic-safety-notice"
        style={{
          padding: '6px 14px',
          borderTop: '1px solid rgba(56, 189, 248, 0.15)',
          backgroundColor: 'rgba(2, 6, 23, 0.6)',
          fontSize: '0.625rem',
          color: '#64748b',
          textAlign: 'center',
          letterSpacing: '0.02em',
        }}
      >
        OBSERVATIONAL HUD ONLY — EXECUTION & GOVERNANCE REMAIN AUTHORITATIVE
      </div>
    </div>
  );
};
