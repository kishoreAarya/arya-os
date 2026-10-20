# AryaOS V1 Stage 16 — Scoped Permission & Authority Model

## 1. Zero-Trust Default-DENY Invariant

Every connector operation, agent dispatch, and mission workflow adheres to the principle of least privilege:
* In the absence of an explicit, unexpired grant or permission, execution is rejected immediately.
* **No Inferred Authority**:
  * Agent rank or trustworthiness does **not** grant capability permissions.
  * AI Provider tier or model benchmark does **not** grant authority.
  * Mission priority or urgency does **not** bypass permission scopes.
  * Historical task success or collective learning signals do **not** confer future authority.

---

## 2. Resource-Scoped Authorization

Permissions and grants are bounded by explicit resource scopes:

| Connector Type | Resource Scope Dimension | Example Scope | Allowed Operations |
|---|---|---|---|
| `FILESYSTEM` | Directory Root / Subpath | `/workspace/src` | `['read_file', 'list_directory']` |
| `GITHUB` | Organization / Repository | `aryaos/*` | `['read_issue', 'create_issue']` |
| `SLACK` | Channel / Thread | `#dev-announcements` | `['send']` |
| `HTTP` | Fully Qualified Domain | `api.github.com` | `['get', 'post']` |

Scope matching supports exact matches, wildcard prefixes (`aryaos/*`), and path hierarchy matching (`/workspace`). Out-of-scope targets are denied unconditionally.

---

## 3. Multi-Tier Authority Evaluation Chain

When an action is dispatched to the Universal Action Bus, the authority evaluation chain proceeds through five gates:

$$\text{AGENT GRANT} \to \text{MISSION GRANT} \to \text{CONNECTOR PERMISSION} \to \text{SCOPE MATCH} \to \text{HUMAN SIGNOFF}$$

1. **Agent Grant**: If `agentId` is present, agent must hold an active, non-expired `AgentCapabilityGrant`.
2. **Mission Grant**: If `missionId` is present, mission must hold an active, non-expired `MissionCapabilityGrant`.
3. **Connector Permission**: Connector must declare an authorized `ConnectorPermission` covering the requested operation.
4. **Scope Verification**: Target resource must fall within granted resource paths.
5. **Human Approval Gate**: If the permission or effective risk tier is `CRITICAL` or `HIGH` with mutating side effects, explicit human operator signoff is required. Autonomous approval spoofing (e.g. `SYSTEM` or `AUTONOMOUS_AGENT`) is denied.

---

## 4. Permission Versioning & Stale Decision Invalidation

* Every connector tracks an integer `permissionVersion`.
* When permissions are added, restricted, or revoked, `permissionVersion` increments.
* Any cached authorization token referencing an older `permissionVersion` is flagged as stale and rejected, requiring reauthorization.
