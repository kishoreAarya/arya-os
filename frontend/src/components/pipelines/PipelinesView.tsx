import React, { useEffect, useState, useRef } from 'react';
import {
  RefreshCw,
  GitBranch,
  Clock,
  DollarSign,
  AlertCircle,
  CheckCircle2,
  XCircle,
  ChevronRight,
  X,
  Layers,
  Sparkles,
  ShieldCheck,
  Cpu,
  ArrowRight,
  Play,
  Plus,
  Copy,
  Check,
  FileText,
  Video,
  Image as ImageIcon,
  Music,
  CheckSquare,
} from 'lucide-react';
import {
  fetchLineage,
  fetchWorkflowRunDetail,
  fetchWorkflowRuns,
  createWorkflowRun,
  executeWorkflowRun,
  fetchPendingApprovals,
  decideApproval,
} from '../../api/dashboardApi';
import {
  ApprovalCheckpointItem,
  LineageResponse,
  WorkflowRunItem,
  WorkflowStatusType,
} from '../../types/dashboard';

export const CANONICAL_STAGES = [
  { id: 'created', label: 'Created' },
  { id: 'trend_selected', label: 'Trend' },
  { id: 'script_generated', label: 'Script' },
  { id: 'storyboard_generated', label: 'Storyboard' },
  { id: 'video_generated', label: 'Video' },
  { id: 'approved', label: 'Approved' },
  { id: 'published', label: 'Published' },
  { id: 'analytics_collected', label: 'Analytics' },
  { id: 'learning_updated', label: 'Learning' },
];

export const PipelinesView: React.FC = () => {
  const [runs, setRuns] = useState<WorkflowRunItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const [limit] = useState(15);
  const [offset, setOffset] = useState(0);

  // Selected run state
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunItem | null>(null);
  const [lineage, setLineage] = useState<LineageResponse | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalCheckpointItem[]>([]);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Workflow Launcher modal state
  const [isLauncherOpen, setIsLauncherOpen] = useState(false);
  const [launcherTopic, setLauncherTopic] = useState('');
  const [launcherMode, setLauncherMode] = useState<'assisted' | 'autonomous' | 'manual'>('assisted');
  const [launcherProjectId, setLauncherProjectId] = useState('00000000-0000-0000-0000-000000000001');
  const [launcherExecuteImmediately, setLauncherExecuteImmediately] = useState(true);
  const [isLaunching, setIsLaunching] = useState(false);
  const [launcherError, setLauncherError] = useState<string | null>(null);

  // Action states
  const [isExecutingRun, setIsExecutingRun] = useState(false);
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [copiedScript, setCopiedScript] = useState(false);
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);
  const [decisionNotes, setDecisionNotes] = useState<Record<string, string>>({});
  const [decisionErrors, setDecisionErrors] = useState<Record<string, string>>({});

  const pollIntervalRef = useRef<any>(null);

  useEffect(() => {
    loadRuns();
  }, [offset]);

  // Polling for running / pending selected workflow
  useEffect(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    if (
      selectedRun &&
      ['running', 'pending', 'awaiting_approval'].includes(selectedRun.status)
    ) {
      pollIntervalRef.current = setInterval(async () => {
        try {
          const [updatedRun, updatedApprovals] = await Promise.all([
            fetchWorkflowRunDetail(selectedRun.id),
            fetchPendingApprovals(selectedRun.id).catch(() => []),
          ]);

          setSelectedRun(updatedRun);
          setPendingApprovals(updatedApprovals);

          // If reached terminal status, stop polling and update list
          if (updatedRun.status === 'completed' || updatedRun.status === 'failed') {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
            loadRuns();
          }
        } catch {
          // Keep polling or ignore network hiccups
        }
      }, 3000);
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [selectedRun?.id, selectedRun?.status]);

  const loadRuns = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchWorkflowRuns({ limit, offset });
      setRuns(data);
      if (data.length > 0 && !launcherProjectId) {
        setLauncherProjectId(data[0].project_id);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load workflow runs';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectRun = async (runId: string) => {
    setSelectedRunId(runId);
    setIsLoadingDetail(true);
    setDetailError(null);
    setSelectedRun(null);
    setLineage(null);
    setPendingApprovals([]);
    setExecuteError(null);
    setDecisionErrors({});

    try {
      const [runData, lineageData, approvalsData] = await Promise.allSettled([
        fetchWorkflowRunDetail(runId),
        fetchLineage(runId),
        fetchPendingApprovals(runId),
      ]);

      if (runData.status === 'fulfilled') {
        setSelectedRun(runData.value);
      } else {
        throw new Error(runData.reason?.message || 'Failed to fetch run details');
      }

      if (lineageData.status === 'fulfilled') {
        setLineage(lineageData.value);
      }

      if (approvalsData.status === 'fulfilled') {
        setPendingApprovals(approvalsData.value);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load run details';
      setDetailError(msg);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // Launch New Workflow Run
  const handleLaunchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!launcherTopic.trim()) {
      setLauncherError('Please provide a topic for the workflow run.');
      return;
    }
    if (!launcherProjectId.trim()) {
      setLauncherError('Please provide a valid project UUID.');
      return;
    }

    setIsLaunching(true);
    setLauncherError(null);

    try {
      const res = await createWorkflowRun({
        project_id: launcherProjectId.trim(),
        topic: launcherTopic.trim(),
        mode: launcherMode,
        execute: launcherExecuteImmediately,
      });

      setIsLauncherOpen(false);
      setLauncherTopic('');
      await loadRuns();
      if (res.workflow_run_id) {
        handleSelectRun(res.workflow_run_id);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to launch workflow run';
      setLauncherError(msg);
    } finally {
      setIsLaunching(false);
    }
  };

  // Execute Existing Pending Run
  const handleExecuteExistingRun = async (runId: string) => {
    setIsExecutingRun(true);
    setExecuteError(null);
    try {
      await executeWorkflowRun(runId);
      // Immediately refresh selected run
      const updated = await fetchWorkflowRunDetail(runId);
      setSelectedRun(updated);
      loadRuns();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to execute workflow run';
      setExecuteError(msg);
    } finally {
      setIsExecutingRun(false);
    }
  };

  // Copy Script to Clipboard
  const handleCopyScript = (scriptText: string) => {
    navigator.clipboard.writeText(scriptText);
    setCopiedScript(true);
    setTimeout(() => setCopiedScript(false), 2000);
  };

  // Decide Approval Checkpoint
  const handleDecideApproval = async (
    checkpointId: string,
    action: 'approve' | 'reject' | 'retry' | 'manual_edit' | 'continue'
  ) => {
    setIsSubmittingDecision(true);
    setDecisionErrors((prev) => ({ ...prev, [checkpointId]: '' }));

    try {
      await decideApproval(checkpointId, {
        action,
        reviewer_notes: decisionNotes[checkpointId] || undefined,
      });

      // Refresh approvals list and run details
      if (selectedRunId) {
        const [updatedApprovals, updatedRun] = await Promise.all([
          fetchPendingApprovals(selectedRunId),
          fetchWorkflowRunDetail(selectedRunId),
        ]);
        setPendingApprovals(updatedApprovals);
        setSelectedRun(updatedRun);
        loadRuns();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit approval decision';
      setDecisionErrors((prev) => ({ ...prev, [checkpointId]: msg }));
    } finally {
      setIsSubmittingDecision(false);
    }
  };

  const renderStatusBadge = (status: WorkflowStatusType) => {
    switch (status) {
      case 'completed':
        return (
          <span className="status-badge status-completed">
            <CheckCircle2 size={12} />
            Completed
          </span>
        );
      case 'running':
        return (
          <span className="status-badge status-running">
            <RefreshCw size={12} className="animate-spin" />
            Running
          </span>
        );
      case 'awaiting_approval':
        return (
          <span className="status-badge status-approval">
            <Clock size={12} />
            Approval
          </span>
        );
      case 'failed':
        return (
          <span className="status-badge status-failed">
            <XCircle size={12} />
            Failed
          </span>
        );
      case 'pending':
      default:
        return (
          <span className="status-badge status-pending">
            <Clock size={12} />
            Pending
          </span>
        );
    }
  };

  const getStageIndex = (stage: string | null) => {
    if (!stage) return -1;
    return CANONICAL_STAGES.findIndex((s) => s.id.toLowerCase() === stage.toLowerCase());
  };

  return (
    <div style={{ maxWidth: '1600px', margin: '0 auto', padding: '1.5rem', width: '100%' }}>
      {/* Top Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.5rem',
        }}
      >
        <div>
          <h2
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <GitBranch size={22} color="var(--accent-primary)" />
            Pipelines & Workflow Runs
          </h2>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Control plane for launching, monitoring, inspecting artifacts, and resolving human checkpoints.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            type="button"
            onClick={() => setIsLauncherOpen(true)}
            className="btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <Plus size={16} />
            <span>Launch Pipeline</span>
          </button>

          <button
            type="button"
            onClick={loadRuns}
            disabled={isLoading}
            className="btn-secondary"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Refresh Runs</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: selectedRunId ? '1fr 580px' : '1fr',
          gap: '1.5rem',
          alignItems: 'start',
        }}
      >
        {/* Table Container */}
        <div className="creator-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div
            style={{
              padding: '1rem 1.25rem',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              Execution Log ({runs.length} runs listed)
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Offset: {offset} | Limit: {limit}
            </span>
          </div>

          {isLoading && runs.length === 0 ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 0.75rem' }} />
              <p style={{ fontSize: '0.875rem' }}>Loading workflow runs from database...</p>
            </div>
          ) : error ? (
            <div
              style={{
                padding: '2.5rem',
                textAlign: 'center',
                color: 'var(--danger)',
                backgroundColor: 'rgba(239, 68, 68, 0.05)',
              }}
            >
              <AlertCircle size={28} style={{ margin: '0 auto 0.5rem' }} />
              <p style={{ fontSize: '0.875rem', fontWeight: 500 }}>{error}</p>
              <button
                type="button"
                onClick={loadRuns}
                className="btn-secondary"
                style={{ marginTop: '1rem' }}
              >
                Retry
              </button>
            </div>
          ) : runs.length === 0 ? (
            <div style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              <GitBranch size={32} style={{ margin: '0 auto 0.75rem', opacity: 0.4 }} />
              <p style={{ fontSize: '0.9375rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
                No workflow runs found
              </p>
              <p style={{ fontSize: '0.8125rem', marginTop: '0.25rem' }}>
                Launch a new workflow pipeline above to trigger autonomous or assisted video production.
              </p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  textAlign: 'left',
                  fontSize: '0.8125rem',
                }}
              >
                <thead>
                  <tr
                    style={{
                      borderBottom: '1px solid var(--border-color)',
                      backgroundColor: 'rgba(255, 255, 255, 0.02)',
                    }}
                  >
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Run ID</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Topic</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Status</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Stage</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Mode</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Cost</th>
                    <th style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)' }}>Created</th>
                    <th style={{ padding: '0.75rem 1rem', textAlign: 'right', color: 'var(--text-muted)' }}>
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => {
                    const isSelected = selectedRunId === r.id;
                    return (
                      <tr
                        key={r.id}
                        onClick={() => handleSelectRun(r.id)}
                        style={{
                          borderBottom: '1px solid var(--border-color)',
                          backgroundColor: isSelected
                            ? 'rgba(99, 102, 241, 0.08)'
                            : 'transparent',
                          cursor: 'pointer',
                          transition: 'background-color 0.15s',
                        }}
                      >
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            fontFamily: 'monospace',
                            color: 'var(--text-secondary)',
                          }}
                          title={r.id}
                        >
                          {r.id.slice(0, 8)}…
                        </td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            fontWeight: 500,
                            color: 'var(--text-primary)',
                            maxWidth: '240px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {r.topic || 'Untitled Workflow'}
                        </td>
                        <td style={{ padding: '0.75rem 1rem' }}>{renderStatusBadge(r.status)}</td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            fontFamily: 'monospace',
                            color: 'var(--text-secondary)',
                            fontSize: '0.75rem',
                          }}
                        >
                          {r.current_stage || '—'}
                        </td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            textTransform: 'capitalize',
                            color: 'var(--text-muted)',
                          }}
                        >
                          {r.mode}
                        </td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            color: 'var(--text-secondary)',
                          }}
                        >
                          ${Number(r.total_cost_usd || 0).toFixed(4)}
                        </td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            color: 'var(--text-muted)',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {new Date(r.created_at).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                            month: 'short',
                            day: 'numeric',
                          })}
                        </td>
                        <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                          <button
                            type="button"
                            className="btn-secondary"
                            style={{
                              padding: '4px 8px',
                              fontSize: '0.75rem',
                              borderColor: isSelected
                                ? 'var(--accent-primary)'
                                : 'var(--border-color)',
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelectRun(r.id);
                            }}
                          >
                            Inspect
                            <ChevronRight size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination Controls */}
          <div
            style={{
              padding: '0.875rem 1.25rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderTop: '1px solid var(--border-color)',
              backgroundColor: 'var(--bg-secondary)',
            }}
          >
            <button
              type="button"
              className="btn-secondary"
              disabled={offset === 0 || isLoading}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Previous
            </button>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Showing {runs.length > 0 ? offset + 1 : 0} – {offset + runs.length}
            </span>
            <button
              type="button"
              className="btn-secondary"
              disabled={runs.length < limit || isLoading}
              onClick={() => setOffset(offset + limit)}
            >
              Next
            </button>
          </div>
        </div>

        {/* Detail Panel */}
        {selectedRunId && (
          <div
            className="creator-card"
            style={{
              display: 'flex',
              flexDirection: 'column',
              maxHeight: 'calc(100vh - 160px)',
              overflowY: 'auto',
              gap: '1.25rem',
            }}
          >
            {/* Detail Header */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                paddingBottom: '0.75rem',
                borderBottom: '1px solid var(--border-color)',
              }}
            >
              <div>
                <span
                  style={{
                    fontSize: '0.6875rem',
                    textTransform: 'uppercase',
                    color: 'var(--accent-primary)',
                    fontWeight: 700,
                    letterSpacing: '0.05em',
                  }}
                >
                  Workflow Run Control Plane
                </span>
                <h3
                  style={{
                    fontSize: '1.0625rem',
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                    marginTop: '2px',
                  }}
                >
                  {selectedRun?.topic || 'Selected Run'}
                </h3>
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontFamily: 'monospace',
                    color: 'var(--text-muted)',
                  }}
                >
                  {selectedRunId}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSelectedRunId(null)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px',
                }}
              >
                <X size={18} />
              </button>
            </div>

            {isLoadingDetail ? (
              <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                <RefreshCw size={20} className="animate-spin" style={{ margin: '0 auto 0.5rem' }} />
                <p style={{ fontSize: '0.8125rem' }}>Fetching run state, artifacts, and checkpoints...</p>
              </div>
            ) : detailError ? (
              <div
                style={{
                  padding: '1.5rem',
                  color: 'var(--danger)',
                  fontSize: '0.8125rem',
                  backgroundColor: 'rgba(239, 68, 68, 0.05)',
                  borderRadius: '6px',
                }}
              >
                <AlertCircle size={18} style={{ marginBottom: '0.5rem' }} />
                <p>{detailError}</p>
              </div>
            ) : selectedRun ? (
              <>
                {/* Status Bar */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.75rem',
                    borderRadius: '8px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  <div>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block' }}>
                      Status
                    </span>
                    <div style={{ marginTop: '2px' }}>{renderStatusBadge(selectedRun.status)}</div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block' }}>
                      Total Cost
                    </span>
                    <span
                      style={{
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                      }}
                    >
                      ${Number(selectedRun.total_cost_usd || 0).toFixed(4)}
                    </span>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block' }}>
                      Mode
                    </span>
                    <span
                      style={{
                        fontSize: '0.8125rem',
                        textTransform: 'capitalize',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {selectedRun.mode}
                    </span>
                  </div>
                </div>

                {/* Unexecuted Run Action: Start Execution */}
                {selectedRun.status === 'pending' && (
                  <div
                    style={{
                      padding: '0.875rem',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(99, 102, 241, 0.08)',
                      border: '1px solid rgba(99, 102, 241, 0.25)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                        Workflow Ready to Execute
                      </span>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                        This run was created in pending status. Trigger the autonomous orchestrator.
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleExecuteExistingRun(selectedRun.id)}
                      disabled={isExecutingRun}
                      className="btn-primary"
                      style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', padding: '6px 12px' }}
                    >
                      {isExecutingRun ? (
                        <RefreshCw size={14} className="animate-spin" />
                      ) : (
                        <Play size={14} />
                      )}
                      <span>Execute Run</span>
                    </button>
                  </div>
                )}

                {executeError && (
                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'rgba(239, 68, 68, 0.1)',
                      color: 'var(--danger)',
                      fontSize: '0.75rem',
                    }}
                  >
                    {executeError}
                  </div>
                )}

                {/* Failure Reason Alert */}
                {selectedRun.failure_reason && (
                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'rgba(239, 68, 68, 0.1)',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      color: '#fca5a5',
                      fontSize: '0.75rem',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.375rem',
                        fontWeight: 600,
                        marginBottom: '0.25rem',
                      }}
                    >
                      <XCircle size={14} color="var(--danger)" />
                      Failure Reason:
                    </div>
                    <p style={{ wordBreak: 'break-word' }}>{selectedRun.failure_reason}</p>
                  </div>
                )}

                {/* Canonical Pipeline Stage Stepper */}
                <div>
                  <h4
                    style={{
                      fontSize: '0.75rem',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: 'var(--text-muted)',
                      marginBottom: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.375rem',
                    }}
                  >
                    <Layers size={14} />
                    Pipeline Stage Stepper (Monitoring)
                  </h4>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(3, 1fr)',
                      gap: '0.5rem',
                    }}
                  >
                    {CANONICAL_STAGES.map((s, idx) => {
                      const currentIdx = getStageIndex(selectedRun.current_stage);
                      const isCompleted = currentIdx > idx || selectedRun.status === 'completed';
                      const isCurrent = currentIdx === idx && selectedRun.status !== 'completed';
                      const isFailed = isCurrent && selectedRun.status === 'failed';

                      let bgColor = 'var(--bg-primary)';
                      let borderColor = 'var(--border-color)';
                      let textColor = 'var(--text-muted)';

                      if (isCompleted) {
                        bgColor = 'rgba(16, 185, 129, 0.08)';
                        borderColor = 'rgba(16, 185, 129, 0.4)';
                        textColor = 'var(--success)';
                      } else if (isFailed) {
                        bgColor = 'rgba(239, 68, 68, 0.08)';
                        borderColor = 'rgba(239, 68, 68, 0.4)';
                        textColor = 'var(--danger)';
                      } else if (isCurrent) {
                        bgColor = 'rgba(99, 102, 241, 0.15)';
                        borderColor = 'var(--accent-primary)';
                        textColor = 'var(--accent-primary)';
                      }

                      return (
                        <div
                          key={s.id}
                          style={{
                            padding: '0.5rem',
                            borderRadius: '6px',
                            backgroundColor: bgColor,
                            border: `1px solid ${borderColor}`,
                            fontSize: '0.6875rem',
                            textAlign: 'center',
                          }}
                        >
                          <span
                            style={{
                              display: 'block',
                              fontWeight: isCurrent || isCompleted ? 600 : 400,
                              color: textColor,
                            }}
                          >
                            {s.label}
                          </span>
                          <span
                            style={{
                              fontSize: '0.625rem',
                              color: 'var(--text-muted)',
                              marginTop: '2px',
                              display: 'block',
                            }}
                          >
                            {isCompleted
                              ? '✓ Done'
                              : isFailed
                              ? '✗ Failed'
                              : isCurrent
                              ? '● Active'
                              : 'Pending'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Approval Review & Decision Console */}
                {pendingApprovals.length > 0 && (
                  <div
                    style={{
                      padding: '1rem',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '0.75rem',
                      }}
                    >
                      <h4
                        style={{
                          fontSize: '0.8125rem',
                          fontWeight: 700,
                          color: '#f59e0b',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.375rem',
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                        }}
                      >
                        <CheckSquare size={16} />
                        Human Approval Checkpoint
                      </h4>
                      <span
                        style={{
                          fontSize: '0.6875rem',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor: 'rgba(245, 158, 11, 0.2)',
                          color: '#f59e0b',
                          fontWeight: 600,
                        }}
                      >
                        Action Required
                      </span>
                    </div>

                    {pendingApprovals.map((cp) => (
                      <div
                        key={cp.id}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.75rem',
                          backgroundColor: 'var(--bg-primary)',
                          padding: '0.875rem',
                          borderRadius: '6px',
                          border: '1px solid var(--border-color)',
                          marginBottom: '0.5rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                            Stage: {cp.stage.toUpperCase()} ({cp.reference_table})
                          </span>
                          <span style={{ fontSize: '0.6875rem', fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                            {cp.id.slice(0, 8)}
                          </span>
                        </div>

                        {/* Review Content */}
                        {cp.review_content && (
                          <div
                            style={{
                              padding: '0.75rem',
                              borderRadius: '4px',
                              backgroundColor: 'var(--bg-secondary)',
                              fontSize: '0.75rem',
                              border: '1px solid var(--border-color)',
                            }}
                          >
                            <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                              Reviewable Asset Content:
                            </span>
                            {Boolean(cp.review_content.content) && (
                              <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4, color: 'var(--text-primary)' }}>
                                {String(cp.review_content.content)}
                              </p>
                            )}
                            {Boolean(cp.review_content.storage_path) && (
                              <p style={{ fontFamily: 'monospace', color: 'var(--accent-primary)', wordBreak: 'break-all' }}>
                                {String(cp.review_content.storage_path)}
                              </p>
                            )}
                            {Boolean(cp.review_content.shots) && (
                              <p style={{ color: 'var(--text-secondary)' }}>
                                Storyboard: {Array.isArray(cp.review_content.shots) ? cp.review_content.shots.length : 'Multiple'} shots configured
                              </p>
                            )}
                          </div>
                        )}

                        {/* Reviewer Notes Textarea */}
                        <div>
                          <label
                            style={{
                              fontSize: '0.6875rem',
                              color: 'var(--text-muted)',
                              display: 'block',
                              marginBottom: '2px',
                            }}
                          >
                            Reviewer Notes (Optional feedback / edit directives):
                          </label>
                          <textarea
                            value={decisionNotes[cp.id] || ''}
                            onChange={(e) =>
                              setDecisionNotes((prev) => ({ ...prev, [cp.id]: e.target.value }))
                            }
                            placeholder="Add guidance or revision requests..."
                            className="input-text"
                            rows={2}
                            style={{
                              width: '100%',
                              fontSize: '0.75rem',
                              padding: '6px',
                              backgroundColor: 'var(--bg-secondary)',
                              borderRadius: '4px',
                              border: '1px solid var(--border-color)',
                              color: 'var(--text-primary)',
                              resize: 'vertical',
                            }}
                          />
                        </div>

                        {/* Decision Error Alert */}
                        {decisionErrors[cp.id] && (
                          <div
                            style={{
                              padding: '0.5rem',
                              borderRadius: '4px',
                              backgroundColor: 'rgba(239, 68, 68, 0.1)',
                              color: 'var(--danger)',
                              fontSize: '0.75rem',
                            }}
                          >
                            {decisionErrors[cp.id]}
                          </div>
                        )}

                        {/* Decision Action Buttons */}
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            onClick={() => handleDecideApproval(cp.id, 'approve')}
                            disabled={isSubmittingDecision}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '4px',
                              backgroundColor: 'var(--success)',
                              color: '#fff',
                              border: 'none',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                            }}
                          >
                            <CheckCircle2 size={12} />
                            Approve
                          </button>

                          <button
                            type="button"
                            onClick={() => handleDecideApproval(cp.id, 'reject')}
                            disabled={isSubmittingDecision}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '4px',
                              backgroundColor: 'var(--danger)',
                              color: '#fff',
                              border: 'none',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                            }}
                          >
                            <XCircle size={12} />
                            Reject
                          </button>

                          <button
                            type="button"
                            onClick={() => handleDecideApproval(cp.id, 'retry')}
                            disabled={isSubmittingDecision}
                            className="btn-secondary"
                            style={{
                              padding: '5px 10px',
                              fontSize: '0.75rem',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                            }}
                          >
                            <RefreshCw size={12} />
                            Retry
                          </button>

                          <button
                            type="button"
                            onClick={() => handleDecideApproval(cp.id, 'manual_edit')}
                            disabled={isSubmittingDecision}
                            className="btn-secondary"
                            style={{
                              padding: '5px 10px',
                              fontSize: '0.75rem',
                            }}
                          >
                            Manual Edit
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Workflow Artifact References */}
                <div>
                  <h4
                    style={{
                      fontSize: '0.75rem',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: 'var(--text-muted)',
                      marginBottom: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.375rem',
                    }}
                  >
                    <FileText size={14} />
                    Produced Workflow Artifacts
                  </h4>

                  {!selectedRun.artifacts ||
                  (!selectedRun.artifacts.script_content &&
                    !selectedRun.artifacts.video_path &&
                    !selectedRun.artifacts.thumbnail_path &&
                    !selectedRun.artifacts.audio_path &&
                    !selectedRun.artifacts.storyboard &&
                    (!selectedRun.artifacts.images || selectedRun.artifacts.images.length === 0)) ? (
                    <div
                      style={{
                        padding: '1.25rem',
                        textAlign: 'center',
                        color: 'var(--text-muted)',
                        backgroundColor: 'var(--bg-primary)',
                        borderRadius: '6px',
                        fontSize: '0.75rem',
                      }}
                    >
                      No artifacts produced yet for this workflow run.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      {/* Script Artifact */}
                      {selectedRun.artifacts.script_content && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              marginBottom: '0.5rem',
                            }}
                          >
                            <span
                              style={{
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                color: 'var(--text-primary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.375rem',
                              }}
                            >
                              <FileText size={14} color="var(--accent-primary)" />
                              Generated Production Script
                            </span>
                            <button
                              type="button"
                              onClick={() => handleCopyScript(selectedRun.artifacts!.script_content!)}
                              className="btn-secondary"
                              style={{
                                padding: '3px 8px',
                                fontSize: '0.6875rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.25rem',
                              }}
                            >
                              {copiedScript ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
                              <span>{copiedScript ? 'Copied!' : 'Copy Script'}</span>
                            </button>
                          </div>
                          <div
                            style={{
                              maxHeight: '160px',
                              overflowY: 'auto',
                              padding: '0.625rem',
                              borderRadius: '4px',
                              backgroundColor: 'var(--bg-secondary)',
                              fontSize: '0.75rem',
                              lineHeight: 1.4,
                              color: 'var(--text-secondary)',
                              whiteSpace: 'pre-wrap',
                              fontFamily: 'monospace',
                            }}
                          >
                            {selectedRun.artifacts.script_content}
                          </div>
                        </div>
                      )}

                      {/* Video Artifact */}
                      {selectedRun.artifacts.video_path && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden' }}>
                            <Video size={16} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
                            <div style={{ overflow: 'hidden' }}>
                              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block' }}>
                                Master Video Asset
                              </span>
                              <span
                                style={{
                                  fontSize: '0.6875rem',
                                  fontFamily: 'monospace',
                                  color: 'var(--text-muted)',
                                  display: 'block',
                                  textOverflow: 'ellipsis',
                                  overflow: 'hidden',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {selectedRun.artifacts.video_path}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Thumbnail Artifact */}
                      {selectedRun.artifacts.thumbnail_path && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                          }}
                        >
                          <ImageIcon size={16} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
                          <div style={{ overflow: 'hidden' }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block' }}>
                              High-CTR Thumbnail
                            </span>
                            <span
                              style={{
                                fontSize: '0.6875rem',
                                fontFamily: 'monospace',
                                color: 'var(--text-muted)',
                                display: 'block',
                                textOverflow: 'ellipsis',
                                overflow: 'hidden',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {selectedRun.artifacts.thumbnail_path}
                            </span>
                          </div>
                        </div>
                      )}

                      {/* Audio Artifact */}
                      {selectedRun.artifacts.audio_path && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                          }}
                        >
                          <Music size={16} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
                          <div style={{ overflow: 'hidden' }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block' }}>
                              Master Audio Track
                            </span>
                            <span
                              style={{
                                fontSize: '0.6875rem',
                                fontFamily: 'monospace',
                                color: 'var(--text-muted)',
                                display: 'block',
                                textOverflow: 'ellipsis',
                                overflow: 'hidden',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {selectedRun.artifacts.audio_path}
                            </span>
                          </div>
                        </div>
                      )}

                      {/* Storyboard Shots */}
                      {selectedRun.artifacts.storyboard && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>
                            Storyboard Specification
                          </span>
                          <pre
                            style={{
                              fontSize: '0.6875rem',
                              color: 'var(--text-muted)',
                              backgroundColor: 'var(--bg-secondary)',
                              padding: '6px',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              maxHeight: '120px',
                            }}
                          >
                            {JSON.stringify(selectedRun.artifacts.storyboard, null, 2)}
                          </pre>
                        </div>
                      )}

                      {/* Generated Images List */}
                      {selectedRun.artifacts.images && selectedRun.artifacts.images.length > 0 && (
                        <div
                          style={{
                            padding: '0.875rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>
                            Generated Keyframe Visuals ({selectedRun.artifacts.images.length})
                          </span>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {selectedRun.artifacts.images.map((img, iIdx) => (
                              <div
                                key={iIdx}
                                style={{
                                  fontSize: '0.6875rem',
                                  fontFamily: 'monospace',
                                  color: 'var(--text-secondary)',
                                  textOverflow: 'ellipsis',
                                  overflow: 'hidden',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                • {img}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Lineage & Quality Score Trace */}
                <div>
                  <h4
                    style={{
                      fontSize: '0.75rem',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: 'var(--text-muted)',
                      marginBottom: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.375rem',
                    }}
                  >
                    <ShieldCheck size={14} />
                    Artifact Lineage & Quality Scores
                  </h4>

                  {!lineage || lineage.trace.length === 0 ? (
                    <div
                      style={{
                        padding: '1rem',
                        textAlign: 'center',
                        color: 'var(--text-muted)',
                        backgroundColor: 'var(--bg-primary)',
                        borderRadius: '6px',
                        fontSize: '0.75rem',
                      }}
                    >
                      No artifact lineage records recorded for this run yet.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      {lineage.trace.map((item, tIdx) => (
                        <div
                          key={`${item.reference_id}-${tIdx}`}
                          style={{
                            padding: '0.75rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              marginBottom: '0.375rem',
                            }}
                          >
                            <span
                              style={{
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                color: 'var(--accent-primary)',
                                textTransform: 'capitalize',
                              }}
                            >
                              {item.artifact_type} (v{item.version})
                            </span>
                            <span
                              style={{
                                fontSize: '0.6875rem',
                                color: 'var(--text-muted)',
                                fontFamily: 'monospace',
                              }}
                            >
                              {item.reference_table}
                            </span>
                          </div>

                          {/* Quality Scores */}
                          {item.quality_scores.length > 0 && (
                            <div style={{ marginTop: '0.375rem' }}>
                              <span
                                style={{
                                  fontSize: '0.625rem',
                                  color: 'var(--text-muted)',
                                  textTransform: 'uppercase',
                                }}
                              >
                                Quality Validation:
                              </span>
                              <div
                                style={{
                                  display: 'flex',
                                  flexWrap: 'wrap',
                                  gap: '0.375rem',
                                  marginTop: '2px',
                                }}
                              >
                                {item.quality_scores.map((qs, qIdx) => (
                                  <span
                                    key={qIdx}
                                    style={{
                                      fontSize: '0.6875rem',
                                      padding: '2px 6px',
                                      borderRadius: '4px',
                                      backgroundColor: 'var(--bg-card)',
                                      color:
                                        qs.score >= 80
                                          ? 'var(--success)'
                                          : qs.score >= 60
                                          ? 'var(--warning)'
                                          : 'var(--danger)',
                                      border: '1px solid var(--border-color)',
                                    }}
                                  >
                                    {qs.dimension}: {qs.score}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Generation Attempts */}
                          {item.generation_attempts.length > 0 && (
                            <div style={{ marginTop: '0.375rem' }}>
                              <span
                                style={{
                                  fontSize: '0.625rem',
                                  color: 'var(--text-muted)',
                                  textTransform: 'uppercase',
                                }}
                              >
                                Provider Attempts:
                              </span>
                              <div
                                style={{
                                  display: 'flex',
                                  flexDirection: 'column',
                                  gap: '2px',
                                  marginTop: '2px',
                                }}
                              >
                                {item.generation_attempts.map((ga, gIdx) => (
                                  <div
                                    key={gIdx}
                                    style={{
                                      fontSize: '0.6875rem',
                                      color: ga.succeeded ? 'var(--text-secondary)' : 'var(--danger)',
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: '0.375rem',
                                    }}
                                  >
                                    <Cpu size={10} />
                                    <span>
                                      Attempt #{ga.attempt_number}{ga.provider_id ? ` [${ga.provider_id}]` : ''} (Cost: ${ga.cost_usd}):{' '}
                                      {ga.succeeded ? 'Succeeded' : `Failed: ${ga.failure_reason}`}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </div>
        )}
      </div>

      {/* Workflow Launcher Modal */}
      {isLauncherOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1.5rem',
          }}
          onClick={() => !isLaunching && setIsLauncherOpen(false)}
        >
          <div
            className="creator-card"
            style={{
              maxWidth: '520px',
              width: '100%',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
              position: 'relative',
              boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
            }}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="launcher-title"
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3
                id="launcher-title"
                style={{
                  fontSize: '1.125rem',
                  fontWeight: 700,
                  color: 'var(--text-primary)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                }}
              >
                <Sparkles size={18} color="var(--accent-primary)" />
                Launch Workflow Pipeline
              </h3>
              <button
                type="button"
                onClick={() => setIsLauncherOpen(false)}
                disabled={isLaunching}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px',
                }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              Initialize a production video workflow run across research, scripting, audio, visuals, and assembly.
            </p>

            {launcherError && (
              <div
                style={{
                  padding: '0.75rem',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  color: 'var(--danger)',
                  fontSize: '0.75rem',
                }}
              >
                {launcherError}
              </div>
            )}

            <form onSubmit={handleLaunchSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Topic Input */}
              <div>
                <label
                  htmlFor="launcher-topic"
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    display: 'block',
                    marginBottom: '0.375rem',
                  }}
                >
                  Topic / Concept Title *
                </label>
                <input
                  id="launcher-topic"
                  type="text"
                  value={launcherTopic}
                  onChange={(e) => setLauncherTopic(e.target.value)}
                  placeholder="e.g. 5 Breakthrough AI Discoveries This Week"
                  className="input-text"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    fontSize: '0.8125rem',
                    backgroundColor: 'var(--bg-secondary)',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                  autoFocus
                />
              </div>

              {/* Mode Select */}
              <div>
                <label
                  htmlFor="launcher-mode"
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    display: 'block',
                    marginBottom: '0.375rem',
                  }}
                >
                  Execution Mode
                </label>
                <select
                  id="launcher-mode"
                  value={launcherMode}
                  onChange={(e) => setLauncherMode(e.target.value as any)}
                  className="input-select"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    fontSize: '0.8125rem',
                    backgroundColor: 'var(--bg-secondary)',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <option value="assisted">Assisted (Pauses at Human Approval Checkpoints)</option>
                  <option value="autonomous">Autonomous (Fully Automated End-to-End)</option>
                  <option value="manual">Manual (Step-by-Step Validation)</option>
                </select>
              </div>

              {/* Project ID */}
              <div>
                <label
                  htmlFor="launcher-project-id"
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    display: 'block',
                    marginBottom: '0.375rem',
                  }}
                >
                  Project UUID
                </label>
                <input
                  id="launcher-project-id"
                  type="text"
                  value={launcherProjectId}
                  onChange={(e) => setLauncherProjectId(e.target.value)}
                  className="input-text"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    fontSize: '0.75rem',
                    fontFamily: 'monospace',
                    backgroundColor: 'var(--bg-secondary)',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              {/* Execute Immediately Toggle */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
                <input
                  id="launcher-execute"
                  type="checkbox"
                  checked={launcherExecuteImmediately}
                  onChange={(e) => setLauncherExecuteImmediately(e.target.checked)}
                  style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                />
                <label
                  htmlFor="launcher-execute"
                  style={{
                    fontSize: '0.8125rem',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  Start pipeline execution immediately in background
                </label>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setIsLauncherOpen(false)}
                  disabled={isLaunching}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLaunching}
                  className="btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                >
                  {isLaunching ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
                  <span>{launcherExecuteImmediately ? 'Launch & Execute' : 'Create Pending Run'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
