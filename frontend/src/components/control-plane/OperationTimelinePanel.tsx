/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Operation Timeline Panel & Canonical Lifecycle Inspector
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No retry, dispatch, or execute buttons.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - 16 canonical states preserved.
 *    - Entries ordered chronologically.
 *    - UNKNOWN states never masked.
 */

import React, { useState } from 'react';
import {
  OperationSummary,
  OperationTimeline,
} from '../../types/controlPlane';
import { controlPlaneSnapshotService } from '../../services/controlPlaneSnapshotService';
import {
  LifecycleBadge,
  EpistemicBadge,
  SecretScrubbedText,
  formatTimestamp,
} from './EpistemicIndicators';

export interface OperationTimelinePanelProps {
  operations?: readonly OperationSummary[];
  selectedOperationId?: string | null;
  onSelectOperation?: (operationId: string) => void;
  className?: string;
}

export const OperationTimelinePanel: React.FC<OperationTimelinePanelProps> = ({
  operations = [],
  selectedOperationId: propSelectedOpId,
  onSelectOperation,
  className = '',
}) => {
  const [internalSelectedOpId, setInternalSelectedOpId] = useState<string | null>(null);
  const activeOpId = propSelectedOpId !== undefined ? propSelectedOpId : internalSelectedOpId;

  // Retrieve timeline for active operation
  const activeTimeline: OperationTimeline | null = activeOpId
    ? controlPlaneSnapshotService.projectOperationTimeline(activeOpId)
    : null;

  const handleSelect = (opId: string) => {
    setInternalSelectedOpId(opId);
    onSelectOperation?.(opId);
  };

  return (
    <div
      data-testid="operation-timeline-panel"
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
            OPERATION TIMELINE & CAUSAL AUDIT
          </span>
          <span
            data-testid="operation-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {operations.length} OPERATIONS
          </span>
        </div>
      </div>

      {operations.length === 0 ? (
        <div
          data-testid="timeline-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO OPERATIONS RECORDED IN OPERATIONAL AUDIT LOG
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Operations List (Left Column) */}
          <div className="lg:col-span-5 flex flex-col gap-2 max-h-[500px] overflow-y-auto pr-1">
            {operations.map((op) => {
              const isSelected = op.operationId === activeOpId;
              return (
                <div
                  key={op.operationId}
                  data-testid={`operation-card-${op.operationId}`}
                  onClick={() => handleSelect(op.operationId)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleSelect(op.operationId);
                    }
                  }}
                  className={`flex flex-col gap-1.5 p-2.5 rounded cursor-pointer transition-all border ${
                    isSelected
                      ? 'bg-slate-900 border-amber-500/50 shadow-lg shadow-black/40'
                      : 'bg-slate-950/60 border-slate-800/60 hover:border-slate-700/80'
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-semibold text-slate-200 truncate">
                      {op.operationId}
                    </span>
                    <LifecycleBadge state={op.status} />
                  </div>

                  <div className="text-[0.625rem] text-slate-400 truncate">
                    ACTION: <span className="text-slate-300">{op.actionId || 'UNKNOWN'}</span>
                  </div>

                  <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-1 border-t border-slate-800/40">
                    <div className="flex items-center gap-1.5">
                      <span>RISK: {op.riskLevel}</span>
                    </div>
                    <EpistemicBadge status={op.epistemicState} size="sm" />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Operation Timeline Detail (Right Column) */}
          <div className="lg:col-span-7 flex flex-col gap-3">
            {activeTimeline ? (
              <div
                data-testid="operation-timeline-detail"
                className="flex flex-col gap-3 p-3.5 rounded bg-slate-950/80 border border-slate-800/80"
              >
                {/* Header with Canonical State & Terminal Status */}
                <div className="flex items-start justify-between gap-2 border-b border-slate-800/60 pb-2">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-amber-400">
                        {activeTimeline.operationId}
                      </span>
                      <LifecycleBadge state={activeTimeline.currentState} />
                      <EpistemicBadge status={activeTimeline.epistemicState} size="sm" />
                    </div>
                    <span className="text-[0.625rem] text-slate-400">
                      CURRENT CANONICAL STATE: <strong className="text-slate-200">{activeTimeline.currentState}</strong>
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {activeTimeline.isTerminal && (
                      <span
                        data-testid="timeline-terminal-badge"
                        className="text-[0.5625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 font-bold"
                      >
                        TERMINAL
                      </span>
                    )}
                  </div>
                </div>

                {/* Chronological Timeline Entries */}
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-semibold text-slate-300">
                    LIFECYCLE TRANSITION LOG ({activeTimeline.entries.length} EVENTS)
                  </span>

                  <div
                    data-testid="timeline-entries-container"
                    className="flex flex-col gap-2 max-h-[340px] overflow-y-auto pr-1"
                  >
                    {activeTimeline.entries.length === 0 ? (
                      <span className="text-[0.625rem] text-slate-500">NO TIMELINE ENTRIES FOUND</span>
                    ) : (
                      activeTimeline.entries.map((entry, idx) => (
                        <div
                          key={`${entry.state}-${idx}`}
                          data-testid="timeline-entry-row"
                          className="flex flex-col gap-1 p-2 rounded bg-slate-900/60 border border-slate-800/60 text-[0.625rem]"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-slate-500 font-bold">#{idx + 1}</span>
                              <LifecycleBadge state={entry.state} />
                              <span className="text-slate-400">via {entry.source || 'UNKNOWN'}</span>
                            </div>
                            <EpistemicBadge status={entry.epistemicState} size="sm" />
                          </div>

                          {entry.reason && (
                            <div className="text-[0.625rem] text-slate-300 bg-slate-950/60 p-1.5 rounded border border-slate-800/40">
                              <SecretScrubbedText text={entry.reason} />
                            </div>
                          )}

                          <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-0.5">
                            <span>TIMESTAMP: {formatTimestamp(entry.timestamp)}</span>
                            {entry.causationId && (
                              <span>CAUSATION: {entry.causationId}</span>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Footer Timestamps */}
                <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-2 border-t border-slate-800/60">
                  <span>STARTED: {formatTimestamp(activeTimeline.startedAt)}</span>
                  <span>UPDATED: {formatTimestamp(activeTimeline.lastUpdatedAt)}</span>
                </div>
              </div>
            ) : (
              <div
                data-testid="no-operation-selected"
                className="p-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded flex flex-col items-center justify-center h-full min-h-[300px]"
              >
                SELECT AN OPERATION FROM THE LIST TO INSPECT ITS CHRONOLOGICAL TIMELINE AND CAUSAL AUDIT LOG
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
