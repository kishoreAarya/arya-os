/**
 * AryaOS V1 — Stage 05: Spatial Action Preview Card
 *
 * Cinematic confirmation modal enforcing the non-automatic execution boundary:
 * Consequential actions require explicit operator confirmation before execution or planning.
 */

import React from 'react';
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  Users,
  Compass,
} from 'lucide-react';
import { ActionProposal } from '../../types/spatialCommand';
import { ExecutionPlan } from '../../types/intelligenceProvider';

export interface SpatialActionPreviewProps {
  proposal: ActionProposal;
  executionPlan?: ExecutionPlan | null;
  onConfirm: () => void;
  onCancel: () => void;
  isReducedMotion?: boolean;
}

export const SpatialActionPreview: React.FC<SpatialActionPreviewProps> = ({
  proposal,
  executionPlan,
  onConfirm,
  onCancel,
}) => {
  return (
    <div
      role="dialog"
      aria-label={`Action Proposal: ${proposal.title}`}
      data-testid="spatial-action-preview"
      style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: '420px',
        maxWidth: 'calc(100vw - 2rem)',
        backgroundColor: 'rgba(7, 10, 18, 0.96)',
        backdropFilter: 'blur(28px)',
        border: '1px solid rgba(245, 158, 11, 0.4)',
        borderRadius: '8px',
        boxShadow: '0 20px 60px rgba(0, 0, 0, 0.9), 0 0 30px rgba(245, 158, 11, 0.2)',
        zIndex: 50,
        pointerEvents: 'auto',
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        color: '#cbd5e1',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '0.875rem 1rem',
          backgroundColor: 'rgba(245, 158, 11, 0.1)',
          borderBottom: '1px solid rgba(245, 158, 11, 0.25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ShieldAlert size={16} color="#f59e0b" />
          <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#f59e0b', letterSpacing: '0.08em' }}>
            ACTION PROPOSAL // REQUIRE CONFIRMATION
          </span>
        </div>
        <span
          style={{
            fontSize: '0.5625rem',
            padding: '1px 5px',
            borderRadius: '2px',
            backgroundColor: 'rgba(245, 158, 11, 0.2)',
            color: '#fbbf24',
            border: '1px solid rgba(245, 158, 11, 0.3)',
          }}
        >
          {proposal.actionClass}
        </span>
      </div>

      {/* Body */}
      <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
        <div>
          <h3
            data-testid="action-proposal-title"
            style={{
              fontSize: '0.875rem',
              fontWeight: 700,
              color: '#f8fafc',
              margin: '0 0 0.375rem 0',
              lineHeight: 1.35,
            }}
          >
            {proposal.title}
          </h3>
          <p
            data-testid="action-proposal-description"
            style={{
              fontSize: '0.6875rem',
              color: '#94a3b8',
              margin: 0,
              lineHeight: 1.5,
            }}
          >
            {proposal.description}
          </p>
        </div>

        {/* Source Memory Anchor */}
        {proposal.sourceMemoryId && (
          <div
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '4px',
              padding: '0.5rem 0.75rem',
            }}
          >
            <span style={{ fontSize: '0.5625rem', color: '#64748b', display: 'block', marginBottom: '2px' }}>
              SOURCE MEMORY ANCHOR
            </span>
            <span style={{ fontSize: '0.6875rem', color: '#38bdf8', fontWeight: 600 }}>
              [{proposal.sourceMemoryId}] {proposal.sourceMemoryTitle}
            </span>
          </div>
        )}

        {/* Context Summary */}
        <div
          style={{
            backgroundColor: 'rgba(15, 23, 42, 0.4)',
            border: '1px solid rgba(255, 255, 255, 0.05)',
            borderRadius: '4px',
            padding: '0.625rem 0.75rem',
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: '0.5rem',
            fontSize: '0.625rem',
          }}
        >
          <div>
            <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <Compass size={11} color="#38bdf8" />
              <span>RELATED</span>
            </div>
            <div style={{ color: '#f8fafc', fontWeight: 700, marginTop: '2px' }}>
              {proposal.contextSummary.relatedCount} records
            </div>
          </div>

          <div>
            <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <Users size={11} color="#38bdf8" />
              <span>ENTITIES</span>
            </div>
            <div style={{ color: '#f8fafc', fontWeight: 700, marginTop: '2px' }}>
              {proposal.contextSummary.entitiesCount} active
            </div>
          </div>

          <div>
            <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <Layers size={11} color="#38bdf8" />
              <span>DECISIONS</span>
            </div>
            <div style={{ color: '#f8fafc', fontWeight: 700, marginTop: '2px' }}>
              {proposal.contextSummary.decisionsCount} precedents
            </div>
          </div>
        </div>

        {/* Intelligence Routing Block (Stage 06) */}
        {executionPlan && (
          <div
            data-testid="spatial-routing-block"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.7)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '6px',
              padding: '0.625rem 0.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.375rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '0.625rem', fontWeight: 700, color: '#38bdf8', letterSpacing: '0.06em' }}>
                INTELLIGENCE ROUTING // {executionPlan.capability}
              </span>
              <span
                data-testid="routing-plan-status"
                style={{
                  fontSize: '0.5625rem',
                  padding: '1px 5px',
                  borderRadius: '2px',
                  backgroundColor:
                    executionPlan.status === 'ROUTED'
                      ? 'rgba(16, 185, 129, 0.2)'
                      : 'rgba(245, 158, 11, 0.2)',
                  color: executionPlan.status === 'ROUTED' ? '#10b981' : '#fbbf24',
                  fontWeight: 600,
                }}
              >
                {executionPlan.status}
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.375rem', fontSize: '0.625rem' }}>
              <div>
                <span style={{ color: '#64748b' }}>PROVIDER: </span>
                <span data-testid="routing-provider-name" style={{ color: '#f8fafc', fontWeight: 600 }}>
                  {executionPlan.providerName}
                </span>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>MODEL: </span>
                <span data-testid="routing-model-id" style={{ color: '#f8fafc', fontWeight: 600 }}>
                  {executionPlan.modelId}
                </span>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>CONTEXT: </span>
                <span style={{ color: '#38bdf8' }}>
                  {executionPlan.contextPackage.memoryContext.length} memories (~{executionPlan.contextPackage.tokenEstimate} tokens)
                </span>
              </div>
              {executionPlan.fallbackProviderId && (
                <div>
                  <span style={{ color: '#64748b' }}>FALLBACK: </span>
                  <span style={{ color: '#94a3b8' }}>{executionPlan.fallbackProviderId}</span>
                </div>
              )}
            </div>

            {executionPlan.routingRationale?.reasons && (
              <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: '0.375rem' }}>
                <span style={{ fontSize: '0.5625rem', color: '#64748b', display: 'block', marginBottom: '2px' }}>
                  ROUTING RATIONALE:
                </span>
                {executionPlan.routingRationale.reasons.slice(0, 2).map((r, i) => (
                  <div key={i} style={{ fontSize: '0.5625rem', color: '#94a3b8', lineHeight: 1.3 }}>
                    • {r}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Execution Type / Status */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.375rem 0.5rem',
            backgroundColor: 'rgba(245, 158, 11, 0.05)',
            borderRadius: '4px',
            border: '1px solid rgba(245, 158, 11, 0.15)',
            fontSize: '0.625rem',
          }}
        >
          <span style={{ color: '#94a3b8' }}>EXECUTION MODE:</span>
          <span style={{ color: '#fbbf24', fontWeight: 700 }}>
            {proposal.executionType === 'BACKEND_ADAPTER'
              ? 'PLANNED (STAGED FOR ORCHESTRATOR)'
              : 'DIRECT SPATIAL EXECUTION'}
          </span>
        </div>
      </div>

      {/* Footer Actions */}
      <div
        style={{
          padding: '0.75rem 1rem',
          backgroundColor: 'rgba(15, 23, 42, 0.7)',
          borderTop: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: '0.625rem',
        }}
      >
        <button
          type="button"
          data-testid="action-proposal-cancel-btn"
          onClick={onCancel}
          style={{
            backgroundColor: 'transparent',
            border: '1px solid rgba(255, 255, 255, 0.15)',
            color: '#94a3b8',
            borderRadius: '4px',
            padding: '5px 12px',
            fontSize: '0.6875rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            fontFamily: 'inherit',
          }}
        >
          <XCircle size={13} />
          CANCEL
        </button>

        <button
          type="button"
          data-testid="action-proposal-confirm-btn"
          onClick={onConfirm}
          style={{
            backgroundColor: 'rgba(245, 158, 11, 0.2)',
            border: '1px solid #f59e0b',
            color: '#fbbf24',
            borderRadius: '4px',
            padding: '5px 14px',
            fontSize: '0.6875rem',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            fontFamily: 'inherit',
            boxShadow: '0 0 16px rgba(245, 158, 11, 0.25)',
          }}
        >
          <CheckCircle2 size={13} />
          CONFIRM EXECUTION
        </button>
      </div>
    </div>
  );
};
