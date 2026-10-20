# AryaOS V1 Stage 16 — Credential Boundary & Identity Architecture

## 1. The Zero Secret Exposure Principle

AryaOS enforces an absolute, non-negotiable architectural invariant:
> **Core AryaOS services must never receive, store, or persist raw secrets (tokens, passwords, private keys, API keys).**

### Mechanisms:
1. **`ConnectorCredentialRef`**: Credentials are represented across all AryaOS subsystems strictly as metadata references:
   * `credentialId`: Unique identifier (e.g. `cred_ref_connector_github_...`)
   * `connectorId`: Bound connector identifier
   * `credentialType`: `'OAUTH2' | 'API_KEY' | 'TOKEN' | 'SERVICE_ACCOUNT' | 'LOCAL_CREDENTIAL' | 'NONE'`
   * `createdAt`: ISO 8601 creation timestamp
   * `expiresAt`: Optional ISO 8601 expiration timestamp
   * `status`: `'VALID' | 'EXPIRED' | 'REVOKED' | 'CONFIGURATION_REQUIRED' | 'UNKNOWN'`
2. **No Plaintext Persistence**: If the runtime environment does not provide a hardware/OS-backed secure vault, credentials are represented as `CONFIGURATION_REQUIRED`. The system rejects the creation of fake software vaults or hardcoded encryption keys.
3. **No Storage in Application State**: Raw secret values are strictly barred from:
   * Missions, Goals, and Plans
   * ActionRequests and ActionResults
   * Spatial Memories and Strategic Knowledge Graph
   * Durable Execution Journals and Envelopes
   * Agent Profiles and Decision Records

---

## 2. Credential Lifecycle & Expiration

```
[Installation] ──► CredentialRef created (status: CONFIGURATION_REQUIRED)
                          │
                          ▼ (OAuth Handshake / Token Binding)
                  status: VALID (with expiresAt)
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
      (Time > expiresAt)          (Operator Revoke)
       status: EXPIRED             status: REVOKED
            │                           │
            ▼                           ▼
  Action Execution BLOCKED      Action Execution DENIED
```

* **Expiration Evaluation**: If `expiresAt` is in the past, `validateCredentialRef()` marks the status as `EXPIRED`.
* **Unknown Expiration**: If expiration cannot be determined, status is `UNKNOWN`. The system never fabricates validity.
* **Offline Deterministic Test Doubles**:
  * `MockConnectorCredentialStore`: In-memory isolated dictionary for integration testing.
  * `MockOAuthProvider`: Simulates OAuth exchange returning valid `CredentialRef` without network access.
