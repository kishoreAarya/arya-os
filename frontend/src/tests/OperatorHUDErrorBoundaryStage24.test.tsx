/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Phase 9.1: React Error Boundary & Panel Fault Isolation Test Suite
 *
 * Strict Architectural Verification:
 * 1. A child panel throwing an unhandled exception during render is caught by OperatorHUDErrorBoundary.
 * 2. The failed panel displays its localized fallback (data-testid="panel-error-fallback").
 * 3. Unaffected sibling panels (e.g. SystemHealthPanel, RecoveryOperationsPanel in Overview tab) remain fully rendered.
 * 4. A child panel failure does NOT crash or unmount the enclosing SpatialCommandConsole or its terminal input.
 * 5. Error presentations strictly suppress stack traces and scrub sensitive tokens/secrets.
 * 6. Normal rendering of all panels remains unchanged when zero exceptions occur.
 * 7. Fallback provides accessible ARIA alert semantics (role="alert", aria-live="assertive") and a retry button.
 * 8. Manual retry clears the error boundary state and re-renders successfully when the fault is transient.
 * 9. Operator can switch between tabs even when one tab encounters an error.
 * 10. Fault containment introduces ZERO action bus calls, network requests, or consequential mutations.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import {
  OperatorHUDErrorBoundary,
  OperatorHUD,
  SystemHealthPanel,
  ApprovalCenterPanel,
  RecoveryOperationsPanel,
  MissionOperationsPanel,
} from '../components/control-plane';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { controlPlaneSnapshotService } from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { actionBusService } from '../services/actionBusService';
import { missionManager } from '../services/missionManager';
import { ControlPlaneSnapshot } from '../types/controlPlane';

// Helper component that throws an error on demand
const FaultyChildComponent: React.FC<{
  shouldThrow?: boolean;
  errorMessage?: string;
  normalContent?: string;
}> = ({
  shouldThrow = true,
  errorMessage = 'CRITICAL_PARSER_FAULT',
  normalContent = 'NORMAL_CHILD_RENDER',
}) => {
  if (shouldThrow) {
    throw new Error(errorMessage);
  }
  return <div data-testid="faulty-child-normal">{normalContent}</div>;
};

function createMockCommandControl(overrides?: Record<string, unknown>) {
  return {
    commandState: 'IDLE',
    commandInput: '',
    currentCommand: null,
    lastResult: null,
    isConsoleOpen: true,
    activeCamera: 'COMMAND',
    historyIndex: -1,
    commandHistory: [],
    executeCommand: vi.fn(),
    submitCommand: vi.fn(),
    cancelCommand: vi.fn(),
    setCommandInput: vi.fn(),
    toggleConsole: vi.fn(),
    navigateHistory: vi.fn(),
    ...overrides,
  };
}

describe('AryaOS V1 Stage 24 — Phase 9.1: Operator HUD Error Boundary & Panel Fault Isolation', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Suppress expected React error boundary logs during tests
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    executionPersistence.clearEnvelope();
    auditEventRegistry.reset();
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    vi.restoreAllMocks();
  });

  // 1. Normal rendering when no error occurs
  it('1. renders children normally and adds zero overhead when no error occurs', () => {
    const { getByTestId, queryByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Test Subsystem">
        <div data-testid="normal-panel-content">HEALTHY_PANEL_TELEMETRY</div>
      </OperatorHUDErrorBoundary>
    );

    expect(getByTestId('normal-panel-content')).toBeDefined();
    expect(getByTestId('normal-panel-content').textContent).toBe('HEALTHY_PANEL_TELEMETRY');
    expect(queryByTestId('panel-error-fallback')).toBeNull();
  });

  // 2. Catches render error and displays localized panel fallback
  it('2. catches rendering error in child component and displays localized panel fallback', () => {
    const { getByTestId, queryByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Approval Center">
        <FaultyChildComponent shouldThrow={true} errorMessage="APPROVAL_STORE_DESERIALIZATION_FAULT" />
      </OperatorHUDErrorBoundary>
    );

    expect(queryByTestId('faulty-child-normal')).toBeNull();
    const fallback = getByTestId('panel-error-fallback');
    expect(fallback).toBeDefined();

    const title = getByTestId('panel-error-title');
    expect(title.textContent).toContain('APPROVAL CENTER // RENDERING ISOLATION FAULT');

    const message = getByTestId('panel-error-message');
    expect(message.textContent).toContain('APPROVAL_STORE_DESERIALIZATION_FAULT');

    const badge = getByTestId('panel-error-badge');
    expect(badge.textContent).toBe('FAULT CONTAINED');
  });

  // 3. Redacts secrets and sensitive credentials from error message
  it('3. strictly scrubs API keys and Bearer tokens from rendered error message', () => {
    const sensitiveError = 'Failed to load policy: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThis api_key=super_secret_password';
    const { getByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Security Gateway">
        <FaultyChildComponent shouldThrow={true} errorMessage={sensitiveError} />
      </OperatorHUDErrorBoundary>
    );

    const message = getByTestId('panel-error-message');
    expect(message.textContent).not.toContain('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9');
    expect(message.textContent).not.toContain('super_secret_password');
    expect(message.textContent).toContain('Bearer [REDACTED_TOKEN]');
    expect(message.textContent).toContain('[REDACTED_SECRET]');
  });

  // 4. Suppresses stack traces from rendered DOM
  it('4. strictly suppresses stack traces from rendered fallback DOM', () => {
    const errorWithStack = new Error('UNEXPECTED_NULL_REFERENCE');
    errorWithStack.stack = 'Error: UNEXPECTED_NULL_REFERENCE\n    at ApprovalCenterPanel.tsx:88:12\n    at renderWithHooks:1234';

    const Thrower: React.FC = () => {
      throw errorWithStack;
    };

    const { getByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Approval Center">
        <Thrower />
      </OperatorHUDErrorBoundary>
    );

    const fallback = getByTestId('panel-error-fallback');
    expect(fallback.textContent).not.toContain('ApprovalCenterPanel.tsx');
    expect(fallback.textContent).not.toContain('renderWithHooks');
    expect(fallback.textContent).not.toContain('at ');
  });

  // 5. Preserves sibling panels in Overview tab when one panel throws
  it('5. isolates child panel crash in Overview tab, preserving sibling panels', () => {
    // Generate valid baseline snapshot
    const snap = controlPlaneSnapshotService.getSnapshot();

    // Create corrupted snapshot where approvals throws on traversal during render
    const badApprovals: any = {
      length: 1,
      map() {
        throw new Error('CORRUPTED_APPROVAL_RECORD_ARRAY');
      },
    };
    const badSnapshot = {
      ...snap,
      approvals: badApprovals,
    };

    const { getByTestId } = render(
      <OperatorHUD
        isOpen={true}
        defaultTab="overview"
        initialSnapshot={badSnapshot as any}
      />
    );

    // Overview section is rendered
    expect(getByTestId('hud-overview-section')).toBeDefined();

    // System Health sibling panel is intact and healthy
    expect(getByTestId('system-health-panel')).toBeDefined();

    // Recovery Operations sibling panel is intact and healthy
    expect(getByTestId('recovery-operations-panel')).toBeDefined();

    // Mission Operations sibling panel is intact and healthy
    expect(getByTestId('mission-operations-panel')).toBeDefined();

    // Approval Center panel has failed, but its fallback is isolated
    expect(getByTestId('panel-error-fallback')).toBeDefined();
    expect(getByTestId('panel-error-title').textContent).toContain('APPROVAL CENTER');
  });

  // 6. Allows switching tabs when one tab panel encounters a rendering failure
  it('6. preserves tab navigation and allows switching away from a failing tab', () => {
    const snap = controlPlaneSnapshotService.getSnapshot();

    // Create corrupted snapshot where recovery throws on traversal
    const badRecovery: any = {
      length: 1,
      map() {
        throw new Error('RECOVERY_GRAPH_TRAVERSAL_FAULT');
      },
    };
    const badSnapshot = {
      ...snap,
      recovery: badRecovery,
    };

    const { getByTestId, queryByTestId } = render(
      <OperatorHUD
        isOpen={true}
        defaultTab="recovery"
        initialSnapshot={badSnapshot as any}
      />
    );

    // Recovery tab displays isolated fallback
    expect(getByTestId('panel-error-fallback')).toBeDefined();
    expect(getByTestId('panel-error-title').textContent).toContain('RECOVERY OPERATIONS');

    // Operator clicks MISSIONS tab
    const missionsTab = getByTestId('hud-tab-missions');
    fireEvent.click(missionsTab);

    // Missions panel renders cleanly
    expect(getByTestId('mission-operations-panel')).toBeDefined();
    expect(queryByTestId('panel-error-fallback')).toBeNull();
  });

  // 7. Accessible alert semantics and retry button
  it('7. provides accessible alert semantics and interactive retry button', () => {
    const onResetSpy = vi.fn();
    const { getByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Causal Evidence" onReset={onResetSpy}>
        <FaultyChildComponent shouldThrow={true} errorMessage="CAUSAL_TIMEOUT" />
      </OperatorHUDErrorBoundary>
    );

    const fallback = getByTestId('panel-error-fallback');
    expect(fallback.getAttribute('role')).toBe('alert');
    expect(fallback.getAttribute('aria-live')).toBe('assertive');

    const retryBtn = getByTestId('panel-error-retry-btn');
    expect(retryBtn).toBeDefined();
    expect(retryBtn.textContent).toBe('RETRY PANEL');

    fireEvent.click(retryBtn);
    expect(onResetSpy).toHaveBeenCalledTimes(1);
  });

  // 8. Manual recovery re-renders successfully when transient fault clears
  it('8. recovers gracefully when error condition resolves and operator clicks retry', () => {
    let shouldFail = true;

    const DynamicComponent: React.FC = () => {
      if (shouldFail) {
        throw new Error('TRANSIENT_PERSISTENCE_LOCK');
      }
      return <div data-testid="recovered-panel">PANEL_RESTORED_SUCCESSFULLY</div>;
    };

    const { getByTestId, queryByTestId } = render(
      <OperatorHUDErrorBoundary panelTitle="Mission Operations">
        <DynamicComponent />
      </OperatorHUDErrorBoundary>
    );

    // Initial state: error caught
    expect(getByTestId('panel-error-fallback')).toBeDefined();
    expect(queryByTestId('recovered-panel')).toBeNull();

    // Transient fault clears
    shouldFail = false;

    // Operator clicks RETRY PANEL
    const retryBtn = getByTestId('panel-error-retry-btn');
    fireEvent.click(retryBtn);

    // Panel recovers and renders healthy content
    expect(queryByTestId('panel-error-fallback')).toBeNull();
    expect(getByTestId('recovered-panel')).toBeDefined();
    expect(getByTestId('recovered-panel').textContent).toBe('PANEL_RESTORED_SUCCESSFULLY');
  });

  // 9. Failure in modal OperatorHUD does not crash SpatialCommandConsole
  it('9. prevents child panel crash in modal OperatorHUD from unmounting enclosing SpatialCommandConsole', () => {
    const snap = controlPlaneSnapshotService.getSnapshot();

    // Simulate an unhandled exception inside MissionOperationsPanel
    const badMissionItem: any = {
      missionId: 'mis-err',
      get title(): string {
        throw new Error('CRITICAL_DEPENDENCY_CYCLE');
      },
    };
    const badSnapshot = {
      ...snap,
      missions: [badMissionItem],
    };

    const mockControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole
        commandControl={mockControl as any}
        showOperatorHud={true}
        defaultHudTab="missions"
        initialControlPlaneSnapshot={badSnapshot as any}
      />
    );

    // Command Console remains 100% mounted and functional
    expect(getByTestId('spatial-command-console')).toBeDefined();
    expect(getByTestId('spatial-command-input')).toBeDefined();
    expect(getByTestId('spatial-command-submit-btn')).toBeDefined();

    // Operator HUD remains mounted
    expect(getByTestId('operator-hud')).toBeDefined();
    expect(getByTestId('hud-header')).toBeDefined();

    // Missions panel displays isolated fallback
    expect(getByTestId('panel-error-fallback')).toBeDefined();
    expect(getByTestId('panel-error-title').textContent).toContain('MISSION OPERATIONS');
  });

  // 10. Zero consequential actions or side-effects during error handling
  it('10. verifies ZERO calls to external APIs, LLM endpoints, or Action Bus during error handling', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const actionSpy = vi.spyOn(actionBusService, 'execute');
    const missionSpy = vi.spyOn(missionManager, 'createMission');

    render(
      <OperatorHUDErrorBoundary panelTitle="Approval Center">
        <FaultyChildComponent shouldThrow={true} errorMessage="CATASTROPHIC_TEST_ERROR" />
      </OperatorHUDErrorBoundary>
    );

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(actionSpy).not.toHaveBeenCalled();
    expect(missionSpy).not.toHaveBeenCalled();
  });
});
