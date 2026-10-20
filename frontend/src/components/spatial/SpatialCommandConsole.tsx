/**
 * AryaOS V1 — Stage 05: Spatial Command Console
 *
 * Cinematic obsidian command terminal for natural language command orchestration,
 * intent visualization, and memory-to-action dispatch.
 */

import React, { useRef, useEffect } from 'react';
import {
  Terminal,
  Send,
  X,
  ChevronUp,
  ChevronDown,
  Sparkles,
  Activity,
  Camera,
  CheckCircle,
  Clock,
  AlertCircle,
  Layers,
  History,
  ShieldCheck,
} from 'lucide-react';
import { UseSpatialCommandReturn } from '../../hooks/useSpatialCommand';
import { useGoalOrchestration } from '../../hooks/useGoalOrchestration';
import { executionPersistence } from '../../services/executionPersistence';
import { OperatorHUD, OperatorHudTab, OperatorHUDErrorBoundary } from './OperatorHUD';
import { controlPlaneSnapshotService } from '../../services/controlPlaneSnapshotService';
import { ControlPlaneSnapshot } from '../../types/controlPlane';

export interface SpatialCommandConsoleProps {
  commandControl: UseSpatialCommandReturn;
  isReducedMotion?: boolean;
  showOperatorHud?: boolean;
  defaultHudTab?: OperatorHudTab;
  initialControlPlaneSnapshot?: ControlPlaneSnapshot | null;
}

const COMMAND_SHORTCUT_PILLS = [
  { label: 'Autonomous Goal', cmd: 'Goal: Research a cinematic concept for AryaOS and prepare a production brief' },
  { label: 'Trace History', cmd: 'Trace history' },
  { label: 'Show Related', cmd: 'Show related memories' },
  { label: 'Show Unresolved', cmd: 'Show unresolved items' },
  { label: 'Find Decisions', cmd: 'Find decisions related to Memory Archive' },
  { label: 'Research Task', cmd: 'Create a research task from this memory' },
  { label: 'Production Plan', cmd: 'Generate a production plan from this decision' },
  { label: 'Hero View', cmd: 'Switch camera to hero view' },
  { label: 'Monumental View', cmd: 'Switch camera to monumental' },
  { label: 'Archive Detail', cmd: 'Switch camera to archive detail' },
  { label: 'Show All', cmd: 'Show all' },
];

export const SpatialCommandConsole: React.FC<SpatialCommandConsoleProps> = ({
  commandControl,
  showOperatorHud = false,
  defaultHudTab = 'overview',
  initialControlPlaneSnapshot,
}) => {
  // Synchronous initialization for snapshot and snapshot error
  let initialSnap: ControlPlaneSnapshot | null = null;
  let initialError: string | null = null;
  if (initialControlPlaneSnapshot !== undefined) {
    initialSnap = initialControlPlaneSnapshot;
  } else {
    try {
      initialSnap = controlPlaneSnapshotService.getSnapshot();
    } catch (err: unknown) {
      initialError = err instanceof Error ? err.message : String(err);
    }
  }

  const [isOperatorHudOpen, setIsOperatorHudOpen] = React.useState<boolean>(showOperatorHud);
  const [controlPlaneError, setControlPlaneError] = React.useState<string | null>(initialError);
  const [controlPlaneSnapshot, setControlPlaneSnapshot] = React.useState<ControlPlaneSnapshot | null>(initialSnap);

  // Synchronize or load snapshot safely on prop change
  React.useEffect(() => {
    if (initialControlPlaneSnapshot !== undefined) {
      setControlPlaneSnapshot(initialControlPlaneSnapshot);
      setControlPlaneError(null);
      return;
    }
    try {
      const snap = controlPlaneSnapshotService.getSnapshot();
      setControlPlaneSnapshot(snap);
      setControlPlaneError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setControlPlaneError(msg);
    }
  }, [initialControlPlaneSnapshot]);

  // Sync prop changes for showOperatorHud
  React.useEffect(() => {
    if (showOperatorHud !== undefined) {
      setIsOperatorHudOpen(showOperatorHud);
    }
  }, [showOperatorHud]);
  const {
    commandState,
    commandInput,
    currentCommand,
    lastResult,
    lastExecutionResult,
    activeCamera,
    memoryEvents,
    isConsoleOpen,
    setCommandInput,
    submitCommand,
    confirmProposal,
    cancelProposal,
    dismissResult,
    setIsConsoleOpen,
    toggleConsole,
    navigateHistory,
  } = commandControl;

  const {
    activeGoal,
    activePlan,
    actions: goalActions,
    isExecuting: isGoalExecuting,
    needsApproval,
    isRecovered,
    recoverySummary,
    currentAction,
    agentTelemetry,
    agentTasks,
    approveAction,
    pauseGoal,
    resumeGoal,
    cancelGoal,
  } = useGoalOrchestration();

  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when console opens
  useEffect(() => {
    if (isConsoleOpen) {
      inputRef.current?.focus();
    }
  }, [isConsoleOpen]);

  return (
    <div
      data-testid="spatial-command-console"
      style={{
        pointerEvents: 'auto',
        margin: '0.5rem 1.5rem 0',
        backgroundColor: 'rgba(7, 10, 18, 0.94)',
        backdropFilter: 'blur(20px)',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '8px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.8), 0 0 16px rgba(56, 189, 248, 0.1)',
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        color: '#cbd5e1',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Console Top Bar */}
      <div
        style={{
          padding: '0.4rem 0.875rem',
          backgroundColor: 'rgba(15, 23, 42, 0.75)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Terminal size={14} color="#38bdf8" />
          <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#f8fafc', letterSpacing: '0.08em' }}>
            ARYAOS // COMMAND CONSOLE
          </span>
          <span
            style={{
              fontSize: '0.5625rem',
              color: '#38bdf8',
              backgroundColor: 'rgba(56, 189, 248, 0.12)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              padding: '1px 5px',
              borderRadius: '2px',
            }}
          >
            STAGE 08 // GOAL ORCHESTRATION
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Active Camera Telemetry */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.625rem', color: '#94a3b8' }}>
            <Camera size={11} color="#38bdf8" />
            <span style={{ color: '#38bdf8' }}>{activeCamera}</span>
          </div>

          {/* Toggle minimize */}
          <button
            type="button"
            data-testid="command-console-toggle-btn"
            onClick={toggleConsole}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#64748b',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '2px',
            }}
            title={isConsoleOpen ? 'Collapse Console' : 'Expand Console'}
          >
            {isConsoleOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {isConsoleOpen && (
        <div style={{ padding: '0.625rem 0.875rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {/* Terminal Input Line */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submitCommand();
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'rgba(15, 23, 42, 0.9)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              borderRadius: '5px',
              padding: '4px 8px',
              gap: '0.5rem',
            }}
          >
            <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#f59e0b', letterSpacing: '0.04em' }}>
              ARYAOS&gt;
            </span>

            <input
              ref={inputRef}
              data-testid="spatial-command-input"
              type="text"
              value={commandInput}
              onChange={(e) => setCommandInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  navigateHistory('up');
                } else if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  navigateHistory('down');
                }
              }}
              placeholder="Enter spatial command or question... (e.g. 'Show related memories', 'Trace history', 'Hero camera')"
              style={{
                flex: 1,
                backgroundColor: 'transparent',
                border: 'none',
                color: '#f8fafc',
                fontSize: '0.75rem',
                outline: 'none',
                fontFamily: 'inherit',
              }}
            />

            <button
              type="submit"
              data-testid="spatial-command-submit-btn"
              style={{
                backgroundColor: 'rgba(56, 189, 248, 0.2)',
                border: '1px solid #38bdf8',
                borderRadius: '3px',
                color: '#38bdf8',
                padding: '3px 8px',
                fontSize: '0.625rem',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.25rem',
                fontFamily: 'inherit',
              }}
            >
              <Send size={11} />
              EXECUTE
            </button>
          </form>

          {/* Quick Action Suggestion Pills */}
          <div
            data-testid="command-suggestion-pills"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              overflowX: 'auto',
              paddingBottom: '2px',
            }}
          >
            {COMMAND_SHORTCUT_PILLS.map((pill) => (
              <button
                key={pill.label}
                type="button"
                data-testid={`command-pill-${pill.label.toLowerCase().replace(/\s+/g, '-')}`}
                onClick={() => {
                  setCommandInput(pill.cmd);
                  submitCommand(pill.cmd);
                }}
                style={{
                  backgroundColor: 'rgba(30, 41, 59, 0.65)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '3px',
                  padding: '2px 7px',
                  fontSize: '0.5625rem',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  fontFamily: 'inherit',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = '#38bdf8';
                  e.currentTarget.style.color = '#38bdf8';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                  e.currentTarget.style.color = '#94a3b8';
                }}
              >
                {pill.label}
              </button>
            ))}
          </div>

          {/* Stage 08: Goal Orchestration Engine Status */}
          {activeGoal && activePlan && (
            <div
              data-testid="goal-orchestration-hud"
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.9)',
                border: '1px solid rgba(147, 51, 234, 0.35)',
                borderRadius: '5px',
                padding: '0.5rem 0.75rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.375rem',
                fontSize: '0.625rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ color: '#c084fc', fontWeight: 700, letterSpacing: '0.06em' }}>
                    GOAL // {activeGoal.status}
                  </span>
                  <span
                    data-testid="goal-plan-version"
                    style={{
                      fontSize: '0.5625rem',
                      padding: '1px 5px',
                      borderRadius: '2px',
                      backgroundColor: 'rgba(147, 51, 234, 0.2)',
                      color: '#e9d5ff',
                      border: '1px solid rgba(147, 51, 234, 0.4)',
                    }}
                  >
                    PLAN v{activePlan.version}
                  </span>
                  {isRecovered && (
                    <span
                      data-testid="goal-recovered-badge"
                      style={{
                        fontSize: '0.5625rem',
                        padding: '1px 5px',
                        borderRadius: '2px',
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        color: '#6ee7b7',
                        border: '1px solid rgba(16, 185, 129, 0.4)',
                        fontWeight: 700,
                      }}
                      title={recoverySummary || 'Recovered from persistent journal'}
                    >
                      DURABLE RECOVERED
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  {needsApproval && currentAction && (
                    <button
                      type="button"
                      data-testid="goal-approve-btn"
                      onClick={() => approveAction(currentAction.actionId)}
                      style={{
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        border: '1px solid #10b981',
                        color: '#6ee7b7',
                        padding: '2px 8px',
                        borderRadius: '3px',
                        fontSize: '0.5625rem',
                        fontWeight: 700,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                    >
                      APPROVE ACTION
                    </button>
                  )}
                  {isGoalExecuting && (
                    <button
                      type="button"
                      data-testid="goal-pause-btn"
                      onClick={pauseGoal}
                      style={{
                        backgroundColor: 'rgba(245, 158, 11, 0.2)',
                        border: '1px solid #f59e0b',
                        color: '#fbbf24',
                        padding: '2px 8px',
                        borderRadius: '3px',
                        fontSize: '0.5625rem',
                        fontWeight: 700,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                    >
                      PAUSE
                    </button>
                  )}
                  {activeGoal.status === 'BLOCKED' && (
                    <button
                      type="button"
                      data-testid="goal-resume-btn"
                      onClick={resumeGoal}
                      style={{
                        backgroundColor: 'rgba(56, 189, 248, 0.2)',
                        border: '1px solid #38bdf8',
                        color: '#7dd3fc',
                        padding: '2px 8px',
                        borderRadius: '3px',
                        fontSize: '0.5625rem',
                        fontWeight: 700,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                    >
                      RESUME
                    </button>
                  )}
                  {(isGoalExecuting || needsApproval) && (
                    <button
                      type="button"
                      data-testid="goal-cancel-btn"
                      onClick={cancelGoal}
                      style={{
                        backgroundColor: 'transparent',
                        border: '1px solid rgba(239, 68, 68, 0.4)',
                        color: '#f87171',
                        padding: '2px 6px',
                        borderRadius: '3px',
                        fontSize: '0.5625rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                    >
                      CANCEL
                    </button>
                  )}
                </div>
              </div>

              <div data-testid="goal-objective" style={{ color: '#f8fafc', fontWeight: 600, lineHeight: 1.3 }}>
                {activeGoal.objective}
              </div>

              {/* Action Graph Nodes List */}
              <div
                data-testid="goal-actions-list"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.25rem',
                  borderTop: '1px solid rgba(255, 255, 255, 0.06)',
                  paddingTop: '0.35rem',
                }}
              >
                {goalActions.map((act) => {
                  const isDone = act.status === 'SUCCEEDED';
                  const isRunning = act.status === 'EXECUTING';
                  const isAppr = act.status === 'AWAITING_APPROVAL';
                  const isFail = act.status === 'FAILED';

                  return (
                    <div
                      key={act.actionId}
                      data-testid={`goal-action-${act.actionId}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: '0.625rem',
                        color: isDone ? '#10b981' : isRunning ? '#38bdf8' : isAppr ? '#fbbf24' : isFail ? '#ef4444' : '#64748b',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                        <span>{isDone ? '✓' : isRunning ? '●' : isAppr ? '⏳' : isFail ? '✗' : '○'}</span>
                        <span style={{ color: isDone || isRunning ? '#f1f5f9' : '#94a3b8' }}>{act.title}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.5625rem' }}>
                        <span style={{ color: '#64748b' }}>[{act.requiredCapability}]</span>
                        <span style={{ fontWeight: 600 }}>{act.status}</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Stage 10: Multi-Agent Operations */}
              <div
                data-testid="agent-operations-hud"
                style={{
                  borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                  paddingTop: '0.35rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.25rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.5625rem' }}>
                  <span style={{ color: '#38bdf8', fontWeight: 700, letterSpacing: '0.05em' }}>
                    AGENT OPERATIONS
                  </span>
                  <div style={{ display: 'flex', gap: '0.35rem' }}>
                    <span style={{ color: '#38bdf8' }}>ACT: {agentTelemetry.runningTasks}</span>
                    <span style={{ color: '#94a3b8' }}>Q: {agentTelemetry.queuedTasks}</span>
                    <span style={{ color: '#10b981' }}>OK: {agentTelemetry.completedTasks}</span>
                    {agentTelemetry.failedTasks > 0 && (
                      <span style={{ color: '#ef4444' }}>FAIL: {agentTelemetry.failedTasks}</span>
                    )}
                  </div>
                </div>

                {agentTasks.length > 0 && (
                  <div
                    data-testid="agent-tasks-list"
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.15rem',
                      maxHeight: '60px',
                      overflowY: 'auto',
                    }}
                  >
                    {agentTasks.slice(0, 3).map((t) => (
                      <div
                        key={t.taskId}
                        data-testid={`agent-task-${t.taskId}`}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: '0.5rem',
                          color: '#cbd5e1',
                          backgroundColor: 'rgba(255, 255, 255, 0.03)',
                          padding: '2px 4px',
                          borderRadius: '2px',
                        }}
                      >
                        <span style={{ color: '#38bdf8' }}>[{t.assignedAgentId || 'UNASSIGNED'}]</span>
                        <span>{t.parentActionId}</span>
                        <span style={{ color: t.status === 'SUCCEEDED' ? '#10b981' : t.status === 'RUNNING' ? '#38bdf8' : '#94a3b8' }}>
                          {t.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Stage 10: Resource Governor Telemetry */}
              <div
                data-testid="resource-governor-hud"
                style={{
                  borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                  paddingTop: '0.35rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: '0.5625rem',
                  color: '#94a3b8',
                }}
              >
                <span style={{ color: '#f59e0b', fontWeight: 700, letterSpacing: '0.04em' }}>RESOURCE GOVERNOR</span>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <span>COST: ${agentTelemetry.cumulativeCostUsd.toFixed(3)}</span>
                  <span>UTIL: {Math.round(agentTelemetry.concurrencyUtilization * 100)}%</span>
                  {agentTelemetry.conflictCount > 0 && (
                    <span style={{ color: '#ef4444' }}>CONFLICTS: {agentTelemetry.conflictCount}</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Stage 11: Intelligence Evaluation & Learning Loop HUD */}
          <div
            data-testid="intelligence-evaluation-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.65)',
              border: '1px solid rgba(168, 85, 247, 0.25)',
              borderRadius: '4px',
              padding: '0.35rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.2rem',
              fontSize: '0.5625rem',
              color: '#94a3b8',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#a855f7', fontWeight: 700, letterSpacing: '0.04em' }}>
                INTELLIGENCE EVALUATION &amp; LEARNING
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="eval-quality-badge" style={{ color: '#10b981' }}>QUALITY: 98%</span>
                <span data-testid="eval-signals-badge" style={{ color: '#38bdf8' }}>SIGNALS: VALIDATED</span>
                <span data-testid="eval-governance-badge" style={{ color: '#f59e0b' }}>GOV: HUMAN-LOCKED</span>
              </div>
            </div>
          </div>

          {/* Stage 12: Long-Horizon Mission Control HUD */}
          <div
            data-testid="mission-control-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(245, 158, 11, 0.3)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#fbbf24', fontWeight: 700, letterSpacing: '0.05em' }}>
                MISSION CONTROL // LONG-HORIZON ADAPTIVE OPS
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="mission-status-badge" style={{ color: '#10b981' }}>STATUS: ACTIVE</span>
                <span data-testid="mission-plan-version-badge" style={{ color: '#38bdf8' }}>PLAN: v1</span>
                <span data-testid="mission-risk-badge" style={{ color: '#f59e0b' }}>RISK: LOW</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem', color: '#94a3b8' }}>
              <div>
                <span>PROGRESS: </span>
                <span data-testid="mission-progress-metric" style={{ color: '#f8fafc', fontWeight: 600 }}>100%</span>
              </div>
              <div>
                <span>CRITICAL PATH: </span>
                <span data-testid="mission-critical-path-metric" style={{ color: '#38bdf8', fontWeight: 600 }}>ON TRACK</span>
              </div>
              <div>
                <span>DEADLINE: </span>
                <span data-testid="mission-deadline-metric" style={{ color: '#10b981', fontWeight: 600 }}>FEASIBLE</span>
              </div>
              <div>
                <span>BUDGET: </span>
                <span data-testid="mission-budget-metric" style={{ color: '#cbd5e1', fontWeight: 600 }}>NORMAL</span>
              </div>
            </div>

            {/* Stage 12: Mission Timeline */}
            <div
              data-testid="mission-timeline-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#fbbf24' }}>MISSION</span>
                <span>→</span>
                <span style={{ color: '#38bdf8' }}>GOAL</span>
                <span>→</span>
                <span style={{ color: '#a855f7' }}>ACTION</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>AGENT</span>
                <span>→</span>
                <span style={{ color: '#cbd5e1' }}>GATEWAY</span>
                <span>→</span>
                <span style={{ color: '#f59e0b' }}>EVAL</span>
              </div>
              <span data-testid="mission-timeline-checkpoint" style={{ color: '#94a3b8' }}>CHECKPOINT: SYNCED</span>
            </div>
          </div>

          {/* Stage 13: Strategic Knowledge & Long-Term Memory HUD */}
          <div
            data-testid="strategic-knowledge-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.85)',
              border: '1px solid rgba(168, 85, 247, 0.35)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#c084fc', fontWeight: 700, letterSpacing: '0.05em' }}>
                STRATEGIC KNOWLEDGE // LONG-TERM MEMORY GRAPH
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="knowledge-facts-badge" style={{ color: '#38bdf8' }}>FACTS: ACTIVE</span>
                <span data-testid="knowledge-confidence-badge" style={{ color: '#10b981' }}>CONF: HIGH</span>
                <span data-testid="knowledge-contradictions-badge" style={{ color: '#f59e0b' }}>CONTRADICTIONS: 0 OPEN</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.4rem', color: '#94a3b8' }}>
              <div>
                <span>PATTERNS: </span>
                <span data-testid="knowledge-patterns-metric" style={{ color: '#f8fafc', fontWeight: 600 }}>DISCOVERED</span>
              </div>
              <div>
                <span>STRATEGIES: </span>
                <span data-testid="knowledge-strategies-metric" style={{ color: '#38bdf8', fontWeight: 600 }}>VALIDATED</span>
              </div>
              <div>
                <span>MISSION LESSONS: </span>
                <span data-testid="knowledge-lessons-metric" style={{ color: '#10b981', fontWeight: 600 }}>INDEXED</span>
              </div>
            </div>

            {/* Stage 13: Knowledge Trace Inspector */}
            <div
              data-testid="knowledge-trace-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#c084fc' }}>FACT</span>
                <span>→</span>
                <span style={{ color: '#38bdf8' }}>EVIDENCE</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>EXECUTION</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>MISSION</span>
                <span>→</span>
                <span style={{ color: '#f59e0b' }}>OUTCOME</span>
              </div>
              <span data-testid="knowledge-trace-status" style={{ color: '#94a3b8' }}>PROVENANCE: AUDITED</span>
            </div>
          </div>

          {/* Stage 14: Decision Intelligence HUD */}
          <div
            data-testid="decision-intelligence-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.9)',
              border: '1px solid rgba(56, 189, 248, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#38bdf8', fontWeight: 700, letterSpacing: '0.05em' }}>
                DECISION INTELLIGENCE // STRATEGY & CONSEQUENCE
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="decision-active-badge" style={{ color: '#38bdf8' }}>ACTIVE: DRAFT</span>
                <span data-testid="decision-confidence-badge" style={{ color: '#10b981' }}>CONF: HIGH</span>
                <span data-testid="decision-approval-badge" style={{ color: '#f59e0b' }}>STATUS: AWAITING_REVIEW</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem', color: '#94a3b8' }}>
              <div>
                <span>OPTIONS: </span>
                <span data-testid="decision-options-metric" style={{ color: '#f8fafc', fontWeight: 600 }}>DIVERSE</span>
              </div>
              <div>
                <span>TRADEOFFS: </span>
                <span data-testid="decision-tradeoffs-metric" style={{ color: '#38bdf8', fontWeight: 600 }}>PRESERVED</span>
              </div>
              <div>
                <span>RISK: </span>
                <span data-testid="decision-risk-metric" style={{ color: '#f59e0b', fontWeight: 600 }}>EVALUATED</span>
              </div>
              <div>
                <span>EVIDENCE: </span>
                <span data-testid="decision-evidence-metric" style={{ color: '#10b981', fontWeight: 600 }}>GROUNDED</span>
              </div>
            </div>

            {/* Stage 14: Consequence View */}
            <div
              data-testid="consequence-view-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="consequence-pipeline-trace" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#38bdf8' }}>OPTION</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>SCENARIO</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>CONSEQUENCES</span>
                <span>→</span>
                <span style={{ color: '#ef4444' }}>RISKS</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>RESOURCES</span>
                <span>→</span>
                <span style={{ color: '#38bdf8' }}>EVIDENCE</span>
              </div>
              <span data-testid="consequence-status" style={{ color: '#94a3b8' }}>SIMULATION: DETERMINISTIC</span>
            </div>

            {/* Stage 14: Decision Trace */}
            <div
              data-testid="decision-trace-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="decision-trace-pipeline" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#38bdf8' }}>DECISION</span>
                <span>→</span>
                <span style={{ color: '#f59e0b' }}>RECOMMENDATION</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>EVIDENCE</span>
                <span>→</span>
                <span style={{ color: '#38bdf8' }}>KNOWLEDGE</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>MISSION</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>OUTCOME</span>
              </div>
              <span data-testid="decision-lineage-status" style={{ color: '#94a3b8' }}>LINEAGE: VERIFIED</span>
            </div>
          </div>

          {/* Stage 15: Universal Action Bus HUD */}
          <div
            data-testid="action-bus-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(16, 185, 129, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#10b981', fontWeight: 700, letterSpacing: '0.05em' }}>
                ACTION BUS // EXTERNAL CAPABILITY ORCHESTRATION
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="action-bus-status-badge" style={{ color: '#10b981' }}>BUS: ONLINE</span>
                <span data-testid="action-bus-governance-badge" style={{ color: '#38bdf8' }}>PERMS: SANDBOXED</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '0.25rem', color: '#94a3b8' }}>
              <div>
                <span>QUEUED: </span>
                <span data-testid="action-bus-queued-count" style={{ color: '#f8fafc', fontWeight: 600 }}>0</span>
              </div>
              <div>
                <span>AUTH: </span>
                <span data-testid="action-bus-authorized-count" style={{ color: '#38bdf8', fontWeight: 600 }}>READY</span>
              </div>
              <div>
                <span>EXEC: </span>
                <span data-testid="action-bus-executing-count" style={{ color: '#fbbf24', fontWeight: 600 }}>0</span>
              </div>
              <div>
                <span>DONE: </span>
                <span data-testid="action-bus-completed-count" style={{ color: '#10b981', fontWeight: 600 }}>0</span>
              </div>
              <div>
                <span>FAIL: </span>
                <span data-testid="action-bus-failed-count" style={{ color: '#ef4444', fontWeight: 600 }}>0</span>
              </div>
              <div>
                <span>APPROVAL: </span>
                <span data-testid="action-bus-approval-required-count" style={{ color: '#f59e0b', fontWeight: 600 }}>0</span>
              </div>
            </div>

            {/* Stage 15: Capability Status View */}
            <div
              data-testid="capability-status-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>CAPABILITIES: <strong style={{ color: '#f8fafc' }}>7 REGISTERED</strong></span>
                <span data-testid="capability-availability-badge" style={{ color: '#10b981' }}>AVAIL: 100%</span>
                <span data-testid="capability-risk-badge" style={{ color: '#f59e0b' }}>RISK: GOVERNED</span>
              </div>
              <span data-testid="capability-permissions-status" style={{ color: '#94a3b8' }}>PERMISSIONS: DEFAULT_DENY</span>
            </div>

            {/* Stage 15: Action Trace View */}
            <div
              data-testid="action-trace-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="action-trace-pipeline" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#10b981' }}>ACTION</span>
                <span>→</span>
                <span style={{ color: '#38bdf8' }}>AUTHORIZATION</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>CAPABILITY</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>EXECUTION</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>RESULT</span>
              </div>
              <span data-testid="action-boundary-status" style={{ color: '#94a3b8' }}>GATEWAY: SEPARATE</span>
            </div>
          </div>

          {/* Stage 16: Connector Fabric HUD */}
          <div
            data-testid="connector-fabric-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(245, 158, 11, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#f59e0b', fontWeight: 700, letterSpacing: '0.05em' }}>
                CONNECTOR FABRIC // IDENTITY & ACCESS MANAGEMENT
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="connector-status-badge" style={{ color: '#10b981' }}>STATUS: ACTIVE</span>
                <span data-testid="connector-health-badge" style={{ color: '#38bdf8' }}>HEALTH: HEALTHY</span>
                <span data-testid="connector-auth-badge" style={{ color: '#f59e0b' }}>AUTH: CRED_REF_VALID</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.25rem', color: '#94a3b8' }}>
              <div>
                <span>CONNECTORS: </span>
                <span data-testid="connector-count-badge" style={{ color: '#f8fafc', fontWeight: 600 }}>3 ONLINE</span>
              </div>
              <div>
                <span>PERMISSIONS: </span>
                <span data-testid="connector-permissions-count" style={{ color: '#38bdf8', fontWeight: 600 }}>8 SCOPED</span>
              </div>
              <div>
                <span>CAPABILITIES: </span>
                <span data-testid="connector-capabilities-count" style={{ color: '#10b981', fontWeight: 600 }}>7 MAPPED</span>
              </div>
              <div>
                <span>VERSION: </span>
                <span data-testid="connector-perm-version" style={{ color: '#c084fc', fontWeight: 600 }}>v1 DETERMINISTIC</span>
              </div>
            </div>

            {/* Stage 16: Permission Matrix View */}
            <div
              data-testid="permission-matrix-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span>AGENT: <strong data-testid="permission-matrix-agent" style={{ color: '#cbd5e1' }}>SCOPED</strong></span>
                <span>MISSION: <strong data-testid="permission-matrix-mission" style={{ color: '#38bdf8' }}>LINKED</strong></span>
                <span>CONN: <strong data-testid="permission-matrix-connector" style={{ color: '#f59e0b' }}>FILESYSTEM</strong></span>
                <span>SCOPE: <strong data-testid="permission-matrix-scope" style={{ color: '#10b981' }}>/workspace</strong></span>
                <span>RISK: <strong data-testid="permission-matrix-risk" style={{ color: '#ef4444' }}>TIER_GOVERNED</strong></span>
                <span>STATE: <strong data-testid="permission-matrix-status" style={{ color: '#10b981' }}>GRANTED</strong></span>
              </div>
              <span data-testid="permission-default-deny-badge" style={{ color: '#94a3b8' }}>DEFAULT: DENY</span>
            </div>

            {/* Stage 16: Connector Audit View */}
            <div
              data-testid="connector-audit-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="connector-audit-pipeline" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#38bdf8' }}>CONNECT</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>AUTHORIZE</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>PERM_CHANGE</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>HEALTH</span>
                <span>→</span>
                <span style={{ color: '#ef4444' }}>REVOKE</span>
              </div>
              <span data-testid="connector-audit-status" style={{ color: '#94a3b8' }}>AUDIT: PERSISTED</span>
            </div>
          </div>

          {/* Stage 17: Real Connector Activation & Credential Status HUD */}
          <div
            data-testid="connector-activation-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(16, 185, 129, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#10b981', fontWeight: 700, letterSpacing: '0.05em' }}>
                REAL CONNECTOR ACTIVATION // GOVERNED INTEGRATION
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="activation-mode-badge" style={{ color: '#38bdf8' }}>TRANSPORT: CONTROLLED</span>
                <span data-testid="activation-gate-badge" style={{ color: '#10b981' }}>GATEWAY: SEPARATED</span>
              </div>
            </div>

            <div
              data-testid="authentication-status-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.25rem',
                color: '#94a3b8',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
              }}
            >
              <div>
                <span>CONNECTOR: </span>
                <strong data-testid="auth-hud-connector" style={{ color: '#f8fafc' }}>GITHUB / GDRIVE</strong>
              </div>
              <div>
                <span>STATUS: </span>
                <strong data-testid="auth-hud-status" style={{ color: '#10b981' }}>CONNECTED</strong>
              </div>
              <div>
                <span>HEALTH: </span>
                <strong data-testid="auth-hud-health" style={{ color: '#38bdf8' }}>READY</strong>
              </div>
              <div>
                <span>SCOPE: </span>
                <strong data-testid="auth-hud-scope" style={{ color: '#c084fc' }}>aryaos/core</strong>
              </div>
            </div>

            <div
              data-testid="credential-status-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>CREDENTIAL REF: <strong data-testid="credential-ref-mask" style={{ color: '#cbd5e1' }}>••••a91c</strong></span>
                <span>STATUS: <strong data-testid="credential-status-badge" style={{ color: '#10b981' }}>VALID (NON-PERSISTED)</strong></span>
                <span>SECRETS: <strong data-testid="credential-zero-secrets" style={{ color: '#38bdf8' }}>ZERO_RAW_PERSISTENCE</strong></span>
              </div>
              <span data-testid="credential-isolation-badge" style={{ color: '#10b981' }}>EPHEMERAL_RESOLVER</span>
            </div>
          </div>

          {/* Stage 18: External Event Ingestion & State Synchronization HUD */}
          <div
            data-testid="external-event-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(245, 158, 11, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#f59e0b', fontWeight: 700, letterSpacing: '0.05em' }}>
                EXTERNAL EVENT INGESTION // INBOUND STATE SYNC
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="event-ingress-status" style={{ color: '#10b981' }}>INGRESS: ACTIVE</span>
                <span data-testid="event-auth-mode-badge" style={{ color: '#38bdf8' }}>AUTH: HMAC_VERIFIED</span>
              </div>
            </div>

            <div
              data-testid="event-ingress-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.25rem',
                color: '#94a3b8',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
              }}
            >
              <div>
                <span>SOURCE: </span>
                <strong data-testid="event-hud-source" style={{ color: '#f8fafc' }}>GITHUB / GDRIVE</strong>
              </div>
              <div>
                <span>TYPE: </span>
                <strong data-testid="event-hud-type" style={{ color: '#10b981' }}>issue.created</strong>
              </div>
              <div>
                <span>AUTHENTICATION: </span>
                <strong data-testid="event-hud-auth" style={{ color: '#38bdf8' }}>AUTHENTICATED</strong>
              </div>
              <div>
                <span>EVENT ID: </span>
                <strong data-testid="event-hud-id" style={{ color: '#c084fc' }}>evt_•••91</strong>
              </div>
            </div>

            <div
              data-testid="event-reconciliation-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>CONNECTOR: <strong data-testid="event-hud-connector" style={{ color: '#cbd5e1' }}>connector_github</strong></span>
                <span>STATUS: <strong data-testid="event-hud-status" style={{ color: '#10b981' }}>RECONCILED</strong></span>
                <span>EPISTEMIC: <strong data-testid="event-hud-epistemic" style={{ color: '#f59e0b' }}>OBSERVED_NOT_AUTHORITY</strong></span>
                <span>MISSION: <strong data-testid="event-hud-mission" style={{ color: '#38bdf8' }}>mission_•••42</strong></span>
              </div>
              <span data-testid="event-dedup-badge" style={{ color: '#10b981' }}>DEDUPLICATION: ACTIVE</span>
            </div>
          </div>

          {/* Stage 19: Event-Driven Reaction Engine & Controlled Trigger Orchestration HUD */}
          <div
            data-testid="trigger-reaction-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(192, 132, 252, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: '#c084fc', fontWeight: 700, letterSpacing: '0.05em' }}>
                REACTION ENGINE // CONTROLLED TRIGGER ORCHESTRATION
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="reaction-engine-status" style={{ color: '#10b981' }}>ENGINE: ACTIVE</span>
                <span data-testid="reaction-safety-badge" style={{ color: '#38bdf8' }}>SAFETY: GOVERNED</span>
              </div>
            </div>

            {/* Stage 19: Trigger Registry HUD */}
            <div
              data-testid="trigger-registry-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.25rem',
                color: '#94a3b8',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
              }}
            >
              <div>
                <span>TRIGGERS: </span>
                <strong data-testid="trigger-count-badge" style={{ color: '#f8fafc' }}>REGISTERED (ACTIVE)</strong>
              </div>
              <div>
                <span>STATUS: </span>
                <strong data-testid="trigger-registry-status" style={{ color: '#10b981' }}>ENABLED</strong>
              </div>
              <div>
                <span>IMMUTABILITY: </span>
                <strong data-testid="trigger-immutability-badge" style={{ color: '#38bdf8' }}>VERSION_BUMP</strong>
              </div>
              <div>
                <span>INJECTION: </span>
                <strong data-testid="trigger-safety-badge" style={{ color: '#c084fc' }}>PURE_DECLARATIVE</strong>
              </div>
            </div>

            {/* Stage 19: Trigger Evaluation HUD */}
            <div
              data-testid="trigger-evaluation-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>EVALUATION: <strong data-testid="trigger-evaluation-status" style={{ color: '#cbd5e1' }}>ACTIVE</strong></span>
                <span>MATCHING: <strong data-testid="trigger-evaluation-result" style={{ color: '#10b981' }}>EVALUATED</strong></span>
                <span>RISK TIER: <strong data-testid="reaction-risk-badge" style={{ color: '#f59e0b' }}>GOVERNED</strong></span>
              </div>
              <span data-testid="trigger-filter-mode" style={{ color: '#38bdf8' }}>FILTER: EVENT_PATTERN</span>
            </div>

            {/* Stage 19: Reaction Queue & Proposals HUD */}
            <div
              data-testid="reaction-queue-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>PROPOSALS: <strong data-testid="reaction-queue-status" style={{ color: '#cbd5e1' }}>PROPOSAL_DISPATCH</strong></span>
                <span>APPROVAL: <strong data-testid="reaction-approval-status" style={{ color: '#f59e0b' }}>HUMAN_GATE_ENFORCED</strong></span>
                <span>AUTONOMOUS SIGNOFF: <strong data-testid="reaction-autonomous-signoff" style={{ color: '#ef4444' }}>REJECTED</strong></span>
              </div>
              <span data-testid="reaction-idempotency-badge" style={{ color: '#10b981' }}>IDEMPOTENCY: ENFORCED</span>
            </div>

            {/* Stage 19: Reaction Audit HUD */}
            <div
              data-testid="reaction-audit-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="reaction-audit-pipeline" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#38bdf8' }}>EVENT</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>TRIGGER</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>CONDITION</span>
                <span>→</span>
                <span style={{ color: '#f59e0b' }}>PROPOSAL</span>
                <span>→</span>
                <span style={{ color: '#ef4444' }}>APPROVAL</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>ACTION_BUS</span>
              </div>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="reaction-loop-protection" style={{ color: '#38bdf8' }}>LOOP: DEPTH_≤3_ARMED</span>
                <span data-testid="reaction-gateway-separation" style={{ color: '#10b981' }}>GATEWAY: SEPARATE</span>
              </div>
            </div>
          </div>

          {/* Stage 20: Policy Intelligence & Governed Adaptive Operations HUD */}
          <div
            data-testid="policy-intelligence-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              border: '1px solid rgba(14, 165, 233, 0.4)',
              borderRadius: '4px',
              padding: '0.4rem 0.625rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.5625rem',
              color: '#cbd5e1',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 600, color: '#38bdf8', letterSpacing: '0.05em' }}>
                STAGE 20 POLICY INTELLIGENCE & GOVERNED OPERATIONS
              </span>
              <span
                data-testid="policy-engine-active-badge"
                style={{
                  fontSize: '0.5rem',
                  padding: '0.1rem 0.35rem',
                  borderRadius: '2px',
                  backgroundColor: 'rgba(16, 185, 129, 0.2)',
                  color: '#34d399',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                }}
              >
                GOVERNED_ADAPTIVE
              </span>
            </div>

            {/* Stage 20: Policy Registry HUD */}
            <div
              data-testid="policy-registry-hud"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingTop: '0.2rem',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                fontSize: '0.5rem',
                color: '#94a3b8',
              }}
            >
              <div>
                <span>POLICIES: </span>
                <strong data-testid="policy-count-badge" style={{ color: '#f8fafc' }}>ACTIVE_VERSIONED</strong>
              </div>
              <div>
                <span>STATUS: </span>
                <strong data-testid="policy-registry-status" style={{ color: '#10b981' }}>OPERATIONAL</strong>
              </div>
              <div>
                <span>IMMUTABILITY: </span>
                <strong data-testid="policy-immutability-badge" style={{ color: '#38bdf8' }}>VERSION_INCREMENT</strong>
              </div>
              <div>
                <span>LANGUAGE: </span>
                <strong data-testid="policy-language-badge" style={{ color: '#0ea5e9' }}>PURE_AST_DECLARATIVE</strong>
              </div>
            </div>

            {/* Stage 20: Policy Evaluation HUD */}
            <div
              data-testid="policy-evaluation-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>EVALUATION: <strong data-testid="policy-evaluation-status" style={{ color: '#cbd5e1' }}>ACTIVE</strong></span>
                <span>PRECEDENCE: <strong data-testid="policy-precedence-badge" style={{ color: '#f59e0b' }}>SAFETY_FIRST</strong></span>
                <span>EFFECTS: <strong data-testid="policy-effects-badge" style={{ color: '#10b981' }}>ALLOWLISTED</strong></span>
              </div>
              <span data-testid="policy-scope-mode" style={{ color: '#38bdf8' }}>SCOPE: BOUNDED_EXPLICIT</span>
            </div>

            {/* Stage 20: Policy Proposal & Review HUD */}
            <div
              data-testid="policy-proposal-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>CANDIDATES: <strong data-testid="policy-candidate-status" style={{ color: '#cbd5e1' }}>LEARNING_DERIVED</strong></span>
                <span>APPROVAL: <strong data-testid="policy-approval-gate" style={{ color: '#f59e0b' }}>HUMAN_OPERATOR_REQUIRED</strong></span>
                <span>SELF-MUTATION: <strong data-testid="policy-self-mutation-badge" style={{ color: '#ef4444' }}>STRICTLY_PROHIBITED</strong></span>
              </div>
              <span data-testid="policy-evidence-provenance" style={{ color: '#10b981' }}>PROVENANCE: PRESERVED</span>
            </div>

            {/* Stage 20: Policy Conflict & Resolution HUD */}
            <div
              data-testid="policy-conflict-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>CONFLICTS: <strong data-testid="policy-conflict-status" style={{ color: '#cbd5e1' }}>DETERMINISTIC_RESOLUTION</strong></span>
                <span>HIERARCHY: <strong data-testid="policy-hierarchy-badge" style={{ color: '#38bdf8' }}>8_TIER_ORDERED</strong></span>
                <span>PRESERVATION: <strong data-testid="policy-lossless-conflict-badge" style={{ color: '#10b981' }}>LOSSLESS_AUDIT</strong></span>
              </div>
              <span data-testid="policy-conflict-mode" style={{ color: '#f59e0b' }}>NON_SILENT_DISCARD</span>
            </div>

            {/* Stage 20: Policy Shadow Evaluation HUD */}
            <div
              data-testid="policy-shadow-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span>SHADOW MODE: <strong data-testid="policy-shadow-status" style={{ color: '#cbd5e1' }}>ACTIVE</strong></span>
                <span>RUNTIME IMPACT: <strong data-testid="policy-shadow-runtime-impact" style={{ color: '#10b981' }}>ZERO_MUTATION</strong></span>
                <span>DIVERGENCE: <strong data-testid="policy-shadow-divergence-badge" style={{ color: '#38bdf8' }}>OBSERVED_TRACKED</strong></span>
              </div>
              <span data-testid="policy-shadow-mode-badge" style={{ color: '#c084fc' }}>ISOLATED_EVAL</span>
            </div>

            {/* Stage 20: Policy Audit & Trace HUD */}
            <div
              data-testid="policy-audit-hud"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                paddingTop: '0.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.5rem',
                color: '#64748b',
              }}
            >
              <div data-testid="policy-audit-pipeline" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ color: '#38bdf8' }}>EXPERIENCE</span>
                <span>→</span>
                <span style={{ color: '#fbbf24' }}>SIGNAL</span>
                <span>→</span>
                <span style={{ color: '#c084fc' }}>CANDIDATE</span>
                <span>→</span>
                <span style={{ color: '#0ea5e9' }}>SIMULATION</span>
                <span>→</span>
                <span style={{ color: '#f59e0b' }}>APPROVAL</span>
                <span>→</span>
                <span style={{ color: '#10b981' }}>ACTIVATION</span>
              </div>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <span data-testid="policy-rollback-armed" style={{ color: '#38bdf8' }}>ROLLBACK: ARMED</span>
                <span data-testid="policy-drift-armed" style={{ color: '#10b981' }}>DRIFT: MONITORED</span>
              </div>
            </div>
          </div>

          {/* Stage 21: Governed Policy Control Plane Telemetry HUD */}
          <div
            data-testid="governance-control-plane-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              fontSize: '0.625rem',
              fontFamily: 'monospace',
              backdropFilter: 'blur(8px)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <ShieldCheck size={12} color="#38bdf8" />
                <span style={{ fontWeight: 700, color: '#f8fafc', letterSpacing: '0.05em' }}>
                  GOVERNANCE CONTROL PLANE
                </span>
              </div>
              <span
                data-testid="governance-plane-status"
                style={{
                  fontSize: '0.5625rem',
                  fontWeight: 700,
                  padding: '1px 5px',
                  borderRadius: '3px',
                  backgroundColor: 'rgba(56, 189, 248, 0.2)',
                  color: '#38bdf8',
                }}
              >
                OPERATIONAL
              </span>
            </div>

            <div
              data-testid="governance-decision-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>INTERSECTION: </span>
                <strong data-testid="governance-decision-badge" style={{ color: '#38bdf8' }}>FAIL_CLOSED</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>INVARIANT: </span>
                <strong data-testid="governance-invariant-badge" style={{ color: '#10b981' }}>POLICY_ALLOW_NEQ_AUTH</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>PRECEDENCE: </span>
                <strong data-testid="governance-precedence-badge" style={{ color: '#f59e0b' }}>DETERMINISTIC_HIERARCHY</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>MODE: </span>
                <strong data-testid="governance-decision-mode" style={{ color: '#cbd5e1' }}>FAIL_CLOSED</strong>
              </div>
            </div>

            <div
              data-testid="authority-intersection-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>AUTHORITY TIERS: </span>
                <strong data-testid="authority-intersection-status" style={{ color: '#10b981' }}>5_TIER_INTERSECTION</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>FORMULA: </span>
                <strong data-testid="authority-intersection-formula" style={{ color: '#38bdf8' }}>POLICY_AND_CONNECTOR_AND_ACTION_AND_HUMAN_AND_MISSION</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>HUMAN GATE: </span>
                <strong data-testid="authority-human-gate" style={{ color: '#f59e0b' }}>ANTI_SPOOFING_ACTIVE</strong>
              </div>
            </div>

            <div
              data-testid="governance-staleness-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>SNAPSHOT SYNC: </span>
                <strong data-testid="governance-staleness-status" style={{ color: '#10b981' }}>EPOCH_SYNCHRONIZED</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>RE-EVALUATION: </span>
                <strong data-testid="governance-reevaluation-badge" style={{ color: '#f59e0b' }}>ARMED</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>TTL / DRIFT: </span>
                <strong data-testid="governance-ttl-badge" style={{ color: '#38bdf8' }}>ENFORCED</strong>
              </div>
            </div>

            <div
              data-testid="governance-explanation-hud"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.2rem 0.4rem',
                color: '#94a3b8',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="governance-pipeline-badge" style={{ color: '#0ea5e9' }}>
                  PIPELINE: REQUEST → SNAPSHOT → EVAL → INTERSECT → EXPLAIN
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="governance-provenance-status" style={{ color: '#10b981' }}>
                  PROVENANCE: 10_POINT_EXPLANATION
                </span>
                <span data-testid="governance-evidence-badge" style={{ color: '#38bdf8' }}>
                  EVIDENCE: AUDIT_TRAIL_ACTIVE
                </span>
              </div>
            </div>
          </div>

          {/* Stage 22: Operational Observability & Causal Audit HUD */}
          <div
            data-testid="operational-audit-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(168, 85, 247, 0.25)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              fontSize: '0.625rem',
              fontFamily: 'monospace',
              backdropFilter: 'blur(8px)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Activity size={12} color="#c084fc" />
                <span style={{ fontWeight: 700, color: '#f8fafc', letterSpacing: '0.05em' }}>
                  OPERATIONAL AUDIT & CAUSAL TRUTH
                </span>
              </div>
              <span
                data-testid="operational-audit-status"
                style={{
                  fontSize: '0.5625rem',
                  fontWeight: 700,
                  padding: '1px 5px',
                  borderRadius: '3px',
                  backgroundColor: 'rgba(192, 132, 252, 0.2)',
                  color: '#c084fc',
                }}
              >
                OBSERVATIONAL_TRUTH
              </span>
            </div>

            {/* Causal Graph Pipeline */}
            <div
              data-testid="causal-graph-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>GRAPH: </span>
                <strong data-testid="causal-graph-type" style={{ color: '#c084fc' }}>BOUNDED_DAG</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>DEPTH: </span>
                <strong data-testid="causal-depth-limit" style={{ color: '#10b981' }}>MAX_10</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>NODES: </span>
                <strong data-testid="causal-node-limit" style={{ color: '#38bdf8' }}>MAX_100</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>CYCLE DETECT: </span>
                <strong data-testid="causal-cycle-defense" style={{ color: '#10b981' }}>ENFORCED</strong>
              </div>
            </div>

            {/* Operational Truth Separation */}
            <div
              data-testid="operational-truth-hud"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>INTENT VS TRUTH: </span>
                <strong data-testid="operational-truth-invariant" style={{ color: '#10b981' }}>INTENT_NEQ_TRUTH</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>UNKNOWN STATE: </span>
                <strong data-testid="operational-unknown-invariant" style={{ color: '#f59e0b' }}>PRESERVED</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>ANTI-UPGRADE: </span>
                <strong data-testid="epistemic-anti-upgrade" style={{ color: '#38bdf8' }}>ENFORCED</strong>
              </div>
            </div>

            {/* Deterministic Metrics Sub-Panel */}
            <div
              data-testid="audit-metrics-hud"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.2rem 0.4rem',
                color: '#94a3b8',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="audit-pipeline-chain" style={{ color: '#a855f7' }}>
                  CHAIN: EVENT → TRIGGER → REACTION → POLICY → GOVERNANCE → ACTION → RESULT → RECONCILE
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="audit-immutability-badge" style={{ color: '#10b981' }}>
                  AUDIT: APPEND_ONLY
                </span>
                <span data-testid="audit-authority-badge" style={{ color: '#ef4444' }}>
                  AUTHORITY: ZERO_AUTHORITY
                </span>
              </div>
            </div>
          </div>

          {/* Stage 23: Resilient Autonomous Operations & Recovery Control HUD */}
          <div
            data-testid="recovery-control-plane-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              fontSize: '0.625rem',
              fontFamily: 'monospace',
              backdropFilter: 'blur(8px)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <ShieldCheck size={12} color="#38bdf8" />
                <span style={{ fontWeight: 700, color: '#f8fafc', letterSpacing: '0.05em' }}>
                  RECOVERY CONTROL PLANE & EPISTEMIC SAFETY
                </span>
              </div>
              <span
                data-testid="recovery-control-hud-status"
                style={{
                  fontSize: '0.5625rem',
                  fontWeight: 700,
                  padding: '1px 5px',
                  borderRadius: '3px',
                  backgroundColor: 'rgba(56, 189, 248, 0.2)',
                  color: '#38bdf8',
                }}
              >
                GOVERNED_RECOVERY
              </span>
            </div>

            {/* Recovery Control Telemetry Matrix */}
            <div
              data-testid="recovery-telemetry-matrix"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>RECOVERY STATE: </span>
                <strong data-testid="recovery-hud-state" style={{ color: '#38bdf8' }}>READY</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>FAILURE CLASS: </span>
                <strong data-testid="recovery-hud-class" style={{ color: '#fbbf24' }}>TRANSIENT</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>DECISION: </span>
                <strong data-testid="recovery-hud-decision" style={{ color: '#34d399' }}>RETRY</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>OPERATIONAL TRUTH: </span>
                <strong data-testid="recovery-hud-truth" style={{ color: '#38bdf8' }}>OBSERVED</strong>
              </div>
            </div>

            {/* Bounds & Policy Governance Sub-Panel */}
            <div
              data-testid="recovery-bounds-subpanel"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>POLICY STATE: </span>
                <strong data-testid="recovery-hud-policy" style={{ color: '#a855f7' }}>ACTIVE / v42</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>GOVERNANCE: </span>
                <strong data-testid="recovery-hud-governance" style={{ color: '#10b981' }}>GOVERNED</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>RECOVERY DEPTH: </span>
                <strong data-testid="recovery-hud-depth" style={{ color: '#cbd5e1' }}>1 / 3</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>RETRY COUNT: </span>
                <strong data-testid="recovery-hud-retries" style={{ color: '#cbd5e1' }}>0 / 2</strong>
              </div>
            </div>

            {/* Epistemic Safety & Non-Authority Verification */}
            <div
              data-testid="recovery-safety-footer"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.2rem 0.4rem',
                color: '#94a3b8',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="recovery-epistemic-badge" style={{ color: '#38bdf8' }}>
                  EPISTEMIC: STRICT_TRUTH_SEPARATION
                </span>
                <span data-testid="recovery-reconcile-badge" style={{ color: '#c084fc' }}>
                  RECONCILIATION: BOUNDED_PROBE
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="recovery-authority-badge" style={{ color: '#ef4444' }}>
                  AUTHORITY: ZERO_AUTHORITY
                </span>
              </div>
            </div>
          </div>

          {/* Stage 24: Mission Operations Control Plane & Operator HUD Integration */}
          <div
            data-testid="stage24-control-plane-hud"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(245, 158, 11, 0.3)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              fontSize: '0.625rem',
              fontFamily: 'monospace',
              backdropFilter: 'blur(8px)',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Activity size={12} color="#f59e0b" />
                <span style={{ fontWeight: 700, color: '#f8fafc', letterSpacing: '0.05em' }}>
                  CONTROL PLANE OPERATOR HUD // STAGE 24 PROJECTION
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <span
                  data-testid="control-plane-hud-status"
                  style={{
                    fontSize: '0.5625rem',
                    fontWeight: 700,
                    padding: '1px 5px',
                    borderRadius: '3px',
                    backgroundColor: 'rgba(245, 158, 11, 0.15)',
                    color: '#fbbf24',
                    border: '1px solid rgba(245, 158, 11, 0.3)',
                  }}
                >
                  OBSERVATIONAL_HUD
                </span>
                <button
                  type="button"
                  data-testid="toggle-operator-hud-btn"
                  onClick={() => setIsOperatorHudOpen((prev) => !prev)}
                  style={{
                    fontSize: '0.5625rem',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '3px',
                    backgroundColor: isOperatorHudOpen ? 'rgba(245, 158, 11, 0.35)' : 'rgba(148, 163, 184, 0.15)',
                    color: isOperatorHudOpen ? '#fbbf24' : '#94a3b8',
                    border: '1px solid rgba(148, 163, 184, 0.25)',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {isOperatorHudOpen ? 'HIDE FULL HUD' : 'OPEN FULL HUD'}
                </button>
              </div>
            </div>

            {/* Error Banner if snapshot service threw */}
            {controlPlaneError && (
              <div
                data-testid="control-plane-error-banner"
                style={{
                  backgroundColor: 'rgba(239, 68, 68, 0.15)',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                  color: '#f87171',
                  padding: '0.25rem 0.5rem',
                  borderRadius: '3px',
                }}
              >
                SNAPSHOT ERROR: {controlPlaneError}
              </div>
            )}

            {/* Telemetry Matrix */}
            <div
              data-testid="control-plane-telemetry-matrix"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.5rem',
                backgroundColor: 'rgba(2, 6, 23, 0.4)',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                border: '1px solid rgba(148, 163, 184, 0.1)',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>SNAPSHOT ID: </span>
                <strong data-testid="control-plane-snapshot-id" style={{ color: '#38bdf8' }}>
                  {controlPlaneSnapshot?.snapshotId ? controlPlaneSnapshot.snapshotId.substring(0, 16) + '...' : 'UNKNOWN'}
                </strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>MISSIONS: </span>
                <strong data-testid="control-plane-missions-count" style={{ color: '#fbbf24' }}>
                  {controlPlaneSnapshot?.missions.length ?? 0}
                </strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>OPERATIONS: </span>
                <strong data-testid="control-plane-operations-count" style={{ color: '#34d399' }}>
                  {controlPlaneSnapshot?.operations.length ?? 0}
                </strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>APPROVALS REQ: </span>
                <strong data-testid="control-plane-approvals-count" style={{ color: '#c084fc' }}>
                  {controlPlaneSnapshot?.approvals.length ?? 0}
                </strong>
              </div>
            </div>

            {/* Invariant Footer */}
            <div
              data-testid="control-plane-safety-footer"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.2rem 0.4rem',
                color: '#94a3b8',
              }}
            >
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="control-plane-epistemic-badge" style={{ color: '#38bdf8' }}>
                  EPISTEMIC: STRICT_PROJECTION
                </span>
                <span data-testid="control-plane-truth-badge" style={{ color: '#34d399' }}>
                  PERSISTENCE: TRUTHFUL_MIRROR
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span data-testid="control-plane-authority-badge" style={{ color: '#ef4444' }}>
                  AUTHORITY: ZERO_AUTHORITY
                </span>
              </div>
            </div>
          </div>

          {/* Full Master Operator HUD Overlay Modal (when toggled open) */}
          {isOperatorHudOpen && (
            <OperatorHUDErrorBoundary panelTitle="Master Operator HUD Modal">
              <OperatorHUD
                isOpen={isOperatorHudOpen}
                defaultTab={defaultHudTab}
                initialSnapshot={initialControlPlaneSnapshot !== undefined ? initialControlPlaneSnapshot : undefined}
                onClose={() => setIsOperatorHudOpen(false)}
              />
            </OperatorHUDErrorBoundary>
          )}

          {/* Active Execution In Progress / Cancellation Control */}
          {(commandState === 'EXECUTING' || commandState === 'CONFIRMING') && (
            <div
              data-testid="gateway-executing-banner"
              style={{
                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                borderRadius: '4px',
                padding: '0.375rem 0.625rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.6875rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#38bdf8' }}>
                <Activity size={12} />
                <span>DISPATCHING VIA EXECUTION GATEWAY...</span>
              </div>
              <button
                type="button"
                data-testid="gateway-cancel-btn"
                onClick={cancelProposal}
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                  borderRadius: '3px',
                  color: '#f87171',
                  padding: '2px 8px',
                  fontSize: '0.5625rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                CANCEL EXECUTION
              </button>
            </div>
          )}

          {/* Result / Notification Alert Banner */}
          {lastResult && (
            <div
              data-testid="command-result-alert"
              style={{
                backgroundColor:
                  lastResult.status === 'EXECUTED'
                    ? 'rgba(16, 185, 129, 0.12)'
                    : lastResult.status === 'PLANNED'
                    ? 'rgba(245, 158, 11, 0.12)'
                    : 'rgba(239, 68, 68, 0.12)',
                border:
                  lastResult.status === 'EXECUTED'
                    ? '1px solid rgba(16, 185, 129, 0.3)'
                    : lastResult.status === 'PLANNED'
                    ? '1px solid rgba(245, 158, 11, 0.3)'
                    : '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '4px',
                padding: '0.375rem 0.625rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.6875rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    fontSize: '0.5625rem',
                    fontWeight: 700,
                    padding: '1px 5px',
                    borderRadius: '2px',
                    backgroundColor:
                      lastResult.status === 'EXECUTED'
                        ? '#10b981'
                        : lastResult.status === 'PLANNED'
                        ? '#f59e0b'
                        : '#ef4444',
                    color: '#020617',
                  }}
                >
                  {lastResult.status}
                </span>
                <span style={{ color: '#f1f5f9' }}>{lastResult.message}</span>
              </div>

              <button
                type="button"
                data-testid="command-result-dismiss-btn"
                onClick={dismissResult}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#64748b',
                  cursor: 'pointer',
                  padding: '2px',
                  display: 'flex',
                  alignItems: 'center',
                }}
                title="Dismiss result"
              >
                <X size={12} />
              </button>
            </div>
          )}

          {/* Stage 07: Real Provider Execution Gateway Telemetry */}
          {lastExecutionResult && (
            <div
              data-testid="gateway-execution-telemetry"
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                borderRadius: '4px',
                padding: '0.375rem 0.625rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.25rem',
                fontSize: '0.625rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ color: '#38bdf8', fontWeight: 700, letterSpacing: '0.04em' }}>
                  GATEWAY EXECUTION TELEMETRY
                </span>
                <span
                  data-testid="gateway-execution-state"
                  style={{
                    fontSize: '0.5625rem',
                    fontWeight: 700,
                    padding: '1px 5px',
                    borderRadius: '2px',
                    backgroundColor:
                      lastExecutionResult.status === 'SUCCEEDED' ||
                      lastExecutionResult.status === 'FALLBACK_SUCCEEDED' ||
                      (lastExecutionResult.status as string) === 'SUCCESS'
                        ? 'rgba(16, 185, 129, 0.2)'
                        : lastExecutionResult.status === 'CANCELLED'
                        ? 'rgba(148, 163, 184, 0.2)'
                        : 'rgba(239, 68, 68, 0.2)',
                    color:
                      lastExecutionResult.status === 'SUCCEEDED' ||
                      lastExecutionResult.status === 'FALLBACK_SUCCEEDED' ||
                      (lastExecutionResult.status as string) === 'SUCCESS'
                        ? '#10b981'
                        : lastExecutionResult.status === 'CANCELLED'
                        ? '#94a3b8'
                        : '#ef4444',
                  }}
                >
                  {lastExecutionResult.status}
                </span>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: '0.5rem',
                  color: '#94a3b8',
                }}
              >
                <div>
                  <span style={{ color: '#64748b' }}>PROVIDER: </span>
                  <span
                    data-testid="gateway-telemetry-provider"
                    style={{ color: '#f8fafc', fontWeight: 600 }}
                  >
                    {lastExecutionResult.providerId}
                  </span>
                </div>
                <div>
                  <span style={{ color: '#64748b' }}>MODEL: </span>
                  <span
                    data-testid="gateway-telemetry-model"
                    style={{ color: '#f8fafc', fontWeight: 600 }}
                  >
                    {lastExecutionResult.modelId}
                  </span>
                </div>
                <div>
                  <span style={{ color: '#64748b' }}>LATENCY: </span>
                  <span
                    data-testid="gateway-telemetry-latency"
                    style={{ color: '#38bdf8', fontWeight: 600 }}
                  >
                    {lastExecutionResult.latencyMs}ms
                  </span>
                </div>
                <div>
                  <span style={{ color: '#64748b' }}>FALLBACK: </span>
                  <span
                    data-testid="gateway-telemetry-fallback"
                    style={{
                      color: lastExecutionResult.fallbackUsed ? '#fbbf24' : '#64748b',
                      fontWeight: 600,
                    }}
                  >
                    {lastExecutionResult.fallbackUsed ? 'YES' : 'NO'}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
