# AryaOS V1 — Stage 17: OAuth Boundary Specification

## 1. Scope & Objective

The Stage 17 OAuth Boundary establishes a standardized, secure RFC 6749 Authorization Code Flow for external service integrations (e.g. GitHub, Google Drive).

It ensures that:
1. Third-party authentication workflows cannot expose credentials to core application memory, state journals, or persistence stores.
2. CSRF attacks against OAuth callback endpoints are completely mitigated via single-use, cryptographically generated state tokens.
3. OAuth parameters, client secrets, and exchange tokens are handled ephemerally and exchanged directly into opaque `ConnectorCredentialRef` objects.

---

## 2. Component Hierarchy

```
+---------------------------------------------------------------------------------+
|                           OAuthProviderRegistry                                 |
| - Registers provider configurations (authorizationEndpoint, tokenEndpoint,      |
|   supported scopes, default grant types) for GitHub and Google Drive.           |
+---------------------------------------------------------------------------------+
                                         │
                                         ▼
+---------------------------------------------------------------------------------+
|                            OAuthSessionService                                  |
| - Generates cryptographically secure CSRF state tokens (TTL: 10 minutes)        |
| - Stores active session nonces in memory.                                       |
| - Consumes state nonces upon callback; state tokens are strictly SINGLE-USE.    |
+---------------------------------------------------------------------------------+
                                         │
                                         ▼
+---------------------------------------------------------------------------------+
|                               OAuthBoundary                                     |
| - generateAuthorizationUrl(connectorId, scopes, redirectUri)                   |
| - handleCallback(code, state, connectorId)                                      |
|   1. Validates & consumes single-use state token.                               |
|   2. Exchanges code for ephemeral credentials via mock/real transport.          |
|   3. Emits opaque ConnectorCredentialRef.                                      |
|   4. Zeroes out all raw token memory.                                           |
+---------------------------------------------------------------------------------+
```

---

## 3. Threat Model & Countermeasures

| Threat Vector | Mitigation Strategy | Verification Rule |
| :--- | :--- | :--- |
| **CSRF Callback Forgery** | `OAuthSessionService.consumeSession(state)` ensures each state parameter is validated and purged immediately upon receipt. | Unrecognized or replayed state tokens immediately throw `Security Boundary Violation: Invalid or expired OAuth state token`. |
| **Raw Token Persistence** | Ephemeral tokens received from token endpoints are stored strictly in-memory (`MockConnectorCredentialStore` / volatile vault). | `credentialBoundary.assertNoRawCredentials` verifies zero `access_token`, `refresh_token`, or `bearer` fields in `CredentialRef` or persistence envelopes. |
| **Code Interception** | Authorization codes have single-use lifecycles and are never recorded in `ExecutionPersistence` or journal logs. | Test suite explicitly verifies that `authorizationCode` is not retained in any persistent record. |
| **Missing Client Configuration** | OAuth initiation without configured `clientId` fails fast. | Throws `CONFIGURATION_REQUIRED` exception before initiating handshake. |

---

## 4. Supported OAuth Providers

### GitHub OAuth Profile
- **Authorization Endpoint**: `https://github.com/login/oauth/authorize`
- **Token Endpoint**: `https://github.com/login/oauth/access_token`
- **Supported Scopes**: `repo`, `read:org`, `user:email`
- **Default Scopes**: `repo:status`, `public_repo`

### Google Drive OAuth Profile
- **Authorization Endpoint**: `https://accounts.google.com/o/oauth2/v2/auth`
- **Token Endpoint**: `https://oauth2.googleapis.com/token`
- **Supported Scopes**: `https://www.googleapis.com/auth/drive.readonly`, `https://www.googleapis.com/auth/drive.metadata.readonly`
- **Default Scopes**: `https://www.googleapis.com/auth/drive.readonly`
- **Access Type**: `offline` (for refresh token handling within secure ephemeral vault)
