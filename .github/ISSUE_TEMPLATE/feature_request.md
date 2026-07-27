---
name: Feature request
about: Propose new backend functionality (not agent/validator/pipeline logic)
title: "[Feature] "
labels: enhancement
assignees: ""
---

<!--
Reminder of current project boundaries: n8n stays the pipeline
orchestrator; this backend exposes REST endpoints + data integrity
around it. If this request is really "wire up the Image Agent to a
real provider" or "build the n8n workflow for X," that's expected
Sprint 3+/4+ work, not a gap — feel free to still file it, just say so
in the description so it's triaged correctly.
-->

## Problem

<!-- What's missing or awkward about the backend today? -->

## Proposed solution

## Which layer does this belong in?

- [ ] `api/routers` (new endpoint)
- [ ] `services` (new business logic)
- [ ] `models` (new table / schema change — will need a migration)
- [ ] `providers` / `storage` (new backend/integration)
- [ ] `workers` (new scheduled job)
- [ ] CI / tooling
- [ ] Other:

## Out of scope for this request (check if true)

- [ ] This does NOT require deployment automation
- [ ] This does NOT require an n8n workflow change
- [ ] This does NOT require wiring a real agent/validator provider call
