/**
 * AryaOS V1 — Spatial Intent Parser, Planner & Job Package Assembler
 * Phase 7: Deterministic compiler transforming raw user intentions into validated
 * sequence shots and formal Job Packages across the decision-to-execution boundary.
 */

import { CapabilitiesManifest, GenerationType, CreatorGeneratePayload } from '../types/creator';
import { Project, Shot, Sequence } from '../types/productionTimeline';
import { ProductionRecommendation } from '../types/productionDecision';
import { AryaIntent, AryaParsedDirectives, AryaJobPackage } from '../types/spatialIntent';
import { validateShot, evaluateSequenceReadiness } from './continuityEngine';

/**
 * 1. Deterministically parse natural language user commands into structured AryaIntent directives.
 */
export function parseUserCommand(
  rawInput: string,
  project?: Project,
  manifest?: CapabilitiesManifest | null
): AryaIntent {
  const trimmed = rawInput.trim();
  const lower = trimmed.toLowerCase();

  // A. Detect Duration
  let durationSeconds: number | undefined;
  const durationMatch = lower.match(/(\d+)\s*(?:-?\s*seconds?|-?\s*sec|\s*s)\b/);
  if (durationMatch) {
    const val = parseInt(durationMatch[1], 10);
    if (!isNaN(val) && val > 0 && val <= 60) {
      durationSeconds = val;
    }
  }

  // B. Detect Aspect Ratio: prioritize explicit aspect ratio tokens first
  let aspectRatio = '16:9';
  if (lower.includes('1:1')) {
    aspectRatio = '1:1';
  } else if (lower.includes('9:16')) {
    aspectRatio = '9:16';
  } else if (lower.includes('21:9')) {
    aspectRatio = '21:9';
  } else if (lower.includes('4:3')) {
    aspectRatio = '4:3';
  } else if (lower.includes('16:9')) {
    aspectRatio = '16:9';
  } else if (lower.includes('square')) {
    aspectRatio = '1:1';
  } else if (lower.includes('vertical')) {
    aspectRatio = '9:16';
  } else if (lower.includes('ultrawide') || lower.includes('anamorphic')) {
    aspectRatio = '21:9';
  } else if (lower.includes('portrait') && !lower.includes('photo portrait') && !lower.includes('portrait of')) {
    aspectRatio = '9:16';
  }

  // C. Detect Generation Type
  let generationType: GenerationType = 'video';
  const hasVideoExplicit =
    /\b(video|clip|animat|motion|sequence|movie|footage|film|tracking shot|dolly|pan|zoom|push|camera push)\b/.test(lower);
  const hasImageExplicit =
    /\b(image|still|photo|picture|render|poster|concept art|illustration|artwork|wallpaper|visual|cinematic still|drawing|painting)\b/.test(lower);
  const isI2VExplicit =
    /\b(image-to-video|image to video|i2v|animate this|animate shot|from image|from still|camera push on shot)\b/.test(lower);

  if (isI2VExplicit) {
    generationType = 'image_to_video';
  } else if (hasImageExplicit && !hasVideoExplicit) {
    generationType = 'image';
    durationSeconds = undefined; // images do not have duration
  } else if (hasVideoExplicit || durationSeconds !== undefined) {
    generationType = 'video';
    if (!durationSeconds) {
      durationSeconds = 5; // Default standard cinematic shot duration
    }
  } else {
    // Default to image generation for static scene/concept generation when no duration or video keywords
    generationType = 'image';
    durationSeconds = undefined;
  }

  // D. Extract Style Keywords
  const styleKeywords = [
    'cinematic',
    'photorealistic',
    'cyberpunk',
    'futuristic',
    'noir',
    'anime',
    'hyper-realistic',
    'documentary',
    'vaporwave',
    'surrealist',
    'monochrome',
  ];
  const matchedStyles = styleKeywords.filter((s) => lower.includes(s));
  const preferredStyle = matchedStyles.length > 0 ? matchedStyles.join(', ') : undefined;

  // E. Clean Prompt (strip out explicit command boilerplates like "Create a", "Generate a", "Make a")
  let cleanPrompt = trimmed
    .replace(/^(?:create|generate|make|produce|render|build)\s+(?:an?|the)?\s*/i, '')
    .trim();
  if (cleanPrompt.length === 0) {
    cleanPrompt = trimmed;
  }

  // F. Identify active sequence and predecessor continuity
  const activeSeq =
    project?.sequences?.find((s) => s.id === project.activeSequenceId) || project?.sequences?.[0];
  const priorShotsCount = activeSeq ? activeSeq.shots.length : 0;
  const inferredPredecessor = priorShotsCount > 0;

  const constraints: string[] = [];
  if (aspectRatio) constraints.push(`Aspect Ratio: ${aspectRatio}`);
  if (durationSeconds) constraints.push(`Duration: ${durationSeconds}s`);
  if (inferredPredecessor) {
    constraints.push(`Predecessor Continuity: Shot #${priorShotsCount}`);
  }

  const directives: AryaParsedDirectives = {
    cleanPrompt,
    generationType,
    durationSeconds,
    aspectRatio,
    preferredStyle,
    constraints,
    referenceRequirements: {
      requiresStartFrame: generationType === 'image_to_video',
      requiresEndFrame: false,
      requiresReferenceImage: generationType === 'image_to_video',
    },
    inferredPredecessor,
  };

  const intentId = `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

  return {
    id: intentId,
    rawInput: trimmed,
    timestamp: new Date().toISOString(),
    stage: 'INTENTION',
    projectId: project?.id || 'proj-default',
    sequenceId: activeSeq?.id || 'seq-01',
    directives,
  };
}

/**
 * 2. Deterministically compile an AryaIntent into a structured Shot inside the Project's active sequence.
 */
export function compileIntentToShot(
  intent: AryaIntent,
  project: Project,
  manifest?: CapabilitiesManifest | null,
  recommendedModel?: string,
  recommendedProvider?: string,
  targetSequenceId?: string
): { updatedProject: Project; targetShot: Shot } {
  const activeSeq =
    (targetSequenceId && project.sequences.find((s) => s.id === targetSequenceId)) ||
    project.sequences.find((s) => s.id === intent.sequenceId) ||
    project.sequences[0] || {
      id: 'seq-01',
      title: 'Sequence 01',
      order: 1,
      shots: [],
      status: 'READY',
      statusReasons: [],
      totalShots: 0,
      readyShots: 0,
      blockedShots: 0,
      inFlightShots: 0,
      completeShots: 0,
      totalDurationSeconds: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

  const nextOrder = activeSeq.shots.length + 1;
  const shotId = `shot-${Date.now().toString(36)}-${nextOrder}`;

  // Resolve default model/provider for mode if not explicitly recommended
  const modeModels = manifest?.models?.[intent.directives.generationType] || [];
  const defaultModelObj =
    modeModels.find((m) => m.configured && m.default) ||
    modeModels.find((m) => m.configured) ||
    modeModels.find((m) => m.default) ||
    modeModels[0];
  const isRecommendedModelValidForMode = Boolean(
    recommendedModel &&
      (manifest?.models?.[intent.directives.generationType]?.some((m) => m.id === recommendedModel) ||
        (intent.directives.generationType === 'image' &&
          !recommendedModel.toLowerCase().includes('kling') &&
          !recommendedModel.toLowerCase().includes('video')) ||
        (intent.directives.generationType === 'video' &&
          !recommendedModel.toLowerCase().includes('flux') &&
          !recommendedModel.toLowerCase().includes('image')))
  );

  const promptLower = intent.directives.cleanPrompt.toLowerCase();
  const isCameraMotionPrompt =
    promptLower.includes('camera') || promptLower.includes('push') || promptLower.includes('motion') || promptLower.includes('zoom');

  const defaultVideoModel = isCameraMotionPrompt ? 'camera-push' : 'kling-video';
  const defaultVideoProvider = isCameraMotionPrompt ? 'camera_motion' : 'kling';

  const modelToUse =
    (isRecommendedModelValidForMode ? recommendedModel : undefined) ||
    defaultModelObj?.id ||
    (intent.directives.generationType === 'image' ? 'flux-pro/v1.1' : defaultVideoModel);
  const providerToUse =
    (isRecommendedModelValidForMode ? recommendedProvider : undefined) ||
    defaultModelObj?.provider ||
    (intent.directives.generationType === 'image' ? 'fal' : defaultVideoProvider);

  // Check predecessor
  const lastShot = activeSeq.shots[activeSeq.shots.length - 1];
  const predecessorShotId = intent.directives.inferredPredecessor && lastShot ? lastShot.id : undefined;
  const startFrameUrl = predecessorShotId && lastShot?.outputAssetUrl ? lastShot.outputAssetUrl : undefined;

  const newShot: Shot = {
    id: shotId,
    sequenceId: activeSeq.id,
    order: nextOrder,
    title: `Shot ${String(nextOrder).padStart(2, '0')} // ${intent.directives.cleanPrompt.slice(0, 32)}...`,
    prompt: intent.directives.cleanPrompt,
    generationType: intent.directives.generationType,
    selectedModel: modelToUse,
    selectedProvider: providerToUse,
    aspectRatio: intent.directives.aspectRatio,
    duration: intent.directives.durationSeconds,
    startFrame: startFrameUrl,
    dependencyShotIds: predecessorShotId ? [predecessorShotId] : [],
    predecessorShotId,
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
      environment: { status: 'PASS', detail: 'ENVIRONMENT PROMPT ATTACHED', source: 'USER_CONFIGURATION' },
      visual: {
        status: 'PASS',
        detail: `Visual format declared (${intent.directives.aspectRatio})`,
        source: 'USER_CONFIGURATION',
      },
      temporal: {
        status: 'PASS',
        detail: `Temporal sequence ordering valid (Shot #${nextOrder})`,
        source: 'USER_CONFIGURATION',
      },
      startFrame: {
        status: intent.directives.generationType === 'image_to_video'
          ? (startFrameUrl ? 'PROVIDED' : 'MISSING')
          : 'NOT_APPLICABLE',
        detail: predecessorShotId
          ? `Linked to predecessor Shot ${predecessorShotId}`
          : 'Root keyframe shot',
        source: 'USER_CONFIGURATION',
      },
    },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };

  const updatedShots = [...activeSeq.shots, newShot];
  const validatedShots = updatedShots.map((s) => validateShot(s, updatedShots, manifest ?? null));
  const evalSeq = evaluateSequenceReadiness(validatedShots);

  const updatedSequences = project.sequences.map((seq) => {
    if (seq.id !== activeSeq.id) return seq;
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
      totalDurationSeconds: validatedShots.reduce((acc, s) => acc + (s.duration || 0), 0),
    };
  });

  const updatedProject: Project = {
    ...project,
    activeShotId: shotId,
    sequences: updatedSequences,
    updatedAt: new Date().toISOString(),
  };

  const targetShot = validatedShots.find((s) => s.id === shotId) || newShot;

  return {
    updatedProject,
    targetShot,
  };
}

/**
 * 3. Assemble the formal AryaJobPackage contract bridging AryaOS decision-making to the execution layer.
 */
export function assembleJobPackage(
  shot: Shot,
  project: Project,
  manifest: CapabilitiesManifest | null,
  recommendation: ProductionRecommendation | null,
  intentId?: string
): AryaJobPackage {
  const currentModeModels = manifest?.models?.[shot.generationType] || [];
  const modelObj = currentModeModels.find((m) => m.id === shot.selectedModel);

  const recommendationPreflightReady = recommendation ? recommendation.preflight.ready : true;
  const shotPreflightReady = shot.validationResults ? shot.validationResults.isValid : true;
  const isPreflightReady = shotPreflightReady && recommendationPreflightReady;
  const preflightReasons = Array.from(
    new Set([
      ...(shot.validationResults ? shot.validationResults.reasons : []),
      ...(recommendation ? recommendation.preflight.reasons : []),
    ])
  );
  const provider = shot.selectedProvider || modelObj?.provider || 'together';
  const modelName = modelObj?.name || shot.selectedModel;
  const availability = modelObj ? (modelObj.configured ? 'AVAILABLE' : 'UNAVAILABLE') : 'UNAVAILABLE';
  const estimatedCostUsd =
    recommendation?.explanation?.cost?.recentCost ??
    recommendation?.explanation?.cost?.avgKnownCost ??
    undefined;

  const executionPayload: CreatorGeneratePayload = {
    generation_type: shot.generationType,
    prompt: shot.prompt,
    model: shot.selectedModel,
    provider,
    aspect_ratio: shot.aspectRatio,
    resolution: shot.resolution,
    duration_seconds: shot.duration,
    start_frame_url: shot.startFrame,
    end_frame_url: shot.endFrame,
    reference_image_url: shot.referenceAssets?.[0],
  };

  const jobPackageId = `pkg-${shot.id}-${Date.now().toString(36)}`;

  return {
    jobPackageId,
    intentId,
    createdAt: new Date().toISOString(),
    projectId: project.id,
    sequenceId: shot.sequenceId,
    shotId: shot.id,
    shotOrder: shot.order,
    plan: {
      title: shot.title,
      prompt: shot.prompt,
      generationType: shot.generationType,
      durationSeconds: shot.duration,
      mode: shot.generationType,
      fps: 25,
      predecessorShotId: shot.predecessorShotId,
      successorShotId: shot.successorShotId,
      dependencies: shot.dependencyShotIds || [],
      isFirstShotInSequence: shot.order === 1,
    },
    references: {
      firstFrame: shot.startFrame,
      lastFrame: shot.endFrame,
      startFrameUrl: shot.startFrame,
      endFrameUrl: shot.endFrame,
      referenceImageUrl: shot.referenceAssets?.[0],
      referenceAssets: shot.referenceAssets || [],
      visualIdentityReferences: shot.continuityRequirements?.character?.visualIdentityReferences,
    },
    modelRoute: {
      provider,
      model: shot.selectedModel,
      modelName,
      mode: shot.generationType,
      preflightReady: isPreflightReady,
      preflightReasons,
      availability,
      estimatedCostUsd,
      qualityTier: recommendation?.explanation?.quality?.label,
    },
    shotConfiguration: {
      aspectRatio: shot.aspectRatio,
      resolution: shot.resolution,
      duration: shot.duration,
      fps: 25,
    },
    continuityRequirements: {
      character: shot.continuityReport?.character?.status || 'UNAVAILABLE',
      environment: shot.continuityReport?.environment?.status || 'PASS',
      visual: shot.continuityReport?.visual?.status || 'PASS',
      temporal: shot.continuityReport?.temporal?.status || 'PASS',
      startFrame: shot.continuityReport?.startFrame?.status || 'NOT_APPLICABLE',
    },
    outputRequirements: {
      destination: 'ARYAOS_CORRIDOR_STREAM',
      targetFormat: shot.generationType === 'image' ? 'image/png' : 'video/mp4',
    },
    decisionBoundary: 'ARYAOS_ORCHESTRATION_VALIDATED',
    executionPayload,
  };
}
