/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Approval Center Projection Panel
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: Zero approval, rejection, or token issuance buttons.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - Approval requirement is NEVER displayed as a granted approval.
 *    - Explicit states: PENDING, APPROVED, REJECTED, EXPIRED, CANCELLED, UNKNOWN.
 *    - Expiry timestamps and risk levels clearly presented.
 */

import React from 'react';
import { ApprovalSummary } from '../../types/controlPlane';
import {
  LifecycleBadge,
  SecretScrubbedText,
  formatTimestamp,
} from './EpistemicIndicators';

export interface ApprovalCenterPanelProps {
  approvals?: readonly ApprovalSummary[];
  className?: string;
}

export const ApprovalCenterPanel: React.FC<ApprovalCenterPanelProps> = ({
  approvals = [],
  className = '',
}) => {
  return (
    <div
      data-testid="approval-center-panel"
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
            HUMAN APPROVAL REQUIREMENTS & RECORDS
          </span>
          <span
            data-testid="approval-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {approvals.length} RECORDS
          </span>
        </div>
        <div className="text-[0.625rem] text-slate-500">
          OBSERVATIONAL PROJECTION (STAGE 21 GOVERNANCE & STAGE 20 POLICY)
        </div>
      </div>

      {approvals.length === 0 ? (
        <div
          data-testid="approval-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO APPROVAL RECORDS FOUND (ZERO ACTIVE APPROVAL GATES PENDING)
        </div>
      ) : (
        <div
          data-testid="approval-records-list"
          className="flex flex-col gap-2 max-h-[500px] overflow-y-auto pr-1"
        >
          {approvals.map((app) => {
            const isApproved = app.approvalState === 'APPROVED';
            const isPending = app.approvalState === 'PENDING';
            const isRejected = app.approvalState === 'REJECTED';
            const isExpired = app.approvalState === 'EXPIRED';

            return (
              <div
                key={app.approvalId}
                data-testid={`approval-card-${app.approvalId}`}
                className="flex flex-col gap-2 p-3 rounded bg-slate-950/70 border border-slate-800/70"
              >
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold text-amber-400">
                      {app.approvalId}
                    </span>
                    <LifecycleBadge state={app.approvalState} />
                    <span
                      data-testid="approval-risk-badge"
                      className="text-[0.5625rem] px-1.5 py-0.5 rounded font-bold uppercase"
                      style={{
                        backgroundColor:
                          app.riskLevel === 'CRITICAL'
                            ? 'rgba(239, 68, 68, 0.2)'
                            : app.riskLevel === 'HIGH'
                            ? 'rgba(251, 146, 60, 0.2)'
                            : app.riskLevel === 'MEDIUM'
                            ? 'rgba(245, 158, 11, 0.2)'
                            : 'rgba(56, 189, 248, 0.2)',
                        color:
                          app.riskLevel === 'CRITICAL'
                            ? '#f87171'
                            : app.riskLevel === 'HIGH'
                            ? '#fb923c'
                            : app.riskLevel === 'MEDIUM'
                            ? '#fbbf24'
                            : '#38bdf8',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                      }}
                    >
                      RISK: {app.riskLevel}
                    </span>
                  </div>

                  <span className="text-[0.625rem] text-slate-400">
                    EXPIRES: <strong className="text-slate-200">{formatTimestamp(app.expiresAt)}</strong>
                  </span>
                </div>

                {app.actionTitle && (
                  <div className="text-xs text-slate-200 font-semibold">
                    <SecretScrubbedText text={app.actionTitle} />
                  </div>
                )}

                {app.reason && (
                  <div className="text-[0.625rem] text-slate-400 bg-slate-900/50 p-1.5 rounded border border-slate-800/40">
                    <span className="text-slate-500 font-bold mr-1">RATIONALE:</span>
                    <SecretScrubbedText text={app.reason} />
                  </div>
                )}

                {/* Status Explanation Banner */}
                <div
                  data-testid="approval-truth-explanation"
                  className="p-1.5 rounded text-[0.625rem] flex items-center justify-between"
                  style={{
                    backgroundColor: isApproved
                      ? 'rgba(16, 185, 129, 0.1)'
                      : isPending
                      ? 'rgba(245, 158, 11, 0.1)'
                      : isRejected
                      ? 'rgba(239, 68, 68, 0.1)'
                      : 'rgba(100, 116, 139, 0.1)',
                    color: isApproved
                      ? '#34d399'
                      : isPending
                      ? '#fbbf24'
                      : isRejected
                      ? '#f87171'
                      : '#94a3b8',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                  }}
                >
                  <span>
                    {isApproved
                      ? `AUTHORIZATION GRANTED by ${app.actorId || 'UNKNOWN'} at ${formatTimestamp(app.approvedAt)}`
                      : isPending
                      ? 'APPROVAL REQUIRED: Action blocked until authoritative human operator token is issued.'
                      : isRejected
                      ? `APPROVAL REJECTED by ${app.actorId || 'UNKNOWN'} at ${formatTimestamp(app.rejectedAt)}`
                      : isExpired
                      ? 'APPROVAL WINDOW EXPIRED: Authority failed closed.'
                      : `APPROVAL STATE: ${app.approvalState}`}
                  </span>
                </div>

                {/* Footer references */}
                <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-1 border-t border-slate-800/50 flex-wrap gap-1">
                  <span>REQUEST ID: {app.requestId || 'UNKNOWN'}</span>
                  <span>POLICY SNAPSHOT: {app.policySnapshotId || 'UNKNOWN'} (v{app.policyVersion ?? '?'})</span>
                  <span>CREATED: {formatTimestamp(app.createdAt)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
