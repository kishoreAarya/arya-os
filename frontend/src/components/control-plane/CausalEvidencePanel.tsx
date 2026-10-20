/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Causal Evidence & Missing Evidence Panel
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No trace replay or mutation.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - Missing evidence explicitly surfaced and never hidden.
 *    - Cycles and depth truncation prominently flagged.
 *    - Nodes and edges displayed with truthful epistemic statuses.
 */

import React, { useState } from 'react';
import { CausalTraceSummary } from '../../types/controlPlane';
import {
  LifecycleBadge,
  EpistemicBadge,
  SecretScrubbedText,
  formatTimestamp,
} from './EpistemicIndicators';

export interface CausalEvidencePanelProps {
  traces?: readonly CausalTraceSummary[];
  className?: string;
}

export const CausalEvidencePanel: React.FC<CausalEvidencePanelProps> = ({
  traces = [],
  className = '',
}) => {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(
    traces.length > 0 ? traces[0].operationId : null
  );

  const activeTrace = traces.find((t) => t.operationId === selectedTraceId) || traces[0] || null;

  return (
    <div
      data-testid="causal-evidence-panel"
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
            CAUSAL EVIDENCE & TRACE GRAPH
          </span>
          <span
            data-testid="trace-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {traces.length} TRACES
          </span>
        </div>
        <div className="text-[0.625rem] text-slate-500">
          OBSERVATIONAL PROJECTION (STAGE 22 CAUSAL TRACE SERVICE)
        </div>
      </div>

      {traces.length === 0 ? (
        <div
          data-testid="causal-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO CAUSAL TRACES RECORDED (ZERO CAUSAL TREES DISCOVERED)
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Trace Selector (Left Column) */}
          <div className="lg:col-span-4 flex flex-col gap-2 max-h-[450px] overflow-y-auto pr-1">
            {traces.map((trace) => {
              const isSelected = trace.operationId === activeTrace?.operationId;
              return (
                <div
                  key={trace.operationId}
                  data-testid={`trace-card-${trace.operationId}`}
                  onClick={() => setSelectedTraceId(trace.operationId)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelectedTraceId(trace.operationId);
                    }
                  }}
                  className={`flex flex-col gap-1.5 p-2.5 rounded cursor-pointer transition-all border ${
                    isSelected
                      ? 'bg-slate-900 border-amber-500/50 shadow-lg shadow-black/40'
                      : 'bg-slate-950/60 border-slate-800/60 hover:border-slate-700/80'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-200 truncate">
                      {trace.operationId}
                    </span>
                    <span className="text-[0.5625rem] text-slate-400">
                      {trace.nodes.length} NODES
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5 flex-wrap text-[0.5625rem]">
                    {trace.hasMissingEvidence && (
                      <span
                        data-testid="missing-evidence-marker"
                        className="px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 font-bold"
                      >
                        MISSING EVIDENCE
                      </span>
                    )}
                    {trace.hasCycles && (
                      <span className="px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 font-bold">
                        CYCLE DETECTED
                      </span>
                    )}
                    {trace.isTruncated && (
                      <span className="px-1 py-0.5 rounded bg-slate-800 text-slate-400">
                        TRUNCATED
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Trace Nodes & Evidence (Right Column) */}
          <div className="lg:col-span-8 flex flex-col gap-3">
            {activeTrace ? (
              <div
                data-testid="causal-trace-detail"
                className="flex flex-col gap-3 p-3.5 rounded bg-slate-950/80 border border-slate-800/80"
              >
                {/* Header */}
                <div className="flex items-center justify-between border-b border-slate-800/60 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-amber-400">
                      ROOT: {activeTrace.rootNodeId}
                    </span>
                    <span className="text-[0.625rem] text-slate-400">
                      DEPTH: {activeTrace.maxDepthReached}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {activeTrace.hasMissingEvidence && (
                      <span
                        data-testid="missing-evidence-alert"
                        className="text-[0.625rem] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/50 font-bold"
                      >
                        MISSING EVIDENCE DETECTED IN GRAPH
                      </span>
                    )}
                  </div>
                </div>

                {/* Nodes List */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-300">
                    CAUSAL NODES ({activeTrace.nodes.length})
                  </span>
                  <div
                    data-testid="causal-nodes-list"
                    className="flex flex-col gap-1.5 max-h-[300px] overflow-y-auto pr-1"
                  >
                    {activeTrace.nodes.map((node) => {
                      const isMissing = node.evidenceState === 'MISSING_EVIDENCE';
                      return (
                        <div
                          key={node.nodeId}
                          data-testid={`causal-node-${node.nodeId}`}
                          className={`flex flex-col gap-1 p-2 rounded border text-[0.625rem] ${
                            isMissing
                              ? 'bg-amber-950/20 border-amber-500/40 text-amber-200'
                              : 'bg-slate-900/60 border-slate-800/60 text-slate-300'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <div className="flex items-center gap-1.5 truncate">
                              <span className="font-bold text-slate-200">{node.nodeId}</span>
                              <span className="text-slate-500">[{node.nodeType}]</span>
                              <span className="text-slate-300 truncate">
                                <SecretScrubbedText text={node.label} />
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <LifecycleBadge state={node.state} />
                              <EpistemicBadge status={node.epistemicState} size="sm" />
                            </div>
                          </div>

                          <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-0.5">
                            <div className="flex items-center gap-2">
                              <span>DOMAIN: {node.domain}</span>
                              <span>SOURCE: {node.source}</span>
                            </div>
                            <span
                              data-testid="node-evidence-state"
                              className={`px-1 rounded font-bold ${
                                isMissing ? 'text-amber-400 bg-amber-500/20' : 'text-slate-400'
                              }`}
                            >
                              EVIDENCE: {node.evidenceState}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Edges Summary */}
                {activeTrace.edges.length > 0 && (
                  <div className="flex flex-col gap-1 text-[0.625rem] text-slate-400 pt-2 border-t border-slate-800/60">
                    <span className="font-semibold text-slate-300">
                      CAUSAL EDGES ({activeTrace.edges.length})
                    </span>
                    <div className="flex flex-wrap gap-1.5 max-h-[80px] overflow-y-auto">
                      {activeTrace.edges.map((e, idx) => (
                        <span
                          key={`${e.fromNodeId}-${e.toNodeId}-${idx}`}
                          className="px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-800 text-slate-300 text-[0.5625rem]"
                        >
                          {e.fromNodeId} <span className="text-slate-500">&rarr;</span> {e.toNodeId} ({e.edgeType})
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
};
