# AryaOS V1 — Stage 17: Failure Modes & Recovery Specification

## 1. Overview

External integrations inherently introduce non-deterministic failures (network partitions, rate limiting, token expiration, third-party service outages).

Stage 17 coordinates with Stage 15 `ActionReconciliationService` and Stage 09 `DurableRecovery` to ensure that every failure mode is deterministically classified, sanitized, and reconciled without side-effect duplication or credential compromise.

---

## 2. Failure Mode Taxonomy & Handlers

### A. Rate Limiting (HTTP 429 / RATE_LIMITED)
- **Detection**: Caught from transport response headers (`retry-after`, `x-ratelimit-reset`) or error code `RATE_LIMITED`.
- **Classification**: `category: 'RATE_LIMIT'`, `isRetryable: true`.
- **Behavior**:
  1. Calculates required backoff delay (`retryAfterMs`).
  2. Queues retry if within capability's `retryPolicy.maxRetries`.
  3. Emits rate limit warning to `SpatialCommandConsole` HUD.
  4. Never exhausts system threads with busy-waiting.

### B. Credential Expiration & Auth Revocation (HTTP 401 / 403)
- **Detection**: Transport status 401/403 or `CredentialResolver` detecting timestamp expiry (`expiresAt <= Date.now()`).
- **Classification**: `category: 'AUTHORIZATION'`, `status: 'REQUIRES_APPROVAL'`.
- **Behavior**:
  1. Automatically transitions connector health to `AUTH_REQUIRED`.
  2. Blunts autonomous retry loops (prevents continuous failing requests that could lock accounts).
  3. Generates operator notification in `authentication-status-hud` requesting human operator re-authentication.

### C. Network Offline & Partition (503 / NETWORK_OFFLINE)
- **Detection**: `MockConnectorTransport.isNetworkOnline === false` or `fetch` network exception.
- **Classification**: `category: 'TRANSIENT'`, `status: 'FAILED'`.
- **Behavior**:
  1. Fails closed immediately without mutating local state.
  2. Preserves idempotency key and execution fingerprint for safe replay once connection is restored.
  3. Flags `connector-activation-hud` with network offline status.

### D. Timeouts & Transport Latency
- **Detection**: Execution duration exceeds capability `timeoutMs`.
- **Classification**: `category: 'TIMEOUT'`, `status: 'TIMEOUT'`.
- **Behavior**:
  1. Fires `AbortController.abort()` to terminate pending network sockets.
  2. Evaluates `retryPolicy.retryableCategories.includes('TIMEOUT')`.
  3. Records timeout audit event in journal.

### E. Ambiguous External State (`STATE_UNKNOWN`)
- **Detection**: Write operation times out or network disconnects while payload is in flight.
- **Classification**: `status: 'STATE_UNKNOWN'`.
- **Behavior**:
  1. Blocks subsequent attempts to execute identical operations.
  2. Passes request to `actionReconciliationService.reconcile()`.
  3. Performs read-before-write idempotency queries to determine if the external entity was actually created or modified before allowing duplicate dispatch.

---

## 3. Application Restart & Persistence Recovery

Upon browser reload or system restart:
1. `ExecutionPersistence` restores saved connectors and `ConnectorCredentialRef`s.
2. `CredentialBoundary.validateCredentialRef()` re-evaluates all credential expiration timestamps against current system time.
3. Any expired credential immediately moves connector health to `AUTH_REQUIRED`.
4. In-memory secret stores start completely empty; no cached secrets are loaded from LocalStorage, enforcing a clean security boundary.
