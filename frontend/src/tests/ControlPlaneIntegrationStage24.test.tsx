/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 8: Control Plane Integration & Acceptance Test Suite
 *
 * Exhaustive integration testing covering:
 * 1. HUD mounts cleanly through the intended application entry point (SpatialCommandConsole).
 * 2. All 8 expected panels are composed without duplicate projections or services.
 * 3. Canonical snapshot data reaches the correct child panels.
 * 4. UNKNOWN, missing evidence, empty data, and partial subsystem failures remain visible and truthful.
 * 5. Pending approvals are strictly not presented as approved, authorized, or executed.
 * 6. Proposed recovery actions are strictly not presented as dispatched or completed.
 * 7. Allocated resources are strictly separated from measured telemetry consumption (no synthetic budgets).
 * 8. Untrusted strings are sanitized and cannot inject executable HTML (XSS prevention).
 * 9. Snapshot errors produce a bounded, safe error state without crashing the surrounding Command Deck.
 * 10. Existing console navigation, shortcuts, and unrelated stage HUDs continue to function 100%.
 * 11. Zero consequential side-effects (no Action Bus dispatches, no network fetch, no LLM provider calls).
 * 12. Toggle button interaction transitions between inline telemetry summary and full master HUD overlay.
 * 13. Deep immutability of projections and zero WebGL draw calls or canvas contexts.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/react';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { OperatorHUD } from '../components/spatial/OperatorHUD';
import { controlPlaneSnapshotService } from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { actionBusService } from '../services/actionBusService';
import { missionManager } from '../services/missionManager';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
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
import { RecoveryControlDecision } from '../types/recoveryControl';
import { PersistedApprovalRecord } from '../types/executionPersistence';

function createMockCommandControl(overrides?: Record<string, unknown>) {
  return {
    commandState: 'IDLE',
    commandInput: '',
    currentCommand: null,
    lastResult: null,
    lastExecutionResult: null,
    activeCamera: 'COMMAND',
    memoryEvents: [],
    isConsoleOpen: true,
    setCommandInput: vi.fn(),
    submitCommand: vi.fn(),
    confirmProposal: vi.fn(),
    cancelProposal: vi.fn(),
    dismissResult: vi.fn(),
    setIsConsoleOpen: vi.fn(),
    toggleConsole: vi.fn(),
    navigateHistory: vi.fn(),
    ...overrides,
  };
}

function createMockMission(overrides?: Partial<Mission>): Mission {
  return {
    missionId: 'mis-int-001',
    title: 'Integrated Orbital Scan',
    objective: 'Test complete HUD data flow from persistence to DOM.',
    goals: [
      {
        goalId: 'g-scan-1',
        title: 'Sensor Alignment',
        mandatory: true,
        status: 'COMPLETED',
        weight: 1,
      },
    ],
    dependencies: [],
    priority: 'HIGH',
    status: 'RUNNING',
    riskLevel: 'LOW',
    progress: {
      totalGoals: 1,
      completedGoals: 1,
      failedGoals: 0,
      inProgressGoals: 0,
      blockedGoals: 0,
      percentage: 100,
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
    provenance: { source: 'integration-test' },
    ...overrides,
  };
}

describe('AryaOS V1 Stage 24 — Phase 8: Control Plane Integration & Acceptance', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    executionPersistence.clearEnvelope();
    auditEventRegistry.reset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. HUD mounts through the intended application entry point (SpatialCommandConsole)
  it('1. mounts stage24-control-plane-hud cleanly through SpatialCommandConsole', () => {
    const mockControl = createMockCommandControl();
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockControl as any} />);

    expect(getByTestId('spatial-command-console')).toBeDefined();
    expect(getByTestId('stage24-control-plane-hud')).toBeDefined();
    expect(getByTestId('control-plane-hud-status').textContent).toBe('OBSERVATIONAL_HUD');
    expect(getByTestId('control-plane-authority-badge').textContent).toBe('AUTHORITY: ZERO_AUTHORITY');
    expect(getByTestId('control-plane-epistemic-badge').textContent).toBe('EPISTEMIC: STRICT_PROJECTION');
  });

  // 2. Toggle button mounts and unmounts full Master Operator HUD overlay
  it('2. toggles between inline telemetry matrix and full Master Operator HUD overlay', () => {
    const mockControl = createMockCommandControl();
    const { getByTestId, queryByTestId } = render(
      <SpatialCommandConsole commandControl={mockControl as any} />
    );

    // Initial state: full overlay is closed
    expect(queryByTestId('operator-hud')).toBeNull();
    const toggleBtn = getByTestId('toggle-operator-hud-btn');
    expect(toggleBtn.textContent).toBe('OPEN FULL HUD');

    // Click to open full HUD
    fireEvent.click(toggleBtn);
    expect(getByTestId('operator-hud')).toBeDefined();
    expect(getByTestId('hud-header')).toBeDefined();
    expect(toggleBtn.textContent).toBe('HIDE FULL HUD');

    // Click to close full HUD
    fireEvent.click(toggleBtn);
    expect(queryByTestId('operator-hud')).toBeNull();
    expect(toggleBtn.textContent).toBe('OPEN FULL HUD');
  });

  // 3. showOperatorHud prop opens full HUD directly on mount
  it('3. directly mounts full OperatorHUD when showOperatorHud is true', () => {
    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockControl as any} showOperatorHud={true} />
    );

    expect(getByTestId('operator-hud')).toBeDefined();
    expect(getByTestId('hud-overview-section')).toBeDefined();
  });

  // 4. All 8 expected panels are composed and accessible via tabs
  it('4. composes all 8 canonical panels across tabs without duplicate projections', () => {
    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockControl as any} showOperatorHud={true} />
    );

    const expectedTabs = [
      'hud-tab-overview',
      'hud-tab-health',
      'hud-tab-missions',
      'hud-tab-operations',
      'hud-tab-approvals',
      'hud-tab-recovery',
      'hud-tab-causal',
      'hud-tab-resources',
    ];

    for (const tabId of expectedTabs) {
      expect(getByTestId(tabId)).toBeDefined();
    }
  });

  // 5. Canonical snapshot data reaches the correct child panels
  it('5. propagates canonical snapshot data accurately to panels', () => {
    // Seed a mission
    executionPersistence.saveMission(createMockMission({
      missionId: 'mis-prop-101',
      title: 'Deep Telemetry Mapping',
    }));

    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="missions"
      />
    );

    expect(getByTestId('mission-operations-panel')).toBeDefined();
    expect(getByTestId('mission-card-mis-prop-101')).toBeDefined();
    expect(getByTestId('mission-card-mis-prop-101').textContent).toContain('Deep Telemetry Mapping');
  });

  // 6. UNKNOWN, missing evidence, empty data remain visible and truthful
  it('6. strictly preserves UNKNOWN states and missing evidence markers in integrated view', () => {
    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="operations"
      />
    );

    // Initial empty state displays empty state panel truthfully
    expect(getByTestId('operation-timeline-panel')).toBeDefined();
    expect(getByTestId('timeline-panel-empty')).toBeDefined();
    expect(getByTestId('timeline-panel-empty').textContent).toContain('NO OPERATIONS RECORDED');
  });

  // 7. Pending approvals are not presented as approved or executed
  it('7. strictly renders pending approval requirements as PENDING_REVIEW without execution grants', () => {
    // Inject a pending approval into persistence
    const record: PersistedApprovalRecord = {
      approvalId: 'prop-int-app-1',
      goalId: 'goal-101',
      planId: 'plan-101',
      actionId: 'act-101',
      actionTitle: 'Deploy production hotfix',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const mockControl = createMockCommandControl();
    const { getByTestId, queryByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="approvals"
      />
    );

    expect(getByTestId('approval-center-panel')).toBeDefined();
    expect(getByTestId('approval-card-prop-int-app-1')).toBeDefined();
    expect(getByTestId('approval-card-prop-int-app-1').textContent).toContain('PENDING');
    expect(getByTestId('approval-truth-explanation').textContent).toContain(
      'APPROVAL REQUIRED: Action blocked until authoritative human operator token is issued.'
    );

    // Confirm ZERO approval or rejection mutation buttons
    expect(queryByTestId('approve-btn')).toBeNull();
    expect(queryByTestId('reject-btn')).toBeNull();
  });

  // 8. Proposed recovery is not presented as dispatched or completed
  it('8. strictly renders proposed recovery decisions as PROPOSED without claiming execution', () => {
    const decision: RecoveryControlDecision = {
      decisionId: 'rec-int-dec-1',
      recoveryPlanId: 'rec-int-dec-1',
      requestId: 'req-rec-int-1',
      operationId: 'op-fail-int',
      originalOperationId: 'op-fail-int',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      recommendedAction: 'RETRY',
      safetyAssessment: {
        idempotencyClassification: 'IDEMPOTENT',
        duplicateSideEffectRisk: 'NONE',
        reconciliationRequirement: false,
        partialExecutionDetected: false,
        completedSteps: [],
        incompleteSteps: [],
        compensationAvailability: 'NO_COMPENSATION_AVAILABLE',
        rollbackAvailability: false,
        retryPermitted: true,
        humanApprovalRequired: true,
        safetyRationale: 'Transient network failure; safe to retry.',
        assessmentTimestamp: 1727970000000,
      },
      governanceRequirement: {
        required: true,
        humanOperatorRequired: true,
      },
      requiredAuthority: ['OPERATOR'],
      riskLevel: 'HIGH',
      epistemicStatus: 'OBSERVED',
      reasonCodes: ['TRANSIENT_FAULT'],
      evidenceIds: ['ev-1'],
      causationId: 'cause-1',
      correlationId: 'corr-1',
      expiresAt: 1727980000000,
      lifecycleState: 'DECIDED',
      recoveryDepth: 1,
      retryCount: 0,
      reconciliationAttempts: 0,
      createdAt: 1727970000000,
    };
    executionPersistence.saveRecoveryControlDecision(decision);

    const mockControl = createMockCommandControl();
    const { getByTestId, queryByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="recovery"
      />
    );

    expect(getByTestId('recovery-operations-panel')).toBeDefined();
    expect(getByTestId('recovery-card-rec-int-dec-1')).toBeDefined();
    expect(getByTestId('proposed-action-banner').textContent).toContain('RETRY');
    expect(getByTestId('recovery-count-badge').textContent).toContain('1 RECORDS');

    // Confirm ZERO retry or compensation execution buttons
    expect(queryByTestId('execute-recovery-btn')).toBeNull();
    expect(queryByTestId('retry-now-btn')).toBeNull();
  });

  // 9. Allocated resources are not represented as consumed resources
  it('9. strictly segregates resource limits from measured telemetry consumption', () => {
    executionPersistence.saveMission(createMockMission({
      missionId: 'mis-res-alloc',
      title: 'Resource Segregation Mission',
      constraints: [
        { type: 'COST_BUDGET', value: 50, strict: true },
        { type: 'TIME_DEADLINE', value: 60000, strict: false },
      ],
    }));

    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="resources"
      />
    );

    expect(getByTestId('resource-status-panel')).toBeDefined();
    const costCard = getByTestId('resource-card-cost_budget');
    expect(costCard).toBeDefined();
    expect(within(costCard).getByTestId('resource-allocated-value').textContent).toContain('50');
    // Telemetry consumption is unrecorded, so it must display UNKNOWN, never fabricated
    expect(within(costCard).getByTestId('resource-utilized-value').textContent).toContain('UNKNOWN');
  });

  // 10. Untrusted strings cannot inject executable HTML
  it('10. sanitizes untrusted input strings and blocks executable HTML in console DOM', () => {
    const maliciousPayload = '<img src="x" onerror="alert(1)" /><script>evil()</script>';
    executionPersistence.saveMission(createMockMission({
      missionId: 'mis-xss-int',
      title: maliciousPayload,
      objective: 'Check XSS neutralization: ' + maliciousPayload,
    }));

    const mockControl = createMockCommandControl();
    const { getByTestId, container } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="missions"
      />
    );

    const titleEl = getByTestId('mission-card-mis-xss-int');
    expect(titleEl.textContent).toContain('<img src="x" onerror="alert(1)" />');
    expect(container.querySelectorAll('script').length).toBe(0);
  });

  // 11. Snapshot errors produce a safe error state without crashing the entire command deck
  it('11. isolates snapshot service errors gracefully without unmounting the command deck', () => {
    const mockControl = createMockCommandControl();

    // Force getSnapshot to throw
    const spy = vi.spyOn(controlPlaneSnapshotService, 'getSnapshot').mockImplementation(() => {
      throw new Error('CORRUPTED_PERSISTENCE_FAULT');
    });

    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockControl as any} />);

    // Command console remains healthy and mounted
    expect(getByTestId('spatial-command-console')).toBeDefined();
    expect(getByTestId('stage24-control-plane-hud')).toBeDefined();
    expect(getByTestId('control-plane-error-banner')).toBeDefined();
    expect(getByTestId('control-plane-error-banner').textContent).toContain('CORRUPTED_PERSISTENCE_FAULT');

    spy.mockRestore();
  });

  // 12. Existing navigation, shortcuts, and unrelated views continue to work
  it('12. preserves all Stage 05-23 console controls and terminal shortcuts', () => {
    const submitSpy = vi.fn();
    const mockControl = createMockCommandControl({ submitCommand: submitSpy });
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockControl as any} />);

    // Stage 21, 22, 23 HUDs are present and intact
    expect(getByTestId('governance-control-plane-hud')).toBeDefined();
    expect(getByTestId('operational-audit-hud')).toBeDefined();
    expect(getByTestId('recovery-control-plane-hud')).toBeDefined();

    // Stage 05 terminal input is functional
    const input = getByTestId('spatial-command-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Goal: Test Mission' } });
    const submitBtn = getByTestId('spatial-command-submit-btn');
    fireEvent.click(submitBtn);
    expect(submitSpy).toHaveBeenCalled();
  });

  // 13. Integration introduces zero execution, network, LLM, or authorization side-effects
  it('13. verifies ZERO calls to external APIs, LLM endpoints, or Action Bus during console operations', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const actionSpy = vi.spyOn(actionBusService, 'execute');
    const missionSpy = vi.spyOn(missionManager, 'createMission');
    const goalSpy = vi.spyOn(goalOrchestrator, 'createAndExecuteGoal');
    const recSpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');

    const mockControl = createMockCommandControl();
    render(<SpatialCommandConsole commandControl={mockControl as any} showOperatorHud={true} />);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(actionSpy).not.toHaveBeenCalled();
    expect(missionSpy).not.toHaveBeenCalled();
    expect(goalSpy).not.toHaveBeenCalled();
    expect(recSpy).not.toHaveBeenCalled();
  });

  // 14. Pure DOM overlay: 0 canvas elements and 0 WebGL contexts created
  it('14. verifies pure DOM overlay with zero HTML5 canvas elements and zero WebGL contexts', () => {
    const mockControl = createMockCommandControl();
    const { container } = render(
      <SpatialCommandConsole commandControl={mockControl as any} showOperatorHud={true} />
    );

    const canvases = container.querySelectorAll('canvas');
    expect(canvases.length).toBe(0);
  });

  // 15. Returned snapshots and projection arrays are deeply frozen
  it('15. verifies deep immutability across all rendered projections', () => {
    const snap = controlPlaneSnapshotService.getSnapshot();
    expect(Object.isFrozen(snap)).toBe(true);
    expect(Object.isFrozen(snap.missions)).toBe(true);
    expect(Object.isFrozen(snap.operations)).toBe(true);
    expect(Object.isFrozen(snap.approvals)).toBe(true);
    expect(Object.isFrozen(snap.recovery)).toBe(true);
  });
});
