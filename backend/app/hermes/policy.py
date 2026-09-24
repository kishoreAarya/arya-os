"""
AryaOS-owned Hermes policy gate — §4 security boundary (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §4 (security
boundary), §4.1 (toolsets are not authorization), §4.2 (pre_tool_call
gate), §4.3 (fail closed on plugin absence), §4.4 (fail closed on policy
evaluation), §4.5 (no god tool), §7 (delegate_task BLOCKed by name),
§9 (typed capability set), §10 (authorization context), §11 (failure
behavior).

This module is the decision core of the policy gate. It is deliberately
free of runtime concerns: the physical Hermes plugin package, its load
path wiring, and the startup refusal behavior of §4.3 belong to the §3
runtime-adapter slice, which calls verify_policy_plugin_registered()
BEFORE constructing any agent.

Pinned-source contract this implements (commit c0d7294):
- Hook name ``pre_tool_call``; registration via
  ``PluginContext.register_hook("pre_tool_call", callback)``
  (hermes_cli/plugins.py:912).
- Callback kwargs: ``tool_name`` (str), ``args`` (dict), plus
  identity/telemetry fields (task_id, session_id, tool_call_id, turn_id,
  api_request_id, middleware_trace) — hermes_cli/plugins.py:1861-1866.
- Callback returns: ``None`` = proceed; ``{"action": "block", "message":
  str}`` = BLOCK, the message becomes the tool result. A block directive
  WITHOUT a non-empty message is IGNORED by Hermes (plugins.py:1890) —
  therefore every BLOCK here carries a non-empty message. This gate never
  returns "modify" (no argument rewriting) and never returns "approve"
  (human-escalation is the §5.4/§11 approval flow, delivered by the §9/§10
  slices — until then the gate decides ALLOW/BLOCK only).
- Hermes runs the hook BEFORE tool execution (model_tools.py:940 precedes
  _execute_tool at :947); a block means the tool never runs.
- Hermes fails closed for THIS hook at the callback level: a raising or
  timed-out pre_tool_call callback produces a block directive
  (plugins_dispatch.py:49 _HOOK_TIMEOUT_FAIL_CLOSED_HOOKS, #109624).
  Residual Hermes-side fail-open edges verified at the pin and compensated
  for here: (a) an exception raised by the dispatch wrapper itself is
  swallowed and the call proceeds (model_tools.py:780-782) — so the AryaOS
  callback must never raise; (b) a message-less block is ignored
  (plugins.py:1890) — so the callback always emits a non-empty message.

Authorization universe (§4.2/§4.5 — ALLOW only for explicitly authorized
targets; BLOCK everything else):
- TYPED_CAPABILITIES — the §9 capability names (bindings arrive in later
  slices; the names are frozen here per the spec table).
- SANCTIONED_NATIVE_TOOLS — the tool names of the §5.1 frozen toolset
  allowlist. Interpretive note (flagged for review): §4.5 calls §9 "the
  complete universe", while §5.1 mandates a non-empty native toolset
  allowlist whose exposure would be meaningless if the gate BLOCKed it.
  The only reading under which both hold: the §4 gate authorizes (a) typed
  capabilities and (b) the §5.1-sanctioned native tool surface. That
  surface is frozen here as {"todo_list"} (the pinned source resolves the
  "todo" toolset to exactly ["todo_list"], toolsets.py:127). Removing it
  means deleting this constant; it receives no other privileges.
- delegate_task is additionally BLOCKed by name (§7), independent of any
  future registry change.

§10 note: the AuthorizationContext below carries the identity fields the
gate needs to authorize (user/project/job/agent/lineage). The remaining
§10 fields (budget, approval_state, policy_context, per-request
capability/parameters) are supplied by their own slices; the context
dataclass is the extension point. Missing or malformed context is BLOCK
(§11 "Invalid authorization context").

No logging/audit implementation lives here (§13 slice records decisions
via the reason codes); messages carry tool names and reason codes only,
never parameter values.
"""
from dataclasses import dataclass
from typing import Any, Protocol


class HermesPolicyPluginError(RuntimeError):
    """The §4.3 startup assertion failed: the AryaOS policy plugin is not
    verifiably registered in the Hermes plugin registry. Fail-closed: the
    caller (§3 runtime slice) must refuse to construct the agent and fail
    the job.

    `violations` is a list of (code, detail) tuples, mirroring
    app.hermes.config.HermesConfigError.
    """

    def __init__(self, violations: list[tuple[str, str]]):
        self.violations = violations
        rendered = "; ".join(f"{code}: {detail}" for code, detail in violations)
        super().__init__(f"AryaOS Hermes policy plugin verification failed ({rendered})")


# The §9 typed capability set — the capability names Hermes sees as tool
# names. Bindings to AryaOS services arrive in later slices (spec §9 table,
# all rows marked Binding [NEEDS IMPL.]); changes follow §15.
TYPED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "research.search",
        "research.get",
        "story.create",
        "memory.retrieve",
        "provider.generate",
        "asset.get",
        "agent.request",
        "evaluation.run",
        "publishing.request",
    }
)

# §7: delegate_task is explicitly BLOCKed by name in the policy gate,
# independent of toolset configuration (max_spawn_depth=0 is NOT a control;
# no disable_delegate flag exists at the pin).
EXPLICITLY_BLOCKED_TOOLS: tuple[str, ...] = ("delegate_task",)

# The tool names of the §5.1 frozen toolset allowlist (app.hermes.toolsets,
# allowlist ("todo",)); pinned source resolves that toolset to exactly
# ["todo_list"] (toolsets.py:127). See the module docstring's
# "Interpretive note" for the §4.5/§5.1 synthesis this constant encodes.
SANCTIONED_NATIVE_TOOLS: frozenset[str] = frozenset({"todo_list"})

# Identity fields required on every authorization context (§10 minimum,
# identity subset; extended by the §10 slice).
_REQUIRED_CONTEXT_FIELDS = ("user_id", "project_id", "job_id", "agent_id", "lineage_id")


@dataclass(frozen=True)
class AuthorizationContext:
    """Immutable per-job authorization context (§10) supplied by AryaOS to
    the policy gate on every tool request. Identity fields only for now;
    §10's remaining fields (budget, approval_state, policy_context) join
    this dataclass in their own slices. A context is valid only when every
    identity field is a non-empty string.
    """

    user_id: str
    project_id: str
    job_id: str
    agent_id: str
    lineage_id: str


def _context_violation(context: object) -> str | None:
    """Return a reason code describing why `context` is unusable, or None
    when it is a valid AuthorizationContext. Never raises."""
    if not isinstance(context, AuthorizationContext):
        return "blocked_invalid_context_type"
    for field in _REQUIRED_CONTEXT_FIELDS:
        value = getattr(context, field, None)
        if not isinstance(value, str) or not value.strip():
            return f"blocked_invalid_context_field:{field}"
    return None


@dataclass(frozen=True)
class PolicyDecision:
    """One deterministic policy decision.

    `allowed` — True only for an explicitly authorized target with a valid
    authorization context (§4.2).
    `reason_code` — stable machine-readable code (future §13 audit input).
    `message` — non-empty for BLOCK (required by the Hermes hook contract);
    carries the tool name and reason only, never parameter values.
    """

    allowed: bool
    reason_code: str
    message: str


def _allow(reason_code: str) -> PolicyDecision:
    return PolicyDecision(allowed=True, reason_code=reason_code, message="")


def _block(tool_name: object, reason_code: str) -> PolicyDecision:
    name = tool_name if isinstance(tool_name, str) and tool_name else "<invalid>"
    return PolicyDecision(
        allowed=False,
        reason_code=reason_code,
        message=f"Blocked by AryaOS policy gate ({reason_code}): {name!r}",
    )


def evaluate_tool_request(
    tool_name: object,
    parameters: object,
    authorization_context: object,
) -> PolicyDecision:
    """Evaluate one tool request against the §4 policy. Total function:
    NEVER raises — any internal failure is BLOCK (§4.4), because a raising
    callback would fail OPEN through Hermes' dispatch wrapper
    (model_tools.py:780-782 at the pin).

    ALLOW only when the tool name is an authorized target (typed capability
    §9, or §5.1-sanctioned native tool) AND the request is well-formed AND
    the authorization context is valid. BLOCK for everything else,
    including unknown tools, malformed requests, and delegate_task (§7).
    Per-capability parameter SCHEMA validation is §9 binding work; here
    parameters are structurally validated only.
    """
    try:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return _block(tool_name, "blocked_malformed_tool_name")
        if parameters is not None and (
            not isinstance(parameters, dict)
            or any(not isinstance(key, str) for key in parameters)
        ):
            # Tool arguments arrive as JSON objects: str -> value. Anything
            # else is malformed (§4.2).
            return _block(tool_name, "blocked_malformed_parameters")
        context_error = _context_violation(authorization_context)
        if context_error is not None:
            return _block(tool_name, context_error)
        if tool_name in EXPLICITLY_BLOCKED_TOOLS:
            return _block(tool_name, "blocked_explicit")
        if tool_name in TYPED_CAPABILITIES:
            return _allow("allowed_typed_capability")
        if tool_name in SANCTIONED_NATIVE_TOOLS:
            return _allow("allowed_sanctioned_native_tool")
        return _block(tool_name, "blocked_unknown_tool")
    except BaseException:  # noqa: BLE001 — §4.4: never raise, never fail open
        return _block(tool_name, "blocked_internal_error")


# Marker checked by verify_policy_plugin_registered(): identifies a
# registered pre_tool_call callback as the AryaOS policy gate.
POLICY_PLUGIN_MARKER = "__aryaos_policy_plugin__"


def make_pre_tool_call_hook(authorization_context: AuthorizationContext):
    """Build the Hermes-shaped ``pre_tool_call`` callback (§4.2).

    Contract (pinned source, hermes_cli/plugins.py): the callback receives
    ``tool_name`` (str), ``args`` (dict) and identity kwargs; it returns
    ``None`` to proceed or ``{"action": "block", "message": <non-empty str>}``
    to veto (the message becomes the tool result). This callback never
    returns "modify" or "approve" and never raises (§4.4 + the fail-open
    dispatch edge at model_tools.py:780).
    """

    def pre_tool_call_hook(tool_name: str, args: dict | None = None, **_hook_kwargs: Any):
        decision = evaluate_tool_request(tool_name, args, authorization_context)
        if decision.allowed:
            return None
        return {"action": "block", "message": decision.message}

    setattr(pre_tool_call_hook, POLICY_PLUGIN_MARKER, True)
    return pre_tool_call_hook


class PluginContextLike(Protocol):
    """The slice of Hermes' PluginContext the gate needs: register_hook
    (hermes_cli/plugins.py:912). A Protocol keeps this module free of any
    Hermes import; the §3 runtime slice passes the real context object.
    """

    def register_hook(self, hook_name: str, callback: Any) -> Any: ...


def register_policy_plugin(ctx: PluginContextLike, authorization_context: AuthorizationContext):
    """Register the policy gate's pre_tool_call hook on a Hermes plugin
    context (§4.2). Called from the plugin package's ``register(ctx)`` in
    the §3 runtime slice; no Hermes import happens here.
    """
    return ctx.register_hook("pre_tool_call", make_pre_tool_call_hook(authorization_context))


def verify_policy_plugin_registered(callbacks: object) -> None:
    """§4.3 fail-closed startup assertion.

    `callbacks` is the snapshot of callbacks registered for the
    ``pre_tool_call`` hook in the Hermes plugin registry (the §3 runtime
    slice obtains it via ``iter_hook_callbacks("pre_tool_call")`` /
    ``has_hook`` at pin: hermes_cli/plugins.py:1822+, plugins_dispatch.py:557).
    Passes only when at least one callback carries the AryaOS policy plugin
    marker; raises HermesPolicyPluginError("policy_plugin_missing")
    otherwise — for a missing plugin dir, a load failure, or a silent skip
    — and the caller must refuse to start the agent.
    """
    try:
        present = isinstance(callbacks, (list, tuple)) and any(
            callable(cb) and getattr(cb, POLICY_PLUGIN_MARKER, False) is True
            for cb in callbacks
        )
    except Exception:  # noqa: BLE001 — introspection failure is fail-closed
        present = False
    if not present:
        raise HermesPolicyPluginError(
            [
                (
                    "policy_plugin_missing",
                    "the AryaOS policy plugin is not registered for the "
                    "pre_tool_call hook; refusing to start Hermes (§4.3 — "
                    "there is no configuration under which Hermes runs "
                    "inside AryaOS without the policy gate)",
                )
            ]
        )
