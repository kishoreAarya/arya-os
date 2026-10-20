/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Mission Operations Panel & Detail Inspector
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No mission creation, execution, cancellation, or scheduling buttons.
 * 3. EPISTEMIC TRUTHFULNESS:
 *    - Canonical statuses only; non-canonical maps to UNKNOWN.
 *    - Derived progress is prominently labeled as derived with provenance.
 *    - Sourced dependencies differentiate SATISFIED, PENDING, BLOCKED, MISSING_EVIDENCE, UNKNOWN.
 *    - Cycle detection warning displayed without infinite loop.
 *    - Checkpoint completion never confused with mission completion.
 */

import React, { useState } from 'react';
import { MissionSummary } from '../../types/controlPlane';
import {
  MissionDetailProjection,
  controlPlaneSnapshotService,
} from '../../services/controlPlaneSnapshotService';
import {
  LifecycleBadge,
  EpistemicBadge,
  SourceIntegrityBadge,
  ProgressProvenanceBadge,
  SecretScrubbedText,
  formatTimestamp,
} from './EpistemicIndicators';

export interface MissionOperationsPanelProps {
  missions?: readonly MissionSummary[];
  selectedMissionId?: string | null;
  onSelectMission?: (missionId: string) => void;
  className?: string;
}

export const MissionOperationsPanel: React.FC<MissionOperationsPanelProps> = ({
  missions = [],
  selectedMissionId: propSelectedMissionId,
  onSelectMission,
  className = '',
}) => {
  const [internalSelectedId, setInternalSelectedId] = useState<string | null>(null);
  const activeMissionId = propSelectedMissionId !== undefined ? propSelectedMissionId : internalSelectedId;

  // Retrieve detail projection for the active mission
  const activeDetail: MissionDetailProjection | null = activeMissionId
    ? controlPlaneSnapshotService.projectMissionDetail(activeMissionId)
    : null;

  const handleSelect = (missionId: string) => {
    setInternalSelectedId(missionId);
    onSelectMission?.(missionId);
  };

  return (
    <div
      data-testid="mission-operations-panel"
      className={`flex flex-col gap-3 font-mono ${className}`}
      style={{
        backgroundColor: 'rgba(11, 15, 23, 0.85)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '8px',
        padding: '1rem',
      }}
    >
      {/* Panel Header */}
      <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-200 tracking-wider">
            MISSION OPERATIONS PROJECTION
          </span>
          <span
            data-testid="mission-count-badge"
            className="text-[0.625rem] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
          >
            {missions.length} MISSIONS
          </span>
        </div>
      </div>

      {missions.length === 0 ? (
        <div
          data-testid="mission-panel-empty"
          className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded"
        >
          NO MISSIONS REGISTERED IN ACTIVE MEMORY OR DURABLE PERSISTENCE
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Mission List (Left Column) */}
          <div className="lg:col-span-5 flex flex-col gap-2 max-h-[520px] overflow-y-auto pr-1">
            {missions.map((m) => {
              const isSelected = m.missionId === activeMissionId;
              return (
                <div
                  key={m.missionId}
                  data-testid={`mission-card-${m.missionId}`}
                  onClick={() => handleSelect(m.missionId)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleSelect(m.missionId);
                    }
                  }}
                  className={`flex flex-col gap-1.5 p-3 rounded cursor-pointer transition-all border ${
                    isSelected
                      ? 'bg-slate-900 border-amber-500/50 shadow-lg shadow-black/40'
                      : 'bg-slate-950/60 border-slate-800/60 hover:border-slate-700/80'
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span
                      data-testid="mission-card-title"
                      className="text-xs font-semibold text-slate-200 truncate"
                    >
                      <SecretScrubbedText text={m.title} />
                    </span>
                    <LifecycleBadge state={m.status} />
                  </div>

                  {(() => {
                    const progressPct =
                      typeof m.progress === 'object' && m.progress !== null && 'percentage' in m.progress
                        ? (m.progress as any).percentage
                        : typeof m.progress === 'number'
                        ? m.progress
                        : 0;

                    return (
                      <>
                        <div className="text-[0.625rem] text-slate-400 line-clamp-1">
                          <span className="text-slate-500 mr-1">GOAL:</span>
                          <SecretScrubbedText text={m.goalId} />
                        </div>

                        <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-800/40 text-[0.5625rem]">
                          <div className="flex items-center gap-1.5">
                            <span className="text-slate-400 font-bold">PRIORITY:</span>
                            <span className="text-slate-200">{m.priority}</span>
                            <span className="text-slate-600">|</span>
                            <span className="text-slate-400">PROGRESS:</span>
                            <span className="text-amber-400 font-bold">{progressPct}%</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <EpistemicBadge status={m.latestTruthState} size="sm" />
                          </div>
                        </div>
                      </>
                    );
                  })()}
                </div>
              );
            })}
          </div>

          {/* Mission Detail Inspector (Right Column) */}
          <div className="lg:col-span-7 flex flex-col gap-3">
            {activeDetail ? (
              <div
                data-testid="mission-detail-inspector"
                className="flex flex-col gap-3 p-3.5 rounded bg-slate-950/80 border border-slate-800/80"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2 border-b border-slate-800/60 pb-2">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-amber-400">
                        {activeDetail.missionId}
                      </span>
                      <LifecycleBadge state={activeDetail.status} />
                      <EpistemicBadge status={activeDetail.epistemicStatus} />
                      <SourceIntegrityBadge integrity={activeDetail.sourceIntegrity} />
                    </div>
                    <h3 className="text-sm font-semibold text-slate-100">
                      <SecretScrubbedText text={activeDetail.title} />
                    </h3>
                  </div>
                </div>

                {/* Objective */}
                <div className="text-[0.6875rem] text-slate-300 bg-slate-900/50 p-2 rounded border border-slate-800/40">
                  <span className="text-slate-500 font-bold mr-1">OBJECTIVE:</span>
                  <SecretScrubbedText text={activeDetail.objective} />
                </div>

                {/* Progress & Provenance */}
                <div
                  data-testid="mission-progress-section"
                  className="flex flex-col gap-1.5 p-2 rounded bg-slate-900/40 border border-slate-800/40"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400 font-semibold">PROGRESS PROVENANCE</span>
                    <ProgressProvenanceBadge
                      isDerived={activeDetail.progress.progressProvenance === 'DERIVED'}
                      isConsistent={activeDetail.progress.isConsistent}
                      totalGoals={activeDetail.progress.totalGoals}
                      completedGoals={activeDetail.progress.completedGoals}
                    />
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-amber-500 h-2 rounded-full transition-all"
                      style={{
                        width: `${
                          typeof activeDetail.progress.percentage === 'number'
                            ? Math.min(100, Math.max(0, activeDetail.progress.percentage))
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[0.625rem] text-slate-400">
                    <span>
                      COMPLETED: <strong className="text-emerald-400">{activeDetail.progress.completedGoals}</strong>
                    </span>
                    <span>
                      FAILED: <strong className="text-rose-400">{activeDetail.progress.failedGoals}</strong>
                    </span>
                    <span>
                      BLOCKED: <strong className="text-amber-400">{activeDetail.progress.blockedGoals}</strong>
                    </span>
                    <span>
                      TOTAL: <strong className="text-slate-200">{activeDetail.progress.totalGoals}</strong>
                    </span>
                  </div>
                </div>

                {/* Goals Breakdown */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-300">
                    ASSOCIATED GOALS ({activeDetail.goals.length})
                  </span>
                  <div className="flex flex-col gap-1 max-h-[160px] overflow-y-auto pr-1">
                    {activeDetail.goals.length === 0 ? (
                      <span className="text-[0.625rem] text-slate-500">NO ASSOCIATED GOALS FOUND</span>
                    ) : (
                      activeDetail.goals.map((g) => (
                        <div
                          key={g.goalId}
                          data-testid={`goal-row-${g.goalId}`}
                          className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/50 text-[0.625rem]"
                        >
                          <div className="flex items-center gap-2 truncate">
                            <span className="text-slate-500">{g.goalId}</span>
                            <span className="text-slate-200 truncate">
                              <SecretScrubbedText text={g.title} />
                            </span>
                            {g.mandatory && (
                              <span className="text-[0.5rem] px-1 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                                MANDATORY
                              </span>
                            )}
                          </div>
                          <LifecycleBadge state={g.status} />
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Dependency Graph Topology */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-300">
                    DEPENDENCY GRAPH TOPOLOGY ({activeDetail.dependencies.length} EDGES)
                  </span>
                  <div className="flex flex-col gap-1 max-h-[140px] overflow-y-auto pr-1">
                    {activeDetail.dependencies.length === 0 ? (
                      <span className="text-[0.625rem] text-slate-500">NO DEPENDENCY EDGES RECORDED</span>
                    ) : (
                      activeDetail.dependencies.map((dep, idx) => (
                        <div
                          key={`${dep.fromGoalId}-${dep.toGoalId}-${idx}`}
                          data-testid="dependency-row"
                          className="flex items-center justify-between p-1.5 rounded bg-slate-900/40 border border-slate-800/40 text-[0.625rem]"
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="text-slate-300">{dep.fromGoalId}</span>
                            <span className="text-slate-500">depends on</span>
                            <span className="text-slate-300">{dep.toGoalId}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            {dep.isCycle && (
                              <span
                                data-testid="dependency-cycle-warning"
                                className="text-[0.5625rem] px-1 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 font-bold"
                              >
                                CYCLE DETECTED
                              </span>
                            )}
                            <span
                              data-testid="dependency-satisfaction-state"
                              className="text-[0.5625rem] px-1 rounded"
                              style={{
                                backgroundColor:
                                  dep.satisfactionState === 'SATISFIED'
                                    ? 'rgba(16, 185, 129, 0.15)'
                                    : dep.satisfactionState === 'BLOCKED'
                                    ? 'rgba(239, 68, 68, 0.15)'
                                    : dep.satisfactionState === 'MISSING_EVIDENCE'
                                    ? 'rgba(245, 158, 11, 0.2)'
                                    : 'rgba(56, 189, 248, 0.15)',
                                color:
                                  dep.satisfactionState === 'SATISFIED'
                                    ? '#34d399'
                                    : dep.satisfactionState === 'BLOCKED'
                                    ? '#f87171'
                                    : dep.satisfactionState === 'MISSING_EVIDENCE'
                                    ? '#fbbf24'
                                    : '#38bdf8',
                              }}
                            >
                              {dep.satisfactionState}
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Checkpoints */}
                {activeDetail.checkpoints.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-slate-300">
                      INTERMEDIATE CHECKPOINTS ({activeDetail.checkpoints.length})
                    </span>
                    <div className="flex flex-col gap-1 max-h-[100px] overflow-y-auto">
                      {activeDetail.checkpoints.map((cp) => (
                        <div
                          key={cp.checkpointId}
                          data-testid="checkpoint-row"
                          className="flex items-center justify-between p-1 rounded bg-slate-900/30 text-[0.625rem]"
                        >
                          <span className="text-slate-300 truncate">
                            {cp.checkpointId} (v{cp.planVersion})
                          </span>
                          <span className="text-[0.5625rem] text-slate-400">
                            CHECKPOINT STATUS: <strong className="text-slate-200">{cp.statusAtCheckpoint}</strong> (MILESTONE ONLY)
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Metadata & Timestamps */}
                <div className="flex items-center justify-between text-[0.5625rem] text-slate-500 pt-2 border-t border-slate-800/60">
                  <span>CREATED: {formatTimestamp(activeDetail.createdAt)}</span>
                  <span>UPDATED: {formatTimestamp(activeDetail.updatedAt)}</span>
                  <span>PROJECTED: {formatTimestamp(activeDetail.projectedAt)}</span>
                </div>
              </div>
            ) : (
              <div
                data-testid="no-mission-selected"
                className="p-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded flex flex-col items-center justify-center h-full min-h-[300px]"
              >
                SELECT A MISSION FROM THE LIST TO INSPECT DETAILED GRAPH TOPOLOGY, GOALS, CHECKPOINTS, AND PROVENANCE
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
