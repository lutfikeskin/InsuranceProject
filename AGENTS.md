# Insurance Document Platform

Agent context for Cursor. **Active branch:** `feat/gemini-caching-optimization` (Gemini context-cache + telemetry/ops work). Keep aligned with [`CLAUDE.md`](CLAUDE.md) when blast-radius dependencies or feature history change. Phase checklists: [`.cursor/rules/insurance-document-platform-priority.mdc`](.cursor/rules/insurance-document-platform-priority.mdc).

**Repo assets:** Sample policy PDFs are not tracked in git (`assets/` holds only shared static files such as `style.css`). Use local PDFs or golden fixtures under `tests/` for manual and accuracy runs.

**Other branches (not checked out):** `feat/batch-upload-ux` (post-batch upload summary, fallback extraction), `main` (renewals, policy compare, confidence gate, and related modules).

## Change Blast Radius Map

When changing any of the following, ALSO update the listed downstream files. This table reflects real dependencies discovered during implementation.

| Change This                              | Must Also Update                                                |
|------------------------------------------|------------------------------------------------------------------|
| modules/extraction/schemas.py            | prompts.py, services.py, goldens, docs/PROMPTS.md, ui display    |
| modules/extraction/prompts.py            | goldens (test_accuracy.py), docs/PROMPTS.md                      |
| core/database.py (model add/modify)      | Alembic migration, services.py, ui display, docs/DATABASE.md     |
| core/database.py (relationship change)   | Late imports at file bottom (PolicyHistory pattern)              |
| modules/extraction/pipeline.py and pipeline helpers (`cache_version.py`, `gemini_transport.py`, `extraction_assembly.py`, `extraction_response.py`, `extraction_local_cache.py`, `extraction_types.py`, `coverage_registry_minify.py`, `pdf_ops.py`) | Grep for call sites; `gemini_transport.py` also ties to `core/telemetry.py` and `UsageService` |
| views/*.py (Streamlit widgets)           | No key collisions, form vs non-form consistency                  |
| core/services.py (save flow)             | Both new-save AND update-save branches                           |
| core/document_taxonomy.py                | prompts.py classification prompt, accuracy_config.py             |
| Customer model fields                    | customer_resolver.py, ui display, services.py save flow          |
| core/telemetry.py / `AppEvent` model     | `views/telemetry.py`, `app.py` settings modal retention controls, `modules/extraction/gemini_transport.py` `log_event` payloads, `tests/test_telemetry.py` |
| core/backup_bundle.py / core/db_import.py | `views/settings_backup.py`, `app.py` unified backup section, `tests/test_db_import.py` |
| modules/coi/holders.py                   | `views/create_coi.py`, `data/coi_holders.json`, `tests/test_coi_holders.py` |

## Cache Version Hash Dependencies

The auto-cache version derives from prompt + schema hash. Files that trigger cache invalidation when modified:
- modules/extraction/prompts.py (any function)
- modules/extraction/schemas.py (any schema dict)

Hash implementation: `modules/extraction/cache_version.py` (imports the above; do not duplicate hash logic elsewhere).

This is INTENTIONAL. Old cache entries become stale and rebuild on next run.

**Gemini context cache** (separate from local extraction cache): lifecycle in `modules/extraction/gemini_transport.py` (`create_cache`, budgeted `generate_content`). Local disk cache lives under `.cache/extraction_cache/` (gitignored).

## Architecture Constraints (Do Not Violate)

- Stack: Streamlit + SQLite (PostgreSQL planned) + SQLAlchemy + **Gemini 3.1 Flash-Lite** for routing and extraction (`modules/extraction/gemini_transport.py`: `ROUTING_MODEL` / `EXTRACTION_MODEL`)
- Coverage ontology validation logic must not change
- Existing Alembic migration files are immutable — only add new ones
- One-shot extraction architecture in `pipeline.py` is preserved (`GeminiExtractionPipeline`)
- Token efficiency is a hard constraint, not a nice-to-have
- Extract only what is present; null for absent fields; never invent data

## Local Run

- Entry point: `streamlit run app.py`
- Required env: `GEMINI_API_KEY` (read via `os.getenv` or `st.secrets`)
- Streamlit config: `.streamlit/config.toml`
- Deps: `pip install -r requirements.txt` (no pyproject.toml)

## Verification Standard

Before merging or closing work on this branch:

1. Run `pytest tests/ -v --ignore=tests/test_accuracy.py` — must be all green.
2. Run `streamlit run app.py` — must start without errors.
3. Click through main UI flows (upload/review, COI, database, telemetry page, backup export/import in settings).
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
- Telemetry events are append-only audit signals (`core/telemetry.py`); admin can purge by retention days from the settings modal

## Active Modules (this branch)

- Customer, CustomerEntity, PolicyRelationship, PolicyEndorsement (`core/database.py`)
- `core/document_taxonomy.py`, `core/customer_resolver.py`
- `modules/extraction/knowledge_base.py`, `GeminiExtractionPipeline` + `gemini_transport.py`
- `core/telemetry.py` + `views/telemetry.py` — usage/events dashboard
- `core/backup_bundle.py`, `core/db_import.py`, `views/settings_backup.py` — unified export/import
- `modules/coi/holders.py` + COI workflow in `views/create_coi.py`
- `utils/vehicle_utils.py` — COI vehicle description helpers

## Roadmaps

- Near-term: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Enterprise: [`docs/ENTERPRISE_ROADMAP.md`](docs/ENTERPRISE_ROADMAP.md) (decision doc, not committed delivery)

## Feature History (this branch)

- **2026-05 — Gemini caching optimization.** Branch `feat/gemini-caching-optimization`. Context-cache lifecycle and budgeted Gemini calls in `gemini_transport.py`; pipeline wired through `GeminiTransport`; local extraction cache scoped and gitignored.
- **2026-05 — Telemetry.** `AppEvent` table (migration `a1b2c3d4e5f7`), `TelemetryService`, admin telemetry page, correlation IDs on extraction paths.
- **2026-05 — Ops backup.** Unified app backup bundle + DB import/export in settings (`backup_bundle`, `db_import`, `settings_backup`).
- **2026-05 — COI workflow.** Certificate holder registry (`modules/coi/holders.py`), vehicle model in descriptions, holder ADDL INSD defaults, audit plan doc `COI_CREATION_AUDIT_PLAN.md`.

## Audit History

- **2026-05 — comprehensive audit pass.** See [`docs/AUDIT_2026-05.md`](docs/AUDIT_2026-05.md) and [`docs/AUDIT_BASELINE.md`](docs/AUDIT_BASELINE.md). Baseline branch family: `feat/gemini-caching-optimization`.
