/**
 * AryaOS V1 — Stage 14: Decision Intelligence Domain Contracts
 *
 * Formal decision-support layer bridging Missions, Goals, Strategic Knowledge,
 * Multi-Agent Coordination, and Execution Gateway.
 *
 * Fundamental Principle:
 * FACT: evidence-backed observation
 * KNOWLEDGE: validated relationship between facts
 * STRATEGY: reusable advisory approach
 * OPTION: possible course of action
 * SCENARIO: projected consequences of an option
 * DECISION: operator-approved choice
 * EXECUTION: actual work performed after decision
 */

export type DecisionStatus =
  | 'DRAFT'
  | 'ANALYZING'
  | 'OPTIONS_READY'
  | 'SCENARIO_ANALYSIS'
  | 'AWAITING_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'SUPERSEDED'
  | 'EXECUTED'
  | 'CANCELLED';

export type DecisionPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type DecisionConfidence = 'UNKNOWN' | 'LOW' | 'MEDIUM' | 'HIGH';

export type DecisionEvidenceLabel = 'OBSERVED' | 'INFERRED' | 'PROJECTED' | 'UNKNOWN';

export type DecisionObjectiveType =
  | 'QUALITY'
  | 'COST'
  | 'LATENCY'
  | 'RELIABILITY'
  | 'DEADLINE'
  | 'RESOURCE_EFFICIENCY'
  | 'RISK'
  | 'HUMAN_EFFORT'
  | 'LONG_TERM_VALUE';

export type ScenarioType =
  | 'BASELINE'
  | 'OPTIMISTIC'
  | 'CONSTRAINED'
  | 'FAILURE'
  | 'DEADLINE_PRESSURE'
  | 'BUDGET_PRESSURE';

export type DecisionReversibility =
  | 'REVERSIBLE'
  | 'PARTIALLY_REVERSIBLE'
  | 'IRREVERSIBLE';

export type SensitivityImpact =
  | 'HIGH_IMPACT_ASSUMPTION'
  | 'MEDIUM_IMPACT_ASSUMPTION'
  | 'LOW_IMPACT_ASSUMPTION';

export type RiskClassification = 'KNOWN' | 'INFERRED' | 'PROJECTED' | 'UNKNOWN';

export type ConsequentialActionFlag =
  | 'FINANCIAL'
  | 'PROVIDER_POLICY'
  | 'AGENT_AUTONOMY'
  | 'PROTECTED_MEMORY'
  | 'PUBLISHING'
  | 'EXTERNAL_COMMUNICATION'
  | 'IRREVERSIBLE_ACTION'
  | 'MISSION_CANCELLATION'
  | 'SCOPE_EXPANSION'
  | 'BUDGET_EXPANSION';

export interface DecisionObjective {
  id: string;
  type: DecisionObjectiveType;
  name: string;
  description: string;
  targetValue?: string | number;
  weight?: number;
  isHardConstraint?: boolean;
}

export interface DecisionConstraint {
  id: string;
  name: string;
  description: string;
  constraintType:
    | 'BUDGET'
    | 'DEADLINE'
    | 'SECURITY'
    | 'RESOURCE'
    | 'POLICY'
    | 'HUMAN_AUTHORITY'
    | 'OTHER';
  isImmutable: boolean;
  threshold?: string | number;
}

export interface DecisionCriterion {
  id: string;
  name: string;
  objectiveType: DecisionObjectiveType;
  description: string;
  evaluationFormula?: string;
}

export interface DecisionEvidence {
  id: string;
  label: DecisionEvidenceLabel;
  sourceType:
    | 'FACT'
    | 'KNOWLEDGE_NODE'
    | 'EXPERIENCE'
    | 'EVALUATION'
    | 'HISTORICAL_OUTCOME'
    | 'OBSERVATION';
  sourceId: string;
  description: string;
  confidence: DecisionConfidence;
  timestamp: string;
}

export interface Consequence {
  id: string;
  description: string;
  label: DecisionEvidenceLabel;
  dimension: DecisionObjectiveType | 'DEPENDENCY' | 'RECOVERY' | 'OTHER';
  impact: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'UNKNOWN';
  evidenceIds: string[];
  estimatedMetric?: {
    name: string;
    value: string | number;
    unit?: string;
  };
}

export interface RiskAssessment {
  id: string;
  riskId?: string;
  classification: RiskClassification;
  title: string;
  description: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  likelihood: 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN';
  mitigation?: string;
  evidenceIds: string[];
}

export interface ScenarioOutcome {
  expectedOutcome: string;
  consequences: Consequence[];
  risks: RiskAssessment[];
  resourceImpact: string;
  deadlineImpact: string;
  qualityImplications: string;
  failureModes: Array<{
    description: string;
    type: 'EVIDENCE_BACKED' | 'SPECULATIVE';
    evidenceIds: string[];
  }>;
  recoveryImplications: string;
  label: DecisionEvidenceLabel;
}

export interface Scenario {
  id: string;
  type: ScenarioType;
  name: string;
  description: string;
  outcome: ScenarioOutcome;
  keyAssumptions: string[];
  confidence: DecisionConfidence;
}

export interface DecisionOption {
  optionId: string;
  title: string;
  description: string;
  reversibility: DecisionReversibility;
  requiredGoals: string[];
  requiredResources: string[];
  strategyReferences: string[];
  supportingEvidence: DecisionEvidence[];
  assumptions: string[];
  risks: RiskAssessment[];
  estimatedCost: number | 'UNKNOWN';
  estimatedDuration: number | 'UNKNOWN';
  confidence: DecisionConfidence;
  scenarios?: Scenario[];
  fingerprint?: string;
}

export interface DecisionAlternative {
  optionId: string;
  title: string;
  rejectionReason?: string;
  tradeoffSummary: string;
}

export interface TradeoffAnalysis {
  id: string;
  dimensionA: DecisionObjectiveType;
  dimensionB: DecisionObjectiveType;
  optionAImpact: string;
  optionBImpact: string;
  evidence: string[];
  confidence: DecisionConfidence;
}

export interface HistoricalAnalog {
  id: string;
  sourceMissionId: string;
  sourceGoalId?: string;
  similarityFactors: string[];
  outcome: string;
  evidence: string[];
  differences: string[];
  confidence: DecisionConfidence;
}

export interface DecisionSensitivity {
  id: string;
  assumption: string;
  impact: SensitivityImpact;
  evidence: string[];
  affectedOptions: string[];
  rationale: string;
}

export interface DecisionProvenance {
  decisionId: string;
  recommendationId: string;
  optionId: string;
  scenarioIds: string[];
  evidenceIds: string[];
  knowledgeNodeIds: string[];
  experienceIds: string[];
  missionId?: string;
  goalId?: string;
  executionActionIds?: string[];
  timestamp: string;
}

export interface DecisionApproval {
  approvalId: string;
  status: 'AWAITING_REVIEW' | 'APPROVED' | 'REJECTED';
  approvedBy?: string;
  reviewedAt?: string;
  comments?: string;
  requiresHumanApproval: boolean;
  consequentialFlags: ConsequentialActionFlag[];
}

export interface DecisionRecommendation {
  recommendationId: string;
  decisionId: string;
  recommendedOptionId: string;
  recommendedOption: DecisionOption;
  reasoning: string;
  supportingEvidence: DecisionEvidence[];
  tradeoffs: TradeoffAnalysis[];
  risks: RiskAssessment[];
  unknowns: string[];
  confidence: DecisionConfidence;
  alternatives: DecisionAlternative[];
  approvalRequired: boolean;
  status: 'AWAITING_REVIEW' | 'APPROVED' | 'REJECTED';
  createdAt: string;
}

export interface DecisionContext {
  contextId: string;
  missionId?: string;
  goalId?: string;
  objective: string;
  currentState: string;
  constraints: DecisionConstraint[];
  availableResources: string[];
  relevantKnowledge: Array<{
    id: string;
    title: string;
    type: string;
    confidence: string;
  }>;
  relevantExperiences: Array<{
    id: string;
    pattern: string;
    outcome: string;
  }>;
  knownRisks: RiskAssessment[];
  openContradictions: Array<{
    id: string;
    description: string;
    severity: string;
  }>;
  historicalStrategies: Array<{
    id: string;
    name: string;
    successRate?: number;
  }>;
  pendingApprovals: string[];
  deadline?: string;
  budget?: number | 'UNKNOWN';
  objectives: DecisionObjective[];
  fingerprint: string;
  createdAt: string;
}

export interface DecisionExplanation {
  decisionId: string;
  whyThisOption: string;
  whyNotAlternative: Record<string, string>;
  supportingEvidence: DecisionEvidence[];
  knownRisks: RiskAssessment[];
  unknownFactors: string[];
  tradeoffs: TradeoffAnalysis[];
  historicalAnalogies: HistoricalAnalog[];
  confidence: DecisionConfidence;
  sensitivity: DecisionSensitivity[];
  facts: string[];
  inferences: string[];
  projections: string[];
}

export interface PreMortemFailureMode {
  id: string;
  failureMode: string;
  type: 'EVIDENCE_BACKED' | 'SPECULATIVE';
  evidenceIds: string[];
  potentialCause: string;
  earlyWarningSignal: string;
  preventativeAction: string;
}

export interface PreMortemAnalysis {
  id: string;
  optionId: string;
  failureModes: PreMortemFailureMode[];
  worstCaseScenario: string;
  resilienceRating: 'LOW' | 'MEDIUM' | 'HIGH';
  analyzedAt: string;
}

export interface DecisionEvaluation {
  id: string;
  decisionId: string;
  decisionProcessScore: number;
  evidenceQualityScore: number;
  predictionAccuracyScore?: number;
  assumptionAccuracyScore?: number;
  outcomeVariance?: string;
  humanOverrideOccurred: boolean;
  riskPredictionAccuracy?: string;
  evaluationNotes: string;
  evaluatedAt: string;
}

export interface PostDecisionRecord {
  decisionId: string;
  selectedOptionId: string;
  actualOutcome: string;
  expectedOutcome: string;
  variance: string;
  unexpectedEvents: string[];
  humanOverride: boolean;
  lesson: string;
  recordedAt: string;
}

export interface Decision {
  id: string;
  version: number;
  title: string;
  description: string;
  status: DecisionStatus;
  priority: DecisionPriority;
  context: DecisionContext;
  options: DecisionOption[];
  recommendation?: DecisionRecommendation;
  approval: DecisionApproval;
  provenance: DecisionProvenance;
  sensitivity?: DecisionSensitivity[];
  explanation?: DecisionExplanation;
  premortem?: PreMortemAnalysis;
  postDecisionRecord?: PostDecisionRecord;
  evaluation?: DecisionEvaluation;
  previousDecisionId?: string;
  changeReason?: string;
  newEvidence?: DecisionEvidence[];
  changedConstraints?: DecisionConstraint[];
  changedRisks?: RiskAssessment[];
  createdAt: string;
  updatedAt: string;
}
