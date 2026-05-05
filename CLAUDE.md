# Insurance Document Platform

## Current Implementation Phase

- [x] Phase 1: Schema Foundation
- [x] Phase 2: Auto Cache Versioning
- [x] Phase 3: Document Taxonomy
- [x] Phase 4: COI Summary Extraction
- [x] Phase 5: Variant Tracker
- [x] Phase 6: Field Confidence Scoring
- [x] Phase 7: Premium Sanity Audit
- [x] Phase 8: Customer Resolver
- [x] Phase 9: Policy Relationship Detection
- [x] Phase 10: Endorsement Lightweight Capture
- [x] Phase 11: Carrier Knowledge Base Bidirectional
- [x] Phase 12: Golden Set Infrastructure
- [x] Phase 13: Customer UI
- [x] Phase 14: Related Policies UI
- [ ] Phase 15: Documentation Updates

## Change Blast Radius Map

When changing any of the following, ALSO update the listed downstream files. This table reflects real dependencies discovered during implementation.

| Change This                              | Must Also Update                                                |
|------------------------------------------|------------------------------------------------------------------|
| modules/extraction/schemas.py            | prompts.py, services.py, goldens, docs/PROMPTS.md, ui display    |
| modules/extraction/prompts.py            | goldens (test_accuracy.py), docs/PROMPTS.md                      |
| core/database.py (model add/modify)      | Alembic migration, services.py, ui display, docs/DATABASE.md     |
| core/database.py (relationship change)   | Late imports at file bottom (PolicyHistory pattern)              |
| modules/extraction/pipeline.py and pipeline helpers (`cache_version.py`, `gemini_transport.py`, `extraction_assembly.py`, `extraction_response.py`, `extraction_local_cache.py`, `coverage_registry_minify.py`, `extraction_types.py`) | Backing module exists, grep for refactored locations |
| views/*.py (Streamlit widgets)           | No key collisions, form vs non-form consistency                  |
| core/services.py (save flow)             | Both new-save AND update-save branches                           |
| core/document_taxonomy.py                | prompts.py classification prompt, accuracy_config.py             |
| Customer model fields                    | customer_resolver.py, ui display, services.py save flow          |

## Cache Version Hash Dependencies

The auto-cache version derives from prompt + schema hash. Files that trigger cache invalidation when modified:
- modules/extraction/prompts.py (any function)
- modules/extraction/schemas.py (any schema dict)

Hash implementation: `modules/extraction/cache_version.py` (imports the above; do not duplicate hash logic elsewhere).

This is INTENTIONAL. Old cache entries become stale and rebuild on next run.

## Architecture Constraints (Do Not Violate)

- Stack: Streamlit + SQLite (PostgreSQL planned) + SQLAlchemy + Gemini 2.5 Flash
- Coverage ontology validation logic must not change
- Existing Alembic migration files are immutable — only add new ones
- One-shot extraction architecture in pipeline.py is preserved
- Token efficiency is a hard constraint, not a nice-to-have
- Extract only what is present; null for absent fields; never invent data

## Verification Standard (Future Phases)

Before merging or closing a phase, run this checklist:

1. Run `pytest tests/ -v --ignore=tests/test_accuracy.py` — must be all green.
2. Run `streamlit run app.py` — must start without errors.
3. Click through main UI flows — must not crash.
4. If accuracy tests are relevant for the change, run with `GEMINI_API_KEY` set — note pass count (e.g. `5/5`).

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

- Customer
- CustomerEntity
- PolicyRelationship
- PolicyEndorsement
- core/document_taxonomy.py
- core/customer_resolver.py
- modules/extraction/knowledge_base.py