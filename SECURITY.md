# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Report it privately through GitHub:

1. Go to the [Security Advisories page](https://github.com/sidhasadhak/aughor/security/advisories/new).
2. Describe the issue, the impact, and the steps to reproduce it.

You should get an acknowledgement within **7 days**. Aughor is an alpha project
maintained in someone's spare time, so please be patient with the fix timeline —
but the acknowledgement will be prompt.

If you do not get a response within 7 days, open a public issue that says only
*"awaiting a response on a private security report"* — with no details.

## Supported versions

Aughor is pre-1.0 (`0.1.0`) and has no tagged releases yet. Only the `main`
branch receives fixes. There is no long-term-support branch, and no backports.

| Version | Supported |
|---|---|
| `main` | ✅ |
| anything else | ❌ |

## Scope

Aughor connects a large language model to a SQL warehouse. That shape carries
inherent risk. The following are **in scope** and worth reporting:

- Bypassing the read-only SQL gate (`aughor/sql/readonly.py`, `aughor/sql/executor.py`)
  so that a generated query can write, drop, or otherwise mutate data.
- Escaping the per-schema scoping so a query reads tables it was not granted.
- Bypassing the RBAC row policy or the licensing capability gate.
- Extracting stored connection credentials. DSNs and connector secrets are
  encrypted at rest with Fernet (`aughor/db/registry.py`); the key file is
  written `0o600`. Anything that recovers plaintext without the key is a finding.
- Prompt injection through *data* — a value inside a warehouse row that causes
  the agent to exfiltrate data or execute unintended SQL.
- Path traversal or SSRF via connector configuration.
- Secret leakage into logs, SSE event streams, or the OpenAPI schema.

## Out of scope

- **The API is unauthenticated by default.** `AUGHOR_API_KEY` is unset out of
  the box, because Aughor is designed as a local single-user tool bound to
  `localhost`. Reporting "the API has no auth" is not a vulnerability — but
  *bypassing the key when one is set* is.
- CORS is restricted to `http://localhost:3000,http://localhost:3001` by default
  and is configurable via `AUGHOR_CORS_ORIGINS`. Widening it yourself and then
  reporting it is not a finding.
- Vulnerabilities in third-party dependencies that Aughor does not reach. Report
  those upstream. If you can show a reachable path through Aughor, that *is* in
  scope.
- The LLM producing a wrong answer. Aughor has guards for this, but a wrong
  number is a correctness bug, not a security vulnerability — please file it as
  a normal issue.

## Deploying Aughor beyond localhost

Aughor's defaults assume a trusted, single-user, local environment. Before
exposing it to a network:

- Set `AUGHOR_API_KEY` to a strong random value. Every request must then carry
  it as `X-Api-Key` (`/health`, `/docs`, `/redoc`, and `/openapi.json` stay open).
- Set `AUGHOR_CORS_ORIGINS` to the exact origins you serve.
- Terminate TLS in front of the app; Aughor speaks plain HTTP.
- Give the warehouse credential the narrowest read-only grant that works.
