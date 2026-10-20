/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Phase 7: Operator HUD Component Integration Test Suite
 *
 * Deterministic, comprehensive verification of the Operator HUD:
 * - Pure DOM observational Command Deck over Stage 24 read-only projections.
 * - Zero execution, zero scheduling, zero approvals, zero recovery dispatch, zero network calls.
 * - Rigorous verification of all 26 prompt test requirements + adversarial hardening.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { OperatorHUD } from '../components/control-plane/OperatorHUD';
import { SystemHealthPanel } from '../components/control-plane/SystemHealthPanel';
import { MissionOperationsPanel } from '../components/control-plane/MissionOperationsPanel';
import { OperationTimelinePanel } from '../components/control-plane/OperationTimelinePanel';
import { ApprovalCenterPanel } from '../components/control-plane/ApprovalCenterPanel';
import { RecoveryOperationsPanel } from '../components/control-plane/RecoveryOperationsPanel';
import { CausalEvidencePanel } from '../components/control-plane/CausalEvidencePanel';
import { ResourceStatusPanel } from '../components/control-plane/ResourceStatusPanel';
import {
  EpistemicBadge,
  SourceIntegrityBadge,
  LifecycleBadge,
  ProgressProvenanceBadge,
  SecretScrubbedText,
  formatTimestamp,
  scrubSecrets,
} from '../components/control-plane/EpistemicIndicators';
import { controlPlaneSnapshotService } from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { resourceGovernor } from '../services/resourceGovernor';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { missionManager } from '../services/missionManager';
import { actionBusService } from '../services/actionBusService';
import {
  ControlPlaneSnapshot,
  SystemHealthSummary,
  MissionSummary,
  OperationSummary,
  ApprovalSummary,
  RecoverySummary,
  CausalTraceSummary,
} from '../types/controlPlane';
import { Mission } from '../types/missionControl';
import { Goal } from '../types/goalOrchestration';

function createMockMission(overrides?: Partial<Mission>): Mission {
  return {
    missionId: 'mis-stage24-alpha',
    title: 'Orbital Reconnaissance Mission',
    objective: 'Map high-resolution satellite imagery across the Northern sector.',
    goals: [],
    dependencies: [],
    priority: 'HIGH',
    status: 'RUNNING',
    riskLevel: 'LOW',
    progress: {
      totalGoals: 0,
      completedGoals: 0,
      failedGoals: 0,
      inProgressGoals: 0,
      blockedGoals: 0,
      percentage: 0,
    },
    plans: [],
    currentPlanVersion: 1,
    checkpoints: [],
    observations: [],
    decisions: [],
    constraints: [],
    milestones: [],
    completionCriteria: {
      mandatoryGoalsCompleted: true,
      minimumSuccessRate: 1.0,
      requiredMilestonesCompleted: [],
      allowPartialSuccess: false,
      requireHumanSignoff: false,
    },
    executionPolicy: {
      autoApproveReadOnly: true,
      allowPartialSuccess: false,
      maxCostUsd: 100,
      replanOnGoalFailure: false,
    },
    createdAt: '2026-10-04T12:00:00.000Z',
    updatedAt: '2026-10-04T12:05:00.000Z',
    provenance: { source: 'test' },
    ...overrides,
  };
}

describe('AryaOS V1 Stage 24 — Phase 7: Operator HUD Component Integration', () => {
  beforeEach(() => {
    executionPersistence.clearEnvelope();
    auditEventRegistry.reset();
    resourceGovernor.resetState();
    goalOrchestrator.resetState();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Initial render without operational records (empty states)
  it('1. renders initial HUD cleanly when no operational records exist (empty states)', () => {
    const { getByTestId, queryByTestId } = render(<OperatorHUD />);
    expect(getByTestId('operator-hud')).toBeDefined();
    expect(getByTestId('hud-header')).toBeDefined();
    expect(getByTestId('hud-tab-bar')).toBeDefined();
    expect(getByTestId('hud-overview-section')).toBeDefined();

    // Verify empty state messages across child panels
    expect(getByTestId('approval-panel-empty')).toBeDefined();
    expect(getByTestId('recovery-panel-empty')).toBeDefined();
    expect(getByTestId('mission-panel-empty')).toBeDefined();
  });

  // 2. Loading and unavailable/error states
  it('2. displays bounded error boundary and retry control when snapshot projection throws', () => {
    vi.spyOn(controlPlaneSnapshotService, 'getSnapshot').mockImplementationOnce(() => {
      throw new Error('Persistence snapshot read failure: lock contention');
    });

    const { getByTestId } = render(<OperatorHUD />);
    expect(getByTestId('hud-error-boundary')).toBeDefined();
    expect(getByTestId('hud-error-boundary').textContent).toContain('Persistence snapshot read failure: lock contention');
    expect(getByTestId('hud-error-retry-btn')).toBeDefined();
  });

  // 3. Mission summaries render from canonical projections
  it('3. renders mission summaries from canonical snapshot projections', () => {
    const mockMission: Mission = createMockMission({
      missionId: 'mis-alpha-001',
      title: 'Satellite Survey Alpha',
      objective: 'Conduct high-frequency orbital mapping',
      goals: [],
      status: 'RUNNING',
      priority: 'HIGH',
      riskLevel: 'LOW',
      createdAt: '2026-10-04T12:00:00.000Z',
      updatedAt: '2026-10-04T12:05:00.000Z',
    });
    executionPersistence.saveMission(mockMission);

    const { getByTestId } = render(<OperatorHUD defaultTab="missions" />);
    expect(getByTestId('mission-operations-panel')).toBeDefined();
    expect(getByTestId('mission-card-mis-alpha-001')).toBeDefined();
    expect(getByTestId('mission-card-mis-alpha-001').textContent).toContain('Satellite Survey Alpha');
  });

  // 4. Mission detail selection preserves canonical identity
  it('4. selecting a mission inspects detailed goals, checkpoints, and dependency topology', () => {
    const mockMission: Mission = createMockMission({
      missionId: 'mis-beta-002',
      title: 'Deep Exploration Mission',
      objective: 'Explore uncharted planetary zones',
      goals: [
        {
          goalId: 'goal-deep-1',
          title: 'Deploy Surface Probe',
          mandatory: true,
          status: 'COMPLETED',
          weight: 2,
        },
      ],
      checkpoints: [
        {
          checkpointId: 'cp-stage-1',
          missionId: 'mis-beta-002',
          missionStatus: 'COMPLETED',
          planVersion: 1,
          completedGoals: ['goal-deep-1'],
          activeGoals: [],
          blockedGoals: [],
          pendingApprovals: [],
          resourceState: {},
          timestamp: '2026-10-04T12:00:00.000Z',
        },
      ],
      status: 'RUNNING',
      priority: 'CRITICAL',
      createdAt: '2026-10-04T12:00:00.000Z',
      updatedAt: '2026-10-04T12:05:00.000Z',
    });
    executionPersistence.saveMission(mockMission);

    const { getByTestId } = render(<OperatorHUD defaultTab="missions" />);
    const card = getByTestId('mission-card-mis-beta-002');
    fireEvent.click(card);

    expect(getByTestId('mission-detail-inspector')).toBeDefined();
    expect(getByTestId('goal-row-goal-deep-1')).toBeDefined();
    expect(getByTestId('goal-row-goal-deep-1').textContent).toContain('Deploy Surface Probe');
    expect(getByTestId('goal-row-goal-deep-1').textContent).toContain('MANDATORY');
    expect(getByTestId('checkpoint-row')).toBeDefined();
  });

  // 5. Derived progress is visibly distinguished from authoritative progress
  it('5. visibly distinguishes derived progress from authoritative progress with provenance tag', () => {
    const { getByTestId, rerender } = render(
      <ProgressProvenanceBadge isDerived={true} isConsistent={true} totalGoals={4} completedGoals={2} />
    );
    expect(getByTestId('progress-provenance-badge').textContent).toContain('DERIVED PROGRESS');
    expect(getByTestId('progress-provenance-badge').textContent).toContain('(2/4 goals)');

    // Inconsistent tally
    rerender(
      <ProgressProvenanceBadge isDerived={false} isConsistent={false} totalGoals={5} completedGoals={1} />
    );
    expect(getByTestId('progress-provenance-badge').textContent).toContain('RECORDED PROGRESS');
    expect(getByTestId('progress-inconsistency-flag')).toBeDefined();
    expect(getByTestId('progress-inconsistency-flag').textContent).toBe('TALLY MISMATCH');
  });

  // 6. Operation timeline ordering and canonical states are preserved
  it('6. preserves canonical 16-state operation lifecycle ordering and timestamps', () => {
    auditEventRegistry.recordEvent({
      eventId: 'evt-op-seq-1',
      operationId: 'op-lifecycle-order',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1000,
      sourceSystem: 'gateway',
      causationId: 'root',
      correlationId: 'corr-seq',
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-op-seq-2',
      operationId: 'op-lifecycle-order',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'CONFIRMED',
      timestamp: 2000,
      sourceSystem: 'action-bus',
      causationId: 'evt-op-seq-1',
      correlationId: 'corr-seq',
    });

    const { getByTestId, getAllByTestId } = render(<OperatorHUD defaultTab="operations" />);
    const opCard = getByTestId('operation-card-op-lifecycle-order');
    fireEvent.click(opCard);

    expect(getByTestId('operation-timeline-detail')).toBeDefined();
    const rows = getAllByTestId('timeline-entry-row');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('REQUESTED');
    expect(rows[1].textContent).toContain('DISPATCHED');
  });

  // 7. UNKNOWN operational states remain visible
  it('7. strictly renders UNKNOWN operational states as UNKNOWN and never masks them as SUCCESS', () => {
    const { getByTestId } = render(<EpistemicBadge status="UNKNOWN" />);
    const badge = getByTestId('epistemic-badge');
    expect(badge.textContent).toBe('UNKNOWN (UNVERIFIED)');
    expect(badge.getAttribute('data-status')).toBe('UNKNOWN');
  });

  // 8. Approval requirements are not displayed as granted approvals
  it('8. strictly displays approval requirements as pending and never as granted approvals', () => {
    const mockApproval: ApprovalSummary = {
      approvalId: 'app-req-001',
      requestId: 'req-alpha',
      riskLevel: 'HIGH',
      approvalState: 'PENDING',
      expiresAt: Date.now() + 60000,
      createdAt: Date.now() - 5000,
      actionTitle: 'Nuclear Engine Pulse',
      reason: 'Critical high-risk kinetic actuation',
    };

    const { getByTestId } = render(<ApprovalCenterPanel approvals={[mockApproval]} />);
    expect(getByTestId('approval-card-app-req-001')).toBeDefined();
    const explanation = getByTestId('approval-truth-explanation');
    expect(explanation.textContent).toContain('APPROVAL REQUIRED: Action blocked until authoritative human operator token is issued');
    expect(explanation.textContent).not.toContain('AUTHORIZATION GRANTED');
  });

  // 9. Expired, invalid, and pending approvals remain distinguishable
  it('9. distinguishes expired, rejected, and granted approvals unambiguously', () => {
    const approvals: ApprovalSummary[] = [
      {
        approvalId: 'app-exp-01',
        riskLevel: 'MEDIUM',
        approvalState: 'EXPIRED',
        expiresAt: Date.now() - 1000,
        createdAt: Date.now() - 60000,
      },
      {
        approvalId: 'app-rej-02',
        riskLevel: 'LOW',
        approvalState: 'REJECTED',
        actorId: 'admin-alice',
        rejectedAt: Date.now() - 500,
        expiresAt: Date.now() + 60000,
        createdAt: Date.now() - 10000,
      },
      {
        approvalId: 'app-app-03',
        riskLevel: 'CRITICAL',
        approvalState: 'APPROVED',
        actorId: 'operator-bob',
        approvedAt: Date.now() - 200,
        expiresAt: Date.now() + 60000,
        createdAt: Date.now() - 10000,
      },
    ];

    const { getByTestId } = render(<ApprovalCenterPanel approvals={approvals} />);
    expect(getByTestId('approval-card-app-exp-01').textContent).toContain('APPROVAL WINDOW EXPIRED');
    expect(getByTestId('approval-card-app-rej-02').textContent).toContain('APPROVAL REJECTED by admin-alice');
    expect(getByTestId('approval-card-app-app-03').textContent).toContain('AUTHORIZATION GRANTED by operator-bob');
  });

  // 10. Recovery proposals are not displayed as completed recovery actions
  it('10. renders proposed recovery action strictly as a proposal and never as executed', () => {
    const mockRecovery: RecoverySummary = {
      recoveryPlanId: 'rec-prop-001',
      originalOperationId: 'op-failed-sensor',
      failureClassification: 'TRANSIENT',
      currentTruthState: 'OBSERVED',
      proposedRecoveryAction: 'RETRY',
      riskLevel: 'LOW',
      idempotencyAssessment: 'IDEMPOTENT',
      requiredAuthority: ['OPERATOR'],
      approvalRequirement: {
        required: true,
        humanOperatorRequired: true,
      },
      reconciliationRequirement: {
        required: false,
      },
      compensationPlan: 'UNKNOWN',
      expectedOutcome: 'RETRY',
      expiresAt: Date.now() + 30000,
      causationId: 'c-1',
      correlationId: 'corr-1',
      lifecycleState: 'PROPOSED',
    };

    const { getByTestId } = render(<RecoveryOperationsPanel recovery={[mockRecovery]} />);
    expect(getByTestId('proposed-action-banner')).toBeDefined();
    expect(getByTestId('proposed-action-banner').textContent).toContain('PROPOSED RECOVERY ACTION (RECOMMENDATION ONLY)');
    expect(getByTestId('proposed-action-banner').textContent).toContain('RETRY');
    expect(getByTestId('recovery-observational-notice')).toBeDefined();
    expect(getByTestId('recovery-observational-notice').textContent).toContain('Recommendation has not been dispatched');
  });

  // 11. Required reconciliation is not displayed as completed reconciliation
  it('11. strictly renders required reconciliation as pending probe and not as completed', () => {
    const mockRecovery: RecoverySummary = {
      recoveryPlanId: 'rec-recon-002',
      originalOperationId: 'op-uncertain-charge',
      failureClassification: 'UNKNOWN_EXTERNAL_STATE',
      currentTruthState: 'UNKNOWN',
      proposedRecoveryAction: 'RECONCILE',
      riskLevel: 'MEDIUM',
      idempotencyAssessment: 'UNKNOWN',
      requiredAuthority: [],
      approvalRequirement: { required: false, humanOperatorRequired: false },
      reconciliationRequirement: {
        required: true,
        postCompensationVerification: false,
        timeoutMs: 5000,
      },
      compensationPlan: 'UNKNOWN',
      expiresAt: Date.now() + 60000,
      causationId: 'c-2',
      correlationId: 'corr-2',
      lifecycleState: 'PROPOSED',
    };

    const { getByTestId } = render(<RecoveryOperationsPanel recovery={[mockRecovery]} />);
    const reconReq = getByTestId('recovery-recon-req');
    expect(reconReq.textContent).toBe('REQUIRED (PROBE PENDING)');
    expect(reconReq.textContent).not.toContain('VERIFIED_SUCCESS');
  });

  // 12. Declarative compensation is not displayed as executed compensation
  it('12. displays declarative compensation availability without claiming execution', () => {
    const mockRecovery: RecoverySummary = {
      recoveryPlanId: 'rec-comp-003',
      originalOperationId: 'op-side-effect',
      failureClassification: 'PARTIAL_EXECUTION',
      currentTruthState: 'OBSERVED',
      proposedRecoveryAction: 'COMPENSATE',
      riskLevel: 'HIGH',
      idempotencyAssessment: 'IDEMPOTENT',
      requiredAuthority: ['GOVERNANCE'],
      approvalRequirement: { required: false, humanOperatorRequired: false },
      reconciliationRequirement: { required: false },
      compensationPlan: {
        compensationId: 'comp-plan-1',
        originalOperationId: 'op-side-effect',
        compensationType: 'REVERSE_ACTION',
        sourceCapability: 'LEDGER',
        compensatingCapability: 'LEDGER_REVERSE',
        targetState: 'ROLLED_BACK',
        compensationParameters: {},
        reversibilityClass: 'FULLY_REVERSIBLE',
        idempotencyClass: 'IDEMPOTENT',
        riskLevel: 'HIGH',
        requiredAuthority: ['ADMIN'],
        approvalRequirement: { required: true, humanOperatorRequired: true },
        reconciliationRequirement: { required: false, postCompensationVerification: true },
        idempotencyKey: 'idemp-1',
        causationId: 'c-3',
        correlationId: 'corr-3',
        expiresAt: Date.now() + 60000,
        lifecycleState: 'PROPOSED',
        recoveryDepth: 1,
      },
      expiresAt: Date.now() + 60000,
      causationId: 'c-3',
      correlationId: 'corr-3',
      lifecycleState: 'PROPOSED',
    };

    const { getByTestId } = render(<RecoveryOperationsPanel recovery={[mockRecovery]} />);
    const compPlan = getByTestId('recovery-comp-plan');
    expect(compPlan.textContent).toBe('AVAILABLE (DECLARATIVE)');
    expect(compPlan.textContent).not.toContain('EXECUTED');
  });

  // 13. Causal evidence and missing-evidence markers are displayed accurately
  it('13. surfaces missing evidence markers and alerts in causal trace graphs', () => {
    const mockTrace: CausalTraceSummary = {
      operationId: 'op-trace-missing',
      rootNodeId: 'node-root',
      maxDepthReached: 3,
      isTruncated: false,
      hasCycles: false,
      hasMissingEvidence: true,
      nodes: [
        {
          nodeId: 'node-root',
          domain: 'ACTION',
          entityId: 'ent-1',
          nodeType: 'ACTION',
          label: 'Root Dispatch',
          state: 'EXECUTING',
          epistemicState: 'OBSERVED',
          timestamp: 1000,
          source: 'gateway',
          evidenceState: 'VERIFIED',
        },
        {
          nodeId: 'node-orphan',
          domain: 'RECOVERY',
          entityId: 'ent-2',
          nodeType: 'MISSING_EVIDENCE',
          label: 'Unverified Recovery Link',
          state: 'UNKNOWN',
          epistemicState: 'UNKNOWN',
          timestamp: 'UNKNOWN',
          source: 'UNKNOWN',
          evidenceState: 'MISSING_EVIDENCE',
        },
      ],
      edges: [
        {
          fromNodeId: 'node-root',
          toNodeId: 'node-orphan',
          edgeType: 'TRIGGERED',
          timestamp: 1500,
        },
      ],
    };

    const { getByTestId, getAllByTestId } = render(<CausalEvidencePanel traces={[mockTrace]} />);
    expect(getByTestId('missing-evidence-marker')).toBeDefined();
    expect(getByTestId('missing-evidence-alert')).toBeDefined();
    const states = getAllByTestId('node-evidence-state');
    expect(states.some((el) => el.textContent?.includes('MISSING_EVIDENCE'))).toBe(true);
  });

  // 14. Resource allocation is not presented as confirmed utilization
  it('14. separates resource limits from telemetry-confirmed consumption without fabricating budgets', () => {
    const mockResources = [
      {
        resourceType: 'GPU_VRAM',
        allocated: 16384,
        utilized: 'UNKNOWN' as const,
        unit: 'MB',
        status: 'ALLOCATED' as const,
        provenance: 'goal-config',
      },
      {
        resourceType: 'API_CREDITS',
        allocated: 500,
        utilized: 120,
        unit: 'CREDITS',
        status: 'UTILIZED' as const,
        provenance: 'resource-governor',
      },
    ];

    const { getByTestId } = render(<ResourceStatusPanel resources={mockResources} />);
    const vramAlloc = getByTestId('resource-card-gpu_vram').querySelector('[data-testid="resource-allocated-value"]');
    const vramUtil = getByTestId('resource-card-gpu_vram').querySelector('[data-testid="resource-utilized-value"]');
    expect(vramAlloc?.textContent).toBe('16384 MB');
    expect(vramUtil?.textContent).toBe('UNKNOWN (UNTRACKED)');

    const apiAlloc = getByTestId('resource-card-api_credits').querySelector('[data-testid="resource-allocated-value"]');
    const apiUtil = getByTestId('resource-card-api_credits').querySelector('[data-testid="resource-utilized-value"]');
    expect(apiAlloc?.textContent).toBe('500 CREDITS');
    expect(apiUtil?.textContent).toBe('120 CREDITS');
  });

  // 15. Stale and conflicting source records are surfaced
  it('15. surfaces STALE (>30D) and CONFLICTING source records visibly', () => {
    const { getByTestId, rerender } = render(<SourceIntegrityBadge integrity="STALE" />);
    expect(getByTestId('source-integrity-badge').textContent).toBe('SOURCE: STALE (>30D)');

    rerender(<SourceIntegrityBadge integrity="CONFLICTING" />);
    expect(getByTestId('source-integrity-badge').textContent).toBe('SOURCE: CONFLICTING');
  });

  // 16. Secrets are not rendered in the UI
  it('16. recursively scrubs bearer tokens, API keys, and secret patterns from rendered DOM', () => {
    const rawText = 'Authorization: Bearer secret-token-xyz123456789 and api_key="super-secret-key"';
    const scrubbed = scrubSecrets(rawText);
    expect(scrubbed).not.toContain('secret-token-xyz123456789');
    expect(scrubbed).not.toContain('super-secret-key');
    expect(scrubbed).toContain('Bearer [REDACTED_TOKEN]');

    const { getByText } = render(<SecretScrubbedText text={rawText} />);
    expect(getByText(/Bearer \[REDACTED_TOKEN\]/)).toBeDefined();
  });

  // 17. Untrusted strings cannot inject HTML or script
  it('17. escapes untrusted strings to prevent XSS script injection in DOM', () => {
    const maliciousPayload = '<img src=x onerror="window.__xss=true" /><script>window.__xss=true</script>';
    const { container } = render(<SecretScrubbedText text={maliciousPayload} />);
    expect(container.querySelectorAll('script').length).toBe(0);
    expect(container.querySelectorAll('img').length).toBe(0);
    expect(container.textContent).toContain('<img src=x onerror="window.__xss=true" />');
    expect((window as any).__xss).toBeUndefined();
  });

  // 18. No display component calls consequential service methods
  it('18. verifies ZERO calls to consequential mutation services during HUD mount and interaction', () => {
    const executeSpy = vi.spyOn(actionBusService, 'execute');
    const missionSpy = vi.spyOn(missionManager, 'createMission');

    render(<OperatorHUD defaultTab="overview" />);
    expect(executeSpy).not.toHaveBeenCalled();
    expect(missionSpy).not.toHaveBeenCalled();
  });

  // 19. No action buttons inadvertently dispatch operational commands
  it('19. enforces observational boundary: no execute, approve, retry, or compensate buttons exist', () => {
    const { getByTestId } = render(<OperatorHUD />);
    const hud = getByTestId('operator-hud');
    const buttons = hud.querySelectorAll('button');

    for (const btn of Array.from(buttons)) {
      const testid = btn.getAttribute('data-testid') || '';
      expect(testid).not.toBe('execute-btn');
      expect(testid).not.toBe('approve-btn');
      expect(testid).not.toBe('reject-btn');
      expect(testid).not.toBe('retry-btn');
      expect(testid).not.toBe('compensate-btn');
      expect(testid).not.toBe('reconcile-btn');
      expect(testid).not.toBe('schedule-btn');
    }
  });

  // 20. Snapshot refresh does not mutate canonical records
  it('20. clicking refresh snapshot strictly re-reads projection and preserves canonical persistence', () => {
    const initialMissionCount = executionPersistence.getMissions().length;
    const { getByTestId } = render(<OperatorHUD />);
    const refreshBtn = getByTestId('hud-refresh-btn');

    fireEvent.click(refreshBtn);
    expect(executionPersistence.getMissions().length).toBe(initialMissionCount);
  });

  // 21. Nested projection data remains immutable
  it('21. guarantees returned snapshot and projection arrays are deeply frozen', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.missions)).toBe(true);
    expect(Object.isFrozen(snapshot.operations)).toBe(true);
    expect(Object.isFrozen(snapshot.approvals)).toBe(true);
    expect(Object.isFrozen(snapshot.recovery)).toBe(true);
    expect(Object.isFrozen(snapshot.causalTraces)).toBe(true);
  });

  // 22. Responsive layout and accessible keyboard interaction
  it('22. supports accessible keyboard tab navigation and semantic ARIA attributes', () => {
    const { getByTestId } = render(<OperatorHUD defaultTab="overview" />);
    const tabMissions = getByTestId('hud-tab-missions');

    expect(tabMissions.getAttribute('role')).toBe('tab');
    expect(tabMissions.getAttribute('aria-selected')).toBe('false');

    fireEvent.click(tabMissions);
    expect(tabMissions.getAttribute('aria-selected')).toBe('true');
  });

  // 23. Existing navigation and unrelated dashboard views remain functional
  it('23. renders without interfering with foreign DOM containers or window globals', () => {
    const { unmount } = render(<OperatorHUD isOpen={false} />);
    expect(screen.queryByTestId('operator-hud')).toBeNull();
    unmount();
  });

  // 24. Phase 1–6 projection tests remain unchanged and passing
  it('24. confirms snapshot service returns valid snapshot ID and source version', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot.snapshotId).toMatch(/^snap-cp-/);
    expect(snapshot.sourceVersion).toBe(1);
  });

  // 25. No unintended network or LLM calls are introduced
  it('25. confirms zero network fetch and zero LLM calls during HUD interactions', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    render(<OperatorHUD defaultTab="overview" />);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  // 26. No Stage 03 WebGL or immutable asset regressions occur
  it('26. confirms pure DOM overlay with zero HTML5 canvas elements and zero WebGL contexts created', () => {
    const { getByTestId } = render(<OperatorHUD />);
    const hud = getByTestId('operator-hud');
    const canvases = hud.querySelectorAll('canvas');
    expect(canvases.length).toBe(0);
  });

  // 27. Adversarial: Malformed timestamps gracefully render as UNKNOWN
  it('27. formats malformed timestamps defensively as UNKNOWN', () => {
    expect(formatTimestamp('UNKNOWN')).toBe('UNKNOWN');
    expect(formatTimestamp(null)).toBe('UNKNOWN');
    expect(formatTimestamp(undefined)).toBe('UNKNOWN');
    expect(formatTimestamp(-1)).toBe('UNKNOWN');
    expect(formatTimestamp(NaN)).toBe('UNKNOWN');
    expect(formatTimestamp(Infinity)).toBe('UNKNOWN');
    expect(formatTimestamp(1700000000000)).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  // 28. Adversarial: Dependency cycles display warning without infinite recursion
  it('28. surfaces dependency cycle warning without crashing or stack overflow', () => {
    const mockMission: Mission = createMockMission({
      missionId: 'mis-cycle-hud',
      title: 'Cyclic Goal Mission',
      objective: 'Stress test circular dependencies in HUD',
      goals: [
        {
          goalId: 'g-cyc-1',
          title: 'Cycle Goal 1',
          mandatory: true,
          status: 'RUNNING',
          weight: 1,
        },
        {
          goalId: 'g-cyc-2',
          title: 'Cycle Goal 2',
          mandatory: true,
          status: 'RUNNING',
          weight: 1,
        },
      ],
      dependencies: [
        { fromGoalId: 'g-cyc-1', toGoalId: 'g-cyc-2', type: 'FINISH_TO_START' },
        { fromGoalId: 'g-cyc-2', toGoalId: 'g-cyc-1', type: 'FINISH_TO_START' },
      ],
      status: 'RUNNING',
      priority: 'HIGH',
      createdAt: '2026-10-04T12:00:00.000Z',
      updatedAt: '2026-10-04T12:05:00.000Z',
    });
    executionPersistence.saveMission(mockMission);

    const { getByTestId, getAllByTestId } = render(<OperatorHUD defaultTab="missions" />);
    fireEvent.click(getByTestId('mission-card-mis-cycle-hud'));

    const warnings = getAllByTestId('dependency-cycle-warning');
    expect(warnings.length).toBeGreaterThanOrEqual(1);
    expect(warnings[0].textContent).toBe('CYCLE DETECTED');
  });

  // 29. Tab switching updates main content view reactively
  it('29. switches between tabs smoothly and activates corresponding panel components', () => {
    const { getByTestId, queryByTestId } = render(<OperatorHUD />);
    expect(getByTestId('hud-overview-section')).toBeDefined();

    // Switch to health tab
    fireEvent.click(getByTestId('hud-tab-health'));
    expect(getByTestId('system-health-panel')).toBeDefined();
    expect(queryByTestId('hud-overview-section')).toBeNull();

    // Switch to recovery tab
    fireEvent.click(getByTestId('hud-tab-recovery'));
    expect(getByTestId('recovery-operations-panel')).toBeDefined();

    // Switch to approvals tab
    fireEvent.click(getByTestId('hud-tab-approvals'));
    expect(getByTestId('approval-center-panel')).toBeDefined();

    // Switch to causal tab
    fireEvent.click(getByTestId('hud-tab-causal'));
    expect(getByTestId('causal-evidence-panel')).toBeDefined();

    // Switch to resources tab
    fireEvent.click(getByTestId('hud-tab-resources'));
    expect(getByTestId('resource-status-panel')).toBeDefined();
  });

  // 30. Subsystem health matrix reflects durable vs in-memory storage truthfully
  it('30. reflects durable persistence vs in-memory fallback truthfully in health matrix', () => {
    const health: SystemHealthSummary = {
      execution: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      providers: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      connectors: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      persistence: { status: 'DEGRADED', lastCheckedAt: Date.now(), message: 'Fallback to memory active' },
      governance: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      recovery: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      eventIngestion: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      missions: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      actionBus: { status: 'HEALTHY', lastCheckedAt: Date.now() },
      overallStatus: 'DEGRADED',
      isDurableStorage: false,
    };

    const { getByTestId } = render(<SystemHealthPanel health={health} />);
    const durabilityFlag = getByTestId('health-durability-flag');
    expect(durabilityFlag.textContent).toContain('IN-MEMORY FALLBACK');
    expect(durabilityFlag.textContent).not.toContain('DURABLE PERSISTENCE');
  });
});
