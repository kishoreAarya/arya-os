<!--
Arya OS is currently a Sprint 1-3 foundation scaffold: backend
plumbing exists, agents/validators are stubs, n8n workflows and
deployment are not implemented yet. Keep that scope in mind when
filling this out — a PR touching agent/validator internals should say
so explicitly, since that logic is expected to still be a stub today.
-->

## What does this PR change?

<!-- One or two sentences. Link an issue if one exists. -->

## Area(s) touched

- [ ] Backend foundation (`core`, `database`, `models`, `services`, `api`)
- [ ] Storage / providers
- [ ] Workers / scheduler
- [ ] Agents (stub contracts only — real provider calls are Sprint 3+)
- [ ] Validators (stub contracts only — real scoring logic is Sprint 3+)
- [ ] CI / GitHub Actions
- [ ] Docs (README / SECURITY.md / etc.)
- [ ] Other:

## Checklist

- [ ] `uv run ruff check backend` passes locally
- [ ] `uv run black --check backend` passes locally
- [ ] `uv run pytest` passes locally
- [ ] I added/updated tests for any new behavior (not required for stub-only agent/validator scaffolding)
- [ ] If this touches `app/models/`, I generated an Alembic migration and committed it under `alembic/versions/`
- [ ] If this touches `.env.example`, config values are documented and non-sensitive defaults are safe

## Out of scope reminder

This PR should **not** need to touch: `deployment.yml`/`release.yml` workflows, n8n workflow definitions, or integration/end-to-end tests — none of these exist yet by design (see repo README / engineering review). If your change genuinely needs one of these, flag it in the description rather than adding it silently.

## Notes for reviewer

<!-- Anything a reviewer should specifically look at or be aware of. -->
