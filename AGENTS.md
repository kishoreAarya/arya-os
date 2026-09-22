# AryaOS V2 — Agent Operating Contract

## 1. Authority

This repository contains AryaOS V2.

The approved AryaOS V2 architecture is authoritative.
Do not redesign, replace, simplify, merge, or introduce competing architecture
without explicit human approval.

The agent is an IMPLEMENTER, not the system architect.

If a requirement conflicts with the approved architecture:
STOP and report the conflict.

If a requirement is ambiguous:
STOP and ask.

Never invent an API, configuration option, library capability, model capability,
framework behavior, or repository behavior.

Verify uncertain claims from source code, official documentation, or executable tests.

## 2. Git Safety

- Work only on the v2 branch unless explicitly instructed otherwise.
- Never modify main.
- Never force-push.
- Never use `git reset --hard` unless explicitly authorized.
- Never delete branches.
- Never rewrite published history.
- Never commit secrets.
- Never commit generated files or local credentials.
- Before destructive Git operations: STOP and request approval.
- Before committing: inspect the complete diff.
- Never push automatically.

## 3. Implementation Discipline

For every task:

1. Read the relevant existing code.
2. Identify existing interfaces and dependencies.
3. Check the approved architecture.
4. Produce a small implementation plan.
5. Implement the minimum required change.
6. Do not perform unrelated refactoring.
7. Do not rename or reorganize unrelated code.
8. Preserve existing V1 behavior unless V2 explicitly requires a change.
9. Run focused tests.
10. Run relevant broader tests.
11. Perform a security review.
12. Inspect the final diff.
13. Report exactly what changed and what was verified.

## 4. Verification

Never claim that something works unless it was actually tested.

Distinguish:

- VERIFIED — actually executed/tested.
- INFERRED — reasoned from existing code.
- UNVERIFIED — not yet tested.

If a test cannot be executed, explain why.

Do not hide failures.

## 5. Security

Security is mandatory, not optional.

For security-sensitive changes:

- inspect authentication and authorization;
- validate input boundaries;
- check secrets handling;
- check path/file access;
- check command execution;
- check network access;
- check SSRF risks;
- check injection risks;
- check privilege boundaries;
- check tenant/project isolation;
- check logging of sensitive data;
- check dependency/security implications;
- run the approved security-audit skill when applicable.

Security findings must not be silently ignored.

Critical or high-risk findings require human review before proceeding.

## 6. AryaOS Authority Model

AryaOS is the system of record and authority.

AryaOS owns:

- project/job state
- policy and approval
- authorization
- memory
- agent registry
- persona registry
- asset/artifact registry
- lineage
- provider routing
- scheduling definitions
- domain/business rules

Hermes-Agent is an execution/reasoning runtime.

Hermes is NOT:

- the system of record
- AryaOS memory authority
- the AryaOS scheduler
- the AryaOS agent registry
- an unrestricted tool gateway

Do not give Hermes unrestricted authority.

## 7. Hermes Integration

Before implementing Hermes integration:

- pin the Hermes version/commit;
- inspect the actual source code;
- verify the real agent API;
- verify the real tool configuration;
- verify memory/session initialization;
- verify delegation/subagent behavior;
- verify cron/scheduling behavior;
- verify isolation mechanisms.

Never implement undocumented configuration based on assumptions.

In particular, do not assume configuration names such as
`skip_memory=True` or `enabled_toolsets` exist until verified against
the pinned source/version.

Hermes must use typed AryaOS-authorized operations.

NEVER create a universal unrestricted tool such as:

`aryaos_api_call(anything)`

Prefer explicit capability-scoped operations such as:

- research.search
- research.get
- story.create
- memory.retrieve
- provider.generate
- asset.get
- agent.request
- evaluation.run
- publishing.request

## 8. OpenMontage Boundary

OpenMontage is a separate project.

AryaOS creates the Job Package.

OpenMontage executes the media production.

Do not merge OpenMontage responsibilities into AryaOS.

Assets must be registered/referenced through the Asset/Artifact Registry
before being passed through the Job Package boundary.

## 9. Provider Architecture

Use capability-based provider routing.

FAL and ComfyUI are providers/adapters.

RunPod is infrastructure, not a provider.

Do not hard-code one generation provider into domain logic.

## 10. Memory

AryaOS owns authoritative memory.

Hermes may receive bounded context supplied by AryaOS.

Do not create a second authoritative memory system inside Hermes.

Persona Registry and Persona Memory are separate concepts.

## 11. Scheduling

AryaOS owns schedule definitions and scheduling authority.

n8n may execute deterministic triggers/workflows where explicitly integrated.

Do not create competing independent schedulers.

Hermes cron must not silently become a second AryaOS scheduler.

## 12. Evaluation

Evaluation produces evidence.

AryaOS decides:

- retry
- revise
- stop
- human review
- approval

Do not allow an evaluator to silently become an orchestrator.

## 13. Decision Engine

DecisionEngine is an interface/future capability.

Do not introduce Jev or Laya as a V2 runtime dependency without explicit approval.

Do not invent decision-model performance.

## 14. Dependencies

Before adding a dependency:

- verify that it is actually needed;
- inspect existing dependencies for equivalent functionality;
- check maintenance/security status;
- minimize dependency surface;
- document why it is required.

Do not add libraries merely because they are convenient.

## 15. Database

Database changes require:

- explicit migration;
- forward migration testing;
- appropriate rollback consideration;
- relevant tests;
- no destructive production assumptions.

Never modify production data directly.

## 16. Secrets

Never:

- print API keys;
- commit API keys;
- hard-code credentials;
- put secrets into tests;
- expose secrets in logs;
- paste secrets into source files.

Use environment variables or the approved secret mechanism.

## 17. Autonomous Execution

Autonomy means executing approved tasks, not inventing new requirements.

The agent may:

- inspect;
- plan;
- implement;
- test;
- debug;
- audit;
- document.

The agent may NOT independently:

- redesign architecture;
- weaken security;
- bypass authorization;
- change project boundaries;
- change V1;
- publish/deploy production changes;
- push Git history;
- introduce new major infrastructure.

## 18. Stop Conditions

STOP and request human review when:

- architecture is ambiguous;
- requirements conflict;
- a security boundary must be weakened;
- a destructive migration is required;
- V1 behavior must be changed unexpectedly;
- an external API behavior is undocumented;
- a dependency introduces significant risk;
- tests cannot establish correctness;
- a security audit finds a critical/high-risk issue;
- the proposed solution requires architectural deviation.

## 19. Final Report

At the end of every implementation task report:

### Changed
Files and purpose.

### Tests
Exact commands executed and results.

### Security
Checks performed and findings.

### Architecture
Whether the approved architecture was preserved.

### Risks
Known unresolved risks.

### Unverified
Anything that could not be verified.

Do not claim completion when important verification remains outstanding.
