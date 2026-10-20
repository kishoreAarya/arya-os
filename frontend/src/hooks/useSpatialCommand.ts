/**
 * AryaOS V1 — Stage 05: Spatial Command Layer Hook
 *
 * Implements the extended operational state machine:
 * IDLE -> HOVERED -> SELECTED -> INSPECTING -> RELATED_MEMORY -> COMMANDING
 * -> PROPOSING_ACTION -> CONFIRMING -> EXECUTING -> RESULT -> MEMORY_UPDATED -> RETURN
 *
 * Coordinates natural language parsing, context compilation, spatial highlighting,
 * action confirmation flows, and semantic memory event creation.
 */

import { useState, useCallback, useMemo, useEffect } from 'react';
import {
  Command,
  ActionProposal,
  ActionResult,
  MemoryEvent,
  SpatialCommandState,
} from '../types/spatialCommand';
import {
  ExecutionPlan,
  ExecutionResult,
} from '../types/intelligenceProvider';
import { UseMemoryArchiveReturn } from './useMemoryArchive';
import { commandParser } from '../services/commandParser';
import { memoryContextService } from '../services/memoryContextService';
import { actionProposalService } from '../services/actionProposalService';
import { memoryArchiveService } from '../services/memoryArchiveService';
import { providerRouter } from '../services/providerRouter';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { goalOrchestrator } from '../services/goalOrchestrator';

export interface UseSpatialCommandReturn {
  // State
  commandState: SpatialCommandState;
  commandInput: string;
  commandHistory: string[];
  currentCommand: Command | null;
  activeProposal: ActionProposal | null;
  activeExecutionPlan: ExecutionPlan | null;
  lastResult: ActionResult | null;
  lastExecutionResult: ExecutionResult | null;
  highlightedVitrineIds: string[];
  activeCamera: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail';
  memoryEvents: MemoryEvent[];
  isConsoleOpen: boolean;

  // Actions
  setCommandInput: (val: string) => void;
  submitCommand: (rawOverride?: string) => void;
  confirmProposal: () => void;
  cancelProposal: () => void;
  dismissResult: () => void;
  clearHighlights: () => void;
  setActiveCamera: (cam: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail') => void;
  setIsConsoleOpen: (open: boolean) => void;
  toggleConsole: () => void;
  navigateHistory: (direction: 'up' | 'down') => void;
}

export function useSpatialCommand(memoryArchive: UseMemoryArchiveReturn): UseSpatialCommandReturn {
  const [commandState, setCommandState] = useState<SpatialCommandState>('IDLE');
  const [commandInput, setCommandInput] = useState<string>('');
  const [commandHistory, setCommandHistory] = useState<string[]>([
    'Show related memories',
    'Trace history',
    'Show unresolved',
    'Find decisions',
    'Switch camera to monumental',
  ]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [currentCommand, setCurrentCommand] = useState<Command | null>(null);
  const [activeProposal, setActiveProposal] = useState<ActionProposal | null>(null);
  const [activeExecutionPlan, setActiveExecutionPlan] = useState<ExecutionPlan | null>(null);
  const [lastResult, setLastResult] = useState<ActionResult | null>(null);
  const [lastExecutionResult, setLastExecutionResult] = useState<ExecutionResult | null>(null);
  const [highlightedVitrineIds, setHighlightedVitrineIds] = useState<string[]>([]);
  const [activeCamera, setActiveCamera] = useState<
    'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail'
  >('CAM_CinematicHero');
  const [memoryEvents, setMemoryEvents] = useState<MemoryEvent[]>(() =>
    actionProposalService.getMemoryEvents()
  );
  const [isConsoleOpen, setIsConsoleOpen] = useState<boolean>(true);

  // Sync state machine with memoryArchive interaction state when not in command workflow
  useEffect(() => {
    if (
      commandState !== 'COMMANDING' &&
      commandState !== 'PROPOSING_ACTION' &&
      commandState !== 'CONFIRMING' &&
      commandState !== 'EXECUTING' &&
      commandState !== 'RESULT'
    ) {
      setCommandState(memoryArchive.interactionState as SpatialCommandState);
    }
  }, [memoryArchive.interactionState, commandState]);

  // Navigate Command History (Up/Down)
  const navigateHistory = useCallback(
    (direction: 'up' | 'down') => {
      if (commandHistory.length === 0) return;

      if (direction === 'up') {
        const nextIdx = historyIndex < commandHistory.length - 1 ? historyIndex + 1 : historyIndex;
        setHistoryIndex(nextIdx);
        setCommandInput(commandHistory[commandHistory.length - 1 - nextIdx] || '');
      } else {
        const nextIdx = historyIndex > 0 ? historyIndex - 1 : -1;
        setHistoryIndex(nextIdx);
        setCommandInput(nextIdx >= 0 ? commandHistory[commandHistory.length - 1 - nextIdx] : '');
      }
    },
    [commandHistory, historyIndex]
  );

  // Submit Command
  const submitCommand = useCallback(
    async (rawOverride?: string) => {
      const input = (rawOverride !== undefined ? rawOverride : commandInput).trim();
      if (!input) return;

      // Append to history
      setCommandHistory((prev) => [...prev, input]);
      setHistoryIndex(-1);
      setCommandState('COMMANDING');

      // Parse Command with current context
      const cmd = commandParser.parse(input, memoryArchive.selectedMemoryId);
      setCurrentCommand(cmd);

      // 1. Camera Switch Intent
      if (cmd.intent === 'SWITCH_CAMERA' && cmd.targetCamera) {
        setActiveCamera(cmd.targetCamera);
        const proposal = actionProposalService.createProposal(cmd);
        if (proposal) {
          const res = actionProposalService.executeProposal(proposal);
          setLastResult(res);
          setMemoryEvents(actionProposalService.getMemoryEvents());
          setCommandState('RESULT');
          setCommandInput('');
        }
        return;
      }

      // 2. Clear Filters / Show All
      if (cmd.intent === 'CLEAR_FILTERS') {
        setHighlightedVitrineIds([]);
        memoryArchive.resetFilters();
        setCommandState('IDLE');
        setCommandInput('');
        return;
      }

      // 3. Show Unresolved Items
      if (cmd.intent === 'SHOW_UNRESOLVED') {
        const unresolvedMemories = memoryContextService.getUnresolvedMemories();
        const vIds = unresolvedMemories
          .map((m) => m.spatialObjectId)
          .filter((id): id is string => Boolean(id));

        setHighlightedVitrineIds(vIds);
        memoryArchive.setActiveFilter('DECISIONS');

        const proposal = actionProposalService.createProposal(cmd);
        if (proposal) {
          const res = actionProposalService.executeProposal(proposal);
          setLastResult({
            ...res,
            message: `Isolated ${unresolvedMemories.length} memories with pending arbitration or confidence < 85%.`,
          });
          setMemoryEvents(actionProposalService.getMemoryEvents());
          setCommandState('RESULT');
        }
        setCommandInput('');
        return;
      }

      // 4. Trace History
      if (cmd.intent === 'TRACE_HISTORY') {
        const targetId = cmd.targetMemoryId || memoryArchive.selectedMemoryId || 'MEM-0001';
        memoryArchive.selectMemory(targetId);

        // Highlight chronological predecessor, current, successor
        const timeline = memoryArchiveService.getTimelineContext(targetId);
        const chainIds: string[] = [];
        if (timeline?.predecessor?.spatialObjectId) chainIds.push(timeline.predecessor.spatialObjectId);
        const activeVId = memoryArchiveService.getVitrineIdByMemoryId(targetId);
        if (activeVId) chainIds.push(activeVId);
        if (timeline?.successor?.spatialObjectId) chainIds.push(timeline.successor.spatialObjectId);

        setHighlightedVitrineIds(chainIds);

        const proposal = actionProposalService.createProposal(cmd);
        if (proposal) {
          const res = actionProposalService.executeProposal(proposal);
          setLastResult(res);
          setMemoryEvents(actionProposalService.getMemoryEvents());
          setCommandState('RESULT');
        }
        setCommandInput('');
        return;
      }

      // 5. Show Related
      if (cmd.intent === 'SHOW_RELATED') {
        const targetId = cmd.targetMemoryId || memoryArchive.selectedMemoryId || 'MEM-0001';
        memoryArchive.selectMemory(targetId);

        const related = memoryArchiveService.getRelatedMemories(targetId);
        const relatedVIds = related
          .map((r) => r.memory.spatialObjectId)
          .filter((id): id is string => Boolean(id));

        const activeVId = memoryArchiveService.getVitrineIdByMemoryId(targetId);
        if (activeVId) relatedVIds.push(activeVId);

        setHighlightedVitrineIds(relatedVIds);

        const proposal = actionProposalService.createProposal(cmd);
        if (proposal) {
          const res = actionProposalService.executeProposal(proposal);
          setLastResult(res);
          setMemoryEvents(actionProposalService.getMemoryEvents());
          setCommandState('RESULT');
        }
        setCommandInput('');
        return;
      }

      // 6. Find Decisions / Workflows / Artifacts
      if (cmd.intent === 'FIND_DECISIONS') {
        memoryArchive.setActiveFilter('DECISIONS');
        setCommandState('IDLE');
        setCommandInput('');
        return;
      }
      if (cmd.intent === 'SHOW_WORKFLOWS') {
        memoryArchive.setActiveFilter('WORKFLOWS');
        setCommandState('IDLE');
        setCommandInput('');
        return;
      }
      if (cmd.intent === 'SHOW_ARTIFACTS') {
        memoryArchive.setActiveFilter('ARTIFACTS');
        setCommandState('IDLE');
        setCommandInput('');
        return;
      }

      // 7. Open Specific Memory
      if (cmd.intent === 'OPEN_MEMORY' && cmd.targetMemoryId) {
        memoryArchive.selectMemory(cmd.targetMemoryId);
        const vId = memoryArchiveService.getVitrineIdByMemoryId(cmd.targetMemoryId);
        if (vId) setHighlightedVitrineIds([vId]);

        const proposal = actionProposalService.createProposal(cmd);
        if (proposal) {
          const res = actionProposalService.executeProposal(proposal);
          setLastResult(res);
          setMemoryEvents(actionProposalService.getMemoryEvents());
          setCommandState('RESULT');
        }
        setCommandInput('');
        return;
      }

      // 8. Autonomous Goal Orchestration (Stage 08)
      if (cmd.intent === 'ORCHESTRATE_GOAL') {
        const goal = await goalOrchestrator.createAndExecuteGoal(
          input.replace(/^(goal|orchestrate):\s*/i, ''),
          cmd.targetMemoryId
        );
        const isSuccess =
          goal.status === 'COMPLETED' ||
          goal.status === 'EXECUTING' ||
          goal.status === 'AWAITING_APPROVAL';

        setLastResult({
          actionId: goal.goalId,
          success: isSuccess,
          status: goal.status === 'COMPLETED' ? 'EXECUTED' : 'PLANNED',
          message:
            goal.finalSummary ||
            `Goal ${goal.status}: ${goal.objective}`,
          timestamp: goal.updatedAt,
        });
        setMemoryEvents(actionProposalService.getMemoryEvents());
        setCommandState('RESULT');
        setCommandInput('');
        return;
      }

      // 9. Consequential Actions requiring explicit confirmation (Action Proposal Card)
      const proposal = actionProposalService.createProposal(cmd);
      if (proposal) {
        const plan = providerRouter.createExecutionPlan(proposal, cmd.context);
        setActiveProposal(proposal);
        setActiveExecutionPlan(plan);
        setCommandState('PROPOSING_ACTION');
        setCommandInput('');
        return;
      }

      // 9. General Query Search
      if (cmd.intent === 'QUERY_MEMORY') {
        memoryArchive.setSearchQuery(input);
        setCommandState('IDLE');
        setCommandInput('');
        return;
      }

      // 10. Unknown / Unhandled
      setLastResult({
        actionId: 'UNKNOWN',
        success: false,
        status: 'FAILED',
        message: cmd.explanation,
        timestamp: new Date().toISOString(),
      });
      setCommandState('RESULT');
      setCommandInput('');
    },
    [commandInput, memoryArchive]
  );

  // User Confirmation of an Action Proposal
  const confirmProposal = useCallback(() => {
    if (!activeProposal) return;

    setCommandState('CONFIRMING');
    setTimeout(async () => {
      setCommandState('EXECUTING');
      let result: ActionResult;
      if (activeExecutionPlan) {
        const execResult = await providerExecutionAdapter.executePlan(activeExecutionPlan);
        const isSuccess =
          execResult.status === 'SUCCEEDED' ||
          execResult.status === 'FALLBACK_SUCCEEDED' ||
          (execResult.status as string) === 'SUCCESS' ||
          (execResult.status as string) === 'PARTIAL';

        result = {
          actionId: activeProposal.id,
          success: isSuccess,
          status: isSuccess
            ? 'EXECUTED'
            : execResult.status === 'CANCELLED'
            ? 'CANCELLED'
            : execResult.status === 'FAILED' || execResult.status === 'FALLBACK_FAILED'
            ? 'FAILED'
            : 'PLANNED',
          message: isSuccess
            ? `Executed via ${execResult.providerId} (${execResult.modelId}) in ${execResult.latencyMs}ms.${
                execResult.fallbackUsed ? ' (Fallback used)' : ''
              }`
            : execResult.sanitizedError || execResult.error || `Action staged as ${execResult.status} via ${execResult.providerId}.`,
          outputData: execResult.structuredOutput,
          timestamp: execResult.timestamp,
        };
        setLastExecutionResult(execResult);
      } else {
        result = actionProposalService.executeProposal(activeProposal);
      }
      setLastResult(result);
      setMemoryEvents(actionProposalService.getMemoryEvents());
      setActiveProposal(null);
      setActiveExecutionPlan(null);
      setCommandState('RESULT');
    }, 150);
  }, [activeProposal, activeExecutionPlan]);

  // User Cancellation of an Action Proposal
  const cancelProposal = useCallback(() => {
    if (!activeProposal) return;

    setLastResult({
      actionId: activeProposal.id,
      success: false,
      status: 'CANCELLED',
      message: `Action proposal "${activeProposal.title}" was cancelled by operator.`,
      timestamp: new Date().toISOString(),
    });

    setActiveProposal(null);
    setActiveExecutionPlan(null);
    setCommandState('RESULT');
  }, [activeProposal]);

  // Dismiss Result Alert
  const dismissResult = useCallback(() => {
    setLastResult(null);
    setCommandState('IDLE');
  }, []);

  // Clear Highlights
  const clearHighlights = useCallback(() => {
    setHighlightedVitrineIds([]);
  }, []);

  // Toggle Console
  const toggleConsole = useCallback(() => {
    setIsConsoleOpen((prev) => !prev);
  }, []);

  return {
    commandState,
    commandInput,
    commandHistory,
    currentCommand,
    activeProposal,
    activeExecutionPlan,
    lastResult,
    lastExecutionResult,
    highlightedVitrineIds,
    activeCamera,
    memoryEvents,
    isConsoleOpen,

    setCommandInput,
    submitCommand,
    confirmProposal,
    cancelProposal,
    dismissResult,
    clearHighlights,
    setActiveCamera,
    setIsConsoleOpen,
    toggleConsole,
    navigateHistory,
  };
}
