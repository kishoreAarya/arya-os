import { CapabilitiesManifest, GenerationType } from '../types/creator';
import { validateConfiguration } from '../types/productionDecision';
import {
  Shot,
  Sequence,
  Project,
  ContinuityCheckResult,
  ShotContinuityReport,
  ShotValidationResult,
  SequenceStatus,
  TimelineFactSource,
  SequenceExecutionPlan,
  SequenceExecutionPlanItem,
} from '../types/productionTimeline';

/**
 * 1. Evaluate Character Continuity between current shot and predecessor.
 * Factual, non-hallucinatory evaluation. Missing data strictly reports UNAVAILABLE.
 * Adheres to Section 13: "IDENTITY REFERENCE AVAILABLE" instead of "IDENTITY GUARANTEED".
 */
export function evaluateCharacterContinuity(
  currentShot: Shot,
  previousShot?: Shot
): ContinuityCheckResult {
  const currChar = currentShot.characterRequirements || currentShot.continuityRequirements?.character;
  const prevChar = previousShot?.characterRequirements || previousShot?.continuityRequirements?.character;

  if (!currChar || !currChar.characterId) {
    return {
      status: 'UNAVAILABLE',
      detail: 'CHARACTER CONTINUITY: UNAVAILABLE',
      source: 'UNAVAILABLE',
      missingFields: ['characterId', 'declaredAppearance', 'wardrobe', 'hair'],
    };
  }

  if (!previousShot || !prevChar || !prevChar.characterId) {
    return {
      status: 'UNAVAILABLE',
      detail: 'PREVIOUS SHOT CHARACTER REQUIREMENTS UNAVAILABLE',
      source: 'UNAVAILABLE',
      missingFields: ['predecessorCharacterRequirements'],
    };
  }

  // Same character declared
  if (currChar.characterId === prevChar.characterId) {
    const conflicts: string[] = [];
    const matched: string[] = ['characterId'];

    if (currChar.name && prevChar.name && currChar.name === prevChar.name) {
      matched.push('name');
    }

    // Reference asset continuity check (Section 14)
    const prevHasRef = Boolean(
      (prevChar.visualIdentityReferences && prevChar.visualIdentityReferences.length > 0) ||
      (previousShot.referenceAssets && previousShot.referenceAssets.length > 0)
    );
    const currHasRef = Boolean(
      (currChar.visualIdentityReferences && currChar.visualIdentityReferences.length > 0) ||
      (currentShot.referenceAssets && currentShot.referenceAssets.length > 0)
    );

    if (prevHasRef && !currHasRef) {
      conflicts.push(`IDENTITY REFERENCE UNAVAILABLE for ${currChar.name || currChar.characterId}`);
    } else if (currHasRef) {
      matched.push('identityReference');
    }

    // Wardrobe comparison
    if (currChar.wardrobe && prevChar.wardrobe) {
      if (currChar.wardrobe.trim().toLowerCase() !== prevChar.wardrobe.trim().toLowerCase()) {
        conflicts.push(`Wardrobe mismatch: '${prevChar.wardrobe}' vs '${currChar.wardrobe}'`);
      } else {
        matched.push('wardrobe');
      }
    }

    // Hair comparison
    if (currChar.hair && prevChar.hair) {
      if (currChar.hair.trim().toLowerCase() !== prevChar.hair.trim().toLowerCase()) {
        conflicts.push(`Hair style mismatch: '${prevChar.hair}' vs '${currChar.hair}'`);
      } else {
        matched.push('hair');
      }
    }

    if (conflicts.length > 0) {
      return {
        status: 'WARNING',
        detail: conflicts.join(' · '),
        source: 'USER_CONFIGURATION',
        conflicts,
        matchedFields: matched,
      };
    }

    const refNote = currHasRef ? ' (IDENTITY REFERENCE AVAILABLE)' : '';
    return {
      status: 'PASS',
      detail: `Character continuity verified (${currChar.name || currChar.characterId})${refNote}`,
      source: 'USER_CONFIGURATION',
      matchedFields: matched,
    };
  }

  // Declared character transition (different characters)
  return {
    status: 'PASS',
    detail: `Character transition: ${prevChar.name || prevChar.characterId} -> ${currChar.name || currChar.characterId}`,
    source: 'USER_CONFIGURATION',
    matchedFields: ['characterTransition'],
  };
}

/**
 * 2. Evaluate Environment Continuity between current shot and predecessor.
 * Checks location consistency, conflicting location metadata, and time transitions (Section 12).
 */
export function evaluateEnvironmentContinuity(
  currentShot: Shot,
  previousShot?: Shot
): ContinuityCheckResult {
  const currEnv = currentShot.environmentRequirements || currentShot.continuityRequirements?.environment;
  const prevEnv = previousShot?.environmentRequirements || previousShot?.continuityRequirements?.environment;

  const currLoc = currentShot.locationId || currEnv?.location;
  const prevLoc = previousShot?.locationId || prevEnv?.location;

  if (!currLoc && !currEnv?.location) {
    return {
      status: 'UNAVAILABLE',
      detail: 'ENVIRONMENT CONTINUITY: UNAVAILABLE',
      source: 'UNAVAILABLE',
      missingFields: ['location', 'timeOfDay', 'weather'],
    };
  }

  if (!previousShot || (!prevLoc && !prevEnv?.location)) {
    return {
      status: 'UNAVAILABLE',
      detail: 'PREVIOUS SHOT ENVIRONMENT REQUIREMENTS UNAVAILABLE',
      source: 'UNAVAILABLE',
      missingFields: ['predecessorEnvironmentRequirements'],
    };
  }

  const conflicts: string[] = [];
  const matched: string[] = [];

  // Location comparison (locationId or location name)
  const currLocId = currentShot.locationId;
  const prevLocId = previousShot?.locationId;
  if (currLocId && prevLocId) {
    if (currLocId === prevLocId) {
      matched.push('locationId');
    } else {
      conflicts.push(`LOCATION CONFLICT: Location ID shift from '${prevLocId}' to '${currLocId}'`);
    }
  }

  if (currEnv?.location && prevEnv?.location) {
    if (currEnv.location.trim().toLowerCase() === prevEnv.location.trim().toLowerCase()) {
      matched.push('location');
    }
  }

  // Time of Day comparison (Section 12: DAY -> NIGHT should produce warning without declared transition)
  const currTod = (currentShot.timeOfDay || currEnv?.timeOfDay || '').trim().toLowerCase();
  const prevTod = (previousShot?.timeOfDay || prevEnv?.timeOfDay || '').trim().toLowerCase();
  if (currTod && prevTod) {
    if (currTod === prevTod) {
      matched.push('timeOfDay');
    } else {
      conflicts.push(`Time of day shift: '${prevTod.toUpperCase()}' -> '${currTod.toUpperCase()}'`);
    }
  }

  // Weather comparison
  if (currEnv?.weather && prevEnv?.weather) {
    const cW = currEnv.weather.trim().toLowerCase();
    const pW = prevEnv.weather.trim().toLowerCase();
    if (cW === pW) {
      matched.push('weather');
    } else {
      conflicts.push(`Weather shift: '${prevEnv.weather}' -> '${currEnv.weather}'`);
    }
  }

  if (conflicts.length > 0) {
    return {
      status: 'WARNING',
      detail: conflicts.join(' · '),
      source: 'USER_CONFIGURATION',
      conflicts,
      matchedFields: matched,
    };
  }

  if (matched.includes('location') || matched.includes('locationId')) {
    return {
      status: 'PASS',
      detail: `Environment continuity verified: ${currEnv?.location || currLocId}`,
      source: 'USER_CONFIGURATION',
      matchedFields: matched,
    };
  }

  return {
    status: 'PASS',
    detail: `Scene location transition: ${prevEnv?.location || prevLocId} -> ${currEnv?.location || currLocId}`,
    source: 'USER_CONFIGURATION',
    matchedFields: matched,
  };
}

/**
 * 3. Evaluate Visual Continuity (Aspect ratio, resolution, visual style, model).
 * Section 12: Aspect ratio, resolution, or model changes produce deterministic warnings with USER_CONFIGURATION source.
 */
export function evaluateVisualContinuity(
  currentShot: Shot,
  previousShot?: Shot
): ContinuityCheckResult {
  if (!previousShot) {
    return {
      status: 'PASS',
      detail: `Initial shot format declared (${currentShot.aspectRatio})`,
      source: 'USER_CONFIGURATION',
      matchedFields: ['aspectRatio'],
    };
  }

  const conflicts: string[] = [];
  const matched: string[] = [];

  // Aspect ratio continuity
  if (previousShot.aspectRatio !== currentShot.aspectRatio) {
    conflicts.push(`Aspect ratio mismatch: ${previousShot.aspectRatio} -> ${currentShot.aspectRatio}`);
  } else {
    matched.push('aspectRatio');
  }

  // Resolution continuity
  if (previousShot.resolution && currentShot.resolution && previousShot.resolution !== currentShot.resolution) {
    conflicts.push(`Resolution mismatch: ${previousShot.resolution} -> ${currentShot.resolution}`);
  } else if (currentShot.resolution) {
    matched.push('resolution');
  }

  // Model change warning (Section 12: across shots of the same generation type)
  if (
    previousShot.generationType === currentShot.generationType &&
    previousShot.selectedModel &&
    currentShot.selectedModel &&
    previousShot.selectedModel !== currentShot.selectedModel
  ) {
    conflicts.push(`Model changed: ${previousShot.selectedModel} -> ${currentShot.selectedModel}`);
  } else if (currentShot.selectedModel) {
    matched.push('model');
  }

  if (conflicts.length > 0) {
    return {
      status: 'WARNING',
      detail: conflicts.join(' · '),
      source: 'USER_CONFIGURATION',
      conflicts,
      matchedFields: matched,
    };
  }

  return {
    status: 'PASS',
    detail: `Visual format consistent (${currentShot.aspectRatio}${currentShot.resolution ? ` @ ${currentShot.resolution}` : ''})`,
    source: 'USER_CONFIGURATION',
    matchedFields: matched,
  };
}

/**
 * 4. Evaluate Temporal Continuity (Ordering, predecessor sequence, dependencies).
 * Source strictly uses USER_CONFIGURATION (for ordering) or SYSTEM_STATE.
 */
export function evaluateTemporalContinuity(
  currentShot: Shot,
  previousShot?: Shot,
  allShotsInSeq: Shot[] = []
): ContinuityCheckResult {
  if (previousShot && currentShot.order <= previousShot.order) {
    return {
      status: 'BLOCKED',
      detail: `Temporal order inversion: Shot ${currentShot.order} follows Shot ${previousShot.order}`,
      source: 'USER_CONFIGURATION',
      conflicts: ['order'],
    };
  }

  // Verify declared dependency IDs exist in sequence
  const missingDeps = (currentShot.dependencyShotIds || []).filter(
    (depId) => !allShotsInSeq.some((s) => s.id === depId)
  );

  if (missingDeps.length > 0) {
    return {
      status: 'BLOCKED',
      detail: `Missing dependency shot reference: ${missingDeps.join(', ')}`,
      source: 'USER_CONFIGURATION',
      conflicts: missingDeps,
    };
  }

  return {
    status: 'PASS',
    detail: `Temporal sequence ordering valid (Shot #${currentShot.order})`,
    source: 'USER_CONFIGURATION',
    matchedFields: ['order'],
  };
}

/**
 * 5. Start-Frame / Previous-Shot Continuity Evaluation.
 * Differentiates REQUIRED, PROVIDED, MISSING, UNAVAILABLE, NOT_APPLICABLE.
 */
export function evaluateStartFrameContinuity(
  currentShot: Shot,
  allShotsInSeq: Shot[]
): ShotContinuityReport['startFrame'] {
  if (currentShot.generationType !== 'image_to_video') {
    return {
      status: 'NOT_APPLICABLE',
      detail: 'START FRAME NOT APPLICABLE FOR CURRENT MODE',
      source: 'CAPABILITY_MANIFEST',
    };
  }

  // Mode is Image -> Video: Start frame is required
  const targetPredecessorId =
    currentShot.predecessorShotId ||
    (currentShot.temporalRequirements?.requiresStartFrameFromPredecessor
      ? allShotsInSeq.find((s) => s.order === currentShot.order - 1)?.id
      : undefined);

  if (targetPredecessorId) {
    const pred = allShotsInSeq.find((s) => s.id === targetPredecessorId);
    if (!pred) {
      return {
        status: 'MISSING',
        detail: 'START FRAME REQUIRED: PREDECESSOR SHOT NOT FOUND',
        source: 'USER_CONFIGURATION',
      };
    }

    if (pred.outputAssetUrl) {
      return {
        status: 'PROVIDED',
        sourceShotId: pred.id,
        assetUrl: pred.outputAssetUrl,
        detail: `CONTINUITY INPUT // SOURCE: ${pred.id} // TARGET: ${currentShot.id} // TYPE: START_FRAME // STATUS: READY`,
        source: 'HISTORICAL_RUN',
      };
    }

    return {
      status: 'MISSING',
      sourceShotId: pred.id,
      detail: 'START FRAME REQUIRED: SOURCE SHOT OUTPUT NOT AVAILABLE',
      source: 'SYSTEM_STATE',
    };
  }

  // Direct manual startFrame configured on the shot
  if (currentShot.startFrame) {
    return {
      status: 'PROVIDED',
      assetUrl: currentShot.startFrame,
      detail: 'START FRAME PROVIDED VIA DIRECT CONFIGURATION',
      source: 'USER_CONFIGURATION',
    };
  }

  // Missing start frame for Image -> Video
  return {
    status: 'MISSING',
    detail: 'START FRAME REQUIRED',
    source: 'CAPABILITY_MANIFEST',
  };
}

/**
 * 6. Pure deterministic shot validation against capability manifest, dependencies, and continuity.
 */
export function validateShot(
  shot: Shot,
  allShotsInSeq: Shot[],
  manifest: CapabilitiesManifest | null
): Shot {
  // Safe resilience for malformed or undefined shot objects
  if (!shot || typeof shot !== 'object') {
    return shot;
  }

  const order = typeof shot.order === 'number' ? shot.order : 1;
  const previousShot = allShotsInSeq.find((s) => s.order === order - 1);

  // Evaluate continuity dimensions
  const charContinuity = evaluateCharacterContinuity(shot, previousShot);
  const envContinuity = evaluateEnvironmentContinuity(shot, previousShot);
  const visContinuity = evaluateVisualContinuity(shot, previousShot);
  const tempContinuity = evaluateTemporalContinuity(shot, previousShot, allShotsInSeq);
  const startFrameContinuity = evaluateStartFrameContinuity(shot, allShotsInSeq);

  const continuityReport: ShotContinuityReport = {
    character: charContinuity,
    environment: envContinuity,
    visual: visContinuity,
    temporal: tempContinuity,
    startFrame: startFrameContinuity,
  };

  // Determine effective start frame URL (direct or derived from completed predecessor)
  const effectiveStartFrame =
    shot.startFrame || (startFrameContinuity.status === 'PROVIDED' ? startFrameContinuity.assetUrl : undefined);

  // Evaluate preflight against capability manifest using Stage 9 validator
  const preflight = validateConfiguration(
    {
      generationType: shot.generationType || 'image',
      prompt: shot.prompt || '',
      model: shot.selectedModel || '',
      provider: shot.selectedProvider || '',
      aspectRatio: shot.aspectRatio || '16:9',
      resolution: shot.resolution,
      duration: shot.duration,
      startFrameUrl: effectiveStartFrame,
      endFrameUrl: shot.endFrame,
      referenceImageUrl: shot.referenceAssets?.[0],
    },
    manifest
  );

  const reasons: string[] = [];
  const reasonCodes: string[] = [];

  // Check 1: Preflight failures
  if (!preflight.ready) {
    reasons.push(...preflight.reasons);
    reasonCodes.push(...preflight.reasonCodes);
  }

  // Check 2: Dependency completion
  let dependenciesSatisfied = true;
  for (const depId of shot.dependencyShotIds || []) {
    const depShot = allShotsInSeq.find((s) => s.id === depId);
    if (!depShot || depShot.status !== 'COMPLETE') {
      dependenciesSatisfied = false;
      const r = `DEPENDENCY ${depId} NOT COMPLETE`;
      reasons.push(r);
      reasonCodes.push('DEPENDENCY_NOT_SATISFIED');
    }
  }

  // Check 3: Start frame satisfaction for image_to_video
  let startFrameSatisfied = true;
  if (shot.generationType === 'image_to_video' && startFrameContinuity.status !== 'PROVIDED') {
    startFrameSatisfied = false;
    if (!reasons.includes('START FRAME REQUIRED')) {
      reasons.push(startFrameContinuity.detail || 'START FRAME REQUIRED');
      reasonCodes.push('START_FRAME_REQUIRED');
    }
  }

  // Check 4: Temporal ordering
  if (tempContinuity.status === 'BLOCKED') {
    reasons.push(tempContinuity.detail);
    reasonCodes.push('TEMPORAL_ORDER_INVALID');
  }

  const isBlocked = !preflight.ready || !dependenciesSatisfied || !startFrameSatisfied || tempContinuity.status === 'BLOCKED';
  const hasWarnings =
    charContinuity.status === 'WARNING' ||
    envContinuity.status === 'WARNING' ||
    visContinuity.status === 'WARNING';

  const readiness: 'READY' | 'BLOCKED' | 'WARNING' = isBlocked
    ? 'BLOCKED'
    : hasWarnings
    ? 'WARNING'
    : 'READY';

  const validationResults: ShotValidationResult = {
    isValid: !isBlocked,
    readiness,
    reasons: isBlocked ? reasons : hasWarnings ? ['CONTINUITY WARNINGS DETECTED'] : ['READY FOR EXECUTION'],
    reasonCodes: isBlocked ? reasonCodes : ['READY'],
    preflightReady: preflight.ready,
    dependenciesSatisfied,
    startFrameSatisfied,
  };

  // Determine lifecycle status (preserve runtime active/complete states)
  let status = shot.status;
  if (status !== 'COMPLETE' && status !== 'GENERATING' && status !== 'QUEUED' && status !== 'RECOVERY_REQUIRED') {
    if (!shot.prompt || shot.prompt.trim() === '') {
      status = 'DRAFT';
    } else if (isBlocked) {
      status = 'BLOCKED';
    } else {
      status = 'READY';
    }
  }

  if (status === 'RECOVERY_REQUIRED') {
    validationResults.readiness = 'BLOCKED';
    if (!validationResults.reasons.some((r) => r.includes('INTERRUPTED'))) {
      validationResults.reasons = ['PREVIOUS GENERATION INTERRUPTED // VERIFICATION REQUIRED', ...validationResults.reasons];
      validationResults.reasonCodes = ['INTERRUPTED_RECOVERY_REQUIRED', ...validationResults.reasonCodes];
    }
    validationResults.isValid = false;
  }

  const primaryContinuityStatus = hasWarnings ? 'WARNING' : isBlocked ? 'BLOCKED' : 'PASS';

  return {
    ...shot,
    shotId: shot.id,
    order,
    startFrame: effectiveStartFrame,
    status,
    readiness,
    preflightStatus: readiness,
    continuityStatus: primaryContinuityStatus,
    validationResults,
    continuityReport,
  };
}

/**
 * 7. Sequence-level Readiness Evaluator (Section 11).
 * Calculates total shots, total planned duration, ready, blocked, warning, incomplete shots, and continuity warnings.
 */
export function evaluateSequenceReadiness(shots: Shot[]): {
  status: SequenceStatus;
  statusReasons: string[];
  metrics: {
    total: number;
    ready: number;
    blocked: number;
    warning: number;
    inFlight: number;
    complete: number;
    totalDuration: number;
    continuityWarnings: string[];
  };
} {
  const total = shots.length;
  const ready = shots.filter((s) => s.status === 'READY').length;
  const blocked = shots.filter((s) => s.status === 'BLOCKED' || s.status === 'RECOVERY_REQUIRED').length;
  const warning = shots.filter((s) => s.readiness === 'WARNING').length;
  const inFlight = shots.filter((s) => s.status === 'GENERATING' || s.status === 'QUEUED').length;
  const complete = shots.filter((s) => s.status === 'COMPLETE').length;

  const totalDuration = shots.reduce((acc, s) => acc + (s.duration || (s.generationType === 'image' ? 0 : 5)), 0);

  const continuityWarnings: string[] = [];
  shots.forEach((s) => {
    if (s.continuityReport?.character?.status === 'WARNING') {
      continuityWarnings.push(`SHOT ${String(s.order).padStart(2, '0')}: ${s.continuityReport.character.detail}`);
    }
    if (s.continuityReport?.environment?.status === 'WARNING') {
      continuityWarnings.push(`SHOT ${String(s.order).padStart(2, '0')}: ${s.continuityReport.environment.detail}`);
    }
    if (s.continuityReport?.visual?.status === 'WARNING') {
      continuityWarnings.push(`SHOT ${String(s.order).padStart(2, '0')}: ${s.continuityReport.visual.detail}`);
    }
  });

  const metrics = {
    total,
    ready,
    blocked,
    warning,
    inFlight,
    complete,
    totalDuration,
    continuityWarnings,
  };

  if (total === 0) {
    return {
      status: 'READY',
      statusReasons: ['SEQUENCE CONTAINS NO SHOTS'],
      metrics,
    };
  }

  if (inFlight > 0) {
    return {
      status: 'IN_PROGRESS',
      statusReasons: [`${inFlight} SHOT(S) CURRENTLY IN FLIGHT`],
      metrics,
    };
  }

  if (complete === total) {
    return {
      status: 'COMPLETE',
      statusReasons: ['ALL SHOTS COMPLETED'],
      metrics,
    };
  }

  if (blocked > 0) {
    const reasons: string[] = [];
    shots
      .filter((s) => s.status === 'BLOCKED' || s.status === 'RECOVERY_REQUIRED')
      .forEach((s) => {
        const shotReasons = s.validationResults?.reasons?.length > 0
          ? s.validationResults.reasons.join(', ')
          : 'CONFIGURATION BLOCKED';
        reasons.push(`SHOT ${String(s.order).padStart(2, '0')}: ${shotReasons}`);
      });

    return {
      status: 'BLOCKED',
      statusReasons: reasons,
      metrics,
    };
  }

  if (ready > 0 && ready + complete < total) {
    return {
      status: 'PARTIALLY_READY',
      statusReasons: [`${ready} OF ${total} SHOTS READY FOR EXECUTION`],
      metrics,
    };
  }

  return {
    status: 'READY',
    statusReasons: ['ALL REMAINING SHOTS READY FOR EXECUTION'],
    metrics,
  };
}

/**
 * 8. Pure immutable shot reordering.
 * Reassigns 1-indexed order and re-validates shots.
 */
export function reorderShots(
  shots: Shot[],
  sourceIndex: number,
  targetIndex: number,
  manifest: CapabilitiesManifest | null
): Shot[] {
  if (sourceIndex < 0 || sourceIndex >= shots.length || targetIndex < 0 || targetIndex >= shots.length) {
    return shots;
  }

  const result = Array.from(shots);
  const [removed] = result.splice(sourceIndex, 1);
  result.splice(targetIndex, 0, removed);

  // Re-index order
  const reindexed = result.map((s, idx) => ({
    ...s,
    order: idx + 1,
  }));

  // Re-validate all shots with updated sequence context
  return reindexed.map((s) => validateShot(s, reindexed, manifest));
}

/**
 * 9. Duplicate shot immutably (Section 8).
 */
export function duplicateShot(
  shots: Shot[],
  shotId: string,
  manifest: CapabilitiesManifest | null
): Shot[] {
  const targetIndex = shots.findIndex((s) => s.id === shotId);
  if (targetIndex === -1) return shots;

  const original = shots[targetIndex];
  const newId = `shot-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

  const duplicated: Shot = {
    ...JSON.parse(JSON.stringify(original)),
    id: newId,
    shotId: newId,
    title: `${original.title} (Copy)`,
    status: original.prompt ? 'READY' : 'DRAFT',
    outputAssetUrl: undefined,
    outputJobId: undefined,
    dependencyShotIds: [...original.dependencyShotIds],
  };

  const nextShots = [...shots];
  nextShots.splice(targetIndex + 1, 0, duplicated);

  const reindexed = nextShots.map((s, idx) => ({
    ...s,
    order: idx + 1,
  }));

  return reindexed.map((s) => validateShot(s, reindexed, manifest));
}

/**
 * 10. Remove shot immutably (Section 8).
 */
export function removeShot(
  shots: Shot[],
  shotId: string,
  manifest: CapabilitiesManifest | null
): Shot[] {
  const filtered = shots.filter((s) => s.id !== shotId);

  // Clean up references to removed shot from other shots' dependency lists
  const cleaned = filtered.map((s) => ({
    ...s,
    dependencyShotIds: s.dependencyShotIds.filter((dep) => dep !== shotId),
    predecessorShotId: s.predecessorShotId === shotId ? undefined : s.predecessorShotId,
  }));

  const reindexed = cleaned.map((s, idx) => ({
    ...s,
    order: idx + 1,
  }));

  return reindexed.map((s) => validateShot(s, reindexed, manifest));
}

/**
 * 11. Edit shot parameters immutably (Section 8 & 9).
 */
export function editShot(
  shots: Shot[],
  shotId: string,
  updates: Partial<Shot>,
  manifest: CapabilitiesManifest | null
): Shot[] {
  const updated = shots.map((s) => {
    if (s.id !== shotId) return s;
    return {
      ...s,
      ...updates,
      id: s.id, // Preserve immutable ID
    };
  });

  return updated.map((s) => validateShot(s, updated, manifest));
}

/**
 * 12. Link previous shot output to next shot start frame.
 */
export function linkPredecessorStartFrame(
  targetShotId: string,
  sourceShotId: string,
  shots: Shot[],
  manifest: CapabilitiesManifest | null
): Shot[] {
  const updated = shots.map((s) => {
    if (s.id !== targetShotId) return s;

    const sourceShot = shots.find((src) => src.id === sourceShotId);
    const deps = Array.from(new Set([...s.dependencyShotIds, sourceShotId]));

    return {
      ...s,
      predecessorShotId: sourceShotId,
      dependencyShotIds: deps,
      startFrame: sourceShot?.outputAssetUrl || s.startFrame,
      temporalRequirements: {
        order: s.order,
        predecessorId: sourceShotId,
        requiresStartFrameFromPredecessor: true,
        source: 'USER_CONFIGURATION' as TimelineFactSource,
      },
    };
  });

  return updated.map((s) => validateShot(s, updated, manifest));
}

/**
 * 13. Reproduce Shot parameters to workstation console.
 * Distinct from RETRY: Copies configuration for human review without executing.
 */
export function reproduceShotToConsole(shot: Shot) {
  return {
    generationType: shot.generationType,
    prompt: shot.prompt,
    selectedModel: shot.selectedModel,
    selectedProvider: shot.selectedProvider,
    selectedAspectRatio: shot.aspectRatio,
    selectedResolution: shot.resolution,
    selectedDuration: shot.duration,
    startFrameUrl: shot.startFrame,
    endFrameUrl: shot.endFrame,
    referenceImageUrl: shot.referenceAssets?.[0],
  };
}

/**
 * 14. Generate Read-Only Execution Plan for a Sequence (Section 18).
 * Never triggers background dispatch; produces deterministic inspectable plan.
 */
export function generateSequenceExecutionPlan(sequence: Sequence): SequenceExecutionPlan {
  const shots = sequence.shots || [];
  const planItems: SequenceExecutionPlanItem[] = shots.map((shot) => ({
    order: shot.order,
    shotId: shot.id,
    title: shot.title,
    endpoint: 'POST /creator/generate',
    payload: {
      prompt: shot.prompt,
      generation_type: shot.generationType,
      model: shot.selectedModel,
      provider: shot.selectedProvider,
      aspect_ratio: shot.aspectRatio,
      resolution: shot.resolution,
      duration: shot.duration,
      start_frame: shot.startFrame,
      end_frame: shot.endFrame,
      reference_image: shot.referenceAssets?.[0],
    },
    dependencies: shot.dependencyShotIds || [],
    status: shot.status,
    readiness: shot.readiness,
  }));

  const totalDuration = shots.reduce((acc, s) => acc + (s.duration || (s.generationType === 'image' ? 0 : 5)), 0);

  return {
    sequenceId: sequence.id,
    sequenceTitle: sequence.title,
    totalShots: shots.length,
    totalDuration,
    planStatus: sequence.status,
    shots: planItems,
  };
}

/**
 * 15. Factory: Create initial default project and sequence.
 */
export function createDefaultProject(manifest: CapabilitiesManifest | null): Project {
  const defaultImageModel =
    manifest?.models.image.find((m) => m.default)?.id ||
    manifest?.models.image[0]?.id ||
    'black-forest-labs/FLUX.1.1-pro';

  const defaultVideoModel =
    manifest?.models.image_to_video.find((m) => m.default)?.id ||
    manifest?.models.image_to_video[0]?.id ||
    'kling-ai/kling-v1.6-pro';

  const shot1: Shot = {
    id: 'shot-001',
    sequenceId: 'seq-001',
    order: 1,
    title: 'Establishing Shot // Obsidian Station',
    description: 'Wide exterior of deep space orbital station',
    prompt: 'Cinematic wide establishing shot of an obsidian command station in deep space, REC.709 color grade',
    generationType: 'image',
    selectedModel: defaultImageModel,
    selectedProvider: 'together',
    aspectRatio: '16:9',
    resolution: '1344x768',
    dependencyShotIds: [],
    referenceAssets: [],
    characterRequirements: {
      characterId: 'char-commander',
      name: 'Commander Aria',
      declaredAppearance: 'Cybernetic flight suit, silver insignia',
      wardrobe: 'Obsidian carbon flight suit',
      hair: 'Short dark tactical cut',
      source: 'USER_CONFIGURATION',
    },
    environmentRequirements: {
      location: 'Orbital Perimeter',
      environmentType: 'Deep Space',
      timeOfDay: 'Starlight',
      weather: 'Vacuum',
      lighting: 'Cold rim light from blue star',
      source: 'USER_CONFIGURATION',
    },
    visualRequirements: {
      aspectRatio: '16:9',
      resolution: '1344x768',
      visualStyle: 'Cinematic Hard Sci-Fi',
      source: 'USER_CONFIGURATION',
    },
    temporalRequirements: {
      order: 1,
      durationSeconds: 5,
      requiresStartFrameFromPredecessor: false,
      source: 'USER_CONFIGURATION',
    },
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
      visual: { status: 'PASS', detail: 'Initial shot format declared (16:9)', source: 'USER_CONFIGURATION' },
      temporal: { status: 'PASS', detail: 'Temporal sequence ordering valid (Shot #1)', source: 'USER_CONFIGURATION' },
      startFrame: { status: 'NOT_APPLICABLE', detail: 'START FRAME NOT APPLICABLE FOR CURRENT MODE', source: 'CAPABILITY_MANIFEST' },
    },
  };

  const shot2: Shot = {
    id: 'shot-002',
    sequenceId: 'seq-001',
    order: 2,
    title: 'Approach Vector // Motion Push',
    description: 'Slow push into the command bay',
    prompt: 'Slow cinematic camera push-in towards the illuminated command bridge, atmospheric thruster gas',
    generationType: 'image_to_video',
    selectedModel: defaultVideoModel,
    selectedProvider: 'fal',
    aspectRatio: '16:9',
    resolution: '1344x768',
    duration: 5,
    dependencyShotIds: ['shot-001'],
    predecessorShotId: 'shot-001',
    referenceAssets: [],
    characterRequirements: {
      characterId: 'char-commander',
      name: 'Commander Aria',
      wardrobe: 'Obsidian carbon flight suit',
      hair: 'Short dark tactical cut',
      source: 'USER_CONFIGURATION',
    },
    environmentRequirements: {
      location: 'Orbital Perimeter',
      environmentType: 'Deep Space',
      timeOfDay: 'Starlight',
      weather: 'Vacuum',
      lighting: 'Cold rim light from blue star',
      source: 'USER_CONFIGURATION',
    },
    visualRequirements: {
      aspectRatio: '16:9',
      resolution: '1344x768',
      visualStyle: 'Cinematic Hard Sci-Fi',
      source: 'USER_CONFIGURATION',
    },
    temporalRequirements: {
      order: 2,
      predecessorId: 'shot-001',
      durationSeconds: 5,
      requiresStartFrameFromPredecessor: true,
      source: 'USER_CONFIGURATION',
    },
    status: 'BLOCKED',
    readiness: 'BLOCKED',
    provenance: 'USER_CONFIGURATION',
    validationResults: {
      isValid: false,
      readiness: 'BLOCKED',
      reasons: ['DEPENDENCY shot-001 NOT COMPLETE', 'START FRAME REQUIRED: SOURCE SHOT OUTPUT NOT AVAILABLE'],
      reasonCodes: ['DEPENDENCY_NOT_SATISFIED', 'START_FRAME_REQUIRED'],
      preflightReady: false,
      dependenciesSatisfied: false,
      startFrameSatisfied: false,
    },
    continuityReport: {
      character: { status: 'PASS', detail: 'Character continuity verified (Commander Aria)', source: 'USER_CONFIGURATION' },
      environment: { status: 'PASS', detail: 'Environment continuity verified: Orbital Perimeter', source: 'USER_CONFIGURATION' },
      visual: { status: 'PASS', detail: 'Visual format consistent (16:9 @ 1344x768)', source: 'USER_CONFIGURATION' },
      temporal: { status: 'PASS', detail: 'Temporal sequence ordering valid (Shot #2)', source: 'USER_CONFIGURATION' },
      startFrame: {
        status: 'MISSING',
        sourceShotId: 'shot-001',
        detail: 'START FRAME REQUIRED: SOURCE SHOT OUTPUT NOT AVAILABLE',
        source: 'SYSTEM_STATE',
      },
    },
  };

  const initialShots = [shot1, shot2];
  const validatedShots = initialShots.map((s) => validateShot(s, initialShots, manifest));
  const seqEval = evaluateSequenceReadiness(validatedShots);

  const initialSequence: Sequence = {
    id: 'seq-001',
    sequenceId: 'seq-001',
    projectId: 'proj-001',
    order: 1,
    title: 'Sequence 01 // Orbital Infiltration',
    description: 'Establishing approach and entry vectors to deep space station',
    shots: validatedShots,
    status: seqEval.status,
    sequenceStatus: seqEval.status,
    statusReasons: seqEval.statusReasons,
    totalShots: seqEval.metrics.total,
    readyShots: seqEval.metrics.ready,
    blockedShots: seqEval.metrics.blocked,
    warningShots: seqEval.metrics.warning,
    inFlightShots: seqEval.metrics.inFlight,
    completeShots: seqEval.metrics.complete,
    completedShots: seqEval.metrics.complete,
    totalDurationSeconds: seqEval.metrics.totalDuration,
    totalDuration: seqEval.metrics.totalDuration,
    continuityWarnings: seqEval.metrics.continuityWarnings,
    sequencePreflightStatus: seqEval.status === 'BLOCKED' ? 'BLOCKED' : seqEval.status === 'READY' ? 'READY' : 'WARNING',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };

  return {
    id: 'proj-001',
    title: 'Project Nebula // AryaOS Production',
    description: 'Multi-shot cinematic sequence planning workstation',
    sequences: [initialSequence],
    activeSequenceId: 'seq-001',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}
