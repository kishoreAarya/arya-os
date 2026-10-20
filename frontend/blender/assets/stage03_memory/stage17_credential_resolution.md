# AryaOS V1 — Stage 17: Ephemeral Credential Resolution Protocol

## 1. Design Principles

In accordance with the AryaOS Security Model:
1. **Zero Secret Persistence**: Core storage (LocalStorage, SQLite, IndexedDB, ExecutionPersistence) NEVER stores plaintext API keys, passwords, bearer tokens, or client secrets.
2. **Handle-Based Indirection**: Core components identify credentials solely via opaque `ConnectorCredentialRef` handles.
3. **Just-In-Time Ephemeral Materialization**: When an authorized external request requires execution, secrets are resolved in volatile RAM, injected directly into transport headers, and immediately dereferenced.
4. **Leak-Proof Error Scrubbing**: Errors occurring during transport execution are scrubbed to eliminate all traces of authentication tokens before propagation.

---

## 2. Credential Reference Structure

The `ConnectorCredentialRef` object contains zero sensitive fields:

```typescript
export interface ConnectorCredentialRef {
  credentialId: string;           // Opaque reference ID (e.g., 'cred_ref_gh_10283')
  connectorId: ConnectorId;       // Associated connector identifier
  credentialType: CredentialType; // 'OAUTH2' | 'API_KEY' | 'TOKEN' | 'LOCAL_CREDENTIAL' | 'NONE'
  createdAt: string;              // ISO 8601 timestamp
  expiresAt?: string;             // Optional expiration timestamp
  status: CredentialStatus;       // 'VALID' | 'EXPIRED' | 'REVOKED' | 'CONFIGURATION_REQUIRED'
  metadata?: Record<string, unknown>; // Non-sensitive metadata (e.g. scopes, tokenType, accountId)
}
```

---

## 3. Ephemeral Resolution Lifecycle

```
Action Request
      │
      ▼
ActionBusService (checks authorization & grants)
      │
      ▼
CapabilityAdapter.execute(request)
      │
      ▼
CredentialResolver.resolve(credentialRef)
      │
      ├─► Validate Status: checks if REVOKED, EXPIRED, or CONFIGURATION_REQUIRED
      ├─► Retrieve Secret: reads from in-memory MockConnectorCredentialStore / secure vault
      └─► Return EphemeralCredential: { headers: { 'Authorization': 'Bearer ...' }, expiresAt }
      │
      ▼
ConnectorTransport.execute(requestWithHeaders)
      │
      ├─► Successful response received
      │      OR
      └─► Error caught -> CredentialResolver.sanitizeError(err)
      │
      ▼
FINALLY BLOCK:
      ephemeralCred = { headers: {} }; // Clear volatile reference
```

---

## 4. Error Sanitization & Masking Engine

When third-party API transports fail (e.g. 401 Unauthorized, 403 Forbidden, 429 Rate Limit, or network failures), upstream exception messages often reflect request headers.

The `CredentialResolver.sanitizeError` engine scrubs:
- `Bearer [a-zA-Z0-9\-._~+/]+=*`
- `ghp_[a-zA-Z0-9_]{15,}`
- `sk-[a-zA-Z0-9_-]{15,}`
- `password[:=]\s*[^,\s]+`
- Basic authentication Base64 payloads

All matching substrings are replaced with `[REDACTED_SECRET]`, ensuring that audit trails, execution envelopes, HUD overlays, and console logs remain completely clean.
