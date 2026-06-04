# Insurance Document Platform

Agent context for Cursor. **Active development branch:** `feat/batch-upload-ux` (batch upload UX, fallback extraction, HTMX/Jinja/Flask web UI). Keep aligned with [`CLAUDE.md`](CLAUDE.md) when blast-radius dependencies or feature history change. Phase checklists: [`.cursor/rules/insurance-document-platform-priority.mdc`](.cursor/rules/insurance-document-platform-priority.mdc).

**Primary UI target:** `webapp/` (Flask + Jinja + HTMX). Reuse `core/` and `modules/` from there. Legacy Streamlit (`app.py`, `views/`) is not the main development surface in this repo; the internal COI Streamlit app lives in `coi-app-tni`.

**Python:** Use **3.10+** locally (`python3` on macOS may be 3.9 and will crash on `dict | None` type hints). Dockerfile uses 3.11. Example: `/opt/homebrew/bin/python3.10`.

**Repo assets:** Sample policy PDFs are not tracked in git (`assets/` holds only shared static files such as `style.css`). Use local PDFs or golden fixtures under `tests/` for manual and accuracy runs.

## Repo Split

- `/Users/lutfikeskin/Downloads/coi-app-tni` is the stable internal Streamlit COI app repo. It was published separately from the `feat/gemini-caching-optimization` baseline for company use and Streamlit hosting.
- `/Users/lutfikeskin/Downloads/InsuranceProject` remains the active product-development repo. Build batch upload, extraction, and future HTMX/Jinja frontend work here, primarily from `feat/batch-upload-ux`.
- Do not automatically merge development branches into `coi-app-tni`. Port only selected production fixes that the internal COI app needs.
- `feat/gemini-caching-optimization` is now a deployment baseline/reference branch, not the default place for new product work.

## Change Blast Radius Map

When changing any of the following, ALSO update the listed downstream files. This table reflects real dependencies discovered during implementation.

| Change This                              | Must Also Update                                                |
|------------------------------------------|------------------------------------------------------------------|
| modules/extraction/schemas.py            | prompts.py, services.py, goldens, docs/PROMPTS.md, ui display    |
| modules/extraction/prompts.py            | goldens (test_accuracy.py), docs/PROMPTS.md                      |
| core/database.py (model add/modify)      | Alembic migration, services.py, ui display, docs/DATABASE.md     |
| core/database.py (relationship change)   | Late imports at file bottom (PolicyHistory pattern)              |
| modules/extraction/pipeline.py and pipeline helpers (`cache_version.py`, `gemini_transport.py`, `extraction_assembly.py`, `extraction_response.py`, `extraction_local_cache.py`, `extraction_types.py`, `coverage_registry_minify.py`, `pdf_ops.py`) | Grep for call sites; `gemini_transport.py` ties to `UsageService` and extraction cache behavior |
| views/*.py (Streamlit widgets)           | No key collisions, form vs non-form consistency                  |
| core/services.py (save flow)             | Both new-save AND update-save branches                           |
| core/document_taxonomy.py                | prompts.py classification prompt, accuracy_config.py             |
| Customer model fields                    | customer_resolver.py, ui display, services.py save flow          |
| core/history_model.py                    | history_service.py, services.py save flow, Alembic migration     |
| core/notification_model.py               | notification_service.py, views/renewals.py, Alembic migration `e7d8b9a0c1f2`; new methods need an entry in `KNOWN_METHODS` (notification_service.py) for spell-check warnings |
| modules/notifications/                   | views/renewals.py email-preview dialog. The `draft_renewal_email()` signature is part of the future-email-integration contract |
| core/comparison_service.py               | views/compare_policies.py (only consumer today). Couples to `HistoryService.SCALAR_FIELD_MAP` and private sig helpers |
| views/upload_queue.py                    | views/process_policies.py post-batch KPI/table/CSV summary; `tests/test_upload_queue.py` |
| `ExtractionPipeline.run(allow_non_extractable=...)` / `process_pdf` | views/process_policies.py “Try extraction anyway” flows; review banner for `forced_extraction`; bulk-save must not silently skip forced rows; `core/document_taxonomy.py` extractable groups |

## Cache Version Hash Dependencies

The auto-cache version derives from prompt + schema hash. Files that trigger cache invalidation when modified:
- modules/extraction/prompts.py (any function)
- modules/extraction/schemas.py (any schema dict)

Hash implementation: `modules/extraction/cache_version.py` (imports the above; do not duplicate hash logic elsewhere).

This is INTENTIONAL. Old cache entries become stale and rebuild on next run.

**Gemini context cache** (separate from local extraction cache): lifecycle in `modules/extraction/gemini_transport.py` (`create_cache`, budgeted `generate_content`). Local disk cache lives under `.cache/extraction_cache/` (gitignored). Forced fallback extraction skips the local extraction cache.

## Architecture Constraints (Do Not Violate)

- Stack: Streamlit + SQLite (PostgreSQL planned) + SQLAlchemy + **Gemini 3.1 Flash-Lite** for routing and extraction (`modules/extraction/gemini_transport.py`: `ROUTING_MODEL` / `EXTRACTION_MODEL`)
- Coverage ontology validation logic must not change
- Existing Alembic migration files are immutable — only add new ones
- One-shot extraction architecture in `pipeline.py` is preserved (`GeminiExtractionPipeline`)
- Token efficiency is a hard constraint, not a nice-to-have
- Extract only what is present; null for absent fields; never invent data

## Local Run

- **Webapp (preferred):** `webapp/` — scaffold TBD; run the Flask entrypoint once added (e.g. `flask --app webapp run`).
- **Legacy Streamlit (optional):** `python3.10 -m streamlit run app.py` — only if you need the old UI; requires 3.10+.
- Required env: `GEMINI_API_KEY`
- Deps: `pip install -r requirements.txt` (no pyproject.toml)

## Verification Standard

Before merging or closing work on this branch:

1. Run `pytest tests/ -v --ignore=tests/test_accuracy.py` — must be all green.
2. Run `streamlit run app.py` — must start without errors.
3. Click through main UI flows (upload/review, batch summary, fallback extraction retry, COI, database).
4. If accuracy tests are relevant, run with `GEMINI_API_KEY` set — note pass count.
5. Update matching files under `docs/` when behavior or schemas change.

## Key Design Decisions

- Personal name is always the customer anchor (not business name)
- Document type is classified before policy type
- Variant tracker composite key: fingerprint + document_type + policy_type
- Customer resolution: confirmed = auto-link, suggested = human review, none = create new
- Cache version is auto-derived from prompt+schema hash
- COI/Memorandum extraction includes vehicles/drivers when present; absent fields must stay null/empty
- Field confidence is per-field, not policy-level
- Goldens organized by carrier/document_type with `_meta` routing
- Forced / fallback extraction is user-controlled: applications, quotes, or failed parses can be retried with `allow_non_extractable=True`; results carry `forced_extraction=True` and `source_document_type` so the review UI can warn the broker.

## Active Modules (this branch)

- Customer, CustomerEntity, PolicyRelationship, PolicyEndorsement (`core/database.py`)
- PolicyHistory (`core/history_model.py` + `core/history_service.py`)
- NotificationLog (`core/notification_model.py` + `core/notification_service.py`) — renewal-contact audit trail
- `modules/notifications/` — pure renewal email draft generator; no SMTP/scheduler
- `core/comparison_service.py` + `views/compare_policies.py` — two-policy diff workflow
- `core/document_taxonomy.py`, `core/customer_resolver.py`
- `modules/extraction/knowledge_base.py`, `GeminiExtractionPipeline` + `gemini_transport.py`
- `views/process_policies.py` + `views/upload_queue.py` — batch upload, summary table/CSV, fallback retry actions
- COI workflow in `views/create_coi.py`
- `views/ui_utils.py` — shared widget helpers for confidence display/gating

## Roadmaps

- Near-term: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Enterprise: [`docs/ENTERPRISE_ROADMAP.md`](docs/ENTERPRISE_ROADMAP.md) (decision doc, not committed delivery)

## Feature History (this branch)

- **2026-05 — confidence gate.** Soft UI nudge: extracted fields below the selected confidence threshold render blank on the review form so the broker has to type them in. Save is never blocked.
- **2026-05 — renewals MVP.** New sidebar page (`views/renewals.py`) with urgency buckets, email-draft preview, and mark-contacted actions. Email sending remains deferred.
- **2026-05 — policy comparison.** New sidebar page (`views/compare_policies.py`) for side-by-side diff of two saved policies; powered by `core/comparison_service.py`.
- **2026-05 — batch upload UX.** Post-batch summary in `views/process_policies.py`: KPI strip, enhanced results table with retry hints, CSV exports. Logic in `views/upload_queue.py` (unit-tested in `tests/test_upload_queue.py`).
- **2026-05 — fallback extraction.** `ExtractionPipeline.run(allow_non_extractable=True)` forces `full_policy` for applications, quotes, and user-retried failures; tags `forced_extraction` / `source_document_type`; skips cache on forced runs. UI: “Try extraction anyway” in upload step + review warning banner; bulk-save includes forced rows instead of skipping non-extractable docs silently.
- **2026-06 — repo split.** `coi-app-tni` is a separate stable Streamlit deployment repo for the internal COI app. Keep active product development in `InsuranceProject`.

## Audit History

- **2026-05 — comprehensive audit pass.** See [`docs/AUDIT_2026-05.md`](docs/AUDIT_2026-05.md) and [`docs/AUDIT_BASELINE.md`](docs/AUDIT_BASELINE.md). Baseline branch family: `feat/gemini-caching-optimization`.
