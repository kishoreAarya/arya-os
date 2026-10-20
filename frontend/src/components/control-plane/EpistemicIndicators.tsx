/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Epistemic & Integrity Indicator Badges
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No mutation, execution, or dispatch.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - UNKNOWN is never rendered as SUCCESS or hidden.
 *    - Inferred/Projected is clearly distinguished from Confirmed/Observed.
 *    - Secret patterns are scrubbed before display.
 */

import React from 'react';
import { EpistemicStatus } from '../../types/operationalAudit';
import { SourceIntegrityStatus } from '../../services/controlPlaneSnapshotService';

// ============================================================================
// 1. Epistemic Status Badges
// ============================================================================

export interface EpistemicBadgeProps {
  status?: EpistemicStatus | string;
  className?: string;
  size?: 'sm' | 'md';
}

const EPISTEMIC_CONFIG: Record<
  string,
  { bg: string; text: string; border: string; label: string }
> = {
  OBSERVED: {
    bg: 'rgba(56, 189, 248, 0.15)',
    text: '#38bdf8',
    border: 'rgba(56, 189, 248, 0.4)',
    label: 'OBSERVED',
  },
  CONFIRMED: {
    bg: 'rgba(16, 185, 129, 0.15)',
    text: '#34d399',
    border: 'rgba(16, 185, 129, 0.4)',
    label: 'CONFIRMED',
  },
  INFERRED: {
    bg: 'rgba(168, 85, 247, 0.15)',
    text: '#c084fc',
    border: 'rgba(168, 85, 247, 0.4)',
    label: 'INFERRED',
  },
  PROJECTED: {
    bg: 'rgba(245, 158, 11, 0.15)',
    text: '#fbbf24',
    border: 'rgba(245, 158, 11, 0.4)',
    label: 'PROJECTED',
  },
  UNKNOWN: {
    bg: 'rgba(239, 68, 68, 0.15)',
    text: '#f87171',
    border: 'rgba(239, 68, 68, 0.4)',
    label: 'UNKNOWN (UNVERIFIED)',
  },
};

export const EpistemicBadge: React.FC<EpistemicBadgeProps> = ({
  status = 'UNKNOWN',
  className = '',
  size = 'sm',
}) => {
  const norm = String(status).toUpperCase();
  const config = EPISTEMIC_CONFIG[norm] || EPISTEMIC_CONFIG.UNKNOWN;
  const padding = size === 'sm' ? '1px 6px' : '2px 8px';
  const fontSize = size === 'sm' ? '0.625rem' : '0.6875rem';

  return (
    <span
      data-testid="epistemic-badge"
      data-status={norm}
      className={`font-mono inline-flex items-center uppercase tracking-wider font-semibold rounded ${className}`}
      style={{
        backgroundColor: config.bg,
        color: config.text,
        border: `1px solid ${config.border}`,
        padding,
        fontSize,
        whiteSpace: 'nowrap',
      }}
    >
      {config.label}
    </span>
  );
};

// ============================================================================
// 2. Source Integrity Badges
// ============================================================================

export interface SourceIntegrityBadgeProps {
  integrity?: SourceIntegrityStatus | string;
  className?: string;
}

const INTEGRITY_CONFIG: Record<
  string,
  { bg: string; text: string; border: string; label: string }
> = {
  VERIFIED: {
    bg: 'rgba(16, 185, 129, 0.15)',
    text: '#34d399',
    border: 'rgba(16, 185, 129, 0.35)',
    label: 'SOURCE: VERIFIED',
  },
  INCOMPLETE: {
    bg: 'rgba(245, 158, 11, 0.15)',
    text: '#fbbf24',
    border: 'rgba(245, 158, 11, 0.35)',
    label: 'SOURCE: INCOMPLETE',
  },
  STALE: {
    bg: 'rgba(251, 146, 60, 0.15)',
    text: '#fb923c',
    border: 'rgba(251, 146, 60, 0.35)',
    label: 'SOURCE: STALE (>30D)',
  },
  CONFLICTING: {
    bg: 'rgba(239, 68, 68, 0.2)',
    text: '#f87171',
    border: 'rgba(239, 68, 68, 0.5)',
    label: 'SOURCE: CONFLICTING',
  },
};

export const SourceIntegrityBadge: React.FC<SourceIntegrityBadgeProps> = ({
  integrity = 'VERIFIED',
  className = '',
}) => {
  const norm = String(integrity).toUpperCase();
  const config = INTEGRITY_CONFIG[norm] || INTEGRITY_CONFIG.VERIFIED;

  return (
    <span
      data-testid="source-integrity-badge"
      data-integrity={norm}
      className={`font-mono inline-flex items-center uppercase tracking-wider font-semibold rounded ${className}`}
      style={{
        backgroundColor: config.bg,
        color: config.text,
        border: `1px solid ${config.border}`,
        padding: '1px 6px',
        fontSize: '0.5625rem',
        whiteSpace: 'nowrap',
      }}
    >
      {config.label}
    </span>
  );
};

// ============================================================================
// 3. Canonical Lifecycle State Badges
// ============================================================================

export interface LifecycleBadgeProps {
  state?: string;
  className?: string;
}

export const LifecycleBadge: React.FC<LifecycleBadgeProps> = ({
  state = 'UNKNOWN',
  className = '',
}) => {
  const norm = String(state).toUpperCase();

  let bg = 'rgba(100, 116, 139, 0.15)';
  let text = '#94a3b8';
  let border = 'rgba(100, 116, 139, 0.35)';

  if (['COMPLETED', 'SUCCEEDED', 'HEALTHY', 'ACTIVE', 'VERIFIED'].includes(norm)) {
    bg = 'rgba(16, 185, 129, 0.15)';
    text = '#34d399';
    border = 'rgba(16, 185, 129, 0.4)';
  } else if (['EXECUTING', 'RUNNING', 'DISPATCHED', 'AUTHORIZED', 'PROBING'].includes(norm)) {
    bg = 'rgba(56, 189, 248, 0.15)';
    text = '#38bdf8';
    border = 'rgba(56, 189, 248, 0.4)';
  } else if (['PLANNED', 'PROPOSED', 'REQUESTED', 'PENDING', 'GOVERNED', 'DEFERRED', 'PAUSED'].includes(norm)) {
    bg = 'rgba(245, 158, 11, 0.15)';
    text = '#fbbf24';
    border = 'rgba(245, 158, 11, 0.4)';
  } else if (['FAILED', 'REJECTED', 'DENIED', 'DEGRADED', 'BLOCKED', 'CANCELLED'].includes(norm)) {
    bg = 'rgba(239, 68, 68, 0.15)';
    text = '#f87171';
    border = 'rgba(239, 68, 68, 0.4)';
  } else if (norm === 'UNKNOWN') {
    bg = 'rgba(239, 68, 68, 0.2)';
    text = '#fca5a5';
    border = 'rgba(239, 68, 68, 0.5)';
  }

  return (
    <span
      data-testid="lifecycle-badge"
      data-state={norm}
      className={`font-mono inline-flex items-center uppercase tracking-wider font-semibold rounded ${className}`}
      style={{
        backgroundColor: bg,
        color: text,
        border: `1px solid ${border}`,
        padding: '1px 6px',
        fontSize: '0.625rem',
        whiteSpace: 'nowrap',
      }}
    >
      {norm}
    </span>
  );
};

// ============================================================================
// 4. Progress Provenance Badge
// ============================================================================

export interface ProgressProvenanceBadgeProps {
  isDerived: boolean;
  isConsistent: boolean;
  totalGoals?: number;
  completedGoals?: number;
}

export const ProgressProvenanceBadge: React.FC<ProgressProvenanceBadgeProps> = ({
  isDerived,
  isConsistent,
  totalGoals,
  completedGoals,
}) => {
  return (
    <div
      data-testid="progress-provenance-badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.35rem',
        fontSize: '0.5625rem',
        fontFamily: 'monospace',
      }}
    >
      <span
        style={{
          padding: '1px 5px',
          borderRadius: '2px',
          backgroundColor: isDerived ? 'rgba(168, 85, 247, 0.15)' : 'rgba(56, 189, 248, 0.15)',
          color: isDerived ? '#c084fc' : '#38bdf8',
          border: isDerived ? '1px solid rgba(168, 85, 247, 0.35)' : '1px solid rgba(56, 189, 248, 0.35)',
        }}
      >
        {isDerived ? 'DERIVED PROGRESS' : 'RECORDED PROGRESS'}
      </span>
      {!isConsistent && (
        <span
          data-testid="progress-inconsistency-flag"
          style={{
            padding: '1px 5px',
            borderRadius: '2px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            color: '#f87171',
            border: '1px solid rgba(239, 68, 68, 0.35)',
          }}
          title="Progress record conflicts with goal count tally"
        >
          TALLY MISMATCH
        </span>
      )}
      {totalGoals !== undefined && completedGoals !== undefined && (
        <span style={{ color: '#94a3b8' }}>
          ({completedGoals}/{totalGoals} goals)
        </span>
      )}
    </div>
  );
};

// ============================================================================
// 5. Safe Text & Secret Scrubbing
// ============================================================================

const SECRET_PATTERNS = [
  /Bearer\s+[A-Za-z0-9_\-.~+/]+=*/gi,
  /(?:api[_-]?key|secret|token|password|auth)[\s:=]+["']?([A-Za-z0-9_\-.~+/]+)["']?/gi,
  /sk-[A-Za-z0-9]{20,}/gi,
];

export function scrubSecrets(input: unknown): string {
  if (input === null || input === undefined) return '';
  let str = String(input);
  for (const pattern of SECRET_PATTERNS) {
    str = str.replace(pattern, (match) => {
      if (match.toLowerCase().startsWith('bearer')) {
        return 'Bearer [REDACTED_TOKEN]';
      }
      return '[REDACTED_SECRET]';
    });
  }
  return str;
}

export const SecretScrubbedText: React.FC<{ text?: string | number | null; className?: string }> = ({
  text,
  className = '',
}) => {
  const sanitized = scrubSecrets(text);
  return <span className={className}>{sanitized}</span>;
};

// ============================================================================
// 6. Safe Timestamp Formatter
// ============================================================================

export function formatTimestamp(ts: unknown): string {
  if (typeof ts === 'string' && ts === 'UNKNOWN') return 'UNKNOWN';
  if (typeof ts === 'number' && Number.isFinite(ts) && ts > 0) {
    try {
      return new Date(ts).toISOString();
    } catch {
      return 'UNKNOWN';
    }
  }
  return 'UNKNOWN';
}
