# Hermes-Agent Integration Specification (AryaOS V2)

Status: DRAFT SPECIFICATION — NOT IMPLEMENTED
Owner: AryaOS V2
Scope: Design/specification only. No production code or dependency change
is established by this document. The source-provisioning decision recorded
in §14.1 is established by this document.

Provenance of findings:
- The Hermes behavioral facts in this document were supplied by the operator
  from prior source-level and isolated runtime verification sessions performed
  against the pinned Hermes commit below. Those verification reports are NOT
  committed to this repository. Every such fact is tagged [VERIFIED-SUPPLIED].
- Facts about AryaOS interfaces are tagged [EXISTS] (inspected in this
  repository) or [NEEDS IMPLEMENTATION] (no such interface exists yet; must be
  built and reviewed before use).
- Anything neither verified nor existing is tagged [TO VERIFY AT IMPLEMENTATION].
  Per AGENTS.md §7, no configuration name may be assumed to exist until checked
  against the pinned Hermes source.

---

## 1. Purpose and Responsibility Boundary

AryaOS is the system of record and the authority. Hermes-Agent is a
reasoning/execution runtime embedded by AryaOS for a single, bounded purpose:
running LLM reasoning loops over AryaOS-authorized, typed operations.

AryaOS owns (unchanged by this integration):
- project/job state and workflow runs;
- policy and approval;
- authorization;
- memory (authoritative);
- agent registry and persona registry;
- asset/artifact registry and lineage;
- provider routing (capability-based, `backend/app/providers/router.py` [EXISTS]);
- schedule definitions;
- domain/business rules and decisions (retry/revise/stop/human review).

Hermes is NOT:
- the system of record;
- the memory authority;
- the scheduler;
- the agent registry;
- an unrestricted tool gateway.

Hermes may:
- receive a bounded task and bounded context from AryaOS;
- reason over explicitly granted typed capabilities (§9);
- return results and tool-request outcomes to AryaOS.

Hermes may NOT:
- hold authoritative state;
- initiate work not requested by AryaOS;
- bypass the AryaOS policy gate;
- spawn subagents (§7);
- schedule future work (§8).

OpenMontage remains a separate media-production system. Hermes never talks to
OpenMontage. AryaOS creates the Job Package; assets cross the boundary only
through the Asset/Artifact Registry. No Hermes capability may reference
OpenMontage internals.

## 2. Hermes Version / Commit Pin

- Pinned Hermes commit: `c0d7294769a38c17ceae51d8f7995e66e1dcae27`
  [VERIFIED-SUPPLIED: this is the commit against which source-level and
  isolated runtime verification was performed].
- The pin is absolute. No floating branch, tag, or `latest`. See §15 for the
  upgrade policy.
- Implementation must record the commit hash in the AryaOS configuration
  surface (exact setting name: [NEEDS IMPLEMENTATION]) and assert at startup
  that the loaded Hermes source matches the pin. Mismatch = refuse to start
  (fail closed, §11).

## 3. Embedding Model

Hermes is embedded directly in-process as the AIAgent class
[VERIFIED-SUPPLIED: direct `AIAgent` embedding was the verified integration
path]. Explicitly excluded:

- Hermes Gateway: must never run inside or alongside AryaOS. No gateway
  process, no gateway ports, no gateway configuration [VERIFIED-SUPPLIED].
- Hermes CLI runtime: not used. AryaOS does not shell out to Hermes
  [VERIFIED-SUPPLIED].
- Hermes cron scheduler: not started, not configured (§8)
  [VERIFIED-SUPPLIED].
- No second scheduler of any kind inside Hermes.

The embedding surface is a single AryaOS-owned runtime module
[NEEDS IMPLEMENTATION] that:
1. prepares the environment (§5, env scrub);
2. verifies startup invariants (§4, plugin check);
3. constructs `AIAgent` with an explicit, allowlisted configuration;
4. drives the agent loop under AryaOS resource limits (§12);
5. tears down and discards all Hermes state at job end (§6).

## 4. Security Boundary

4.1 Toolsets are not authorization.
`enabled_toolsets` / `disabled_toolsets` control which tools are exposed to
the model; they are a reduction of attack surface, NOT an authorization
mechanism [VERIFIED-SUPPLIED]. Authorization happens exclusively in AryaOS.

4.2 The authorization boundary is the AryaOS `pre_tool_call` policy gate.
Every tool request issued by Hermes — regardless of tool name, call path
(`invoke_tool`, inline executor, or any other path) — must pass through the
AryaOS policy plugin before execution [VERIFIED-SUPPLIED: Hermes supports a
plugin hook point that AryaOS verification confirmed can intercept tool calls
at commit c0d7294]. The policy gate is implemented as an AryaOS-owned Hermes
plugin [NEEDS IMPLEMENTATION] that:
- receives the full tool request (tool name + parameters) and the AryaOS
  authorization context (§10);
- evaluates the request against AryaOS policy for the requested capability;
- returns ALLOW only for explicitly authorized typed capabilities (§9);
- returns BLOCK for everything else, including unknown tools, malformed
  requests, and any path not in the typed capability set.

4.3 Fail closed on plugin absence.
At startup, before any agent construction, AryaOS must explicitly verify that
the AryaOS policy plugin is loaded and registered in the Hermes plugin
registry [VERIFIED-SUPPLIED: plugin registration is observable at runtime;
verification confirmed the load state can be checked]. If the policy plugin is
not loaded — for any reason (plugin dir misconfigured, load error, silent
skip) — AryaOS must refuse to start the agent and fail the job. There is no
configuration under which Hermes runs inside AryaOS without the policy gate.
This is a hard invariant, enforced by an explicit post-load assertion, not by
convention.

4.4 Fail closed on policy evaluation.
Any exception, timeout, or indeterminate result inside the policy gate is
treated as BLOCK (§11). The policy gate never fails open.

4.5 No god tool.
The typed capability set (§9) is the complete universe of things Hermes can
do. There is no generic `aryaos_api_call`/`run_anything` capability, and the
policy gate must structurally reject any tool whose name is not in the typed
registry.

## 5. Hermes Configuration

All configuration is explicit and reviewed at startup. Defaults are never
trusted.

5.1 Toolsets.
- `enabled_toolsets` must always be an explicit, non-empty allowlist — never
  `None` [VERIFIED-SUPPLIED: `enabled_toolsets=None` exposes the full tool
  surface; verification confirmed `None` means unrestricted]. `None` is
  rejected by AryaOS startup validation.
- Dangerous toolsets are excluded: shell/terminal, arbitrary file write,
  browser, code execution/IDE, delegation/subagents, MCP, cron/scheduler,
  messaging/communication. The exact Hermes toolset names for the allowlist
  must be enumerated from the pinned source at implementation time
  [TO VERIFY AT IMPLEMENTATION]; the enumerated list becomes a frozen constant
  in the AryaOS runtime module and any change to it follows §15.
- The allowlist approach is mandatory: adding a toolset requires editing the
  frozen allowlist, not removing entries from a denylist.

5.2 Filesystem isolation.
- Dedicated `HERMES_HOME` [VERIFIED-SUPPLIED: Hermes honors a dedicated home
  directory]. `HERMES_HOME` is rooted under the AryaOS data directory —
  development `<AryaOS data root>/hermes`, production
  `<deployment data root>/hermes`. The exact deployment mount is
  environment/deployment configuration, not hard-coded into application
  code.
- Hermes uses per-job isolation: each job runs in
  `<HERMES_HOME>/jobs/<job_id>/`.
- "Never the AryaOS repo" is clarified: the sanctioned gitignored AryaOS
  data directory is explicitly allowed for Hermes runtime state;
  source-controlled/configuration areas are not.
- "Never the user home" means: `HERMES_HOME` and every descendant of the
  user's home directory are forbidden.
- Isolated `config.yaml` written by AryaOS into `HERMES_HOME`
  [VERIFIED-SUPPLIED: Hermes reads its configuration from `config.yaml` under
  its home]. AryaOS generates this file at runtime; it is never hand-edited
  and never committed.
- `security.tirith_fail_open=false` [VERIFIED-SUPPLIED: Hermes has a
  `security.tirith_fail_open` setting; the verified safe value is `false`].
  AryaOS asserts this value in the generated config and treats any other
  value as a startup failure.

5.3 No MCP servers, no project plugins.
- MCP server configuration: none. Zero MCP entries in the generated config.
- Project-level plugins: none. The only plugin is the AryaOS policy plugin,
  loaded from an AryaOS-controlled plugin path [NEEDS IMPLEMENTATION].

5.4 Approvals remain manual.
Hermes-side auto-approval of dangerous actions is not used. Approvals that
matter are AryaOS Approval records [EXISTS: `backend/app/models/approval.py`],
and the policy gate checks approval state (§10) before ALLOW on
approval-gated capabilities.

5.5 Environment scrubbing before import.
Before `import` of any Hermes module, the embedding module must scrub the
process environment of inherited variables that could alter Hermes behavior
or escape isolation — e.g. variables pointing Hermes at a different home,
enabling gateway/CLI/cron behavior, or pre-configuring tools/MCP. The exact
variable names must be enumerated from the pinned source at implementation
time [TO VERIFY AT IMPLEMENTATION] and scrubbed by removal (not override) in
a single, testable pre-import step. If scrubbing cannot be performed, the
runtime refuses to import Hermes.

## 6. Memory and State

- Hermes memory: disabled [VERIFIED-SUPPLIED].
- `session_search`: disabled [VERIFIED-SUPPLIED].
- Agent construction flags — verified to exist and to have the stated effect
  at the pinned commit [VERIFIED-SUPPLIED]:
  - `skip_memory=True`
  - `skip_context_files=True`
  - `skip_background_review=True`
- AryaOS owns authoritative memory. Hermes receives only the bounded context
  AryaOS supplies in the task; it has no independent recall path.
  `memory.retrieve` (§9) is the only memory access, and it reads from AryaOS.
- All Hermes state (session files, caches, scratch) must remain inside the
  dedicated per-job `HERMES_HOME` directory (§5.2). The default retention
  policy is deletion at successful job completion; failure/cleanup semantics
  are to be defined by the runtime implementation, and no archive/retention
  subsystem is introduced yet. No Hermes state may leak into AryaOS
  directories or survive into another job unless AryaOS explicitly promotes
  selected state into AryaOS-owned authoritative state.

## 7. Delegation

- The delegation toolset is excluded from `enabled_toolsets` (§5.1).
- `delegate_task` is explicitly BLOCKed by name in the AryaOS policy gate,
  independent of toolset configuration.
- Rationale, from verification [VERIFIED-SUPPLIED]:
  - `max_spawn_depth=0` does NOT reliably disable delegation; it must not be
    treated as a control.
  - No `disable_delegate` flag exists in Hermes at the pinned commit.
- Therefore delegation is prevented by (a) toolset exclusion, (b) policy
  BLOCK on the tool name, and (c) the acceptance test T7 (§16). Hermes runs
  exactly one reasoning loop for exactly one AryaOS job. No subagents, ever.

## 8. Scheduling

- Hermes cron is excluded: not configured, not started, and excluded from
  toolsets (§5.1) [VERIFIED-SUPPLIED].
- The Hermes gateway must never run inside AryaOS (§3). No process, thread,
  or port associated with the gateway is permitted.
- AryaOS owns schedule definitions. The existing AryaOS scheduler is
  APScheduler for internal maintenance only [EXISTS:
  `backend/app/workers/scheduler.py`]; it is not affected by this
  integration.
- n8n, if used later, remains deterministic execution infrastructure
  triggered by AryaOS-owned schedule definitions. It does not become a
  second scheduler authority and does not invoke Hermes directly; any n8n →
  Hermes path goes through an AryaOS API that enforces §4.

## 9. Typed AryaOS Capabilities

Hermes acts only through typed, capability-scoped operations exposed as
tools. Each maps to exactly one AryaOS operation surface. Initial capability
set (names are the tool names Hermes sees):

| Capability           | Semantics                                                        | AryaOS surface                              | Status                  |
|----------------------|------------------------------------------------------------------|---------------------------------------------|-------------------------|
| `research.search`    | Search trends/research sources within an authorized project       | Research service [EXISTS: trend_sources]     | Binding [NEEDS IMPL.]   |
| `research.get`       | Fetch one research item by ID                                     | Research models/service                     | Binding [NEEDS IMPL.]   |
| `story.create`       | Create/revise story/script drafts as proposals                    | Script agent + content models [EXISTS]      | Binding [NEEDS IMPL.]   |
| `memory.retrieve`    | Read-only retrieval from AryaOS authoritative memory               | Memory service                              | Service [NEEDS IMPL.]   |
| `provider.generate`  | Request generation through the capability-based provider router    | `backend/app/providers/router.py` [EXISTS]  | Binding [NEEDS IMPL.]   |
| `asset.get`          | Read asset metadata/reference by ID from the Asset Registry        | Asset/artifact registry                     | Registry [NEEDS IMPL.]  |
| `agent.request`      | Request work from an already-registered, policy-authorized AryaOS agent (via AryaOS queue); cannot create or register agents | Agent registry [EXISTS: agents/registry.py] | Binding [NEEDS IMPL.]   |
| `evaluation.run`     | Run an evaluator to produce evidence (no decisions, §12 of AGENTS) | Evaluation service                          | Service [NEEDS IMPL.]   |
| `publishing.request` | Request publishing for an AryaOS-owned publish job/artifact (never arbitrary external destinations or credentials) | Publishing router/service [EXISTS]          | Binding [NEEDS IMPL.]   |

Rules:
- Every capability is request/response, typed (Pydantic schema per capability
  [NEEDS IMPLEMENTATION]), and validated before execution.
- Capabilities with side effects (`story.create`, `provider.generate`,
  `publishing.request`, `agent.request`, `evaluation.run`) create normal
  AryaOS records (job, run, approval, lineage) exactly as the equivalent
  AryaOS internal call would. Hermes is never a shortcut around AryaOS
  bookkeeping.
- FORBIDDEN: any universal/generic tool such as `aryaos_api_call`,
  `http_request`, `shell`, `file_write`, `browser`, `code_run`. The policy
  gate structurally rejects any tool name outside the table above.
- Adding/removing a capability requires editing this spec's table, the typed
  registry, and the policy rules together, with security review.

## 10. Authorization Context

Every Hermes job runs with an authorization context constructed by AryaOS and
supplied to the policy gate on every tool request [NEEDS IMPLEMENTATION].
Minimum fields:

- `user_id` — the responsible human principal.
- `project_id` — project/tenant scope (isolation boundary).
- `job_id` / `workflow_run_id` — the AryaOS job this agent loop serves
  [EXISTS: workflow run IDs in models/core.py, lineage via
  services/lineage_service.py].
- `agent_id` — identity of the Hermes agent instance (AryaOS-issued).
- `capability` — requested typed capability (§9).
- `tool_name` — raw Hermes tool name as requested.
- `parameters` — full, unmodified tool parameters (post schema-validation,
  pre-execution).
- `budget` — remaining budget for the job (USD and/or tool calls, §12).
- `approval_state` — relevant AryaOS Approval records/flags
  [EXISTS: models/approval.py].
- `policy_context` — persona, policy version, feature flags relevant to the
  decision.
- `lineage_id` / `correlation_id` — for lineage and audit correlation.

The context is immutable for the duration of a tool request. Missing or
malformed context = BLOCK (§11).

## 11. Failure Behavior (Fail Closed)

All failure handling follows one rule: when in doubt, deny and surface a
structured error to AryaOS. Hermes never "recovers" past the policy gate.

| Failure                          | Behavior                                                                 |
|----------------------------------|--------------------------------------------------------------------------|
| Missing policy plugin at startup | Refuse to construct the agent; fail the job before any model call (§4.3). |
| Policy hook raises/times out     | BLOCK the tool call; abort the agent loop; job → failed with reason.      |
| Agent-loop timeout               | Terminate the loop; job → failed; partial results recorded as non-final.  |
| Invalid/unknown capability       | BLOCK; logged as policy violation with full request payload.              |
| Invalid authorization context    | BLOCK; abort loop (indicates AryaOS bug, not model behavior).             |
| Provider unavailable             | `provider.generate` returns the router's structured failure [EXISTS: `AllProvidersFailedError`]; the loop may not retry past configured limits (§12). |
| Budget violation                 | Deny further `provider.generate`/chargeable calls; job → failed/budget-exceeded; no silent continuation. |
| Approval required but absent     | Capability returns PENDING_APPROVAL; loop ends with job awaiting AryaOS approval; never auto-approves. |
| Malformed tool request           | BLOCK; logged; counted against the job's malformed-request limit (§12).   |

Every failure path must produce an AryaOS-side audit record (§13). Hermes-side
diagnostics are best-effort only and are not authoritative.

## 12. Resource Limits

All limits are AryaOS settings [NEEDS IMPLEMENTATION], per job, enforced by
the embedding runtime and/or the policy gate — not trusted to Hermes:

- Max agent iterations per job.
- Max wall-clock execution time per job (hard timeout).
- Max tool calls per job (total), and per capability.
- Max generation budget per job (USD), integrated with the provider router's
  cost accounting [EXISTS: router cost ceiling / `CostLimitExceededError`].
- Max context size (tokens/bytes) supplied to Hermes.
- Max malformed/blocked tool requests tolerated before job abort.

Recommended initial defaults are to be set at implementation with operator
input; this spec fixes only that the limits exist, are configurable, are
finite, and are enforced even if Hermes ignores or misreports them
(defense in depth: AryaOS-side counters and timers own the truth).

## 13. Observability

AryaOS records, for every Hermes job and every tool request (structured
logging via structlog [EXISTS: core/logging.py] plus persistent audit
[NEEDS IMPLEMENTATION]):

- job identity: user/project/job/workflow_run/agent IDs;
- correlation/lineage IDs;
- capability and tool name;
- decision (ALLOW/BLOCK) and policy reason code;
- parameter digest (full parameters in the audit store; digests in logs —
  never log secrets or raw credentials);
- outcome (success/failure/timeout), duration, cost;
- resource-limit counters before/after;
- Hermes commit pin, config hash, plugin load verification result.

Hermes is not the system of record: its internal logs, if captured, are
diagnostic attachments only. Reconstructing what happened requires only
AryaOS records. Blocked/denied requests are first-class audit events, not
noise.

## 14. Source Provisioning and Dependency Strategy

14.1 Source provisioning (decided).
- Hermes source is provisioned as a Git submodule: `vendor/hermes-agent`.
- The submodule MUST point to exactly
  `c0d7294769a38c17ceae51d8f7995e66e1dcae27`. The submodule pointer
  (gitlink) is the repository-level source of truth for the approved
  Hermes source version.
- No floating Hermes branch, tag, or version is permitted for production.
- Updating Hermes requires an explicit AryaOS change reviewed against §15.
  Changing the submodule pointer alone is not sufficient to bypass the
  runtime/source verification requirements.
- Runtime/build verification must not rely solely on Git metadata being
  present inside the production container. The later runtime/build slice
  [NEEDS IMPLEMENTATION] must record the approved Hermes commit SHA and
  the tree hash of that commit
  (`eff225d07a45bcff9ecd96d4632564657218798e` at the current pin) in an
  AryaOS-controlled manifest or equivalent immutable build metadata, and
  startup verification (§2) must fail closed on absence or mismatch.
- Basis [VERIFIED-SUPPLIED]: the pinned Hermes repository intentionally
  does not support normal wheel/sdist building (`setup.py` blocks
  `bdist_wheel`/`sdist` outside a Nix build), so Hermes cannot be consumed
  as a standard PyPI-style dependency or a non-editable `git+https`
  dependency. Supported consumption at the pin is a source checkout with
  an editable install; the upstream installer itself supports
  `--commit SHA` pinning.

14.2 Dependency strategy (deliberately unresolved).
- Dependency-union work (installing Hermes's dependencies into AryaOS's
  uv + lockfile environment [EXISTS: pyproject.toml, uv.lock]) is kept
  separate from source provisioning. The decision in §14.1 does NOT
  authorize `pyproject.toml`, `uv.lock`, Docker, or dependency changes.
- The dependency mechanism must still be selected against the existing
  packaging and runtime surface (uv + lockfile + hatchling build of
  `backend/app`, docker-compose deployment [EXISTS]).
- Selection criteria (minimum): pinability to the exact commit, reproducible
  install, no accidental floating resolution, no secret leakage into the
  artifact, and compatibility with the startup assertions of §2/§4/§5.
- Until that mechanism is chosen and reviewed, Hermes remains absent from
  AryaOS dependencies. No `pyproject.toml` change is authorized by this
  spec.

## 15. Upgrade Policy

- Hermes stays pinned to `c0d7294769a38c17ceae51d8f7995e66e1dcae27`.
- Any change to the pin requires, in order:
  1. source verification of the new commit (agent API, toolsets, plugin
     hooks, memory/session flags, delegation, cron, gateway, env vars,
     config surface) — refreshed findings for every [VERIFIED-SUPPLIED] and
     [TO VERIFY AT IMPLEMENTATION] item in this spec;
  2. isolated runtime security verification (policy gate bypass attempts,
     fail-closed behavior, isolation of HERMES_HOME, scrub effectiveness);
  3. architecture review against the approved AryaOS V2 architecture;
  4. explicit human approval recorded before the pin changes.
- An upgrade is effected by moving the `vendor/hermes-agent` submodule
  pointer (§14.1). Changing the pointer alone is not sufficient: the
  recorded manifest/build metadata of §14.1 must be updated in the same
  change and must agree with the new pin.
- No automated upgrade path may exist. Dependency bots/renovate must not be
  able to bump Hermes silently.

## 16. Acceptance Tests

Concrete tests to be implemented with the integration (pytest, following the
`backend/tests/test_*_unit.py` convention [EXISTS]; runtime tests require the
pinned Hermes source available in the test environment — environment
provisioning is part of the implementation task):

- T1 `test_hermes_unauthorized_tool_blocked` — tool outside the typed
  capability set (e.g. `shell`, `file_write`, `delegate_task`) → policy gate
  returns BLOCK; job fails; audit record exists.
- T2 `test_hermes_authorized_tool_allowed` — `research.search` with valid
  authz context and policy → ALLOW; executes against a stubbed AryaOS
  service; result recorded.
- T3 `test_hermes_invoke_tool_path_blocked` — tool request routed via
  Hermes' `invoke_tool` path with an unauthorized tool → BLOCK (proves the
  gate covers non-inline call paths).
- T4 `test_hermes_inline_executor_path_blocked` — tool request routed via
  the inline executor path with an unauthorized tool → BLOCK.
- T5 `test_hermes_missing_policy_plugin_no_startup` — policy plugin absent
  (bad plugin dir / load failure) → runtime refuses to construct the agent;
  no model call is made; job fails with reason `policy_plugin_missing`.
- T6 `test_hermes_dangerous_toolsets_unavailable` — instantiated agent's
  tool surface contains only the frozen allowlist; no shell/file/browser/
  code/delegation/mcp/cron tools present; `enabled_toolsets is None` rejected
  by startup validation.
- T7 `test_hermes_cron_not_running` — after agent construction and loop
  execution, no Hermes cron/scheduler objects, tasks, or jobs exist
  (introspection + task registry sweep).
- T8 `test_hermes_gateway_not_running` — no gateway process/thread/listener
  started; no gateway-related ports bound.
- T9 `test_hermes_dedicated_home` — all files Hermes writes during a job land
  under the dedicated `HERMES_HOME`; repo dir, user home, and AryaOS data
  paths outside `HERMES_HOME` are untouched (filesystem snapshot diff).
- T10 `test_hermes_no_aryaos_fs_access_without_capability` — with no
  filesystem capability granted, agent loop cannot read AryaOS files
  (canary files remain unread; no fs tool calls succeed).
- T11 `test_hermes_no_shell_browser_code_execution` — repeated prompting of
  the agent to execute shell/browser/code yields only BLOCKed attempts; no
  process spawn, no subprocess, and no arbitrary network access; network
  access is limited to AryaOS-approved model/provider endpoints required by
  the runtime.
- T12 `test_hermes_bounded_iterations_and_timeouts` — agent loop exceeding
  max iterations or wall-clock is terminated by AryaOS; job marked failed;
  limits enforced even when the model "volunteers" to stop later.
- T13 `test_hermes_aryaos_remains_system_of_record` — after a full job with
  ALLOWed tools, all authoritative state (job status, results, lineage,
  approvals) and any explicitly promoted memory are recoverable from AryaOS
  stores with Hermes state deleted.
- T14 `test_hermes_env_scrubbed_before_import` — dangerous env vars
  (enumerated list from §5.5) are absent from the environment seen by the
  Hermes import; scrub step is testable in isolation.
- T15 `test_hermes_memory_disabled` — constructed agent has memory,
  session_search disabled and skip flags set per §6; no memory files created
  outside `HERMES_HOME`; no second memory authority (retrieval only via
  `memory.retrieve`).
- T16 `test_hermes_budget_and_approval_gates` — budget exhaustion denies
  chargeable calls; approval-gated capability without approval returns
  PENDING_APPROVAL and never executes.

Security acceptance tests must not silently pass when the Hermes source or
required runtime environment is unavailable. Missing Hermes source is an
explicit integration-environment failure, not a successful test skip. Any
intentional test-profile exclusion must be explicit and must not be reported
as security verification.

---

## Appendix A: Open Items Requiring Decisions at Implementation Time

1. Exact `enabled_toolsets` allowlist names (from pinned source) — §5.1.
2. Exact env-var scrub list (from pinned source) — §5.5.
3. Hermes runtime-state failure/cleanup semantics for unsuccessful jobs
   (§5.2, §6).
4. Source provisioning for Hermes — RESOLVED: Git submodule
   `vendor/hermes-agent` at the pinned commit (§14.1). Dependency-union
   mechanism remains open (§14.2).
5. Resource-limit default values — §12.
6. Audit store for tool-request records — §13.
7. Binding of each typed capability to its AryaOS service — §9 table.
8. AryaOS settings names for pin, limits, and plugin path — §2, §12.

## Appendix B: Traceability to AGENTS.md

- §1 ↔ AGENTS.md §6 (authority model), §8 (OpenMontage boundary).
- §4 ↔ AGENTS.md §7 (no unrestricted tool gateway; typed operations).
- §6 ↔ AGENTS.md §10 (memory authority).
- §8 ↔ AGENTS.md §11 (scheduling authority).
- §9 ↔ AGENTS.md §7, §9 (typed capabilities; provider architecture —
  `provider.generate` routes through the capability-based router, RunPod
  stays infrastructure).
- §12 ↔ AGENTS.md §12 analog (evaluation produces evidence; limits prevent
  evaluator-turned-orchestrator).
- §14 ↔ AGENTS.md §14 (dependency discipline).
- §15 ↔ AGENTS.md §7 (pin before integration).
