# AryaOS V1 Stage 15 — Security Boundary & Secret Sanitization

## 1. Zero Secret Leakage Invariant

AryaOS enforces a strict invariant across all persistence, logging, telemetry, and audit mechanisms:
> **No raw secrets, credentials, tokens, passwords, or Authorization headers may ever be committed to persistent storage or exposed in UI telemetry.**

### Implemented Protections:
* **Deep Recursive Sanitization**: `executionPersistence.sanitizeForPersistence()` crawls all payload objects, arrays, and primitives.
* **Sensitive Key Redaction**: Keys matching `apikey`, `api_key`, `token`, `secret`, `password`, `bearer`, `credential`, `privatekey`, `authorization` are replaced with `[REDACTED_SECRET]`.
* **Token Pattern Masking**: `sanitizeString()` scans text payloads with regular expressions to scrub `Bearer <token>`, `sk-<key>`, `ghp_<token>`, and `key-<key>` patterns.
* **State Field Protection**: Explicitly preserves non-sensitive enum states (e.g. `authorizationState: 'AUTHORIZED'`) to ensure telemetry fidelity without leaking credentials.

---

## 2. Sandboxing Enforcement Matrix

| Sandbox Dimension | Rule | Enforcement Mechanism |
|---|---|---|
| **Filesystem Paths** | Must be within `/workspace`, `/data`, `/tmp/sandbox` | Prefix matching in `actionAuthorizationService.checkSandbox()` |
| **Directory Traversal** | Reject any path containing `../` or `..\` | String pattern check; rejects immediately with code `ERR_PERMISSION` |
| **HTTP Egress** | Must match declared domains (`api.github.com`, `api.aryaos.local`) | Domain parse and allowlist lookup |
| **GitHub Repositories** | Must match authorized repo list (`owner/repo`) | Strict string equality against `allowedRepositories` |
| **Payload Ceiling** | Must not exceed `maxPayloadBytes` (10MB default) | Serialized length check before adapter dispatch |

---

## 3. Sandboxed Mock Adapter Isolation

To guarantee offline determinism and zero network leak risks:
* Reference mock adapters (`MockFileAdapter`, `MockWebAdapter`, `MockGitHubAdapter`, `MockNotificationAdapter`) maintain internal in-memory data structures.
* Tests execute without real GitHub tokens, real filesystem mutation, or outbound internet access.
* Zero live external API calls are made during CI or unit tests.
