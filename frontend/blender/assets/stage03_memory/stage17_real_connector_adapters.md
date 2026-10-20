# AryaOS V1 — Stage 17: Real Connector Adapters Specification

## 1. Overview

Stage 17 introduces real connector adapters that bridge Stage 15 `CapabilityAdapter` interfaces with Stage 17 `ConnectorTransport` implementations.

Each adapter:
1. Validates input parameters against capability schemas.
2. Resolves ephemeral credentials through `CredentialResolver`.
3. Dispatches HTTP requests through declared transport endpoints.
4. Normalizes external responses and maps errors into standard Action Bus statuses (`SUCCEEDED`, `FAILED`, `RATE_LIMIT`, `TIMEOUT`, `REQUIRES_APPROVAL`).

---

## 2. GitHub Connector Adapter (`GitHubConnectorAdapter`)

### Capabilities Bound
- `github.issue_read` (and alias `github.read_issue`): Read-only issue inspection.
- `github.issue_write` (and alias `github.create_issue`): High-risk issue creation.

### Operations & Validation Rules
- **`get_issue`**:
  - Required parameters: `repository` (format `owner/repo`), `issueNumber` (positive integer).
  - Risk tier: `LOW`.
  - HTTP method: `GET /repos/{owner}/{repo}/issues/{issueNumber}`.
- **`create_issue`**:
  - Required parameters: `repository`, `title`. Optional: `body`, `labels`.
  - Risk tier: `HIGH` (mandates human operator approval).
  - HTTP method: `POST /repos/{owner}/{repo}/issues`.

### Rate Limit & Error Handling
- Normalizes HTTP 429 and `RATE_LIMITED` error codes into `RATE_LIMIT` status.
- Extracts `retry-after` / `x-ratelimit-reset` timestamps into `retryAfterMs`.
- Designates rate-limited requests as retryable under exponential backoff.

---

## 3. Google Drive Connector Adapter (`GoogleDriveConnectorAdapter`)

### Capabilities Bound
- `google_drive.list_files`: Query directory listings within authorized path trees.
- `google_drive.read_file`: Fetch file metadata and read-only content.

### Operations & Validation Rules
- **`list_files`**:
  - Optional parameters: `pageSize`, `query`.
  - Risk tier: `LOW`.
  - Method: `GET /drive/v3/files?pageSize={pageSize}&q={query}`.
- **`read_file`**:
  - Required parameters: `fileId` (alphanumeric string).
  - Risk tier: `LOW`.
  - Method: `GET /drive/v3/files/{fileId}?alt=media`.

### Path Sandboxing & Traversal Defense
- File operations enforce declared scope boundaries: `/drive/root` and `/drive/workspace`.
- Paths attempting traversal (`../`, `/etc/shadow`, root escape) are blocked prior to transport dispatch.

---

## 4. Adapter Factory & Registration Lifecycle

The `ConnectorAdapterFactory` binds both adapters into `adapterRegistry` upon application bootstrap:

```typescript
export class ConnectorAdapterFactory {
  public initializeAdapters(): void {
    adapterRegistry.registerAdapter('github.issue_read', githubConnectorAdapter);
    adapterRegistry.registerAdapter('github.issue_write', githubConnectorAdapter);
    adapterRegistry.registerAdapter('google_drive.list_files', googleDriveConnectorAdapter);
    adapterRegistry.registerAdapter('google_drive.read_file', googleDriveConnectorAdapter);
  }
}
```

This guarantees seamless interoperation between Stage 15 `ActionBusService` and Stage 17 connector implementations without hardcoding integrations into core kernel loops.
