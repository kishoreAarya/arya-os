/**
 * AryaOS V1 — Stage 15: Action Reconciliation Service
 *
 * Reconciles uncertain external state before retrying or declaring failure.
 * When external actions encounter timeouts or network disconnects, checks
 * whether the side-effect already succeeded before executing duplicate actions.
 */

import {
  ActionRequest,
  ActionResult,
  ActionExecutionStatus,
} from '../types/actionBus';
import { adapterRegistry, MockGitHubAdapter, MockFileAdapter } from './capabilityAdapter';
import { actionResultNormalizer } from './actionResultNormalizer';
import { executionPersistence } from './executionPersistence';

export interface ReconciliationResult {
  reconciled: boolean;
  status: ActionExecutionStatus;
  reconciledResult?: ActionResult;
  note: string;
}

export class ActionReconciliationService {
  /**
   * Reconciles uncertain external state for an interrupted or timed-out request.
   */
  public async reconcile(request: ActionRequest): Promise<ReconciliationResult> {
    const adapter = adapterRegistry.getAdapter(request.capabilityId);

    // 1. Check if result is already recorded in persistence
    const existing = executionPersistence.getActionResult(request.actionId);
    if (existing && existing.success) {
      return {
        reconciled: true,
        status: 'SUCCEEDED',
        reconciledResult: existing,
        note: 'Action execution already verified in persistence.',
      };
    }

    // 2. GitHub Issue Reconciliation
    if (request.capabilityId === 'github.create_issue' && adapter instanceof MockGitHubAdapter) {
      const repo = request.parameters.repository as string;
      const title = request.parameters.title as string;
      if (repo && title) {
        const existingIssue = adapter.getIssueDirect(repo, title);
        if (existingIssue) {
          const reconciledResult: ActionResult = actionResultNormalizer.normalizeSuccess(
            request,
            {
              repository: repo,
              issueNumber: existingIssue.number,
              title: existingIssue.title,
              reconciled: true,
              url: `https://github.com/${repo}/issues/${existingIssue.number}`,
            },
            0
          );
          executionPersistence.saveActionResult(reconciledResult);
          return {
            reconciled: true,
            status: 'SUCCEEDED',
            reconciledResult,
            note: `Reconciled with existing GitHub issue #${existingIssue.number} in ${repo}; prevented duplicate side effect.`,
          };
        }
      }
    }

    // 3. Filesystem Write Reconciliation
    if (request.capabilityId === 'filesystem.write' && adapter instanceof MockFileAdapter) {
      const path = request.parameters.path as string;
      const expectedContent = request.parameters.content as string;
      if (path) {
        try {
          const fileCheck = await adapter.execute({
            ...request,
            operation: 'read_file',
            parameters: { path },
          }) as { content?: string };

          if (fileCheck && fileCheck.content === expectedContent) {
            const reconciledResult = actionResultNormalizer.normalizeSuccess(
              request,
              { path, bytesWritten: expectedContent.length, reconciled: true },
              0
            );
            executionPersistence.saveActionResult(reconciledResult);
            return {
              reconciled: true,
              status: 'SUCCEEDED',
              reconciledResult,
              note: `Reconciled filesystem state: Target file '${path}' already written with matching content.`,
            };
          }
        } catch {
          // File does not exist, not yet executed
        }
      }
    }

    // 4. If query unsupported or state cannot be verified:
    return {
      reconciled: false,
      status: 'STATE_UNKNOWN',
      note: 'External state cannot be definitively verified. Action marked STATE_UNKNOWN to prevent duplicate side effects.',
    };
  }
}

export const actionReconciliationService = new ActionReconciliationService();
