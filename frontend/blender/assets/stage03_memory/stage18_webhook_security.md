# Stage 18: Webhook Security, Authentication & Secret Hygiene

## 1. Threat Model & Invariant Controls
Inbound event processing exposes an application to unauthenticated data streams, forged webhooks, replay attacks, parameter poisoning, and secret leakage. Stage 18 implements defensive layers at every pipeline transition.

| Threat | Architectural Defense | Verification Result |
| :--- | :--- | :--- |
| **Forged Webhook / Spoofing** | Cryptographic HMAC-SHA256 signature verification via `webhookAuthenticationService` | Verified; rejected invalid/tampered signatures |
| **Replay Attacks** | Bounded (15-min) sliding window cache indexing deterministic event fingerprints | Verified; identical deliveries rejected as `DUPLICATE_EVENT` |
| **Timestamp Manipulation / Stale Replay** | Strict 5-minute maximum timestamp drift enforcement (`EXPIRED_TIMESTAMP`) | Verified; rejected events with drift > 300,000ms |
| **Revoked / Disabled Connector Ingress** | Connector status gatekeeper checking Stage 16 Connector Fabric status | Verified; events from `REVOKED` or `DISABLED` connectors rejected |
| **Secret Exfiltration / Accidental Logging** | Recursive payload scrubbing stripping Bearer tokens, passwords, and API keys | Verified; zero plaintext secrets in journal or localStorage |
| **Event Flood / DoS** | Concurrency token throttling and rate limiting window guards | Verified; excessive deliveries return `RATE_LIMITED` |
| **Consequential Action Triggering** | Default DENY for autonomous writes without operator approval | Verified; blocked unauthorized write execution |
| **Permission Elevation via Event** | Strict isolation between inbound event schema and permission services | Verified; zero mutations to `AgentCapabilityGrant` or connector scopes |

## 2. Cryptographic Authentication Protocol
- **GitHub**: Header `x-hub-signature-256` verified against configured connector webhook secret using HMAC-SHA256.
- **Google Drive**: Header `x-goog-channel-token` verified against connector authorization channel token.
- **Timestamp Verification**: Header `x-github-delivery-timestamp` or `x-goog-message-timestamp` compared against `Date.now()`. Rejection triggered if `|now - ts| > 300,000ms`.

## 3. Secret Sanitization Implementation
`eventSanitizer.ts` performs deep traversal of incoming event JSON structures:
- Keys matching `/password|token|secret|authorization|credential|api_key/i` have their values replaced with `[REDACTED_SECRET]`.
- String fields containing `Bearer [a-zA-Z0-9_\-\.]+` or `ghp_[a-zA-Z0-9]+` are masked.
- Journal records and local storage persistence envelopes pass through `executionPersistence.sanitizeForPersistence()`, preventing raw credentials from being saved to disk or state journals.
