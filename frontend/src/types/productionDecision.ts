import { GenerationType, CapabilitiesManifest } from './creator';
import { ProductionRun, SystemOperationalState } from './productionRun';

/**
 * Stage 9: Stable machine-readable reason codes for decision outcomes.
 */
export type DecisionReasonCode =
  | 'CAPABILITY_MANIFEST_UNAVAILABLE'
  | 'GENERATION_TYPE_UNSUPPORTED'
  | 'MODEL_UNSUPPORTED'
  | 'MODEL_UNAVAILABLE'
  | 'PROMPT_REQUIRED'
  | 'PROMPT_TOO_LONG'
  | 'ASPECT_RATIO_UNSUPPORTED'
  | 'RESOLUTION_UNSUPPORTED'
  | 'DURATION_UNSUPPORTED'
  | 'START_FRAME_REQUIRED'
  | 'END_FRAME_UNSUPPORTED'
  | 'CONFIGURATION_READY'
  | 'COST_DATA_UNAVAILABLE'
  | 'QUALITY_DATA_UNAVAILABLE'
  | 'PROVIDER_UNAVAILABLE';

/**
 * Stage 9: Provenance source attribution for all facts surfaced in decision intelligence.
 */
export type FactSource =
  | 'CAPABILITY_MANIFEST'
  | 'HISTORICAL_RUN'
  | 'USER_CONFIGURATION'
  | 'SYSTEM_STATE'
  | 'UNAVAILABLE';

export interface AttributedFact {
  id: string;
  label: string;
  value: string;
  source: FactSource;
  detail?: string;
}

export interface DecisionCategoryItem {
  id: string;
  label: string;
  status: 'PASSED' | 'FAILED' | 'WARNING';
  reasonCode: DecisionReasonCode;
  detail?: string;
  source: FactSource;
}

export interface DecisionCategorization {
  hardBlocks: DecisionCategoryItem[];
  warnings: DecisionCategoryItem[];
  facts: AttributedFact[];
  userDecision: {
    status: 'READY' | 'BLOCKED' | 'WARNING';
    directive: string;
    requiresConfirmation: boolean;
  };
}

export interface PreflightSummaryItem {
  key: string;
  label: string;
  value: string;
  status:
    | 'SUPPORTED'
    | 'NOT_SUPPORTED'
    | 'VALID'
    | 'REQUIRED'
    | 'NOT_REQUIRED'
    | 'MISSING'
    | 'READY'
    | 'BLOCKED'
    | 'WARNING'
    | 'NONE';
}

export interface ExecutionPayloadPreview {
  mode: GenerationType;
  model: string;
  modelName: string;
  provider: string;
  aspectRatio: string;
  resolution: string;
  promptStatus: 'READY' | 'EMPTY' | 'TRUNCATED';
  promptPreview: string;
  referenceStatus: 'NONE' | 'ATTACHED' | 'REQUIRED';
  startFrameStatus: 'NONE' | 'ATTACHED' | 'REQUIRED';
  endFrameStatus: 'NONE' | 'ATTACHED';
  durationSeconds?: number;
  dispatchSteps: string[];
}

export interface NormalizedCapabilityEntry {
  provider: string;
  model: string;
  modelName: string;
  supportedMode: GenerationType;
  supportedAspectRatios: string[];
  supportedResolutions: string[];
  supportedDurations: number[];
  referenceSupport: boolean | 'UNAVAILABLE';
  startFrameSupport: boolean | 'UNAVAILABLE';
  endFrameSupport: boolean | 'UNAVAILABLE';
  availability: 'AVAILABLE' | 'UNAVAILABLE';
  costTier: number | 'UNAVAILABLE';
  configured: boolean;
}

export interface ConfigurationParameters {
  generationType: GenerationType;
  prompt?: string;
  model: string;
  provider?: string;
  aspectRatio: string;
  resolution?: string;
  duration?: number;
  referenceImageUrl?: string;
  startFrameUrl?: string;
  endFrameUrl?: string;
  requiresReference?: boolean;
}

export interface PreflightCheckItem {
  id: string;
  label: string;
  status: 'PASSED' | 'FAILED' | 'SKIPPED' | 'WARNING';
  detail?: string;
  reasonCode?: DecisionReasonCode;
  source?: FactSource;
}

export interface PreflightValidationResult {
  ready: boolean;
  status: 'READY' | 'BLOCKED' | 'WARNING';
  reason?: string;
  reasons: string[];
  reasonCode?: DecisionReasonCode;
  reasonCodes: DecisionReasonCode[];
  checks: PreflightCheckItem[];
}

export interface ProductionCostDecision {
  avgKnownCost: number | null;
  recentCost: number | null;
  totalKnownCost: number;
  runCount: number;
  hasCostData: boolean;
  displayStatus: string;
  source: FactSource;
  reasonCode?: DecisionReasonCode;
}

export interface ProductionQualityDecision {
  qualityScore: number | null;
  qualityDataAvailable: boolean;
  label: 'KNOWN' | 'UNKNOWN' | 'NOT SUPPORTED' | 'UNAVAILABLE';
  displayText: string;
  source: FactSource;
  reasonCode?: DecisionReasonCode;
}

export interface ProductionDecisionExplanation {
  modelName: string;
  modelId: string;
  provider: string;
  availability: 'AVAILABLE' | 'UNAVAILABLE';
  supportedAspectRatios: string[];
  supportedResolutions: string[];
  supportedDurations: number[];
  startFrameSupport: 'SUPPORTED' | 'NOT SUPPORTED' | 'UNAVAILABLE';
  endFrameSupport: 'SUPPORTED' | 'NOT SUPPORTED' | 'UNAVAILABLE';
  referenceSupport: 'SUPPORTED' | 'OPTIONAL' | 'REQUIRED' | 'NOT SUPPORTED' | 'UNAVAILABLE';
  cost: ProductionCostDecision;
  quality: ProductionQualityDecision;
}

export interface ProductionRecommendation {
  status: 'READY' | 'BLOCKED' | 'WARNING';
  directive: string;
  reason?: string;
  reasons: string[];
  reasonCode?: DecisionReasonCode;
  reasonCodes: DecisionReasonCode[];
  preflight: PreflightValidationResult;
  explanation: ProductionDecisionExplanation;
  categorization: DecisionCategorization;
  preflightSummary: PreflightSummaryItem[];
  executionPreview: ExecutionPayloadPreview;
}

/**
 * 1. Build normalized capability decision matrix from backend capabilities manifest.
 * Captures ONLY factual fields actually supplied by the backend.
 * Missing fields default to 'UNAVAILABLE'.
 */
export function buildCapabilityDecisionMatrix(
  manifest: CapabilitiesManifest | null
): NormalizedCapabilityEntry[] {
  if (!manifest || !manifest.models) return [];

  const matrix: NormalizedCapabilityEntry[] = [];
  const aspectRatios = (manifest.aspect_ratios || []).map((ar) => ar.id);
  const resolutions = (manifest.resolutions || []).map((r) => r.id);
  const durations = (manifest.durations || []).map((d) => d.value);

  const modes: GenerationType[] = ['image', 'video', 'image_to_video'];
  for (const mode of modes) {
    const models = manifest.models[mode] || [];
    for (const m of models) {
      matrix.push({
        provider: m.provider || 'UNAVAILABLE',
        model: m.id,
        modelName: m.name || m.id,
        supportedMode: mode,
        supportedAspectRatios: aspectRatios,
        supportedResolutions: resolutions,
        supportedDurations: mode === 'image' ? [] : durations,
        referenceSupport: mode === 'image' ? true : mode === 'image_to_video' ? true : false,
        startFrameSupport: typeof m.start_frame === 'boolean' ? m.start_frame : 'UNAVAILABLE',
        endFrameSupport: typeof m.end_frame === 'boolean' ? m.end_frame : 'UNAVAILABLE',
        availability: m.configured ? 'AVAILABLE' : 'UNAVAILABLE',
        costTier: typeof m.cost_tier === 'number' ? m.cost_tier : 'UNAVAILABLE',
        configured: Boolean(m.configured),
      });
    }
  }

  return matrix;
}

/**
 * 2. Pre-flight configuration validation engine.
 * Pure deterministic evaluation of configuration against capability constraints.
 */
export function validateConfiguration(
  config: ConfigurationParameters,
  manifest: CapabilitiesManifest | null
): PreflightValidationResult {
  const checks: PreflightCheckItem[] = [];
  const reasons: string[] = [];
  const reasonCodes: DecisionReasonCode[] = [];

  if (!manifest) {
    return {
      ready: false,
      status: 'BLOCKED',
      reason: 'CAPABILITY_MANIFEST_UNAVAILABLE',
      reasons: ['Capability manifest unavailable'],
      reasonCode: 'CAPABILITY_MANIFEST_UNAVAILABLE',
      reasonCodes: ['CAPABILITY_MANIFEST_UNAVAILABLE'],
      checks: [
        {
          id: 'manifest',
          label: 'CAPABILITY MANIFEST LOADED',
          status: 'FAILED',
          detail: 'Manifest not loaded',
          reasonCode: 'CAPABILITY_MANIFEST_UNAVAILABLE',
          source: 'SYSTEM_STATE',
        },
      ],
    };
  }

  // Check 1: Mode supported
  const validModes = manifest.generation_types?.length
    ? manifest.generation_types.map((t) => t.id)
    : (['image', 'video', 'image_to_video'] as GenerationType[]);
  const isModeSupported =
    validModes.includes(config.generationType) || Boolean(manifest.models?.[config.generationType]?.length);
  if (isModeSupported) {
    checks.push({
      id: 'mode',
      label: 'MODE SUPPORTED',
      status: 'PASSED',
      reasonCode: 'CONFIGURATION_READY',
      source: 'CAPABILITY_MANIFEST',
    });
  } else {
    checks.push({
      id: 'mode',
      label: 'MODE SUPPORTED',
      status: 'FAILED',
      detail: `Mode '${config.generationType}' unsupported`,
      reasonCode: 'GENERATION_TYPE_UNSUPPORTED',
      source: 'CAPABILITY_MANIFEST',
    });
    reasons.push(`Generation mode '${config.generationType}' is not supported by backend`);
    reasonCodes.push('GENERATION_TYPE_UNSUPPORTED');
  }

  // Check 2: Model supported in current mode & availability
  const currentModeModels = manifest.models?.[config.generationType] || [];
  const selectedModelObj = currentModeModels.find((m) => m.id === config.model);
  if (selectedModelObj) {
    if (selectedModelObj.configured === false) {
      checks.push({
        id: 'model',
        label: 'MODEL AVAILABLE',
        status: 'FAILED',
        detail: 'MODEL NO LONGER AVAILABLE',
        reasonCode: 'MODEL_UNAVAILABLE',
        source: 'CAPABILITY_MANIFEST',
      });
      reasons.push('MODEL NO LONGER AVAILABLE');
      reasonCodes.push('MODEL_UNAVAILABLE');
    } else {
      checks.push({
        id: 'model',
        label: 'MODEL SUPPORTED',
        status: 'PASSED',
        detail: selectedModelObj.name,
        reasonCode: 'CONFIGURATION_READY',
        source: 'CAPABILITY_MANIFEST',
      });
    }
  } else {
    const existsOtherMode = Object.values(manifest.models || {})
      .flat()
      .some((m) => m.id === config.model);
    const detail = existsOtherMode
      ? `Model '${config.model}' is incompatible with ${config.generationType} mode`
      : `MODEL NO LONGER AVAILABLE (${config.model})`;
    const rCode: DecisionReasonCode = existsOtherMode ? 'MODEL_UNSUPPORTED' : 'MODEL_UNAVAILABLE';
    checks.push({
      id: 'model',
      label: 'MODEL SUPPORTED',
      status: 'FAILED',
      detail,
      reasonCode: rCode,
      source: 'CAPABILITY_MANIFEST',
    });
    reasons.push(detail);
    reasonCodes.push(rCode);
  }

  // Check 3: Prompt validation (if provided)
  if (typeof config.prompt === 'string') {
    if (config.prompt.trim() === '') {
      checks.push({
        id: 'prompt',
        label: 'PROMPT VALID',
        status: 'FAILED',
        detail: 'PROMPT REQUIRED',
        reasonCode: 'PROMPT_REQUIRED',
        source: 'USER_CONFIGURATION',
      });
      reasons.push('PROMPT REQUIRED');
      reasonCodes.push('PROMPT_REQUIRED');
    } else if (config.prompt.length > 2000) {
      checks.push({
        id: 'prompt',
        label: 'PROMPT VALID',
        status: 'FAILED',
        detail: 'PROMPT TOO LONG',
        reasonCode: 'PROMPT_TOO_LONG',
        source: 'USER_CONFIGURATION',
      });
      reasons.push('PROMPT TOO LONG');
      reasonCodes.push('PROMPT_TOO_LONG');
    } else {
      checks.push({
        id: 'prompt',
        label: 'PROMPT VALID',
        status: 'PASSED',
        reasonCode: 'CONFIGURATION_READY',
        source: 'USER_CONFIGURATION',
      });
    }
  }

  // Check 4: Aspect Ratio supported
  const validAspectRatios = (manifest.aspect_ratios || []).map((ar) => ar.id);
  if (validAspectRatios.includes(config.aspectRatio)) {
    checks.push({
      id: 'aspect_ratio',
      label: 'ASPECT RATIO SUPPORTED',
      status: 'PASSED',
      reasonCode: 'CONFIGURATION_READY',
      source: 'CAPABILITY_MANIFEST',
    });
  } else {
    checks.push({
      id: 'aspect_ratio',
      label: 'ASPECT RATIO SUPPORTED',
      status: 'FAILED',
      detail: `Aspect ratio '${config.aspectRatio}' unsupported`,
      reasonCode: 'ASPECT_RATIO_UNSUPPORTED',
      source: 'CAPABILITY_MANIFEST',
    });
    reasons.push(`Aspect ratio '${config.aspectRatio}' is not supported`);
    reasonCodes.push('ASPECT_RATIO_UNSUPPORTED');
  }

  // Check 5: Resolution supported (if specified)
  if (config.resolution) {
    const validResolutions = (manifest.resolutions || []).map((r) => r.id);
    if (validResolutions.includes(config.resolution)) {
      checks.push({
        id: 'resolution',
        label: 'RESOLUTION SUPPORTED',
        status: 'PASSED',
        reasonCode: 'CONFIGURATION_READY',
        source: 'CAPABILITY_MANIFEST',
      });
    } else {
      checks.push({
        id: 'resolution',
        label: 'RESOLUTION SUPPORTED',
        status: 'FAILED',
        detail: `Resolution '${config.resolution}' unsupported`,
        reasonCode: 'RESOLUTION_UNSUPPORTED',
        source: 'CAPABILITY_MANIFEST',
      });
      reasons.push(`Resolution '${config.resolution}' is not supported`);
      reasonCodes.push('RESOLUTION_UNSUPPORTED');
    }
  }

  // Check 6: Duration supported (if video or image_to_video)
  if (config.generationType === 'video' || config.generationType === 'image_to_video') {
    if (typeof config.duration === 'number') {
      const validDurations = (manifest.durations || []).map((d) => d.value);
      if (validDurations.includes(config.duration)) {
        checks.push({
          id: 'duration',
          label: 'DURATION SUPPORTED',
          status: 'PASSED',
          reasonCode: 'CONFIGURATION_READY',
          source: 'CAPABILITY_MANIFEST',
        });
      } else {
        checks.push({
          id: 'duration',
          label: 'DURATION SUPPORTED',
          status: 'FAILED',
          detail: `Duration ${config.duration}s unsupported`,
          reasonCode: 'DURATION_UNSUPPORTED',
          source: 'CAPABILITY_MANIFEST',
        });
        reasons.push(`Duration ${config.duration}s is not supported`);
        reasonCodes.push('DURATION_UNSUPPORTED');
      }
    }
  }

  // Check 7: Required reference conditioning
  if (config.requiresReference) {
    if (config.referenceImageUrl) {
      checks.push({
        id: 'reference',
        label: 'REFERENCE AVAILABLE',
        status: 'PASSED',
        reasonCode: 'CONFIGURATION_READY',
        source: 'USER_CONFIGURATION',
      });
    } else {
      checks.push({
        id: 'reference',
        label: 'REFERENCE AVAILABLE',
        status: 'FAILED',
        detail: 'REFERENCE REQUIRED',
        reasonCode: 'START_FRAME_REQUIRED',
        source: 'USER_CONFIGURATION',
      });
      reasons.push('Reference image is required for this conditioning');
      reasonCodes.push('START_FRAME_REQUIRED');
    }
  }

  // Check 8: Start Frame conditioning for image_to_video
  if (config.generationType === 'image_to_video') {
    const hasStartFrame = Boolean(config.startFrameUrl || config.referenceImageUrl);
    if (hasStartFrame) {
      checks.push({
        id: 'start_frame',
        label: 'START FRAME AVAILABLE',
        status: 'PASSED',
        reasonCode: 'CONFIGURATION_READY',
        source: 'USER_CONFIGURATION',
      });
    } else {
      checks.push({
        id: 'start_frame',
        label: 'START FRAME AVAILABLE',
        status: 'FAILED',
        detail: 'START FRAME REQUIRED',
        reasonCode: 'START_FRAME_REQUIRED',
        source: 'USER_CONFIGURATION',
      });
      reasons.push('START FRAME REQUIRED');
      reasonCodes.push('START_FRAME_REQUIRED');
    }
  }

  // Check 9: End Frame conditioning
  if (config.endFrameUrl) {
    if (selectedModelObj && selectedModelObj.end_frame) {
      checks.push({
        id: 'end_frame',
        label: 'END FRAME SUPPORTED',
        status: 'PASSED',
        reasonCode: 'CONFIGURATION_READY',
        source: 'CAPABILITY_MANIFEST',
      });
    } else {
      checks.push({
        id: 'end_frame',
        label: 'END FRAME SUPPORTED',
        status: 'FAILED',
        detail: 'END FRAME UNSUPPORTED (V1 Contract)',
        reasonCode: 'END_FRAME_UNSUPPORTED',
        source: 'CAPABILITY_MANIFEST',
      });
      reasons.push('End frame is not supported by this model (V1 Contract)');
      reasonCodes.push('END_FRAME_UNSUPPORTED');
    }
  }

  const isReady = checks.every((c) => c.status === 'PASSED' || c.status === 'SKIPPED');
  const primaryReason = reasons[0];
  const primaryReasonCode: DecisionReasonCode = isReady
    ? 'CONFIGURATION_READY'
    : reasonCodes[0] || 'MODEL_UNSUPPORTED';

  return {
    ready: isReady,
    status: isReady ? 'READY' : 'BLOCKED',
    reason: primaryReason,
    reasons,
    reasonCode: primaryReasonCode,
    reasonCodes: isReady ? ['CONFIGURATION_READY'] : reasonCodes,
    checks,
  };
}

/**
 * 3. Cost-aware factual decision support derived from real historical run costs.
 * Never estimates or fabricates pricing.
 */
export function deriveCostDecisionSupport(
  modelId: string,
  provider: string,
  historicalRuns: ProductionRun[]
): ProductionCostDecision {
  const matchingRuns = historicalRuns.filter((r) => {
    const modelMatches = r.model === modelId || r.requestedModel === modelId || r.actualModel === modelId;
    const providerMatches =
      !provider ||
      r.provider === provider ||
      r.requestedProvider === provider ||
      r.actualProvider === provider;
    const cost = r.costUsd !== undefined ? r.costUsd : r.cost;
    return (modelMatches || providerMatches) && typeof cost === 'number' && cost > 0;
  });

  if (matchingRuns.length === 0) {
    return {
      avgKnownCost: null,
      recentCost: null,
      totalKnownCost: 0,
      runCount: 0,
      hasCostData: false,
      displayStatus: 'COST COMPARISON UNAVAILABLE',
      source: 'UNAVAILABLE',
      reasonCode: 'COST_DATA_UNAVAILABLE',
    };
  }

  const total = matchingRuns.reduce((sum, r) => sum + (r.costUsd ?? r.cost ?? 0), 0);
  const avg = total / matchingRuns.length;
  const recentRun = matchingRuns[0];
  const recentCost = recentRun ? (recentRun.costUsd ?? recentRun.cost ?? null) : null;

  return {
    avgKnownCost: avg,
    recentCost,
    totalKnownCost: total,
    runCount: matchingRuns.length,
    hasCostData: true,
    displayStatus: `$${avg.toFixed(4)}`,
    source: 'HISTORICAL_RUN',
  };
}

/**
 * 4. Quality-aware decision support derived strictly from existing verified metrics.
 * If metrics are absent, surfaces UNAVAILABLE without fabricating scores.
 */
export function deriveQualityDecisionSupport(
  modelId: string,
  historicalRuns: ProductionRun[]
): ProductionQualityDecision {
  const matchingRun = historicalRuns.find((r) => {
    const modelMatches = r.model === modelId || r.requestedModel === modelId || r.actualModel === modelId;
    return modelMatches && typeof (r as any).qualityScore === 'number';
  });

  if (matchingRun && typeof (matchingRun as any).qualityScore === 'number') {
    const score = (matchingRun as any).qualityScore;
    return {
      qualityScore: score,
      qualityDataAvailable: true,
      label: 'KNOWN',
      displayText: `Score: ${score}/100`,
      source: 'HISTORICAL_RUN',
    };
  }

  return {
    qualityScore: null,
    qualityDataAvailable: false,
    label: 'UNAVAILABLE',
    displayText: 'QUALITY DATA UNAVAILABLE',
    source: 'UNAVAILABLE',
    reasonCode: 'QUALITY_DATA_UNAVAILABLE',
  };
}

/**
 * 5. Deterministic Operational Production Recommendation Engine.
 * Never claims subjective superiority (no "best", "fastest", "optimal").
 */
export function deriveProductionRecommendation(
  config: ConfigurationParameters,
  manifest: CapabilitiesManifest | null,
  operationalState: SystemOperationalState,
  historicalRuns: ProductionRun[]
): ProductionRecommendation {
  const preflight = validateConfiguration(config, manifest);

  const currentModeModels = manifest?.models?.[config.generationType] || [];
  const selectedModelObj = currentModeModels.find((m) => m.id === config.model);

  const cost = deriveCostDecisionSupport(
    config.model,
    selectedModelObj?.provider || config.provider || '',
    historicalRuns
  );

  const quality = deriveQualityDecisionSupport(config.model, historicalRuns);

  const supportedAspectRatios = (manifest?.aspect_ratios || []).map((ar) => ar.id);
  const supportedResolutions = (manifest?.resolutions || []).map((r) => r.id);
  const supportedDurations = (manifest?.durations || []).map((d) => d.value);

  const startFrameSupport = selectedModelObj
    ? selectedModelObj.start_frame
      ? 'SUPPORTED'
      : 'NOT SUPPORTED'
    : 'UNAVAILABLE';

  const endFrameSupport = selectedModelObj
    ? selectedModelObj.end_frame
      ? 'SUPPORTED'
      : 'NOT SUPPORTED'
    : 'UNAVAILABLE';

  const referenceSupport =
    config.generationType === 'image'
      ? 'OPTIONAL'
      : config.generationType === 'image_to_video'
      ? 'REQUIRED'
      : 'NOT SUPPORTED';

  const explanation: ProductionDecisionExplanation = {
    modelName: selectedModelObj?.name || config.model || 'UNAVAILABLE',
    modelId: config.model || 'UNAVAILABLE',
    provider: selectedModelObj?.provider || config.provider || 'UNAVAILABLE',
    availability: selectedModelObj
      ? selectedModelObj.configured
        ? 'AVAILABLE'
        : 'UNAVAILABLE'
      : 'UNAVAILABLE',
    supportedAspectRatios,
    supportedResolutions,
    supportedDurations,
    startFrameSupport,
    endFrameSupport,
    referenceSupport,
    cost,
    quality,
  };

  let status: 'READY' | 'BLOCKED' | 'WARNING';
  let directive: string;

  if (!preflight.ready) {
    status = 'BLOCKED';
    directive = 'EXECUTION BLOCKED';
  } else if (operationalState === 'DEGRADED') {
    status = 'WARNING';
    directive = 'READY FOR EXECUTION (SYSTEM DEGRADED)';
  } else if (operationalState === 'ERROR') {
    status = 'WARNING';
    directive = 'READY FOR EXECUTION (SYSTEM ERROR DETECTED)';
  } else {
    status = 'READY';
    directive = 'READY FOR EXECUTION';
  }

  // Stage 9: Decision Categorization (HARD BLOCK, WARNING, FACT, USER DECISION)
  const hardBlocks: DecisionCategoryItem[] = preflight.checks
    .filter((c) => c.status === 'FAILED')
    .map((c) => ({
      id: c.id,
      label: c.label,
      status: 'FAILED' as const,
      reasonCode: c.reasonCode || 'MODEL_UNSUPPORTED',
      detail: c.detail || c.label,
      source: c.source || 'CAPABILITY_MANIFEST',
    }));

  const warnings: DecisionCategoryItem[] = [];
  if (!quality.qualityDataAvailable) {
    warnings.push({
      id: 'quality_data',
      label: 'QUALITY DATA',
      status: 'WARNING',
      reasonCode: 'QUALITY_DATA_UNAVAILABLE',
      detail: 'QUALITY DATA UNAVAILABLE',
      source: 'UNAVAILABLE',
    });
  }
  if (!cost.hasCostData) {
    warnings.push({
      id: 'cost_data',
      label: 'COST HISTORY',
      status: 'WARNING',
      reasonCode: 'COST_DATA_UNAVAILABLE',
      detail: 'COST COMPARISON UNAVAILABLE',
      source: 'UNAVAILABLE',
    });
  }
  if (operationalState === 'DEGRADED' || operationalState === 'ERROR') {
    warnings.push({
      id: 'system_state',
      label: 'SYSTEM STATE',
      status: 'WARNING',
      reasonCode: 'PROVIDER_UNAVAILABLE',
      detail: `SYSTEM ${operationalState}`,
      source: 'SYSTEM_STATE',
    });
  }

  const facts: AttributedFact[] = [
    {
      id: 'model',
      label: 'MODEL',
      value: explanation.modelName,
      source: 'CAPABILITY_MANIFEST',
    },
    {
      id: 'provider',
      label: 'PROVIDER',
      value: explanation.provider,
      source: 'CAPABILITY_MANIFEST',
    },
    {
      id: 'mode',
      label: 'MODE',
      value: config.generationType === 'image_to_video' ? 'IMAGE → VIDEO' : config.generationType.toUpperCase(),
      source: 'USER_CONFIGURATION',
    },
    {
      id: 'aspect',
      label: 'ASPECT',
      value: config.aspectRatio,
      source: 'USER_CONFIGURATION',
    },
    {
      id: 'resolution',
      label: 'RESOLUTION',
      value: config.resolution || '1024x1024',
      source: config.resolution ? 'USER_CONFIGURATION' : 'CAPABILITY_MANIFEST',
    },
    {
      id: 'runs_count',
      label: 'HISTORICAL RUNS',
      value: String(cost.runCount),
      source: 'HISTORICAL_RUN',
    },
    {
      id: 'recent_cost',
      label: 'RECENT COST',
      value: cost.recentCost !== null ? `$${cost.recentCost.toFixed(4)}` : (cost.hasCostData ? cost.displayStatus : 'UNAVAILABLE'),
      source: cost.hasCostData ? 'HISTORICAL_RUN' : 'UNAVAILABLE',
    },
    {
      id: 'avg_cost',
      label: 'AVG COST',
      value: cost.avgKnownCost !== null ? `$${cost.avgKnownCost.toFixed(4)}` : 'UNAVAILABLE',
      source: cost.hasCostData ? 'HISTORICAL_RUN' : 'UNAVAILABLE',
    },
    {
      id: 'quality_data',
      label: 'QUALITY DATA',
      value: quality.displayText,
      source: quality.source,
    },
  ];

  const categorization: DecisionCategorization = {
    hardBlocks,
    warnings,
    facts,
    userDecision: {
      status,
      directive,
      requiresConfirmation: true,
    },
  };

  // Stage 9: Pre-flight Summary
  const conditioningStatus =
    config.generationType === 'image_to_video'
      ? (config.startFrameUrl || config.referenceImageUrl ? 'ATTACHED' : 'MISSING')
      : config.generationType === 'image'
      ? 'NOT_REQUIRED'
      : 'OPTIONAL';

  const preflightSummary: PreflightSummaryItem[] = [
    {
      key: 'mode',
      label: 'MODE',
      value: config.generationType === 'image_to_video' ? 'IMAGE → VIDEO' : config.generationType.toUpperCase(),
      status: 'SUPPORTED',
    },
    {
      key: 'model',
      label: 'MODEL',
      value: explanation.modelName,
      status: selectedModelObj ? (selectedModelObj.configured ? 'SUPPORTED' : 'NOT_SUPPORTED') : 'NOT_SUPPORTED',
    },
    {
      key: 'capability',
      label: 'CAPABILITY',
      value: selectedModelObj ? (selectedModelObj.configured ? 'SUPPORTED' : 'UNCONFIGURED') : 'UNSUPPORTED',
      status: selectedModelObj && selectedModelObj.configured ? 'SUPPORTED' : 'NOT_SUPPORTED',
    },
    {
      key: 'prompt',
      label: 'PROMPT',
      value: config.prompt
        ? (config.prompt.length > 2000 ? 'TOO LONG' : 'VALID')
        : (preflight.checks.find((c) => c.id === 'prompt')?.status === 'FAILED' ? 'MISSING' : 'VALID'),
      status: config.prompt
        ? (config.prompt.length > 2000 ? 'NOT_SUPPORTED' : 'VALID')
        : (preflight.checks.find((c) => c.id === 'prompt')?.status === 'FAILED' ? 'MISSING' : 'VALID'),
    },
    {
      key: 'aspect',
      label: 'ASPECT',
      value: config.aspectRatio,
      status: (manifest?.aspect_ratios || []).some((ar) => ar.id === config.aspectRatio) ? 'SUPPORTED' : 'NOT_SUPPORTED',
    },
    {
      key: 'resolution',
      label: 'RESOLUTION',
      value: config.resolution || '1024x1024',
      status: (manifest?.resolutions || []).some((r) => r.id === (config.resolution || '1024x1024')) ? 'SUPPORTED' : 'NOT_SUPPORTED',
    },
    {
      key: 'conditioning',
      label: 'CONDITIONING',
      value: conditioningStatus === 'NOT_REQUIRED' ? 'NOT REQUIRED' : conditioningStatus,
      status: conditioningStatus as any,
    },
    {
      key: 'status',
      label: 'STATUS',
      value: status,
      status: status as any,
    },
  ];

  if (status === 'BLOCKED' && preflight.reason) {
    preflightSummary.push({
      key: 'reason',
      label: 'REASON',
      value: preflight.reason,
      status: 'BLOCKED',
    });
  }

  // Stage 9: Read-Only Execution Payload Preview
  const promptPreview = config.prompt
    ? (config.prompt.length > 60 ? `${config.prompt.slice(0, 57)}...` : config.prompt)
    : 'None';

  const executionPreview: ExecutionPayloadPreview = {
    mode: config.generationType,
    model: config.model,
    modelName: explanation.modelName,
    provider: explanation.provider,
    aspectRatio: config.aspectRatio,
    resolution: config.resolution || '1024x1024',
    promptStatus: !config.prompt ? 'EMPTY' : config.prompt.length > 2000 ? 'TRUNCATED' : 'READY',
    promptPreview,
    referenceStatus: config.referenceImageUrl ? 'ATTACHED' : (config.requiresReference ? 'REQUIRED' : 'NONE'),
    startFrameStatus: (config.startFrameUrl || config.referenceImageUrl) ? 'ATTACHED' : (config.generationType === 'image_to_video' ? 'REQUIRED' : 'NONE'),
    endFrameStatus: config.endFrameUrl ? 'ATTACHED' : 'NONE',
    durationSeconds: config.generationType !== 'image' ? config.duration : undefined,
    dispatchSteps: [
      '→ POST /creator/generate',
      '→ RECEIVE JOB ID',
      '→ BEGIN STATUS POLLING',
      '→ UPDATE COMMAND CORE',
      '→ UPDATE WORKFLOW ORBIT',
      '→ LOAD RESULT INTO VIEWPORT',
    ],
  };

  return {
    status,
    directive,
    reason: preflight.reason,
    reasons: preflight.reasons,
    reasonCode: preflight.reasonCode,
    reasonCodes: preflight.reasonCodes,
    preflight,
    explanation,
    categorization,
    preflightSummary,
    executionPreview,
  };
}
