/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * System Health Subsystem Panel
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No mutation, execution, or dispatch.
 * 3. EPISTEMIC TRUTHFULNESS: Displays canonical subsystem health without masking failures or UNKNOWN states.
 */

import React from 'react';
import {
  SystemHealthSummary,
  SubsystemHealthRecord,
} from '../../types/controlPlane';
import { LifecycleBadge, formatTimestamp } from './EpistemicIndicators';

export interface SystemHealthPanelProps {
  health?: SystemHealthSummary | null;
  className?: string;
}

interface SubsystemItem {
  id: string;
  name: string;
  record?: SubsystemHealthRecord;
}

export const SystemHealthPanel: React.FC<SystemHealthPanelProps> = ({
  health,
  className = '',
}) => {
  if (!health) {
    return (
      <div
        data-testid="system-health-panel-empty"
        className={`p-4 rounded border border-slate-800 bg-slate-950/80 text-slate-400 font-mono text-xs ${className}`}
      >
        <span>SYSTEM HEALTH TELEMETRY UNAVAILABLE (NO SNAPSHOT RECORD)</span>
      </div>
    );
  }

  const subsystems: SubsystemItem[] = [
    { id: 'execution', name: 'Execution Gateway', record: health.execution },
    { id: 'providers', name: 'Intelligence Providers', record: health.providers },
    { id: 'connectors', name: 'Connector Fabric', record: health.connectors },
    { id: 'persistence', name: 'Execution Persistence', record: health.persistence },
    { id: 'governance', name: 'Governance Control Plane', record: health.governance },
    { id: 'recovery', name: 'Recovery Control Plane', record: health.recovery },
    { id: 'eventIngestion', name: 'Event Ingestion Engine', record: health.eventIngestion },
    { id: 'missions', name: 'Mission Operations', record: health.missions },
    { id: 'actionBus', name: 'Universal Action Bus', record: health.actionBus },
  ];

  return (
    <div
      data-testid="system-health-panel"
      className={`flex flex-col gap-3 font-mono ${className}`}
      style={{
        backgroundColor: 'rgba(11, 15, 23, 0.85)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '8px',
        padding: '1rem',
      }}
    >
      {/* Header with Overall Status & Durability Flag */}
      <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-200 tracking-wider">
            SUBSYSTEM HEALTH MATRIX
          </span>
          <LifecycleBadge state={health.overallStatus} />
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span
            data-testid="health-durability-flag"
            className="flex items-center gap-1"
            style={{
              color: health.isDurableStorage ? '#34d399' : '#fbbf24',
            }}
          >
            <span>STORAGE:</span>
            <strong>{health.isDurableStorage ? 'DURABLE PERSISTENCE' : 'IN-MEMORY FALLBACK'}</strong>
          </span>
        </div>
      </div>

      {/* Subsystem Grid */}
      <div
        data-testid="subsystems-grid"
        className="grid grid-cols-1 md:grid-cols-3 gap-2"
      >
        {subsystems.map(({ id, name, record }) => {
          const status = record?.status || 'UNKNOWN';
          const message = record?.message || 'No additional status message';
          const lastChecked = formatTimestamp(record?.lastCheckedAt);

          return (
            <div
              key={id}
              data-testid={`subsystem-card-${id}`}
              className="flex flex-col gap-1 p-2.5 rounded bg-slate-900/60 border border-slate-800/60 hover:border-slate-700/60 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300 truncate" title={name}>
                  {name}
                </span>
                <LifecycleBadge state={status} />
              </div>
              <p className="text-[0.625rem] text-slate-400 line-clamp-2" title={message}>
                {message}
              </p>
              <div className="mt-auto pt-1 flex items-center justify-between text-[0.5625rem] text-slate-500">
                <span>CHECKED:</span>
                <span className="text-slate-400">{lastChecked}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
