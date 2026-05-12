# Enterprise Readiness Roadmap — Insurance Document Platform

What it would take to ship this platform as an enterprise SaaS to insurance brokerages and carriers. **None of the items below are committed work.** This document exists so the team can make a deliberate choice between investing in enterprise infrastructure (months 1–6 of meaningful engineering) versus continuing to add point features (`docs/ROADMAP.md`).

**Audience:** founders, CTO, engineering leads making the enterprise-readiness vs. product-velocity tradeoff.

**Source:** explorer audit recorded in `.claude/plans/i-am-planning-to-dreamy-puddle.md` under Part D.

---

## Reading guide

Each item is **Current state → Missing → Effort → Strategic value**.

- **Effort:** S = ≤1 week, M = 1–3 weeks, L = 1–2 months (single-engineer).
- **Tiers reflect blocking-ness for enterprise sale**, not chronological order.

---

## Tier 1 — Critical (a real enterprise customer will refuse to sign without these)

### 1. Authentication & Authorization

- **Current:** Single Gemini API key in `st.secrets` or environment. No user model. Settings dialog (`app.py:46`) lets anyone enter or clear the key.
- **Missing:** User table, password storage (bcrypt), session management, login UI, password reset, optional MFA.
- **Effort:** L.
- **Strategic:** Blocks every multi-user scenario.

### 2. Role-Based Access Control (RBAC)

- **Current:** All authenticated traffic sees all data.
- **Missing:** Role definitions (admin / underwriter / broker / read-only / approver), permissions per action (upload, edit, generate COI, delete, export, approve), customer/portfolio scope (broker A sees only their book), `@require_role` decorators on services and views.
- **Effort:** M.
- **Strategic:** SOC 2 separation-of-duties; required by most carrier procurement reviews.

### 3. Multi-Tenancy

- **Current:** Single SQLite file (`insurance_data.db`). No `tenant_id` anywhere. Shared extraction cache (`.cache/extraction_cache/`).
- **Missing:** `tenant_id` FK on every customer-scoped table (customer, policy, vehicle, driver, history, ...), row-level security middleware (server-side query filter), per-tenant cache scope, tenant lifecycle (create, suspend, delete, export).
- **Effort:** L.
- **Strategic:** Without this, every customer needs a separate deployment — a non-starter for SaaS economics.

### 4. SSO (OIDC / SAML)

- **Current:** None.
- **Missing:** Okta / AzureAD / Auth0 / Ping integration, JIT user provisioning, federated logout, group→role mapping.
- **Effort:** M (assumes a single provider library, e.g. `authlib`).
- **Strategic:** Most insurance brokerages have a corporate IdP and will not provision a separate password.

### 5. Compliance — GDPR / CCPA / retention / encryption at rest

- **Current:** No retention policy, no encryption at rest, no PII handling docs, no right-to-export / right-to-delete.
- **Missing:**
  - Retention service: auto-purge customer records older than configurable horizon (default 7 years).
  - Encryption at rest: PostgreSQL with `pgcrypto` for sensitive columns OR app-layer envelope encryption.
  - Right-to-access API: generate full data export for a customer.
  - Right-to-deletion API: cascade-delete a customer and all linked records (or anonymize if audit retention requires).
  - PII regex in `core/logger.py` to mask emails, phones, SSNs before any log write.
- **Effort:** L.
- **Strategic:** Selling to anyone in Europe, California, or any insurer concerned about regulators.

### 6. PostgreSQL migration

- **Current:** SQLite on local disk; Alembic migrations exist but not enforced; no backup story; file-lock concurrency only.
- **Missing:** Production DB URI via env var, connection pooling (`SQLAlchemy create_engine(pool_pre_ping=True)`), Alembic enforcement in CI, logical backups (`pg_dump` daily), point-in-time recovery (managed Postgres or `pg_basebackup` + WAL archive), disaster-recovery runbook.
- **Effort:** M.
- **Strategic:** SQLite is fine for the demo; not fine for production.

---

## Tier 2 — High (operational maturity)

### 7. Observability — logs, metrics, error tracking

- **Current:** Basic file logs in `core/logger.py`. No structured logging. No central error tracking. No metrics.
- **Missing:**
  - Structured JSON logs (`python-json-logger`) with `timestamp`, `level`, `service`, `user_id`, `tenant_id`, `request_id`.
  - Sentry / Rollbar for error tracking + alerting.
  - Latency / throughput / error-rate metrics (Prometheus-compatible exporter or OpenTelemetry).
  - Distributed tracing for the async extraction pipeline.
  - `/health` and `/ready` HTTP endpoints for orchestrators.
- **Effort:** M.
- **Strategic:** Incident response. Every customer eventually asks "what's your uptime SLA and how would you know?"

### 8. Deployment — Docker, Kubernetes, secrets

- **Current:** `Dockerfile` exists. No docker-compose. No k8s manifests. Secrets via `.streamlit/secrets.toml` or env vars.
- **Missing:** `docker-compose.yml` for local dev, k8s manifests (Deployment + Service + Ingress + PVC for cache/logs), Helm chart, secret management integration (Vault / AWS SM / k8s Secrets), explicit env separation (dev / staging / prod with separate DBs, API keys, URLs).
- **Effort:** L.
- **Strategic:** Reproducibility, disaster recovery, and customer-specific deployment SKUs (on-prem vs. dedicated cloud).

### 9. REST API for integrations

- **Current:** UI-only. Extraction + COI generation are not programmatically accessible.
- **Missing:**
  - FastAPI wrapper exposing the existing services:
    - `POST /policies` (upload + extract)
    - `GET /policies/{id}`
    - `PUT /policies/{id}`
    - `POST /coi` (generate ACORD 25)
    - `DELETE /policies/{id}` (soft-delete)
  - OpenAPI / Swagger docs.
  - API key authentication separate from user SSO.
  - Rate limiting + cost metering.
  - Integration examples (AMS360, Applied Epic).
- **Effort:** L–M.
- **Strategic:** Enables every integration sale (agency management systems, carrier portals, BI tools).

### 10. CI/CD pipeline

- **Current:** None visible. Manual testing assumed.
- **Missing:** GitHub Actions workflow running pytest, ruff, bandit, Docker image build on PR; staging deploy on PR merge; production deploy on tagged release; smoke tests post-deploy.
- **Effort:** S (one well-written `.github/workflows/ci.yml` covers most of it).
- **Strategic:** Release confidence; required for any team beyond one person.

### 11. Audit logging beyond PolicyHistory

- **Current:** Field-level policy edits tracked in PolicyHistory (`core/history_model.py`).
- **Missing:** Central audit log table: actor (user_id), action (verb), resource (type + id), result (success/failure), timestamp, IP address, user-agent, optional tenant_id. Immutable storage — append-only DB table OR external sink (CloudWatch, S3 + Object Lock).
- **Effort:** M.
- **Strategic:** SOC 2, HIPAA, internal forensics.

---

## Tier 3 — Medium (scale + integration depth)

### 12. Webhooks / event bus

- **Current:** Synchronous extraction + save flow.
- **Missing:** Event bus (Celery + Redis for in-cluster; SQS/Kafka for cross-system), webhook subscriptions (`policy.extracted`, `policy.expiring`, `coi.generated`), event schema with versioning, async job retries with idempotency keys.
- **Effort:** M.
- **Strategic:** Lets external systems react to events; precondition for renewal-reminder integrations.

### 13. Per-user rate limiting + quotas

- **Current:** Shared daily Gemini budget (`DEFAULT_DAILY_BUDGET` in `core/constants.py`).
- **Missing:** Redis-backed per-user / per-tenant quotas (e.g. 100 extractions/month for broker tier), per-endpoint rate limits (10 req/min for upload), cost attribution by customer for chargeback, soft-limit warnings at 80%.
- **Effort:** S–M.
- **Strategic:** SaaS billing tiers; protects against runaway costs.

### 14. Security hardening

- **Current:** Schema validation only. No file size limit. No malware scanning. No secrets rotation schedule.
- **Missing:** Upload size limit (10 MB), malware scanning (ClamAV daemon or VirusTotal API), PDF bomb detection (decompression-limit check), CSRF protection verification (Streamlit defaults), Pydantic input validators on every API endpoint, scheduled secrets rotation (annual key re-issue with overlap period).
- **Effort:** S–M.
- **Strategic:** Reduces attack surface; required for any SOC 2 audit.

### 15. E2E + load + security tests

- **Current:** 91 unit tests (post-2026-05 audit). No E2E. No load. No security scans in CI.
- **Missing:** Cypress or Playwright for UI flows (upload → review → save → COI), locust for load (1000 policies, 50 concurrent extractions), Bandit + OWASP dependency-check in CI, regression accuracy gate (`tests/test_accuracy.py` golden set in CI behind a manual gate to control cost).
- **Effort:** M.
- **Strategic:** Release confidence at scale; required to ship monthly without regressions.

---

## Sequencing — a realistic 6-month enterprise plan

If the decision is "go enterprise," the dependency order matters. Auth and multi-tenancy gate almost everything else.

**Months 1–2 — Identity and isolation foundation**
- #1 Auth, #2 RBAC, #3 Multi-tenancy. Ships together.
- #4 SSO can land in month 2 once the user model exists.

**Months 2–3 — Compliance and data**
- #5 Compliance (PII masking, right-to-export, retention).
- #6 PostgreSQL migration (rolls in parallel with #5).
- #11 Audit logging.

**Months 3–4 — Production posture**
- #7 Observability.
- #8 Deployment.
- #10 CI/CD.

**Months 4–5 — Integration surface**
- #9 REST API.
- #12 Webhooks.
- #13 Rate limiting / quotas.

**Months 5–6 — Hardening**
- #14 Security hardening.
- #15 Test depth (E2E, load, security scans in CI).

After this, the platform is genuinely enterprise-grade. **Total scope:** ~6 engineer-months, more with QA and design support, less with parallel teams.

---

## Decision framework

Before starting any of the above, answer:

1. **Are there enterprise customers asking for this?** If no, ship `docs/ROADMAP.md` items first; revisit when a deal needs unblocking.
2. **Single brokerage or many?** If you only ever sell to one customer, skip multi-tenancy (#3) and SSO (#4).
3. **What is the data-residency constraint?** If customers require regional hosting, deployment (#8) becomes a Tier-1 item.
4. **What is your compliance commitment?** SOC 2 Type II is the realistic minimum for insurance — and it forces #1, #2, #5, #7, #11, #14 to all ship before audit.

If the answer to (1) is "yes" and (4) includes SOC 2, the 6-month plan above is the path. Otherwise, lean on `docs/ROADMAP.md` and revisit this document quarterly.
