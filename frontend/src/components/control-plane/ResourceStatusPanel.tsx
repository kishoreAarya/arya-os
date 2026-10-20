/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Resource Status Panel (Allocation vs Verified Utilization)
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No resource reallocation, quota mutation, or reservation.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - Resource allocation (limits) is STRICTLY separated from verified utilization.
 *    - Allocation does NOT imply utilization.
 *    - If utilization is untracked/unverified, displays 'UNKNOWN' without fabricating synthetic numbers.
 */

import React from 'react';
import { MissionResourceSummary } from '../../services/controlPlaneSnapshotService';
import { LifecycleBadge } from './EpistemicIndicators';

export interface ResourceStatusPanelProps {
  resources?: readonly MissionResourceSummary[];
  missionTitle?: string;
  className?: string;
}

export const ResourceStatusPanel: React.FC<ResourceStatusPanelProps> = ({
  resources = [],
  missionTitle,
  className = '',
}) => {
  return (
    <div
      data-testid="resource-status-panel"
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
            RESOURCE ALLOCATION VS TELEMETRY UTILIZATION
          </span>
          <span
            data-testid="resource-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {resources.length} ALLOCATIONS
          </span>
        </div>
        {missionTitle && (
          <div className="text-[0.625rem] text-slate-400">
            SCOPE: <span className="text-amber-400">{missionTitle}</span>
          </div>
        )}
      </div>

      {resources.length === 0 ? (
        <div
          data-testid="resource-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO RESOURCE ALLOCATIONS CONFIGURED FOR ACTIVE MISSIONS (ZERO ARTIFICIAL BUDGET FABRICATED)
        </div>
      ) : (
        <div
          data-testid="resource-items-list"
          className="grid grid-cols-1 md:grid-cols-2 gap-2.5 max-h-[450px] overflow-y-auto pr-1"
        >
          {resources.map((res, idx) => {
            const isUtilizedKnown = typeof res.utilized === 'number';
            const unitStr = res.unit ? ` ${res.unit}` : '';
            const allocatedStr = typeof res.allocated === 'number' || typeof res.allocated === 'string'
              ? `${res.allocated}${unitStr}`
              : 'UNSPECIFIED';
            const utilizedStr = isUtilizedKnown
              ? `${res.utilized}${unitStr}`
              : 'UNKNOWN (UNTRACKED)';

            return (
              <div
                key={`${res.resourceType}-${idx}`}
                data-testid={`resource-card-${res.resourceType.toLowerCase()}`}
                className="flex flex-col gap-2 p-3 rounded bg-slate-950/70 border border-slate-800/70"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-200 uppercase">
                    {res.resourceType}
                  </span>
                  <LifecycleBadge state={res.status} />
                </div>

                <div className="text-[0.625rem] text-slate-400">
                  PROVENANCE: <span className="text-slate-300">{res.provenance}</span>
                </div>

                {/* Metrics Breakdown: Allocation vs Telemetry */}
                <div className="grid grid-cols-2 gap-2 bg-slate-900/50 p-2 rounded border border-slate-800/40 text-[0.625rem]">
                  <div>
                    <span className="text-slate-500 font-bold block">ALLOCATED LIMIT:</span>
                    <strong
                      data-testid="resource-allocated-value"
                      className="text-slate-200"
                    >
                      {allocatedStr}
                    </strong>
                  </div>
                  <div>
                    <span className="text-slate-500 font-bold block">VERIFIED UTILIZATION:</span>
                    <strong
                      data-testid="resource-utilized-value"
                      className={isUtilizedKnown ? 'text-emerald-400' : 'text-amber-400'}
                    >
                      {utilizedStr}
                    </strong>
                  </div>
                </div>

                {/* Epistemic note */}
                <div className="text-[0.5625rem] text-slate-500">
                  {isUtilizedKnown
                    ? '* Sourced directly from Stage 10 Resource Governor telemetry.'
                    : '* Telemetry absent. Allocation does not prove consumption.'}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
