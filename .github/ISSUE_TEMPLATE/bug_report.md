---
name: Bug report
about: Something in the existing backend foundation isn't working as expected
title: "[Bug] "
labels: bug
assignees: ""
---

<!--
Scope check first: Arya OS today is a backend foundation only — no
n8n workflows, no wired agents/validators (they're stubs by design),
no deployment automation. If this bug is actually "the pipeline
doesn't generate a video," that's expected — Sprint 3+ scope, not a
bug. File this template for issues in what actually exists today:
FastAPI app, models, migrations, storage, provider-router scaffolding,
health checks, CI.
-->

## What happened?

## What did you expect to happen?

## Steps to reproduce

1.
2.
3.

## Environment

- Where this was run: [local `uv run uvicorn` / docker compose / other]
- Relevant `.env` settings (redact secrets): 

## Logs / traceback

```
paste here
```

## Affected area

- [ ] API routers (`health` / `approvals` / `feature-flags` / `lineage`)
- [ ] Database / models / migrations
- [ ] Storage (local / S3)
- [ ] Provider router / capability registry
- [ ] Worker scheduler
- [ ] CI workflow
- [ ] Other:
