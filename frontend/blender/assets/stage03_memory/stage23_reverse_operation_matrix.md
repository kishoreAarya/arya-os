# ARYAOS V1 — STAGE 23: REVERSE OPERATION MATRIX
## DECLARATIVE REVERSE MAPPINGS, PARAMETER CONSTRAINTS & REVERSIBILITY TIERS

**STATUS:** FROZEN & RATIFIED ARCHITECTURAL CONTRACT  
**BOUNDARY:** STAGE 23 RECOVERY CONTROL PLANE  

---

### 1. Architectural Principles

Stage 23 enforces **Declarative Reverse Operations**.
- **No Speculative Guessing**: Stage 23 NEVER attempts to dynamically synthesize an inverse action from capability names (e.g. converting `do_x` into `undo_x`).
- **No Generic Inverse Functions**: Arbitrary inverse callbacks, `eval()`, dynamic code generation, and shell scripts are strictly prohibited.
- **Bounded Contract Registration**: Only capabilities with explicitly registered, verified, and testable compensating semantics may participate in automated compensation.

---

### 2. Supported Declarative Reverse Mappings

| Source Capability | Compensating Capability | Compensation Type | Reversibility Tier | Target State | Required Target Params | Risk Level | Human Approval Required? | Post-Compensation Probe |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `filesystem.write` | `filesystem.delete` | `RESOURCE_CLEANUP` | `FULLY_REVERSIBLE` | `FILE_REMOVED` | `path` (or `filePath`) | `HIGH` | **YES** (Stage 21 Human Gate) | `filesystem.stat` (expect 404 / not found) |
| `filesystem.create_directory` | `filesystem.delete_directory` | `RESOURCE_CLEANUP` | `FULLY_REVERSIBLE` | `DIRECTORY_REMOVED` | `path` (or `dirPath`) | `HIGH` | **YES** (Stage 21 Human Gate) | `filesystem.stat` (expect 404 / not found) |
| `github.create_issue` | `github.close_issue` | `STATE_CORRECTION` | `COMPENSATABLE` | `ISSUE_CLOSED` | `repository`, `issueNumber` | `MEDIUM` | **NO** (Automated Governance) | `github.get_issue` (state == 'closed') |
| `github.create_comment` | `github.delete_comment` | `RESOURCE_CLEANUP` | `FULLY_REVERSIBLE` | `COMMENT_DELETED` | `repository`, `commentId` | `MEDIUM` | **NO** (Automated Governance) | `github.get_comment` (expect 404 / not found) |

---

### 3. Irreversible Capabilities (No Automatic Inverse)

Certain real-world capabilities cause irreversible side effects once dispatched. Stage 23 deterministically assigns them `COMPENSATION_UNAVAILABLE` with `reversibilityClass: 'IRREVERSIBLE'`:

| Irreversible Capability | Domain | Reason Why Inverse is Impossible | Recovery Policy |
| :--- | :--- | :--- | :--- |
| `notification.send` | Notifications / Slack | Once an external user receives an alert, communication cannot be un-received. | `COMPENSATION_UNAVAILABLE` |
| `notification.broadcast` | Webhooks / Pager | Broad external alert cannot be retracted across arbitrary subscribers. | `COMPENSATION_UNAVAILABLE` |
| `email.send` | SMTP / Sendgrid | Delivered email messages cannot be recalled reliably from external mail exchangers. | `COMPENSATION_UNAVAILABLE` |
| `webhook.trigger` | External Webhook | Downstream third-party consumers immediately ingest payload; side effect escapes OS boundary. | `COMPENSATION_UNAVAILABLE` |
| `external_http.post` | Arbitrary HTTP POST | Arbitrary endpoints have undefined side effect semantics without an explicit contract. | `COMPENSATION_UNAVAILABLE` |

---

### 4. Read-Only Capabilities (Zero Side Effect)

Read-only inquiries create no persistent side effects in the external environment. Stage 23 deterministically assigns them `COMPENSATION_NOT_REQUIRED`:

| Read-Only Capability | Domain | Justification |
| :--- | :--- | :--- |
| `web.search` | Search Engine | Information retrieval query; zero persistent state modifications. |
| `filesystem.read` | Filesystem | File read-only operation; file content remains unaltered. |
| `filesystem.stat` | Filesystem | Metadata inquiry; zero mutation. |
| `github.read` | GitHub API | Repository inspection; zero mutation. |
| `github.get_issue` | GitHub API | Issue metadata read; zero mutation. |
| `external_http.get` | HTTP Gateway | Safe HTTP GET inquiry; adheres to RFC 7231 read-only semantics. |
| `database.read` | Database Fabric | Query / SELECT statement; zero row modification. |

---

### 5. Parameter Constraints & Mapping Rules

When formulating a `DeclarativeCompensationPlan`, parameters are derived strictly through deterministic extraction:

1. **Parameter Inheritance**:
   - `filesystem.write` $\rightarrow$ `filesystem.delete`: The file path is extracted strictly from `params.path` or `params.filePath`.
   - If path is missing or empty, Stage 23 halts with `COMPENSATION_UNSAFE`.
2. **Sanitization Against Injection**:
   - Parameters are scrubbed using `validateAndSanitizePayload()`.
   - URL-like injection attempts (e.g. `path: "https://evil.com/delete"`) are rejected immediately with `RecoveryContractViolationError`.
   - Secret keys (`api_key`, `token`, `password`, `bearer`) are stripped and rejected.
3. **Idempotency Key Derivation**:
   - `idempotencyKey = "comp-idem-" + originalOperationId + "-" + compensatingCapability + "-" + timestamp`
   - Guarantees the compensation key is unique, deterministic, and never collides with the original mutation.
