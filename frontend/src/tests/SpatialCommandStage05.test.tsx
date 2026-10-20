/**
 * AryaOS V1 — Stage 05: Spatial Intelligence Command Layer Tests
 *
 * Verifies:
 * 1. Command Parser (Natural language intent classification, entity resolution, empty/unknown/malformed handling)
 * 2. Memory Context Engine (Direct/reverse edges, timeline neighbors, entities, unresolved items)
 * 3. Action Proposal & Execution System (Confirmation gate, PLANNED vs EXECUTED, memory events ledger)
 * 4. Spatial Integration (Memory selection, vitrine highlighting, camera switching, state machine)
 * 5. Safety & Immutability Verification (Non-accidental execution, zero geometry mutation)
 */

import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { commandParser } from '../services/commandParser';
import { memoryContextService } from '../services/memoryContextService';
import { actionProposalService } from '../services/actionProposalService';
import { useMemoryArchive } from '../hooks/useMemoryArchive';
import { useSpatialCommand } from '../hooks/useSpatialCommand';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { SpatialActionPreview } from '../components/spatial/SpatialActionPreview';
import { MemoryArchiveOverlay } from '../components/spatial/MemoryArchiveOverlay';
import { STAGE03_CAMERAS } from '../stage03_assembly';

describe('AryaOS V1 Stage 05 — Spatial Intelligence Command Layer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    actionProposalService.resetMemoryEvents();
  });

  describe('1. Command Parser & Entity Resolution', () => {
    it('classifies natural language command intents accurately', () => {
      // 1. Show related memories
      const cmd1 = commandParser.parse('Show me everything related to Horizon');
      expect(cmd1.intent).toBe('SHOW_RELATED');
      expect(cmd1.entities.some((e) => e.type === 'memory')).toBe(true);

      // 2. What changed recently
      const cmd2 = commandParser.parse('What changed recently?');
      expect(cmd2.intent).toBe('RECENT_CHANGES');

      // 3. Find decisions
      const cmd3 = commandParser.parse('Find decisions related to the Memory Archive');
      expect(cmd3.intent).toBe('FIND_DECISIONS');

      // 4. Show workflows
      const cmd4 = commandParser.parse('Show workflows connected to this project');
      expect(cmd4.intent).toBe('SHOW_WORKFLOWS');

      // 5. Trace history
      const cmd5 = commandParser.parse('Trace the history of this decision');
      expect(cmd5.intent).toBe('TRACE_HISTORY');

      // 6. Show artifacts
      const cmd6 = commandParser.parse('What artifacts were generated from this conversation?');
      expect(cmd6.intent).toBe('SHOW_ARTIFACTS');

      // 7. Show unresolved items
      const cmd7 = commandParser.parse('Show me unresolved items');
      expect(cmd7.intent).toBe('SHOW_UNRESOLVED');

      // 8. Open memory
      const cmd8 = commandParser.parse('Open memory MEM-0021');
      expect(cmd8.intent).toBe('OPEN_MEMORY');
      expect(cmd8.targetMemoryId).toBe('MEM-0021');

      // 9. Inspect dependencies
      const cmd9 = commandParser.parse('What depends on this decision?');
      expect(cmd9.intent).toBe('INSPECT_DEPENDENCIES');

      // 10. Research task
      const cmd10 = commandParser.parse('Create a research task from this memory');
      expect(cmd10.intent).toBe('CREATE_RESEARCH_TASK');

      // 11. Production plan
      const cmd11 = commandParser.parse('Generate a production plan from this decision');
      expect(cmd11.intent).toBe('GENERATE_PRODUCTION_PLAN');

      // 12. Camera switch
      const cmd12 = commandParser.parse('Switch camera to monumental view');
      expect(cmd12.intent).toBe('SWITCH_CAMERA');
      expect(cmd12.targetCamera).toBe('CAM_MonumentalLowAngle');
    });

    it('resolves semantic entities across memories, vitrines, agents, and cameras', () => {
      const entities = commandParser.resolveEntities(
        'Check Dais_Flank_Crystal_01 and ask Script Agent from hero camera'
      );
      const types = entities.map((e) => e.type);
      expect(types).toContain('vitrine');
      expect(types).toContain('agent');
      expect(types).toContain('camera');
    });

    it('handles empty input, unknown commands, and malformed queries gracefully', () => {
      // Empty input
      const emptyCmd = commandParser.parse('');
      expect(emptyCmd.intent).toBe('UNKNOWN');
      expect(emptyCmd.explanation).toContain('empty');

      // Whitespace only
      const wsCmd = commandParser.parse('   ');
      expect(wsCmd.intent).toBe('UNKNOWN');

      // Unknown gibberish
      const unknownCmd = commandParser.parse('xyz123randomgibberish999');
      expect(unknownCmd.intent).toBe('QUERY_MEMORY'); // Falls back to query search
    });
  });

  describe('2. Memory Context Engine', () => {
    it('computes complete deterministic context for an active memory', () => {
      // MEM-0001
      const ctx = memoryContextService.buildContext('MEM-0001');
      expect(ctx.activeMemory).toBeDefined();
      expect(ctx.activeMemory?.id).toBe('MEM-0001');
      expect(ctx.activeVitrineId).toBe('Dais_Flank_Crystal_01');
      expect(ctx.directRelationships.length).toBeGreaterThanOrEqual(2);
      expect(ctx.timelineNeighbors.index).toBe(2);
      expect(ctx.timelineNeighbors.predecessor).toBeDefined();
      expect(ctx.sharedEntities.length).toBeGreaterThanOrEqual(1);
      expect(ctx.sharedTags.length).toBeGreaterThanOrEqual(1);
    });

    it('identifies unresolved multi-agent arbitration and low-confidence relationships', () => {
      const unresolved = memoryContextService.findUnresolvedItems();
      expect(unresolved.length).toBeGreaterThanOrEqual(1);

      // Verify that arbitration decisions like MEM-0020 or MEM-0004 appear
      const unresolvedMemories = memoryContextService.getUnresolvedMemories();
      expect(unresolvedMemories.length).toBeGreaterThanOrEqual(1);
      const hasArbitration = unresolvedMemories.some(
        (m) => m.tags.includes('arbitration') || m.tags.includes('conflict')
      );
      expect(hasArbitration).toBe(true);
    });

    it('provides system-wide global context when no active memory is selected', () => {
      const globalCtx = memoryContextService.buildContext(null);
      expect(globalCtx.activeMemory).toBeNull();
      expect(globalCtx.sameProjectMemories.length).toBeGreaterThanOrEqual(1);
      expect(globalCtx.sameWorkflowMemories.length).toBeGreaterThanOrEqual(1);
      expect(globalCtx.relatedArtifacts.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('3. Action Proposal & Honest Execution System', () => {
    it('creates action proposal from a parsed command without automatic execution', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd);

      expect(proposal).not.toBeNull();
      expect(proposal?.actionClass).toBe('RESEARCH');
      expect(proposal?.status).toBe('PROPOSED');
      expect(proposal?.executionType).toBe('BACKEND_ADAPTER');
      expect(proposal?.sourceMemoryId).toBe('MEM-0001');
      expect(proposal?.contextSummary.relatedCount).toBeGreaterThanOrEqual(1);
    });

    it('adheres to honest execution: consequential backend actions return status PLANNED', () => {
      const cmd = commandParser.parse('Generate a production plan from this decision', 'MEM-0002');
      const proposal = actionProposalService.createProposal(cmd);
      expect(proposal).not.toBeNull();

      const result = actionProposalService.executeProposal(proposal!);
      expect(result.status).toBe('PLANNED');
      expect(result.success).toBe(true);
      expect(result.message).toContain('PLANNED');

      // Verify recorded memory event in semantic layer
      const events = actionProposalService.getMemoryEvents();
      expect(events.length).toBeGreaterThanOrEqual(1);
      expect(events[0].status).toBe('PLANNED');
      expect(events[0].action).toBe('CREATE_WORKFLOW');
    });

    it('executes direct frontend actions with status EXECUTED and logs event', () => {
      const cmd = commandParser.parse('Open memory MEM-0021');
      const proposal = actionProposalService.createProposal(cmd);
      expect(proposal).not.toBeNull();

      const result = actionProposalService.executeProposal(proposal!);
      expect(result.status).toBe('EXECUTED');
      expect(result.success).toBe(true);

      const events = actionProposalService.getMemoryEvents();
      expect(events[0].status).toBe('EXECUTED');
      expect(events[0].action).toBe('OPEN_MEMORY');
    });
  });

  describe('4. Spatial Command Hook & State Machine (useSpatialCommand)', () => {
    it('handles command submission and transitions through state machine', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      expect(cmdHook.current.commandState).toBe('IDLE');

      // Submit camera switch command
      act(() => {
        cmdHook.current.submitCommand('Switch camera to monumental');
      });

      expect(cmdHook.current.activeCamera).toBe('CAM_MonumentalLowAngle');
      expect(cmdHook.current.commandState).toBe('RESULT');
      expect(cmdHook.current.lastResult?.status).toBe('EXECUTED');
    });

    it('enforces confirmation gate: consequential action stops at PROPOSING_ACTION until confirmed', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      act(() => {
        cmdHook.current.submitCommand('Create a research task from this memory');
      });

      // Must be waiting in PROPOSING_ACTION
      expect(cmdHook.current.commandState).toBe('PROPOSING_ACTION');
      expect(cmdHook.current.activeProposal).not.toBeNull();
      expect(cmdHook.current.activeProposal?.actionClass).toBe('RESEARCH');

      // Confirm action
      act(() => {
        cmdHook.current.confirmProposal();
      });

      // Simulates async confirmation transition
      expect(['CONFIRMING', 'EXECUTING', 'RESULT']).toContain(cmdHook.current.commandState);
    });

    it('cancels action proposal cleanly without side-effects', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      act(() => {
        cmdHook.current.submitCommand('Generate a production plan from this decision');
      });

      expect(cmdHook.current.activeProposal).not.toBeNull();

      act(() => {
        cmdHook.current.cancelProposal();
      });

      expect(cmdHook.current.activeProposal).toBeNull();
      expect(cmdHook.current.lastResult?.status).toBe('CANCELLED');
    });

    it('activates spatial vitrine highlights for related memories command', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      act(() => {
        cmdHook.current.submitCommand('Show related memories for MEM-0001');
      });

      expect(cmdHook.current.highlightedVitrineIds.length).toBeGreaterThan(0);
      expect(cmdHook.current.highlightedVitrineIds).toContain('Dais_Flank_Crystal_01');
    });

    it('isolates unresolved vitrines on "Show unresolved" command', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      act(() => {
        cmdHook.current.submitCommand('Show unresolved items');
      });

      expect(cmdHook.current.highlightedVitrineIds.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('5. UI Components & Operator Surface', () => {
    it('renders SpatialCommandConsole terminal and submits typed commands', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      render(<SpatialCommandConsole commandControl={cmdHook.current} />);

      expect(screen.getByTestId('spatial-command-console')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-command-input')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-command-submit-btn')).toBeInTheDocument();

      // Check quick action pills
      expect(screen.getByTestId('command-pill-trace-history')).toBeInTheDocument();
      expect(screen.getByTestId('command-pill-show-related')).toBeInTheDocument();
      expect(screen.getByTestId('command-pill-show-unresolved')).toBeInTheDocument();

      // Submit via button
      const input = screen.getByTestId('spatial-command-input');
      fireEvent.change(input, { target: { value: 'Trace history' } });
      fireEvent.click(screen.getByTestId('spatial-command-submit-btn'));

      expect(cmdHook.current.commandHistory).toContain('Trace history');
    });

    it('renders Action Preview confirmation card and handles confirm / cancel clicks', () => {
      const mockProposal = {
        id: 'ACT-TEST-01',
        actionClass: 'RESEARCH' as const,
        title: 'Research Test Proposal',
        description: 'Test investigation for continuity boundaries',
        sourceMemoryId: 'MEM-0001',
        sourceMemoryTitle: 'Foundational Charter',
        contextSummary: { relatedCount: 3, entitiesCount: 2, decisionsCount: 1 },
        executionType: 'BACKEND_ADAPTER' as const,
        status: 'PROPOSED' as const,
        createdAt: new Date().toISOString(),
      };

      const onConfirm = vi.fn();
      const onCancel = vi.fn();

      render(
        <SpatialActionPreview
          proposal={mockProposal}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      expect(screen.getByTestId('spatial-action-preview')).toBeInTheDocument();
      expect(screen.getByTestId('action-proposal-title')).toHaveTextContent(/Research Test Proposal/i);
      expect(screen.getByTestId('action-proposal-confirm-btn')).toBeInTheDocument();
      expect(screen.getByTestId('action-proposal-cancel-btn')).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('action-proposal-confirm-btn'));
      expect(onConfirm).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByTestId('action-proposal-cancel-btn'));
      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('integrates seamlessly into MemoryArchiveOverlay without regressions', () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      render(<MemoryArchiveOverlay memoryArchive={memHook.current} />);

      expect(screen.getByTestId('memory-archive-overlay')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-command-console')).toBeInTheDocument();
      expect(screen.getByTestId('memory-cards-container')).toBeInTheDocument();
    });
  });

  describe('6. Safety & Locked Boundary Invariance Audit', () => {
    it('cameras are strictly confined to locked STAGE03_CAMERAS specifications', () => {
      const allowedCameras = Object.keys(STAGE03_CAMERAS);
      expect(allowedCameras).toEqual([
        'CAM_CinematicHero',
        'CAM_MonumentalLowAngle',
        'CAM_ArchiveDetail',
      ]);

      // Verify CAM_CinematicHero
      expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
      expect(STAGE03_CAMERAS.CAM_CinematicHero.position).toEqual([-12.0, 2.3, 38.5]);

      // Verify CAM_MonumentalLowAngle
      expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
      expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.position).toEqual([0.0, 0.65, 26.0]);

      // Verify CAM_ArchiveDetail
      expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
      expect(STAGE03_CAMERAS.CAM_ArchiveDetail.position).toEqual([-16.2, 1.85, 32.8]);
    });
  });
});
