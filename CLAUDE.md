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
- [ ] Phase 9: Policy Relationship Detection
- [ ] Phase 10: Endorsement Lightweight Capture
- [ ] Phase 11: Carrier Knowledge Base Bidirectional
- [ ] Phase 12: Golden Set Infrastructure
- [ ] Phase 13: Customer UI
- [ ] Phase 14: Related Policies UI
- [ ] Phase 15: Documentation Updates

## Architecture Constraints (Do Not Violate)

- Stack: Streamlit + SQLite (PostgreSQL planned) + SQLAlchemy + Gemini 2.5 Flash
- Coverage ontology validation logic must not change
- Existing Alembic migration files are immutable — only add new ones
- One-shot extraction architecture in pipeline.py is preserved
- Token efficiency is a hard constraint, not a nice-to-have
- Extract only what is present; null for absent fields; never invent data

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
- core/document_taxonomy.py
- core/customer_resolver.py