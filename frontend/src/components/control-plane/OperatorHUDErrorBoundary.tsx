/**
 * AryaOS V1 — Stage 24: Control Plane Operator HUD
 * Phase 9.1: React Error Boundary & Panel Fault Isolation
 *
 * Strict Architectural Invariants:
 * 1. PURE DOM: Zero WebGL/Canvas/Three.js interaction.
 * 2. OBSERVATIONAL ONLY: No mutation, execution, dispatch, or consequential state alterations.
 * 3. LOCALIZED FAULT CONTAINMENT:
 *    - An unhandled runtime error in one panel MUST NOT crash sibling panels,
 *      the Operator HUD, or the enclosing SpatialCommandConsole.
 * 4. EPISTEMIC & SECRET INTEGRITY:
 *    - Stack traces are strictly suppressed.
 *    - Error messages are recursively scrubbed using scrubSecrets to ensure
 *      no sensitive credentials, tokens, or internal keys leak into the operator DOM.
 * 5. CONTROLLED MANUAL RECOVERY:
 *    - Zero automated retry loops that could trigger cascading render storms.
 *    - Manual retry button allows deterministic reset of the boundary state.
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { scrubSecrets } from './EpistemicIndicators';

export interface OperatorHUDErrorBoundaryProps {
  children: ReactNode;
  /** Human-readable panel title for localized error context */
  panelTitle?: string;
  /** Custom fallback component if preferred over default banner */
  fallback?: ReactNode;
  /** Optional error reporting callback (strictly for diagnostics) */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
  /** Optional callback when operator manually triggers reset/retry */
  onReset?: () => void;
  /** Custom wrapper CSS class */
  className?: string;
}

export interface OperatorHUDErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

export class OperatorHUDErrorBoundary extends Component<
  OperatorHUDErrorBoundaryProps,
  OperatorHUDErrorBoundaryState
> {
  constructor(props: OperatorHUDErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      errorMessage: '',
    };
  }

  static getDerivedStateFromError(error: unknown): OperatorHUDErrorBoundaryState {
    const raw = error instanceof Error ? error.message : String(error);
    const scrubbed = scrubSecrets(raw);
    return {
      hasError: true,
      errorMessage: scrubbed || 'AN UNEXPECTED PANEL RENDERING FAULT OCCURRED',
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: '' });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const title = this.props.panelTitle || 'PANEL COMPONENT';

      return (
        <div
          data-testid="panel-error-fallback"
          role="alert"
          aria-live="assertive"
          className={`p-4 rounded border border-rose-800/80 bg-rose-950/40 text-rose-300 font-mono text-xs flex flex-col gap-2 ${this.props.className || ''}`}
        >
          {/* Header row */}
          <div className="flex items-center justify-between flex-wrap gap-2 pb-1.5 border-b border-rose-900/60">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-rose-500 shadow-sm shadow-rose-500/50" />
              <span data-testid="panel-error-title" className="font-bold tracking-wider text-rose-200">
                {title.toUpperCase()} // RENDERING ISOLATION FAULT
              </span>
            </div>
            <span
              data-testid="panel-error-badge"
              className="text-[0.625rem] px-1.5 py-0.5 rounded bg-rose-900/60 text-rose-300 border border-rose-700/60 font-semibold"
            >
              FAULT CONTAINED
            </span>
          </div>

          {/* Sanitized error message (no stack trace, secrets scrubbed) */}
          <p data-testid="panel-error-message" className="text-[0.6875rem] text-rose-200/90 leading-relaxed">
            {this.state.errorMessage}
          </p>

          {/* Operator recovery footer */}
          <div className="flex items-center justify-between pt-1 flex-wrap gap-2 text-[0.625rem] text-rose-400/80">
            <span>* Unaffected sibling panels and Command Deck remain fully operational.</span>
            <button
              type="button"
              data-testid="panel-error-retry-btn"
              onClick={this.handleReset}
              className="px-2.5 py-1 font-bold rounded bg-rose-900/40 hover:bg-rose-900/70 border border-rose-700 text-rose-100 transition-colors cursor-pointer"
              title="Attempt to re-render this panel"
            >
              RETRY PANEL
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
