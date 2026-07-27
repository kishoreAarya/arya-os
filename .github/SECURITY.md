# Security Policy

## Current project status

Arya OS is currently a **Sprint 1-3 backend foundation scaffold** for a
single-operator, self-hosted content pipeline. It is not a
multi-tenant product and does not currently have any of the following
by design, not by oversight:

- No authentication/authorization on any API route (`/approvals`,
  `/feature-flags`, `/lineage`, `/health`)
- No rate limiting
- No `Users` table

**This backend must not be exposed directly to the public internet
without at least a shared-secret gate or being placed behind a private
tunnel/VPN.** It is intended to run on a private network or behind
something like a Cloudflare Tunnel with access control, not on an
open port.

If you deploy this yourself, you are responsible for:
- Never publishing the Postgres (`5432`) or Redis (`6379`) ports from
  `docker-compose.yml` to a public interface
- Setting real, non-default values for every `*_PASSWORD` /
  `*_API_KEY` field in `.env` — the fallback defaults in
  `docker-compose.yml` (e.g. `change_me`) are placeholders only
- Keeping `DEBUG=false` in any environment other than local development
- Restricting network access to the FastAPI backend to trusted
  clients (your own n8n instance, your own dashboard) only

## Supported versions

This project has no tagged releases yet. Security fixes are applied
to `main` only.

| Version | Supported |
|---|---|
| `main` | ✅ |

## Reporting a vulnerability

This is currently a single-maintainer project. If you find a security
issue:

1. **Do not open a public GitHub issue.**
2. Open a [private security advisory](../../security/advisories/new)
   on this repository, or contact the maintainer directly.
3. Include: affected file(s)/endpoint(s), reproduction steps, and
   potential impact.

Expect an initial response within a few days — there is no formal SLA
yet given the project's current stage.

## Known accepted risks (tracked, not hidden)

These are documented, intentional gaps for the current scope, tracked
for future hardening rather than silently ignored:

- No API authentication (tracked — planned before any public exposure)
- No rate limiting (tracked — deferred until real traffic patterns exist)
- Agents/validators are stubs and perform no real external calls yet,
  so provider-side data handling has not been security-reviewed
  because it does not exist yet
- No automated secret-scanning workflow yet (bandit + pip-audit run in
  CI; a dedicated secrets-scanning step, e.g. gitleaks, is a
  reasonable near-term addition)
