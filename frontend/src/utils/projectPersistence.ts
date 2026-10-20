import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';
import {
  Project,
  Sequence,
  Shot,
  PersistedProjectEnvelope,
} from '../types/productionTimeline';
import { validateShot, evaluateSequenceReadiness } from './continuityEngine';

export const STORAGE_KEY_PROJECT = 'arya_persisted_project_envelope';
export const CURRENT_SCHEMA_VERSION = 1;

/**
 * 1. Sanitize project object for persistence.
 * Prevents credentials, auth headers, or transient sensitive state from entering localStorage.
 * Ensures in-flight generations are safely transitioned to RECOVERY_REQUIRED.
 */
export function sanitizeForPersistence(project: Project): Project {
  if (!project || typeof project !== 'object') {
    throw new Error('Invalid project structure for persistence');
  }

  // Deep clone to ensure immutability
  const clone: Project = JSON.parse(JSON.stringify(project));

  // Sanitize project metadata (strip any token/credential fields if present)
  if (clone.metadata) {
    const sensitiveKeys = ['apikey', 'token', 'authorization', 'password', 'secret', 'auth'];
    for (const key of Object.keys(clone.metadata)) {
      if (sensitiveKeys.some((s) => key.toLowerCase().includes(s))) {
        delete clone.metadata[key];
      }
    }
  }

  // Sanitize sequences and shots
  clone.sequences = (clone.sequences || []).map((seq) => {
    const cleanShots = (seq.shots || []).map((shot) => {
      let status = shot.status;
      // In-flight or queued shots must not claim complete or in-flight across reload
      if (status === 'QUEUED' || status === 'GENERATING' || status === 'RECOVERY_REQUIRED') {
        status = 'RECOVERY_REQUIRED';
        return {
          ...shot,
          status,
          readiness: 'BLOCKED' as const,
          validationResults: {
            isValid: false,
            readiness: 'BLOCKED' as const,
            reasons: ['PREVIOUS GENERATION INTERRUPTED // VERIFICATION REQUIRED'],
            reasonCodes: ['INTERRUPTED_RECOVERY_REQUIRED'],
            preflightReady: false,
            dependenciesSatisfied: true,
            startFrameSatisfied: true,
          },
          outputAssetUrl: shot.outputAssetUrl?.startsWith('blob:') ? undefined : shot.outputAssetUrl,
          startFrame: shot.startFrame?.startsWith('blob:') ? undefined : shot.startFrame,
        };
      }

      return {
        ...shot,
        status,
        outputAssetUrl: shot.outputAssetUrl?.startsWith('blob:') ? undefined : shot.outputAssetUrl,
        startFrame: shot.startFrame?.startsWith('blob:') ? undefined : shot.startFrame,
      };
    });

    return {
      ...seq,
      shots: cleanShots,
    };
  });

  return clone;
}

/**
 * 2. Deterministically serialize project into a versioned envelope.
 */
export function serializeProject(project: Project): string {
  const sanitized = sanitizeForPersistence(project);
  const envelope: PersistedProjectEnvelope = {
    schemaVersion: CURRENT_SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    project: sanitized,
  };
  return JSON.stringify(envelope);
}

/**
 * 3. Validate persisted project envelope schema and required fields.
 */
export function validatePersistedProject(payload: any): boolean {
  if (!payload || typeof payload !== 'object') return false;

  // Schema version must match exactly (CURRENT_SCHEMA_VERSION = 1)
  if (payload.schemaVersion !== CURRENT_SCHEMA_VERSION) return false;
  if (typeof payload.savedAt !== 'string') return false;

  const proj = payload.project;
  if (!proj || typeof proj !== 'object') return false;
  if (typeof proj.id !== 'string' || typeof proj.title !== 'string') return false;
  if (!Array.isArray(proj.sequences)) return false;

  // Validate each sequence
  for (const seq of proj.sequences) {
    if (!seq || typeof seq !== 'object') return false;
    if (typeof seq.id !== 'string' || typeof seq.title !== 'string') return false;
    if (!Array.isArray(seq.shots)) return false;

    // Validate shots
    for (const shot of seq.shots) {
      if (!shot || typeof shot !== 'object') return false;
      if (typeof shot.id !== 'string') return false;
      if (typeof shot.order !== 'number') return false;
      if (typeof shot.prompt !== 'string') return false;
      if (typeof shot.generationType !== 'string') return false;
      if (typeof shot.selectedModel !== 'string') return false;
      if (typeof shot.aspectRatio !== 'string') return false;
    }
  }

  return true;
}

/**
 * 4. Safely deserialize persisted string payload into a Project.
 * Returns null if payload is malformed or corrupted.
 */
export function deserializeProject(payload: string): Project | null {
  if (!payload || typeof payload !== 'string') return null;

  try {
    const parsed = JSON.parse(payload);
    if (!validatePersistedProject(parsed)) {
      return null;
    }

    const proj: Project = parsed.project;

    // Handle any interrupted shots
    const sanitizedSequences = proj.sequences.map((seq) => ({
      ...seq,
      shots: seq.shots.map((shot) => {
        if (shot.status === 'QUEUED' || shot.status === 'GENERATING' || shot.status === 'RECOVERY_REQUIRED') {
          return {
            ...shot,
            status: 'RECOVERY_REQUIRED' as const,
            readiness: 'BLOCKED' as const,
            validationResults: {
              isValid: false,
              readiness: 'BLOCKED' as const,
              reasons: ['PREVIOUS GENERATION INTERRUPTED // VERIFICATION REQUIRED'],
              reasonCodes: ['INTERRUPTED_RECOVERY_REQUIRED'],
              preflightReady: false,
              dependenciesSatisfied: true,
              startFrameSatisfied: true,
            },
          };
        }
        return shot;
      }),
    }));

    return {
      ...proj,
      sequences: sanitizedSequences,
    };
  } catch (err) {
    // Malformed JSON must fail safely without throwing
    return null;
  }
}

/**
 * 5. Save project to localStorage safely.
 */
export function saveProject(project: Project): boolean {
  try {
    const serialized = serializeProject(project);
    localStorage.setItem(STORAGE_KEY_PROJECT, serialized);
    return true;
  } catch (err) {
    console.warn('Failed to persist project to localStorage:', err);
    return false;
  }
}

/**
 * 6. Load project from localStorage safely.
 */
export function loadProject(): Project | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PROJECT);
    if (!raw) return null;
    return deserializeProject(raw);
  } catch (err) {
    console.warn('Failed to load project from localStorage:', err);
    return null;
  }
}

/**
 * 7. Clear persisted project from localStorage.
 */
export function clearProject(): void {
  try {
    localStorage.removeItem(STORAGE_KEY_PROJECT);
  } catch (err) {
    console.warn('Failed to clear persisted project:', err);
  }
}

/**
 * 8. Detect if a persisted project exists in localStorage.
 */
export function hasPersistedProject(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PROJECT);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    return validatePersistedProject(parsed);
  } catch {
    return false;
  }
}

/**
 * 9. Retrieve envelope metadata (saved timestamp, version) without full restore.
 */
export function getPersistedProjectEnvelope(): PersistedProjectEnvelope | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PROJECT);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!validatePersistedProject(parsed)) return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * 10. Recompute derived state (continuity reports, sequence readiness, preflight, summaries)
 * Adheres to Derived State Rule: Persist source of truth, recalculate derived metrics.
 */
export function recomputeDerivedState(
  project: Project,
  manifest: CapabilitiesManifest | null
): Project {
  if (!project) return project;

  const updatedSequences = project.sequences.map((seq) => {
    const validatedShots = seq.shots.map((shot) =>
      validateShot(shot, seq.shots, manifest)
    );
    const evalSeq = evaluateSequenceReadiness(validatedShots);

    return {
      ...seq,
      shots: validatedShots,
      status: evalSeq.status,
      sequenceStatus: evalSeq.status,
      statusReasons: evalSeq.statusReasons,
      totalShots: evalSeq.metrics.total,
      readyShots: evalSeq.metrics.ready,
      blockedShots: evalSeq.metrics.blocked,
      warningShots: evalSeq.metrics.warning,
      inFlightShots: evalSeq.metrics.inFlight,
      completeShots: evalSeq.metrics.complete,
      completedShots: evalSeq.metrics.complete,
      totalDurationSeconds: evalSeq.metrics.totalDuration,
      totalDuration: evalSeq.metrics.totalDuration,
      continuityWarnings: evalSeq.metrics.continuityWarnings,
      sequencePreflightStatus: (evalSeq.status === 'BLOCKED' ? 'BLOCKED' : evalSeq.status === 'READY' ? 'READY' : 'WARNING') as 'READY' | 'BLOCKED' | 'WARNING',
    };
  });

  return {
    ...project,
    sequences: updatedSequences,
  };
}

/**
 * 11. Check if any shots in the project require manual recovery review.
 */
export function checkForInterruptedShots(project: Project): {
  hasInterrupted: boolean;
  interruptedShotIds: string[];
} {
  const interruptedShotIds: string[] = [];
  if (!project || !project.sequences) {
    return { hasInterrupted: false, interruptedShotIds: [] };
  }

  for (const seq of project.sequences) {
    for (const shot of seq.shots || []) {
      if (shot.status === 'RECOVERY_REQUIRED' || shot.status === 'QUEUED' || shot.status === 'GENERATING') {
        interruptedShotIds.push(shot.id);
      }
    }
  }

  return {
    hasInterrupted: interruptedShotIds.length > 0,
    interruptedShotIds,
  };
}

/**
 * 12. Run Reconciliation with historical runs.
 * Non-autonomous: Never triggers generation. Factual reconciliation only.
 */
export function reconcileProjectWithHistory(
  project: Project,
  history: (HistoryItem | GenerationJob)[]
): Project {
  if (!project || !history || history.length === 0) return project;

  const updatedSequences = project.sequences.map((seq) => {
    const updatedShots = seq.shots.map((shot) => {
      // If shot was waiting on an outputJobId
      if (shot.outputJobId) {
        const matchingJob = history.find((j) => j.job_id === shot.outputJobId);
        if (matchingJob && matchingJob.status === 'completed') {
          const assetUrl =
            ('output' in matchingJob && matchingJob.output?.asset_url)
              ? matchingJob.output.asset_url
              : (matchingJob as any).asset_url || (matchingJob as any).output?.storage_path;
          return {
            ...shot,
            status: 'COMPLETE' as const,
            readiness: 'READY' as const,
            outputAssetUrl: assetUrl,
            provenance: 'HISTORICAL_RUN' as const,
          };
        } else if (matchingJob && matchingJob.status === 'failed') {
          return {
            ...shot,
            status: 'FAILED' as const,
            failureDetails: {
              category: 'PROVIDER',
              stage: 'EXECUTION',
              reason: matchingJob.failure_reason || 'Historical run failed',
              retryEligible: true,
            },
            provenance: 'HISTORICAL_RUN' as const,
          };
        }
      }
      return shot;
    });

    return {
      ...seq,
      shots: updatedShots,
    };
  });

  return {
    ...project,
    sequences: updatedSequences,
  };
}
