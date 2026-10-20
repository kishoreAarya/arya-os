import React, { useEffect, useState, useRef, useMemo } from 'react';
import {
  checkBackendHealth,
  fetchCapabilities,
  fetchHistory,
  getStoredApiKey,
  pollJobStatus,
  submitGeneration,
} from './api/creatorApi';
import {
  CapabilitiesManifest,
  CreatorGeneratePayload,
  GenerationJob,
  GenerationType,
  HealthStatus,
  HistoryItem,
} from './types/creator';
import { deriveSystemState, historyItemToProductionRun, ProductionRun, SystemOperationalState } from './types/productionRun';
import {
  deriveProductionRecommendation,
  ConfigurationParameters,
} from './types/productionDecision';
import { ProductionDecisionCard } from './components/orchestration/ProductionDecisionCard';
import { AppView } from './types/dashboard';
import { Header } from './components/Header';
import { AuthModal } from './components/AuthModal';
import { AtmosphericBackground } from './components/visual/AtmosphericBackground';
import { MotionViewWrapper } from './components/motion/MotionSystem';
import { CommandCore } from './components/command-core/CommandCore';
import { CommandCoreState } from './components/command-core/commandCoreTypes';
import { OperationalStrip } from './components/orchestration/OperationalStrip';
import { WorkflowOrbit } from './components/workflow/WorkflowOrbit';
import { GenerationTypeSelector } from './components/GenerationTypeSelector';
import { PromptSection } from './components/PromptSection';
import { ReferenceUpload } from './components/ReferenceUpload';
import { ConfigPanel } from './components/ConfigPanel';
import { StartEndFrameControls } from './components/StartEndFrameControls';
import { GenerateButton } from './components/GenerateButton';
import { JobStatusCard } from './components/JobStatusCard';
import { AssetPreview } from './components/AssetPreview';
import { HistoryPanel } from './components/HistoryPanel';
import { PipelinesView } from './components/pipelines/PipelinesView';
import { ResearchView } from './components/research/ResearchView';
import { PublishingView } from './components/publishing/PublishingView';
import { LearningView } from './components/learning/LearningView';
import { ProductionTimeline } from './components/timeline/ProductionTimeline';
import { SpatialWorld } from './components/spatial/SpatialWorld';
import { Project, Shot, SequenceOperationalSummary } from './types/productionTimeline';
import { AryaJobPackage } from './types/spatialIntent';
import {
  createDefaultProject,
  validateShot,
  evaluateSequenceReadiness,
  reorderShots,
  duplicateShot,
  removeShot,
  linkPredecessorStartFrame,
  reproduceShotToConsole,
} from './utils/continuityEngine';
import {
  saveProject,
  loadProject,
  clearProject,
  hasPersistedProject,
  getPersistedProjectEnvelope,
  recomputeDerivedState,
  checkForInterruptedShots,
  reconcileProjectWithHistory,
} from './utils/projectPersistence';
import { ProjectRecoveryState, PersistedProjectEnvelope } from './types/productionTimeline';
import {
  checkProductionApiHealth,
  listProjects,
  getProjectTree,
  createRemoteProject,
  createRemoteShot,
  updateRemoteShot,
  submitRemoteJobPackage,
  updateRemoteJobStatus,
  subscribeToProjectTelemetry,
  projectFromRemoteTree,
  PersistenceSyncStatus,
} from './api/productionApi';

const STORAGE_KEY_RECOVERY = 'arya_active_job_recovery';

interface JobRecoveryRecord {
  jobId: string;
  generationType: GenerationType;
  submittedAt: number;
  payloadSnapshot?: CreatorGeneratePayload;
}

const saveJobRecovery = (record: JobRecoveryRecord): void => {
  try {
    localStorage.setItem(STORAGE_KEY_RECOVERY, JSON.stringify(record));
  } catch (err) {
    console.warn('Workspace recovery storage warning:', err);
  }
};

const getJobRecovery = (): JobRecoveryRecord | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_RECOVERY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
};

const clearJobRecovery = (): void => {
  try {
    localStorage.removeItem(STORAGE_KEY_RECOVERY);
  } catch {}
};

interface AppProps {
  initialView?: AppView;
}

export const App: React.FC<AppProps> = ({ initialView }) => {
  // Global backend state
  const [health, setHealth] = useState<HealthStatus>({ status: 'connecting' });
  const [manifest, setManifest] = useState<CapabilitiesManifest | null>(null);
  const [isLoadingManifest, setIsLoadingManifest] = useState(true);
  const [hasApiKey, setHasApiKey] = useState(Boolean(getStoredApiKey()));
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [activeView, setActiveView] = useState<AppView>(() => {
    if (initialView) return initialView;
    if (typeof window !== 'undefined' && window.location?.search) {
      const params = new URLSearchParams(window.location.search);
      const v = params.get('view') as AppView;
      if (
        v === 'spatial' ||
        v === 'creator' ||
        v === 'pipelines' ||
        v === 'research' ||
        v === 'publishing' ||
        v === 'learning'
      ) {
        return v;
      }
    }
    return 'creator';
  });

  // Form State
  const [generationType, setGenerationType] = useState<GenerationType>('image');
  const [prompt, setPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedAspectRatio, setSelectedAspectRatio] = useState('16:9');
  const [selectedResolution, setSelectedResolution] = useState('1024x1024');
  const [selectedDuration, setSelectedDuration] = useState(5);
  const [referenceImageUrl, setReferenceImageUrl] = useState<string | undefined>();
  const [startFrameUrl, setStartFrameUrl] = useState<string | undefined>();
  const [endFrameUrl, setEndFrameUrl] = useState<string | undefined>();

  // Execution & Job State
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentJob, setCurrentJob] = useState<GenerationJob | null>(null);
  const [isActiveGeneration, setIsActiveGeneration] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // History State
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);

  // Stage 10: Multi-Shot Production Timeline State
  const [project, setProject] = useState<Project>(() => createDefaultProject(null));

  // Phase 8: Persistent Production API and Synchronization State
  const [persistenceSyncStatus, setPersistenceSyncStatus] = useState<PersistenceSyncStatus>('ONLINE');
  const activeRemoteJobIdRef = useRef<string | null>(null);

  // Stage 11: Project Persistence and Recovery State
  const [recoveryState, setRecoveryState] = useState<ProjectRecoveryState>('NEW');
  const [persistedEnvelope, setPersistedEnvelope] = useState<PersistedProjectEnvelope | null>(null);
  const [projectStatus, setProjectStatus] = useState<'NEW' | 'SAVED' | 'UNSAVED' | 'RECOVERED'>('NEW');
  const isInitialProjectMountRef = useRef<boolean>(true);

  // Parameter snapshot for active job (immutable, unaffected by subsequent form edits)
  const activeJobSnapshotRef = useRef<CreatorGeneratePayload | null>(null);

  // Polling, Sequence, and Lifecycle Refs
  const pollIntervalRef = useRef<any>(null);
  const activePollingJobIdRef = useRef<string | null>(null);
  const pollErrorCountRef = useRef<number>(0);
  const generationSeqRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const isSubmittingRef = useRef<boolean>(false);

  // Stop polling helper
  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    activePollingJobIdRef.current = null;
    pollErrorCountRef.current = 0;
  };

  // 1. Initial Load: Health, Capabilities, Persistent History, Workspace Recovery, and Remote Project DB
  useEffect(() => {
    isMountedRef.current = true;

    loadHealth();
    loadCapabilities();
    loadHistory();
    checkAndRecoverWorkspace();

    // Phase 8: Initialize Persistent Project from PostgreSQL API with graceful offline fallback
    const initPersistentProject = async () => {
      try {
        const isHealthy = await checkProductionApiHealth();
        if (!isHealthy) {
          throw new Error('Persistent API unavailable');
        }
        if (!isMountedRef.current) return;
        setPersistenceSyncStatus('ONLINE');
        const projects = await listProjects();
        if (projects.length > 0) {
          const tree = await getProjectTree(projects[0].id);
          const mappedProject = projectFromRemoteTree(tree);
          if (isMountedRef.current) {
            setProject(mappedProject);
            setProjectStatus('SAVED');
            setRecoveryState('SAVED');
          }
        } else {
          // Initialize remote project from default
          const defaultProj = createDefaultProject(null);
          const created = await createRemoteProject(defaultProj.title, defaultProj.description);
          const seq = defaultProj.sequences[0];
          if (seq) {
            for (const shot of seq.shots) {
              await createRemoteShot(created.id, {
                sequence_id: created.sequences?.[0]?.id || created.id,
                shot_number: shot.order,
                title: shot.title,
                prompt: shot.prompt,
                model: shot.selectedModel,
                provider: shot.selectedProvider || 'together',
                aspect_ratio: shot.aspectRatio,
                duration: shot.duration,
              }).catch(() => {});
            }
          }
          const tree = await getProjectTree(created.id);
          const mappedProject = projectFromRemoteTree(tree);
          if (isMountedRef.current) {
            setProject(mappedProject);
            setProjectStatus('SAVED');
            setRecoveryState('SAVED');
          }
        }
      } catch (err) {
        console.warn('Persistent API fallback to local cache:', err);
        if (isMountedRef.current) {
          setPersistenceSyncStatus('OFFLINE');
          if (hasPersistedProject()) {
            const envelope = getPersistedProjectEnvelope();
            if (envelope) {
              setPersistedEnvelope(envelope);
              const interrupted = checkForInterruptedShots(envelope.project);
              setRecoveryState(interrupted.hasInterrupted ? 'RECOVERY_REQUIRED' : 'RECOVERABLE');
              setProjectStatus('SAVED');
            }
          }
        }
      }
    };

    initPersistentProject();

    const healthInterval = setInterval(loadHealth, 15000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && activePollingJobIdRef.current) {
        const jobId = activePollingJobIdRef.current;
        const seq = generationSeqRef.current;
        pollJobStatus(jobId)
          .then((updatedJob) => {
            if (!isMountedRef.current || generationSeqRef.current !== seq || activePollingJobIdRef.current !== jobId) {
              return;
            }
            pollErrorCountRef.current = 0;
            setCurrentJob(updatedJob);
            if (updatedJob.status === 'completed') {
              stopPolling();
              clearJobRecovery();
              loadHistory();
            } else if (updatedJob.status === 'failed') {
              stopPolling();
              clearJobRecovery();
            }
          })
          .catch((err) => {
            console.warn('Visibility poll notice:', err);
          });
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      isMountedRef.current = false;
      clearInterval(healthInterval);
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const loadHealth = async () => {
    const res = await checkBackendHealth();
    if (isMountedRef.current) {
      setHealth(res);
    }
  };

  const loadCapabilities = async () => {
    setIsLoadingManifest(true);
    try {
      const data = await fetchCapabilities();
      if (!isMountedRef.current) return;
      setManifest(data);
      setSelectedModel((prev) => {
        if (!prev) {
          const defaultModel =
            data.models[generationType]?.find((m) => m.configured && m.default) ||
            data.models[generationType]?.find((m) => m.configured) ||
            data.models[generationType]?.find((m) => m.default) ||
            data.models[generationType]?.[0];
          return defaultModel ? defaultModel.id : '';
        }
        // Section 15: Preserve user-entered model parameter; do not auto-switch models on refresh!
        return prev;
      });
    } catch (err: any) {
      console.warn('Capabilities fetch notice:', err.message);
    } finally {
      if (isMountedRef.current) {
        setIsLoadingManifest(false);
      }
    }
  };

  const loadHistory = async () => {
    try {
      const data = await fetchHistory();
      if (!isMountedRef.current) return;
      setHistory(data);
    } catch (err: any) {
      console.warn('History fetch notice:', err.message);
    } finally {
      if (isMountedRef.current) {
        setIsLoadingHistory(false);
        setIsRefreshingHistory(false);
      }
    }
  };

  const handleRefreshHistory = () => {
    setIsRefreshingHistory(true);
    loadHistory();
  };

  // Stage 7: Operational Reconcile
  const handleOperationalRefresh = async () => {
    setIsReconciling(true);
    try {
      await Promise.allSettled([
        loadHealth(),
        loadCapabilities(),
        loadHistory(),
        activePollingJobIdRef.current
          ? pollJobStatus(activePollingJobIdRef.current)
              .then((job) => {
                if (isMountedRef.current) setCurrentJob(job);
              })
              .catch(() => {})
          : Promise.resolve(),
      ]);
    } finally {
      if (isMountedRef.current) {
        setIsReconciling(false);
      }
    }
  };

  // Safe Workspace Recovery: Reconnects to in-flight or completed backend jobs after page reload
  const checkAndRecoverWorkspace = async () => {
    const recovery = getJobRecovery();
    if (!recovery || !recovery.jobId) return;

    // Prune stale records older than 30 minutes
    const ageMs = Date.now() - (recovery.submittedAt || 0);
    if (ageMs > 30 * 60 * 1000) {
      clearJobRecovery();
      return;
    }

    const startSeq = generationSeqRef.current;

    if (recovery.payloadSnapshot) {
      activeJobSnapshotRef.current = recovery.payloadSnapshot;
    }

    try {
      const job = await pollJobStatus(recovery.jobId);
      if (!isMountedRef.current || generationSeqRef.current !== startSeq || isSubmittingRef.current) {
        return;
      }

      if (job.status === 'pending' || job.status === 'in_progress') {
        setCurrentJob(job);
        setIsActiveGeneration(true);
        if (job.generation_type) {
          setGenerationType(job.generation_type);
        }
        startPollingJob(job.job_id, startSeq);
      } else if (job.status === 'completed' || job.status === 'failed') {
        setCurrentJob(job);
        setIsActiveGeneration(true);
        if (job.generation_type) {
          setGenerationType(job.generation_type);
        }
        clearJobRecovery();
      }
    } catch (err: any) {
      // Safe fallback: If backend cannot confirm the job (e.g. 404 or restarted), clear record
      console.warn('Workspace recovery verification notice:', err.message);
      clearJobRecovery();
    }
  };

  // Stage 10: Multi-Shot Production Timeline & Story Continuity Control Plane
  useEffect(() => {
    if (!manifest) return;
    setProject((prevProj) => {
      const updatedSequences = prevProj.sequences.map((seq) => {
        const validatedShots = seq.shots.map((shot) =>
          validateShot(shot, seq.shots, manifest)
        );
        const evalSeq = evaluateSequenceReadiness(validatedShots);
        return {
          ...seq,
          shots: validatedShots,
          status: evalSeq.status,
          statusReasons: evalSeq.statusReasons,
          totalShots: evalSeq.metrics.total,
          readyShots: evalSeq.metrics.ready,
          blockedShots: evalSeq.metrics.blocked,
          inFlightShots: evalSeq.metrics.inFlight,
          completeShots: evalSeq.metrics.complete,
        };
      });
      return {
        ...prevProj,
        sequences: updatedSequences,
      };
    });
  }, [manifest]);

  const activeSequence = useMemo(
    () => project.sequences.find((s) => s.id === project.activeSequenceId) || project.sequences[0],
    [project]
  );

  const sequenceSummary: SequenceOperationalSummary | undefined = useMemo(() => {
    if (!activeSequence) return undefined;
    return {
      sequenceNumber: String(activeSequence.order).padStart(2, '0'),
      sequenceTitle: activeSequence.title,
      totalShots: activeSequence.totalShots,
      readyShots: activeSequence.readyShots,
      blockedShots: activeSequence.blockedShots,
      inFlightShots: activeSequence.inFlightShots,
      completeShots: activeSequence.completeShots,
    };
  }, [activeSequence]);

  const updateActiveShotOnJobResult = (
    status: 'COMPLETE' | 'FAILED',
    jobResult?: GenerationJob
  ) => {
    setProject((prevProj) => {
      if (!prevProj.activeShotId) return prevProj;
      const updatedSequences = prevProj.sequences.map((seq) => {
        const shotExists = seq.shots.some((s) => s.id === prevProj.activeShotId);
        if (!shotExists) return seq;

        const updatedShots = seq.shots.map((s) => {
          if (s.id !== prevProj.activeShotId) return s;
          if (status === 'COMPLETE') {
            const assetUrl = jobResult?.output?.asset_url || jobResult?.output?.storage_path;
            return {
              ...s,
              status: 'COMPLETE' as const,
              readiness: 'READY' as const,
              outputAssetUrl: assetUrl,
              outputJobId: jobResult?.job_id,
            };
          } else {
            return {
              ...s,
              status: 'FAILED' as const,
              failureDetails: {
                category: 'PROVIDER',
                stage: 'EXECUTION',
                reason: jobResult?.failure_reason || 'Generation execution failed',
                retryEligible: true,
              },
            };
          }
        });

        const validated = updatedShots.map((s) => validateShot(s, updatedShots, manifest));
        const evalSeq = evaluateSequenceReadiness(validated);

        return {
          ...seq,
          shots: validated,
          status: evalSeq.status,
          statusReasons: evalSeq.statusReasons,
          totalShots: evalSeq.metrics.total,
          readyShots: evalSeq.metrics.ready,
          blockedShots: evalSeq.metrics.blocked,
          inFlightShots: evalSeq.metrics.inFlight,
          completeShots: evalSeq.metrics.complete,
        };
      });

      return {
        ...prevProj,
        sequences: updatedSequences,
      };
    });
  };

  const handleSelectShot = (shot: Shot) => {
    const isJobRunning = Boolean(
      currentJob && (currentJob.status === 'pending' || currentJob.status === 'in_progress')
    );
    if (activePollingJobIdRef.current || isSubmitting || isJobRunning) {
      return;
    }

    setProject((prev) => ({
      ...prev,
      activeShotId: shot.id,
    }));

    setGenerationType(shot.generationType);
    setPrompt(shot.prompt);
    setSelectedModel(shot.selectedModel);
    setSelectedAspectRatio(shot.aspectRatio);
    if (shot.resolution) setSelectedResolution(shot.resolution);
    if (shot.duration) setSelectedDuration(shot.duration);
    setStartFrameUrl(shot.startFrame || '');
    setEndFrameUrl(shot.endFrame || '');
    setReferenceImageUrl(shot.referenceAssets?.[0] || '');
  };

  const handleReproduceShot = (shot: Shot) => {
    const params = reproduceShotToConsole(shot);
    setGenerationType(params.generationType);
    setPrompt(params.prompt);
    setSelectedModel(params.selectedModel);
    setSelectedAspectRatio(params.selectedAspectRatio);
    if (params.selectedResolution) setSelectedResolution(params.selectedResolution);
    if (params.selectedDuration) setSelectedDuration(params.selectedDuration);
    setStartFrameUrl(params.startFrameUrl || '');
    setEndFrameUrl(params.endFrameUrl || '');
    setReferenceImageUrl(params.referenceImageUrl || '');
  };

  const handleReorderShots = (sourceIndex: number, targetIndex: number) => {
    if (!activeSequence) return;
    const reordered = reorderShots(activeSequence.shots, sourceIndex, targetIndex, manifest);
    const evalSeq = evaluateSequenceReadiness(reordered);

    setProject((prev) => ({
      ...prev,
      sequences: prev.sequences.map((seq) =>
        seq.id === activeSequence.id
          ? {
              ...seq,
              shots: reordered,
              status: evalSeq.status,
              statusReasons: evalSeq.statusReasons,
              totalShots: evalSeq.metrics.total,
              readyShots: evalSeq.metrics.ready,
              blockedShots: evalSeq.metrics.blocked,
              inFlightShots: evalSeq.metrics.inFlight,
              completeShots: evalSeq.metrics.complete,
            }
          : seq
      ),
    }));
  };

  const handleAddShot = () => {
    if (!activeSequence) return;
    const nextOrder = activeSequence.shots.length + 1;
    const defaultModel =
      manifest?.models.image.find((m) => m.default)?.id ||
      manifest?.models.image[0]?.id ||
      'black-forest-labs/FLUX.1.1-pro';

    const newShot: Shot = {
      id: `shot-${String(Date.now()).slice(-4)}`,
      sequenceId: activeSequence.id,
      order: nextOrder,
      title: `Shot ${String(nextOrder).padStart(2, '0')} // Sequence Shot`,
      prompt: 'Cinematic composition, atmospheric lighting',
      generationType: 'image',
      selectedModel: defaultModel,
      selectedProvider: 'together',
      aspectRatio: '16:9',
      dependencyShotIds: [],
      referenceAssets: [],
      status: 'READY',
      readiness: 'READY',
      provenance: 'USER_CONFIGURATION',
      validationResults: {
        isValid: true,
        readiness: 'READY',
        reasons: ['READY FOR EXECUTION'],
        reasonCodes: ['READY'],
        preflightReady: true,
        dependenciesSatisfied: true,
        startFrameSatisfied: true,
      },
      continuityReport: {
        character: { status: 'UNAVAILABLE', detail: 'CHARACTER CONTINUITY: UNAVAILABLE', source: 'UNAVAILABLE' },
        environment: { status: 'UNAVAILABLE', detail: 'ENVIRONMENT CONTINUITY: UNAVAILABLE', source: 'UNAVAILABLE' },
        visual: { status: 'PASS', detail: 'Visual format declared (16:9)', source: 'USER_CONFIGURATION' },
        temporal: { status: 'PASS', detail: `Temporal sequence ordering valid (Shot #${nextOrder})`, source: 'USER_CONFIGURATION' },
        startFrame: { status: 'NOT_APPLICABLE', detail: 'START FRAME NOT APPLICABLE FOR CURRENT MODE', source: 'CAPABILITY_MANIFEST' },
      },
    };

    const updatedShots = [...activeSequence.shots, newShot];
    const validatedShots = updatedShots.map((s) => validateShot(s, updatedShots, manifest));
    const evalSeq = evaluateSequenceReadiness(validatedShots);

    setProject((prev) => ({
      ...prev,
      sequences: prev.sequences.map((seq) =>
        seq.id === activeSequence.id
          ? {
              ...seq,
              shots: validatedShots,
              status: evalSeq.status,
              statusReasons: evalSeq.statusReasons,
              totalShots: evalSeq.metrics.total,
              readyShots: evalSeq.metrics.ready,
              blockedShots: evalSeq.metrics.blocked,
              inFlightShots: evalSeq.metrics.inFlight,
              completeShots: evalSeq.metrics.complete,
            }
          : seq
      ),
    }));
  };

  const handleLinkPredecessor = (targetShotId: string, sourceShotId: string) => {
    if (!activeSequence) return;
    const linked = linkPredecessorStartFrame(targetShotId, sourceShotId, activeSequence.shots, manifest);
    const evalSeq = evaluateSequenceReadiness(linked);

    setProject((prev) => ({
      ...prev,
      sequences: prev.sequences.map((seq) =>
        seq.id === activeSequence.id
          ? {
              ...seq,
              shots: linked,
              status: evalSeq.status,
              statusReasons: evalSeq.statusReasons,
              totalShots: evalSeq.metrics.total,
              readyShots: evalSeq.metrics.ready,
              blockedShots: evalSeq.metrics.blocked,
              inFlightShots: evalSeq.metrics.inFlight,
              completeShots: evalSeq.metrics.complete,
            }
          : seq
      ),
    }));
  };

  const handleDuplicateShot = (shot: Shot) => {
    if (!activeSequence) return;
    const duplicated = duplicateShot(activeSequence.shots, shot.id, manifest);
    const evalSeq = evaluateSequenceReadiness(duplicated);

    setProject((prev) => ({
      ...prev,
      sequences: prev.sequences.map((seq) =>
        seq.id === activeSequence.id
          ? {
              ...seq,
              shots: duplicated,
              status: evalSeq.status,
              statusReasons: evalSeq.statusReasons,
              totalShots: evalSeq.metrics.total,
              readyShots: evalSeq.metrics.ready,
              blockedShots: evalSeq.metrics.blocked,
              inFlightShots: evalSeq.metrics.inFlight,
              completeShots: evalSeq.metrics.complete,
            }
          : seq
      ),
    }));
  };

  const handleRemoveShot = (shotId: string) => {
    if (!activeSequence) return;
    const filtered = removeShot(activeSequence.shots, shotId, manifest);
    const evalSeq = evaluateSequenceReadiness(filtered);

    setProject((prev) => ({
      ...prev,
      activeShotId: prev.activeShotId === shotId ? undefined : prev.activeShotId,
      sequences: prev.sequences.map((seq) =>
        seq.id === activeSequence.id
          ? {
              ...seq,
              shots: filtered,
              status: evalSeq.status,
              statusReasons: evalSeq.statusReasons,
              totalShots: evalSeq.metrics.total,
              readyShots: evalSeq.metrics.ready,
              blockedShots: evalSeq.metrics.blocked,
              inFlightShots: evalSeq.metrics.inFlight,
              completeShots: evalSeq.metrics.complete,
            }
          : seq
      ),
    }));
  };

  // Stage 11: Project Restoration and Discard Handlers
  const handleRestoreProject = () => {
    const loaded = loadProject();
    if (loaded) {
      const recomputed = recomputeDerivedState(loaded, manifest);
      const reconciled = reconcileProjectWithHistory(recomputed, history);
      setProject(reconciled);
      setRecoveryState('RESTORED');
      setProjectStatus('RECOVERED');
    }
  };

  const handleDiscardProject = () => {
    clearProject();
    setRecoveryState('NEW');
    setPersistedEnvelope(null);
    setProjectStatus('NEW');
  };

  const handleReviewInterruptedShots = () => {
    if (!project || !project.sequences) return;
    for (const seq of project.sequences) {
      for (const shot of seq.shots) {
        if (shot.status === 'RECOVERY_REQUIRED') {
          handleSelectShot(shot);
          return;
        }
      }
    }
  };

  // Stage 11: Auto-persist production intent on project mutations
  useEffect(() => {
    if (isInitialProjectMountRef.current) {
      isInitialProjectMountRef.current = false;
      return;
    }
    saveProject(project);
    setProjectStatus('SAVED');
  }, [project]);

  // Phase 8 & 9: Subscribe to real-time project telemetry SSE
  useEffect(() => {
    if (!project?.id || persistenceSyncStatus !== 'ONLINE') return;
    const unsubscribe = subscribeToProjectTelemetry(project.id, (event) => {
      const evtType = event.event_type;
      const data = event.data || event.payload || {};
      const targetShotId = event.shot_id || data.shot_id;
      const targetJobId = event.job_id || data.job_id;

      // 1. Update active currentJob state
      if (evtType === 'JOB_SUBMITTED') {
        setCurrentJob((prev) => ({
          job_id: targetJobId || prev?.job_id || 'active-job',
          status: 'pending',
          current_stage: 'SUBMITTED TO OPENMONTAGE',
          progress: 5,
          total_cost_usd: prev?.total_cost_usd || 0,
          created_at: event.timestamp,
          generation_type: prev?.generation_type || ('image' as any),
          model: data.model || prev?.model,
          prompt: prev?.prompt || '',
        }));
      } else if (evtType === 'JOB_STARTED') {
        setCurrentJob((prev) => ({
          job_id: targetJobId || prev?.job_id || 'active-job',
          status: 'in_progress',
          current_stage: 'EXECUTION IN FLIGHT',
          progress: 20,
          total_cost_usd: prev?.total_cost_usd || 0,
          created_at: prev?.created_at || event.timestamp,
          generation_type: prev?.generation_type || ('image' as any),
          model: prev?.model,
          prompt: prev?.prompt || '',
        }));
      } else if (evtType === 'JOB_PROGRESS') {
        setCurrentJob((prev) =>
          prev
            ? {
                ...prev,
                progress: typeof data.progress === 'number' ? Math.round(data.progress * 100) : prev.progress,
                current_stage: data.message || 'PROCESSING VIA OPENMONTAGE',
              }
            : null
        );
      } else if (evtType === 'JOB_COMPLETED') {
        setCurrentJob((prev) =>
          prev
            ? {
                ...prev,
                status: 'completed',
                progress: 100,
                current_stage: 'GENERATION COMPLETE',
                output_url: data.artifact_url || prev.output_url,
              }
            : null
        );
        loadHistory();
      } else if (evtType === 'JOB_FAILED') {
        setCurrentJob((prev) =>
          prev
            ? {
                ...prev,
                status: 'failed',
                progress: 0,
                error_message: data.error || 'OpenMontage execution failed',
                current_stage: 'FAILED',
              }
            : null
        );
      }

      // 2. Synchronize target Production Shot in project state
      if (targetShotId) {
        setProject((prev) => ({
          ...prev,
          sequences: prev.sequences.map((seq) => ({
            ...seq,
            shots: seq.shots.map((s) => {
              if (s.id !== targetShotId) return s;

              let nextStatus = s.status;
              let nextAssetUrl = s.outputAssetUrl;

              if (evtType === 'JOB_QUEUED' || evtType === 'JOB_SUBMITTED') {
                nextStatus = 'QUEUED';
              } else if (evtType === 'JOB_STARTED' || evtType === 'JOB_PROGRESS') {
                nextStatus = 'GENERATING';
              } else if (evtType === 'JOB_COMPLETED') {
                nextStatus = 'COMPLETE';
                if (data.artifact_url) nextAssetUrl = data.artifact_url;
              } else if (evtType === 'JOB_FAILED') {
                nextStatus = 'FAILED';
              } else if (evtType === 'ARTIFACT_READY' && data.artifact_url) {
                nextAssetUrl = data.artifact_url;
              } else if (evtType === 'SHOT_UPDATED') {
                if (data.status) nextStatus = data.status;
                if (data.output_asset_url) nextAssetUrl = data.output_asset_url;
              } else if (evtType === 'JOB_STATUS_CHANGED' && data.job) {
                const rj = data.job;
                nextStatus =
                  rj.status === 'COMPLETED'
                    ? 'COMPLETE'
                    : rj.status === 'FAILED'
                    ? 'FAILED'
                    : rj.status === 'RUNNING'
                    ? 'GENERATING'
                    : rj.status === 'QUEUED'
                    ? 'QUEUED'
                    : s.status;
                if (rj.output_asset_url) nextAssetUrl = rj.output_asset_url;
              }

              return {
                ...s,
                status: nextStatus,
                outputAssetUrl: nextAssetUrl,
              };
            }),
          })),
        }));
      }
    });
    return unsubscribe;
  }, [project?.id, persistenceSyncStatus]);

  // When generation type changes, re-sync model selection
  const handleTypeChange = (type: GenerationType) => {
    setGenerationType(type);
    setError(null);
    setValidationError(null);
    if (manifest?.models?.[type]?.length) {
      const defaultModel = manifest.models[type].find((m) => m.default) || manifest.models[type][0];
      setSelectedModel(defaultModel.id);
    }
  };

  // Active Model Object & Capabilities
  const currentModels = manifest?.models?.[generationType] || [];
  const selectedModelObj = currentModels.find((m) => m.id === selectedModel);

  // Hardened Asynchronous Job Polling Engine
  const startPollingJob = (jobId: string, seq?: number) => {
    stopPolling();
    activePollingJobIdRef.current = jobId;
    const currentSeq = seq !== undefined ? seq : generationSeqRef.current;

    pollIntervalRef.current = setInterval(async () => {
      // Guard: unmounted or superseded by newer generation
      if (!isMountedRef.current || currentSeq !== generationSeqRef.current || activePollingJobIdRef.current !== jobId) {
        stopPolling();
        return;
      }

      try {
        const updatedJob = await pollJobStatus(jobId);

        // Guard against race condition / stale poll tick
        if (!isMountedRef.current || currentSeq !== generationSeqRef.current || activePollingJobIdRef.current !== jobId) {
          return;
        }

        pollErrorCountRef.current = 0;
        setCurrentJob(updatedJob);

        if (updatedJob.status === 'in_progress') {
          if (activeRemoteJobIdRef.current) {
            updateRemoteJobStatus(activeRemoteJobIdRef.current, {
              status: 'RUNNING',
              progress: 0.5,
            }).catch(() => {});
          }
        } else if (updatedJob.status === 'completed') {
          stopPolling();
          clearJobRecovery();
          loadHistory();
          updateActiveShotOnJobResult('COMPLETE', updatedJob);
          if (activeRemoteJobIdRef.current) {
            updateRemoteJobStatus(activeRemoteJobIdRef.current, {
              status: 'COMPLETED',
              progress: 1.0,
              output_asset_url: updatedJob.output?.asset_url || updatedJob.output?.storage_path,
            }).catch(() => {});
            activeRemoteJobIdRef.current = null;
          }
        } else if (updatedJob.status === 'failed') {
          stopPolling();
          clearJobRecovery();
          updateActiveShotOnJobResult('FAILED', updatedJob);
          if (activeRemoteJobIdRef.current) {
            updateRemoteJobStatus(activeRemoteJobIdRef.current, {
              status: 'FAILED',
              error_message: updatedJob.failure_reason,
            }).catch(() => {});
            activeRemoteJobIdRef.current = null;
          }
        }
      } catch (err: any) {
        if (!isMountedRef.current || currentSeq !== generationSeqRef.current || activePollingJobIdRef.current !== jobId) {
          return;
        }

        pollErrorCountRef.current += 1;
        const msg = err?.message || String(err);

        // Classification D: Job not found on backend (404)
        if (msg.includes('not found') || msg.includes('404')) {
          stopPolling();
          clearJobRecovery();
          setError(`Generation job ${jobId} not found on server.`);
          setCurrentJob((prev) =>
            prev && prev.job_id === jobId
              ? { ...prev, status: 'failed', failure_reason: `Job ${jobId} not found on server` }
              : prev
          );
          return;
        }

        // Classification C: Bounded temporary network/polling failure (5 consecutive)
        if (pollErrorCountRef.current >= 5) {
          stopPolling();
          clearJobRecovery();
          setError('Polling connection lost. Backend unreachable after repeated attempts.');
          setCurrentJob((prev) =>
            prev && prev.job_id === jobId
              ? { ...prev, status: 'failed', failure_reason: 'Network polling timeout: backend unreachable' }
              : prev
          );
        } else {
          // Transient failure: keep active job, do not destroy state
          console.warn(`Temporary polling hiccup (attempt ${pollErrorCountRef.current}/5):`, msg);
        }
      }
    }, 2000);
  };

  // Execution Worker with Parameter Snapshot and Duplicate Submission Protection
  const executeGeneration = async (payloadToSubmit: CreatorGeneratePayload) => {
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setIsSubmitting(true);
    setError(null);
    setValidationError(null);
    setCurrentJob(null);
    setIsActiveGeneration(true);
    if (project.activeShotId) {
      setProject((prevProj) => ({
        ...prevProj,
        sequences: prevProj.sequences.map((seq) => ({
          ...seq,
          shots: seq.shots.map((s) =>
            s.id === prevProj.activeShotId ? { ...s, status: 'GENERATING' as const } : s
          ),
        })),
      }));
    }

    // Cancel existing polling before starting new generation
    stopPolling();
    const currentSeq = ++generationSeqRef.current;

    try {
      const job = await submitGeneration(payloadToSubmit);
      if (!isMountedRef.current || currentSeq !== generationSeqRef.current) return;

      if (job.status === 'completed' || job.status === 'failed') {
        clearJobRecovery();
      } else {
        // Persist lightweight recovery record
        saveJobRecovery({
          jobId: job.job_id,
          generationType: payloadToSubmit.generation_type,
          submittedAt: Date.now(),
          payloadSnapshot: payloadToSubmit,
        });
      }

      setCurrentJob(job);
      setIsActiveGeneration(true);
      if (job.status !== 'completed' && job.status !== 'failed') {
        startPollingJob(job.job_id, currentSeq);
      } else if (job.status === 'completed') {
        loadHistory();
        updateActiveShotOnJobResult('COMPLETE', job);
        if (activeRemoteJobIdRef.current) {
          updateRemoteJobStatus(activeRemoteJobIdRef.current, {
            status: 'COMPLETED',
            progress: 1.0,
            output_asset_url: job.output?.asset_url || job.output?.storage_path,
          }).catch(() => {});
          activeRemoteJobIdRef.current = null;
        }
      } else if (job.status === 'failed') {
        updateActiveShotOnJobResult('FAILED', job);
        if (activeRemoteJobIdRef.current) {
          updateRemoteJobStatus(activeRemoteJobIdRef.current, {
            status: 'FAILED',
            error_message: job.failure_reason,
          }).catch(() => {});
          activeRemoteJobIdRef.current = null;
        }
      }
    } catch (err: any) {
      if (!isMountedRef.current || currentSeq !== generationSeqRef.current) return;
      setError(err.message || 'Generation submission failed');
      setCurrentJob(null);
      setIsActiveGeneration(false);
      updateActiveShotOnJobResult('FAILED', undefined);
      if (activeRemoteJobIdRef.current) {
        updateRemoteJobStatus(activeRemoteJobIdRef.current, {
          status: 'FAILED',
          error_message: err.message,
        }).catch(() => {});
        activeRemoteJobIdRef.current = null;
      }
    } finally {
      if (isMountedRef.current && currentSeq === generationSeqRef.current) {
        setIsSubmitting(false);
      }
      isSubmittingRef.current = false;
    }
  };

  // Job Submission Handler
  const handleGenerate = () => {
    setError(null);
    setValidationError(null);

    // Prevent duplicate submissions while job is running or submitting
    const isJobRunning = Boolean(
      currentJob && (currentJob.status === 'in_progress' || currentJob.status === 'pending')
    );
    if (isSubmitting || isSubmittingRef.current || isJobRunning) {
      return;
    }

    // Validation 1: Prompt
    if (!prompt.trim()) {
      setValidationError('Please enter a prompt describing your desired generation.');
      return;
    }

    // Validation 2: Image-to-Video requires start frame
    if (generationType === 'image_to_video' && !startFrameUrl && !referenceImageUrl) {
      setValidationError('Image → Video generation requires a start frame image.');
      return;
    }

    // Validation 3: Stage 8 Pre-flight capability constraints
    if (!productionRecommendation.preflight.ready) {
      setValidationError(
        productionRecommendation.preflight.reason || 'Execution blocked by configuration constraints.'
      );
      return;
    }

    // Immutable parameter snapshot matching the actual backend payload
    const payload: CreatorGeneratePayload = Object.freeze({
      generation_type: generationType,
      prompt: prompt.trim(),
      model: selectedModel,
      provider: selectedModelObj?.provider,
      aspect_ratio: selectedAspectRatio,
      resolution: selectedResolution,
      duration_seconds: generationType !== 'image' ? selectedDuration : undefined,
      start_frame_url: startFrameUrl || referenceImageUrl,
      end_frame_url: endFrameUrl,
      reference_image_url: referenceImageUrl,
    });

    activeJobSnapshotRef.current = payload;
    executeGeneration(payload);
  };

  // Parameter-preserving Retry Handler
  const handleRetry = () => {
    setError(null);
    setValidationError(null);
    const snapshot = activeJobSnapshotRef.current;
    if (snapshot) {
      executeGeneration(snapshot);
    } else {
      handleGenerate();
    }
  };

  // History Selection Handler: loads selected history item into Creative Viewport
  const handleSelectHistoryItem = (item: HistoryItem) => {
    // Stage 7: If a generation is currently active/running, do NOT alter active generation state!
    const isJobRunning = Boolean(currentJob && (currentJob.status === 'pending' || currentJob.status === 'in_progress'));
    if (activePollingJobIdRef.current || isSubmitting || isJobRunning) {
      return;
    }
    setIsActiveGeneration(false);
    setCurrentJob({
      job_id: item.job_id,
      workflow_run_id: item.workflow_run_id,
      status: item.status,
      generation_type: item.generation_type,
      prompt: item.prompt,
      model: item.model,
      provider: item.provider,
      aspect_ratio: item.aspect_ratio,
      duration_seconds: item.duration_seconds,
      total_cost_usd: item.total_cost_usd,
      requested_model: item.requested_model,
      requested_provider: item.requested_provider,
      actual_model: item.actual_model,
      actual_provider: item.actual_provider,
      output: {
        asset_url: item.asset_url,
        storage_path: item.asset_url,
        aspect_ratio: item.aspect_ratio,
        duration_seconds: item.duration_seconds,
      },
    });
  };

  // Stage 6: Run Reproduction Handler (restores parameters to console WITHOUT executing)
  const handleReproduce = (run: ProductionRun) => {
    setGenerationType(run.mode);
    setPrompt(run.prompt);
    if (run.model) {
      setSelectedModel(run.model);
    }
    if (run.parameters.aspectRatio) {
      setSelectedAspectRatio(run.parameters.aspectRatio);
    }
    if (run.parameters.resolution) {
      setSelectedResolution(run.parameters.resolution);
    }
    if (run.parameters.durationSeconds) {
      setSelectedDuration(run.parameters.durationSeconds);
    }
    if (run.parameters.referenceImageUrl) {
      setReferenceImageUrl(run.parameters.referenceImageUrl);
    } else if (run.referenceAsset) {
      setReferenceImageUrl(run.referenceAsset);
    }
    if (run.parameters.startFrameUrl) {
      setStartFrameUrl(run.parameters.startFrameUrl);
    } else if (run.startFrame) {
      setStartFrameUrl(run.startFrame);
    }
    if (run.parameters.endFrameUrl) {
      setEndFrameUrl(run.parameters.endFrameUrl);
    }

    // Clear previous submission errors
    setError(null);
    setValidationError(null);
  };

  // Active Display Telemetry (immune to subsequent form edits while job is active)
  const activeModelName =
    currentJob && (currentJob.status === 'pending' || currentJob.status === 'in_progress')
      ? currentJob.model || selectedModelObj?.name || selectedModel
      : selectedModelObj?.name || selectedModel;

  const activePrompt =
    currentJob && (currentJob.status === 'pending' || currentJob.status === 'in_progress' || currentJob.status === 'completed')
      ? currentJob.prompt || prompt
      : prompt;

  // Derive Command Core State
  const commandCoreState: CommandCoreState = (() => {
    if ((error && !isSubmitting) || (currentJob && currentJob.status === 'failed')) {
      return 'error';
    }
    if (isSubmitting || (currentJob && currentJob.status === 'pending')) {
      return 'generating';
    }
    if (currentJob && currentJob.status === 'in_progress') {
      return 'processing';
    }
    if (currentJob && currentJob.status === 'completed' && isActiveGeneration) {
      return 'complete';
    }
    if (prompt.trim().length > 0) {
      if (generationType === 'image_to_video' && !startFrameUrl && !referenceImageUrl) {
        return 'configuring';
      }
      return 'ready';
    }
    if (referenceImageUrl || startFrameUrl || endFrameUrl || prompt.length > 0) {
      return 'configuring';
    }
    return 'idle';
  })();

  // Stage 7: Operational Metrics and System State Derivation (truthful, non-fabricated)
  const isJobActive = isSubmitting || Boolean(currentJob && (currentJob.status === 'pending' || currentJob.status === 'in_progress'));

  const systemOperationalState: SystemOperationalState = deriveSystemState(
    health.status,
    isSubmitting,
    currentJob?.status,
    error,
    pollErrorCountRef.current
  );

  const queuedRunsCount = (currentJob && currentJob.status === 'pending' ? 1 : 0) +
    history.filter((h) => h.status === 'pending').length;

  const processingRunsCount = (currentJob && currentJob.status === 'in_progress' ? 1 : 0) +
    history.filter((h) => h.status === 'in_progress').length;

  const failedRunsCount = (currentJob && currentJob.status === 'failed' ? 1 : 0) +
    history.filter((h) => h.status === 'failed').length;

  const activeRunsCount = (isJobActive ? 1 : 0) +
    history.filter((h) => h.status === 'pending' || h.status === 'in_progress').length;

  const totalCostUsd = history.reduce((acc, h) => acc + (h.total_cost_usd || 0), 0) +
    (currentJob?.total_cost_usd || 0);

  // Stage 8: Intelligent Production Decision Layer
  const configurationParams: ConfigurationParameters = useMemo(
    () => ({
      generationType,
      prompt: prompt.trim() || undefined,
      model: selectedModel,
      provider: selectedModelObj?.provider,
      aspectRatio: selectedAspectRatio,
      resolution: selectedResolution,
      duration: generationType !== 'image' ? selectedDuration : undefined,
      referenceImageUrl,
      startFrameUrl,
      endFrameUrl,
    }),
    [
      generationType,
      prompt,
      selectedModel,
      selectedModelObj,
      selectedAspectRatio,
      selectedResolution,
      selectedDuration,
      referenceImageUrl,
      startFrameUrl,
      endFrameUrl,
    ]
  );

  const productionRuns: ProductionRun[] = useMemo(
    () => history.map(historyItemToProductionRun),
    [history]
  );

  const productionRecommendation = useMemo(
    () =>
      deriveProductionRecommendation(
        configurationParams,
        manifest,
        systemOperationalState,
        productionRuns
      ),
    [configurationParams, manifest, systemOperationalState, productionRuns]
  );

  const handleOpenStudioWithShot = (shot: Shot | any) => {
    setActiveView('creator');
    if (shot.prompt) {
      setPrompt(shot.prompt);
    }
    if (shot.generationType) {
      setGenerationType(shot.generationType as GenerationType);
    }
    if (shot.selectedModel) {
      setSelectedModel(shot.selectedModel);
    } else if (shot.model) {
      setSelectedModel(shot.model);
    }
    if (shot.aspectRatio) {
      setSelectedAspectRatio(shot.aspectRatio);
    }
    if (shot.duration) {
      setSelectedDuration(shot.duration);
    }
  };

  return (
    <div className="app-container">
      {/* Cinematic Depth & Ambient Layer */}
      <AtmosphericBackground />

      <Header
        health={health}
        onOpenAuth={() => setIsAuthModalOpen(true)}
        hasApiKey={hasApiKey}
        onRefreshHistory={handleRefreshHistory}
        isRefreshingHistory={isRefreshingHistory}
        activeView={activeView}
        onViewChange={setActiveView}
      />

      <MotionViewWrapper viewKey={activeView} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {activeView === 'spatial' && (
          <main style={{ flex: 1, position: 'relative', width: '100%', minHeight: 'calc(100vh - 65px)', overflow: 'hidden' }}>
            <SpatialWorld
              project={project}
              activeShotId={project.activeShotId}
              onSelectShot={handleSelectShot}
              onOpenStudio={() => setActiveView('creator')}
              onOpenStudioWithShot={handleOpenStudioWithShot}
              currentJob={currentJob}
              productionRecommendation={productionRecommendation}
              systemOperationalState={systemOperationalState}
              historyCount={history.length}
              errorState={error || validationError || null}
              capabilitiesManifest={manifest}
              syncStatus={persistenceSyncStatus}
              onProjectChange={(updatedProject) => {
                setProject(updatedProject);
                // Also synchronize newly compiled shots to the database if online
                if (persistenceSyncStatus === 'ONLINE' && updatedProject.id) {
                  const seq = updatedProject.sequences.find((s) => s.id === updatedProject.activeSequenceId) || updatedProject.sequences[0];
                  if (seq) {
                    const latestShot = seq.shots[seq.shots.length - 1];
                    if (latestShot) {
                      createRemoteShot(updatedProject.id, {
                        sequence_id: seq.id,
                        shot_number: latestShot.order,
                        title: latestShot.title,
                        prompt: latestShot.prompt,
                        generation_type: latestShot.generationType,
                        model: latestShot.selectedModel,
                        provider: latestShot.selectedProvider || 'together',
                        aspect_ratio: latestShot.aspectRatio,
                        duration: latestShot.duration,
                        first_frame: latestShot.startFrame,
                        last_frame: latestShot.endFrame,
                        predecessor_shot_id: latestShot.predecessorShotId,
                      }).catch(() => {});
                    }
                  }
                }
              }}
              onDispatchExecution={async (pkg: AryaJobPackage) => {
                try {
                  if (persistenceSyncStatus === 'ONLINE' && project?.id) {
                    const remoteJob = await submitRemoteJobPackage(project.id, pkg, true);
                    activeRemoteJobIdRef.current = remoteJob.id;
                    setCurrentJob({
                      job_id: remoteJob.id,
                      status: 'pending',
                      current_stage: 'SUBMITTED TO OPENMONTAGE',
                      created_at: remoteJob.created_at,
                      generation_type: (pkg.plan.generationType || 'image') as any,
                      model: pkg.modelRoute.model,
                      prompt: pkg.plan.prompt,
                      total_cost_usd: 0,
                    });
                  } else {
                    await executeGeneration(pkg.executionPayload);
                  }
                } catch (e) {
                  console.warn('Remote job package submission fallback:', e);
                  await executeGeneration(pkg.executionPayload);
                }
              }}
            />
          </main>
        )}

        {activeView === 'creator' && (
          <>
            <main className="main-layout">
              {/* Left Column: Creator Form Controls */}
              <section aria-label="Creator Controls">
                <div className="creator-card console-panel">
                  {/* Console Header */}
                  <div className="console-panel-header">
                    <span className="console-panel-title">CONTROL CONSOLE</span>
                    <span className="console-panel-badge">PARAMETERS</span>
                  </div>

                  {/* 1. Generation Type Selection */}
                  <div className="console-section">
                    <div className="console-section-label">01 // GENERATION MODE</div>
                    <GenerationTypeSelector
                      selectedType={generationType}
                      onChange={handleTypeChange}
                    />
                  </div>

                  {/* 2. Prompt Input */}
                  <div className="console-section">
                    <div className="console-section-label">02 // PROMPT & DIRECTIVES</div>
                    <PromptSection
                      prompt={prompt}
                      onChange={setPrompt}
                      generationType={generationType}
                      error={validationError}
                    />
                  </div>

                  {/* 3. Reference Image Upload (Optional or Required for I2V) */}
                  {generationType === 'image' && (
                    <div className="console-section">
                      <div className="console-section-label">03 // REFERENCE INPUT</div>
                      <ReferenceUpload
                        label="Reference Image (Optional)"
                        sublabel="Provide a reference image for style or composition guidance"
                        imageUrl={referenceImageUrl}
                        onImageChange={setReferenceImageUrl}
                      />
                    </div>
                  )}

                  {/* 4. Configuration: Model, Aspect Ratio, Resolution, Duration */}
                  <div className="console-section">
                    <div className="console-section-label">
                      {generationType === 'image' ? '04 // SYNTHESIS ENGINE' : '03 // SYNTHESIS ENGINE'}
                    </div>
                    <ConfigPanel
                      generationType={generationType}
                      models={currentModels}
                      selectedModel={selectedModel}
                      onModelChange={setSelectedModel}
                      aspectRatios={manifest?.aspect_ratios || []}
                      selectedAspectRatio={selectedAspectRatio}
                      onAspectRatioChange={setSelectedAspectRatio}
                      resolutions={manifest?.resolutions || []}
                      selectedResolution={selectedResolution}
                      onResolutionChange={setSelectedResolution}
                      durations={manifest?.durations || []}
                      selectedDuration={selectedDuration}
                      onDurationChange={setSelectedDuration}
                    />
                  </div>

                  {/* 5. Start Frame & End Frame Controls (respects backend capabilities) */}
                  {generationType !== 'image' && (
                    <div className="console-section">
                      <div className="console-section-label">04 // KEYFRAME DIRECTIVES</div>
                      <StartEndFrameControls
                        generationType={generationType}
                        selectedModelObj={selectedModelObj}
                        startFrameUrl={startFrameUrl}
                        onStartFrameChange={setStartFrameUrl}
                        endFrameUrl={endFrameUrl}
                        onEndFrameChange={setEndFrameUrl}
                      />
                    </div>
                  )}

                  {/* Stage 8: Intelligent Production Decision Layer */}
                  <ProductionDecisionCard recommendation={productionRecommendation} />

                  {/* 6. Generate Action Button */}
                  <div className="console-section console-section-execute">
                    <div className="console-section-label">EXECUTE</div>
                    <GenerateButton
                      generationType={generationType}
                      isSubmitting={isSubmitting}
                      isJobRunning={Boolean(currentJob && (currentJob.status === 'in_progress' || currentJob.status === 'pending'))}
                      onClick={handleGenerate}
                      onRetry={handleRetry}
                      disabled={isLoadingManifest}
                      error={error}
                    />
                  </div>
                </div>
              </section>

              {/* Right Column: Viewport, Status, and Telemetry */}
              <section aria-label="Asset Output & Telemetry" className="command-instrument-column">
                {/* Stage 7/8: Operational Control Strip */}
                <OperationalStrip
                  systemState={systemOperationalState}
                  activeCount={activeRunsCount}
                  queuedCount={queuedRunsCount}
                  processingCount={processingRunsCount}
                  failedCount={failedRunsCount}
                  totalCostUsd={totalCostUsd}
                  isRefreshing={isReconciling}
                  onRefresh={handleOperationalRefresh}
                  hasActiveJob={isJobActive}
                  preflightStatus={productionRecommendation.status}
                  sequenceSummary={sequenceSummary}
                  projectStatus={projectStatus}
                />

                {/* 3D Spatial Command Core */}
                <CommandCore
                  state={commandCoreState}
                  generationType={generationType}
                  modelName={activeModelName}
                />

                {/* Spatial Workflow Pipeline Orbit */}
                <WorkflowOrbit
                  generationType={generationType}
                  hasPrompt={prompt.trim().length > 0}
                  hasReference={Boolean(referenceImageUrl || startFrameUrl)}
                  hasModel={Boolean(selectedModel)}
                  modelName={activeModelName}
                  isGenerating={isSubmitting || currentJob?.status === 'pending'}
                  isProcessing={Boolean(currentJob && currentJob.status === 'in_progress')}
                  isCompleted={currentJob?.status === 'completed' && isActiveGeneration}
                  isError={Boolean(currentJob?.status === 'failed') || (Boolean(error) && !isSubmitting && !currentJob)}
                  startFrameUrl={startFrameUrl}
                  endFrameUrl={endFrameUrl}
                  isPreflightBlocked={!productionRecommendation.preflight.ready}
                />

                {/* Active Job Status Card */}
                {currentJob && (
                  <JobStatusCard
                    job={currentJob}
                    onRefresh={() => currentJob.job_id && pollJobStatus(currentJob.job_id).then(setCurrentJob).catch((e) => console.warn(e))}
                    onRetry={handleRetry}
                  />
                )}

                {/* Generated Asset Preview & Download */}
                <AssetPreview
                  currentJob={currentJob}
                  generationType={generationType}
                  prompt={activePrompt}
                  history={history}
                  onSelectHistoryItem={handleSelectHistoryItem}
                />
              </section>
            </main>

            {/* Stage 10: Multi-Shot Production Timeline & Story Continuity Control Plane */}
            <ProductionTimeline
              project={project}
              activeShotId={project.activeShotId}
              onSelectShot={handleSelectShot}
              onReproduceShot={handleReproduceShot}
              onReorderShots={handleReorderShots}
              onAddShot={handleAddShot}
              onDuplicateShot={handleDuplicateShot}
              onRemoveShot={handleRemoveShot}
              onLinkPredecessor={handleLinkPredecessor}
              manifest={manifest}
              recoveryState={recoveryState}
              envelope={persistedEnvelope}
              onRestoreProject={handleRestoreProject}
              onDiscardProject={handleDiscardProject}
              onReviewInterruptedShots={handleReviewInterruptedShots}
              onDismissRecovery={() => setRecoveryState('SAVED')}
            />

            {/* Persistent History Panel across bottom */}
            <footer style={{ padding: '0 1.5rem 2rem', maxWidth: '1600px', margin: '0 auto', width: '100%' }}>
              <HistoryPanel
                history={history}
                isLoading={isLoadingHistory}
                onSelectItem={handleSelectHistoryItem}
                selectedJobId={currentJob?.job_id}
                onReproduce={handleReproduce}
              />
            </footer>
          </>
        )}

        {activeView === 'pipelines' && (
          <main style={{ flex: 1 }}>
            <PipelinesView />
          </main>
        )}

        {activeView === 'research' && (
          <main style={{ flex: 1 }}>
            <ResearchView />
          </main>
        )}

        {activeView === 'publishing' && (
          <main style={{ flex: 1 }}>
            <PublishingView />
          </main>
        )}

        {activeView === 'learning' && (
          <main style={{ flex: 1 }}>
            <LearningView />
          </main>
        )}
      </MotionViewWrapper>

      {/* Authentication Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onKeyUpdated={() => setHasApiKey(Boolean(getStoredApiKey()))}
      />
    </div>
  );
};
