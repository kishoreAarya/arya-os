# Stage 18: External Event Schema & Normalization Specification

## 1. Event Source Definitions
Stage 18 registers external event schemas within `eventSourceRegistry.ts`. Each event source defines strict schema requirements, required fields, and typed parameters.

### 1.1 GitHub Event Source
- **Connector Type**: `GITHUB`
- **Signature Header**: `x-hub-signature-256`
- **Timestamp Header**: `x-github-delivery-timestamp`
- **Supported Event Types**:
  1. `issue.created`: Requires `repository` (string), `issueNumber` (number), `title` (string).
  2. `issue.updated`: Requires `repository` (string), `issueNumber` (number).
  3. `issue.closed`: Requires `repository` (string), `issueNumber` (number).

### 1.2 Google Drive Event Source
- **Connector Type**: `GOOGLE_DRIVE`
- **Signature Header**: `x-goog-channel-token`
- **Timestamp Header**: `x-goog-message-timestamp`
- **Supported Event Types**:
  1. `file.created`: Requires `fileId` (string), `fileName` (string), `path` (string).
  2. `file.updated`: Requires `fileId` (string).
  3. `file.deleted`: Requires `fileId` (string).

## 2. Normalized External Event Schema
Regardless of external provider representation, all events are transformed by `eventNormalizer.ts` into standard `NormalizedExternalEvent` records:

```typescript
export interface NormalizedExternalEvent {
  normalizedEventId: string; // e.g. norm_github_gh_del_101
  originalEventId: string;   // Provider delivery or event ID
  connectorId: string;       // Stage 16 Connector ID
  resourceType: NormalizedResourceType; // 'ISSUE' | 'FILE' | 'RECORD' | 'WORKFLOW'
  resourceId: string;         // Canonical identifier (e.g. aryaos/core#101)
  changeType: NormalizedChangeType; // 'CREATED' | 'UPDATED' | 'DELETED' | 'SYNCED'
  sourceSystem: ExternalEventSource; // 'GITHUB' | 'GOOGLE_DRIVE'
  timestamp: string;          // ISO 8601 ingress timestamp
  data: Record<string, unknown>; // Sanitized provider data
  provenance: {
    provider: ExternalEventSource;
    connectorId: string;
    providerEventType: string;
    receivedAt: string;
    occurredAt: string;
  };
  epistemicStatus: EpistemicStatus; // Default: 'OBSERVED'
}
```

## 3. Epistemic Separation
Normalized events are initially labeled with `epistemicStatus: 'OBSERVED'`. They cannot transition to `'CONFIRMED'` without explicit reconciliation verification through governed Action Bus read-backs.
