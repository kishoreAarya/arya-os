/**
 * AryaOS V1 Phase 8 — Persistent Production API & Remote State Client
 * Connects the spatial & control surfaces to the PostgreSQL-backed REST API under /api/v1.
 */

import { AryaJobPackage } from '../types/spatialIntent';
import { Project, Shot, Sequence, ShotLifecycleStatus } from '../types/productionTimeline';

export interface RemoteProject {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  sequences?: RemoteSequence[];
}

export interface RemoteSequence {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  order_index: number;
  status: string;
  created_at: string;
  updated_at: string;
  shots?: RemoteShot[];
}

export interface RemoteShot {
  id: string;
  project_id: string;
  sequence_id: string;
  shot_number: number;
  title: string;
  prompt: string;
  negative_prompt?: string | null;
  generation_type: string;
  model: string;
  provider: string;
  aspect_ratio: string;
  resolution?: string | null;
  duration?: number | null;
  status: string;
  first_frame?: string | null;
  last_frame?: string | null;
  reference_assets?: string[] | null;
  continuity_status?: string | null;
  predecessor_shot_id?: string | null;
  output_asset_url?: string | null;
  metadata_json?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

export interface RemoteJob {
  id: string;
  project_id: string;
  shot_id?: string | null;
  job_package_id: string;
  provider: string;
  model: string;
  status: 'CREATED' | 'QUEUED' | 'SUBMITTED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  progress: number;
  external_job_id?: string | null;
  error_message?: string | null;
  output_asset_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RemoteProjectTree extends RemoteProject {
  sequences: (RemoteSequence & { shots: RemoteShot[] })[];
}

export type PersistenceSyncStatus = 'ONLINE' | 'OFFLINE' | 'SYNCING' | 'ERROR';

const API_BASE = '/api/v1';

/**
 * Health check for the persistent production API.
 */
export async function checkProductionApiHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * List all persistent projects from PostgreSQL.
 */
export async function listProjects(): Promise<RemoteProject[]> {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) throw new Error(`Failed to list projects: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch full project tree (project + sequences + shots).
 */
export async function getProjectTree(projectId: string): Promise<RemoteProjectTree> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/tree`);
  if (!res.ok) throw new Error(`Failed to get project tree: ${res.statusText}`);
  return res.json();
}

/**
 * Create a new project in PostgreSQL with an initial establishing sequence.
 */
export async function createRemoteProject(name: string, description?: string): Promise<RemoteProject> {
  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error(`Failed to create project: ${res.statusText}`);
  return res.json();
}

/**
 * Update project details.
 */
export async function updateRemoteProject(
  projectId: string,
  patch: { name?: string; description?: string; status?: string }
): Promise<RemoteProject> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update project: ${res.statusText}`);
  return res.json();
}

/**
 * Delete a project and cascade all sequences, shots, and jobs.
 */
export async function deleteRemoteProject(projectId: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'DELETE',
  });
  return res.status === 204;
}

/**
 * Create a sequence within a project.
 */
export async function createRemoteSequence(
  projectId: string,
  name: string,
  orderIndex: number = 1
): Promise<RemoteSequence> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/sequences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, order_index: orderIndex }),
  });
  if (!res.ok) throw new Error(`Failed to create sequence: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch all shots in a project.
 */
export async function fetchRemoteShots(projectId: string): Promise<RemoteShot[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/shots`);
  if (!res.ok) throw new Error(`Failed to fetch shots: ${res.statusText}`);
  return res.json();
}

/**
 * Create a persistent production shot in PostgreSQL.
 */
export async function createRemoteShot(
  projectId: string,
  shotData: Partial<RemoteShot> & { sequence_id: string; title: string; prompt: string; model: string; provider: string }
): Promise<RemoteShot> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/shots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(shotData),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to create shot: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Update a persistent shot in PostgreSQL.
 */
export async function updateRemoteShot(
  shotId: string,
  patch: Partial<RemoteShot>
): Promise<RemoteShot> {
  const res = await fetch(`${API_BASE}/shots/${shotId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to update shot: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Submit a formal AryaJobPackage contract to the backend orchestrator.
 * Transitions shot to QUEUED and creates a tracked ProductionJob in PostgreSQL.
 */
export async function submitRemoteJobPackage(
  projectId: string,
  jobPackage: AryaJobPackage,
  autoDispatch: boolean = false
): Promise<RemoteJob> {
  const url = autoDispatch
    ? `${API_BASE}/projects/${projectId}/jobs?dispatch=true`
    : `${API_BASE}/projects/${projectId}/jobs`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(jobPackage),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to submit job package: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Explicitly dispatch a job to the Execution Gateway.
 */
export async function dispatchRemoteJob(jobId: string, sync: boolean = false): Promise<RemoteJob> {
  const url = sync ? `${API_BASE}/jobs/${jobId}/dispatch?sync=true` : `${API_BASE}/jobs/${jobId}/dispatch`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to dispatch job: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Update job state machine status.
 */
export async function updateRemoteJobStatus(
  jobId: string,
  patch: {
    status?: 'CREATED' | 'QUEUED' | 'SUBMITTED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
    progress?: number;
    external_job_id?: string;
    error_message?: string;
    output_asset_url?: string;
  }
): Promise<RemoteJob> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to update job: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Fetch a persistent job by ID.
 */
export async function getRemoteJob(jobId: string): Promise<RemoteJob> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (!res.ok) throw new Error(`Failed to get job: ${res.statusText}`);
  return res.json();
}

/**
 * List all jobs in a project.
 */
export async function listRemoteJobs(projectId: string): Promise<RemoteJob[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/jobs`);
  if (!res.ok) throw new Error(`Failed to list jobs: ${res.statusText}`);
  return res.json();
}

/**
 * Subscribe to project SSE telemetry stream.
 */
export function subscribeToProjectTelemetry(
  projectId: string,
  onEvent: (event: {
    event_type: string;
    data: any;
    payload?: any;
    shot_id?: string;
    job_id?: string;
    timestamp: string;
  }) => void,
  onError?: (err: any) => void
): () => void {
  if (typeof window === 'undefined' || !window.EventSource) {
    return () => {};
  }

  const sse = new EventSource(`${API_BASE}/projects/${projectId}/events`);

  sse.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data);
      const eventData = parsed.payload || parsed.data || parsed;
      onEvent({
        event_type: parsed.event_type || parsed.event,
        data: eventData,
        payload: eventData,
        shot_id: parsed.shot_id,
        job_id: parsed.job_id,
        timestamp: parsed.timestamp || new Date().toISOString(),
      });
    } catch {
      // Ignored heartbeat comments
    }
  };

  sse.onerror = (err) => {
    onError?.(err);
  };

  return () => {
    sse.close();
  };
}

/**
 * Map RemoteShot to frontend Shot model.
 */
export function shotFromRemote(remote: RemoteShot): Shot {
  const status = (remote.status || 'READY') as ShotLifecycleStatus;
  const isReady = status === 'READY';
  return {
    id: remote.id,
    sequenceId: remote.sequence_id,
    order: remote.shot_number,
    title: remote.title,
    prompt: remote.prompt,
    negativePrompt: remote.negative_prompt || undefined,
    generationType: (remote.generation_type as any) || 'video',
    selectedModel: remote.model,
    selectedProvider: remote.provider,
    aspectRatio: remote.aspect_ratio || '16:9',
    resolution: remote.resolution || '1024x1024',
    duration: remote.duration || 5,
    status,
    readiness: isReady ? 'READY' : status === 'BLOCKED' ? 'BLOCKED' : 'READY',
    startFrame: remote.first_frame || undefined,
    endFrame: remote.last_frame || undefined,
    referenceAssets: remote.reference_assets || [],
    continuityStatus: (remote.continuity_status as any) || 'PASS',
    predecessorShotId: remote.predecessor_shot_id || undefined,
    outputAssetUrl: remote.output_asset_url || undefined,
    dependencyShotIds: remote.predecessor_shot_id ? [remote.predecessor_shot_id] : [],
    provenance: 'USER_CONFIGURATION',
    validationResults: {
      isValid: true,
      readiness: isReady ? 'READY' : 'READY',
      reasons: ['DATABASE SYNCHRONIZED'],
      reasonCodes: ['DB_SYNC'],
      preflightReady: true,
      dependenciesSatisfied: true,
      startFrameSatisfied: true,
    },
    continuityReport: {
      character: { status: 'PASS', detail: 'CHARACTER: PASS', source: 'USER_CONFIGURATION' },
      environment: { status: 'PASS', detail: 'ENVIRONMENT: PASS', source: 'USER_CONFIGURATION' },
      visual: { status: 'PASS', detail: `Visual: ${remote.aspect_ratio}`, source: 'USER_CONFIGURATION' },
      temporal: { status: 'PASS', detail: `Temporal order: #${remote.shot_number}`, source: 'USER_CONFIGURATION' },
      startFrame: {
        status: remote.first_frame ? 'PROVIDED' : 'NOT_APPLICABLE',
        detail: remote.first_frame ? 'Keyframe provided' : 'Not required',
        source: 'USER_CONFIGURATION',
      },
    },
    createdAt: remote.created_at,
    updatedAt: remote.updated_at,
    metadata_json: remote.metadata_json || undefined,
  } as any;
}

/**
 * Map RemoteProjectTree to frontend Project model.
 */
export function projectFromRemoteTree(tree: RemoteProjectTree): Project {
  const sequences: Sequence[] = (tree?.sequences || []).map((seq) => {
    const shots = (seq?.shots || []).map(shotFromRemote);
    const readyShots = shots.filter((s) => s.status === 'READY').length;
    const completeShots = shots.filter((s) => s.status === 'COMPLETE').length;
    const inFlightShots = shots.filter((s) => s.status === 'GENERATING' || s.status === 'QUEUED').length;
    const blockedShots = shots.filter((s) => s.status === 'BLOCKED' || s.status === 'RECOVERY_REQUIRED').length;
    const totalDuration = shots.reduce((acc, s) => acc + (s.duration || 0), 0);

    return {
      id: seq.id,
      projectId: seq.project_id,
      order: seq.order_index,
      title: seq.name,
      description: seq.description || undefined,
      shots,
      status: (seq.status as any) || 'READY',
      statusReasons: ['DATABASE PERSISTED'],
      totalShots: shots.length,
      readyShots,
      blockedShots,
      inFlightShots,
      completeShots,
      totalDurationSeconds: totalDuration,
      createdAt: seq.created_at,
      updatedAt: seq.updated_at,
    };
  });

  const activeSequenceId = sequences[0]?.id || '';
  const activeShotId = sequences[0]?.shots[0]?.id || undefined;

  return {
    id: tree.id,
    title: tree.name,
    description: tree.description || undefined,
    sequences,
    activeSequenceId,
    activeShotId,
    createdAt: tree.created_at,
    updatedAt: tree.updated_at,
  };
}
