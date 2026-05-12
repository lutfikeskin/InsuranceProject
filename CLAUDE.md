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
| utils/text_utils.py                      | services.py `_clean_text` / `_clean_limit_text` delegations, extraction_response.py `_clean_text` / `_parse_us_address` aliases — single source of truth for null coercion |
| views/ui_utils.py                        | process_policies.py review screen badges; intended target for any future per-field confidence rendering in views/ |

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
- utils/text_utils.py (canonical `clean_text` / `clean_limit_text` / `parse_us_address`)
- views/ui_utils.py (shared widget helpers: `build_confidence_map`, `confidence_label`)

## Roadmaps

- Near-term tactical features: [`docs/ROADMAP.md`](docs/ROADMAP.md) — renewal reminders, OCR fallback, bulk export, policy diff, etc.
- Enterprise readiness (auth, multi-tenancy, SSO, compliance, observability, REST API, etc.): [`docs/ENTERPRISE_ROADMAP.md`](docs/ENTERPRISE_ROADMAP.md). **Not committed work** — decision document for the enterprise-investment vs. product-velocity tradeoff.

## Audit History

- **2026-05 — comprehensive audit pass.** Branch `chore/audit-cleanup` from `feat/gemini-caching-optimization` @ `56bde85`. Findings and deferred roadmap: [`docs/AUDIT_2026-05.md`](docs/AUDIT_2026-05.md). Baseline: [`docs/AUDIT_BASELINE.md`](docs/AUDIT_BASELINE.md). Changes were low-risk: text-helper consolidation, narrowing five over-broad exception swallows, deleting dead `_classify_policy`, F401 import cleanup, four new test modules (`test_coi_generator`, `test_extraction_local_cache`, `test_variant_tracker`, `test_coverage_backfill` — 59 new tests), and six UI polish edits (confidence legend, sortable customer table, dialog discard control, API-key clear control, toast wording). Deferred to follow-up branches: `core/services.py` / `views/process_policies.py` / `modules/extraction/pipeline.py` splits, and `ProductRegistry` / per-product extraction modularity (skipped because no new product types are on the roadmap).
- **2026-05 — audit follow-up (organization + roadmap).** Continuation on the same branch. Verified the prior audit's "dead file" candidates — `modules/coi/utils.py` and `scripts/check_models.py` are both live (false positives). Real cleanup: removed two stray root-level PDFs, deleted stale `CHAT_HANDOFF.md`, untracked `test_filled_coi.pdf` (generator output) and `logs/app.log`, consolidated `.gitignore` duplicates, moved the standalone React `education-site/` under `tools/`. Wrote the two roadmap docs linked above. Zero behavior changes.