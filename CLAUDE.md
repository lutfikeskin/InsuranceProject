# Insurance Document Platform

## Change Blast Radius Map

When changing any of the following, ALSO update the listed downstream files. This table reflects real dependencies discovered during implementation.

| Change This                              | Must Also Update                                                |
|------------------------------------------|------------------------------------------------------------------|
| modules/extraction/schemas.py            | prompts.py, services.py, goldens, docs/PROMPTS.md, ui display    |
| modules/extraction/prompts.py            | goldens (test_accuracy.py), docs/PROMPTS.md                      |
| core/database.py (model add/modify)      | Alembic migration, services.py, ui display, docs/DATABASE.md     |
| core/database.py (relationship change)   | Late imports at file bottom (PolicyHistory pattern)              |
| modules/extraction/pipeline.py and pipeline helpers (`cache_version.py`, `gemini_transport.py`, `extraction_assembly.py`, `extraction_response.py`, `extraction_local_cache.py`, `extraction_types.py`, `coverage_registry_minify.py`, `coverage_backfill.py`, `pdf_ops.py`, `auditor.py`) | Backing module exists, grep for refactored locations |
| views/*.py (Streamlit widgets)           | No key collisions, form vs non-form consistency                  |
| core/services.py (save flow)             | Both new-save AND update-save branches                           |
| core/document_taxonomy.py                | prompts.py classification prompt, accuracy_config.py             |
| Customer model fields                    | customer_resolver.py, ui display, services.py save flow          |
| core/coverage_ontology.py                | coverage_normalization.py, schemas.py, services.py validation    |
| core/history_model.py                    | history_service.py, services.py save flow, Alembic migration     |

## Cache Version Hash Dependencies

The auto-cache version derives from prompt + schema hash. Files that trigger cache invalidation when modified:
- modules/extraction/prompts.py (any function)
- modules/extraction/schemas.py (any schema dict)

Hash implementation: `modules/extraction/cache_version.py` (imports the above; do not duplicate hash logic elsewhere).

This is INTENTIONAL. Old cache entries become stale and rebuild on next run.

## Architecture Constraints (Do Not Violate)

- Stack: Streamlit + SQLite (PostgreSQL planned) + SQLAlchemy + Gemini 3.1 Flash-Lite (see modules/extraction/gemini_transport.py)
- Coverage ontology validation logic must not change
- Existing Alembic migration files are immutable — only add new ones
- One-shot extraction architecture in pipeline.py is preserved
- Token efficiency is a hard constraint, not a nice-to-have
- Extract only what is present; null for absent fields; never invent data

## Local Run

- Entry point: `streamlit run app.py`
- Required env: `GEMINI_API_KEY` (read via `os.getenv` or `st.secrets`)
- Streamlit config: `.streamlit/config.toml`
- Deps: `pip install -r requirements.txt` (no pyproject.toml)

## Verification Standard (Future Phases)

Before merging or closing a phase, run this checklist:

1. Run `pytest tests/ -v --ignore=tests/test_accuracy.py` — must be all green.
2. Run `streamlit run app.py` — must start without errors.
3. Click through main UI flows — must not crash.
4. If accuracy tests are relevant for the change, run with `GEMINI_API_KEY` set — note pass count (e.g. `5/5`).
5. If you changed user-visible behavior or schemas, update the matching file under `docs/` (ARCHITECTURE, DATABASE_SCHEMA, PROMPTS, EXTRACTION_PIPELINE, etc.).

## Key Design Decisions

- Personal name is always the customer anchor (not business name)
- Document type is classified before policy type
- Variant tracker composite key: fingerprint + document_type + policy_type
- Customer resolution: confirmed = auto-link, suggested = human review, none = create new
- Cache version is auto-derived from prompt+schema hash
- COI/Memorandum extraction includes vehicles/drivers when present; absent fields must stay null/empty
- Field confidence is per-field, not policy-level
- Goldens organized by carrier/document_type with `_meta` routing

## Active Modules

- Customer, CustomerEntity, PolicyRelationship, PolicyEndorsement (database.py models)
- PolicyHistory (core/history_model.py + core/history_service.py)
- core/document_taxonomy.py
- core/customer_resolver.py
- core/coverage_ontology.py + core/coverage_normalization.py
- core/variant_tracker.py
- core/duplicate_detection.py
- modules/extraction/knowledge_base.py
- modules/extraction/auditor.py (premium sanity / QA)
- modules/extraction/coverage_backfill.py (backfill safety net)