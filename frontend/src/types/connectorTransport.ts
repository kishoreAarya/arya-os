/**
 * AryaOS V1 — Stage 17: Connector Transport Domain Contracts
 *
 * Defines provider-neutral contracts for external system HTTP/network transport,
 * requests, responses, health checks, and errors.
 *
 * ABSOLUTE INVARIANT:
 * The transport layer MUST NOT perform authorization.
 * Authorization remains strictly Stage 16.
 * Transport receives already-authorized requests and executes them against external endpoints.
 */

import { ConnectorId, ConnectorType } from './connectorFabric';

export interface ConnectorTransportContext {
  connectorId: ConnectorId;
  connectorType: ConnectorType;
  actionId?: string;
  idempotencyKey?: string;
  timeoutMs?: number;
  metadata?: Record<string, unknown>;
}

export interface ConnectorRequest {
  endpoint: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  headers?: Record<string, string>;
  queryParams?: Record<string, string | number | boolean>;
  body?: unknown;
  context: ConnectorTransportContext;
}

export interface ConnectorResponse<T = unknown> {
  statusCode: number;
  headers: Record<string, string>;
  data: T;
  durationMs: number;
  rateLimit?: {
    limit: number;
    remaining: number;
    resetTimestamp?: number;
    retryAfterMs?: number;
  };
}

export type ConnectorTransportErrorCode =
  | 'NETWORK_UNAVAILABLE'
  | 'TIMEOUT'
  | 'RATE_LIMITED'
  | 'AUTH_FAILED'
  | 'AUTH_EXPIRED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'SERVER_ERROR'
  | 'CONFIGURATION_REQUIRED'
  | 'SANITY_CHECK_FAILED';

export interface ConnectorTransportError extends Error {
  code: ConnectorTransportErrorCode;
  statusCode?: number;
  retryAfterMs?: number;
  isRetryable: boolean;
  sanitizedDetails?: Record<string, unknown>;
}

export interface ConnectorTransportHealth {
  status: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  latencyMs?: number;
  lastChecked: string;
  details?: Record<string, unknown>;
}

/**
 * Interface for provider-neutral connector transport mechanisms.
 */
export interface ConnectorTransport {
  execute<T = unknown>(request: ConnectorRequest): Promise<ConnectorResponse<T>>;
  checkHealth(context: ConnectorTransportContext): Promise<ConnectorTransportHealth>;
}
