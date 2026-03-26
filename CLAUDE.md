# CLAUDE.md — Insurance Policy Intelligence Hub v2

## What is this project?

A web application for a US-based insurance agency that processes insurance policy PDF documents, extracts structured data using LLM (Gemini/Claude), and stores it in a database. The agency works with multiple carriers whose document formats vary, but the data fields we need are universal US insurance terms.

## Core business context

- The agency primarily handles: Commercial Auto (often with Motor Truck Cargo endorsement), Personal Auto, and General Liability policies.
- ~200 documents/day, 90% are ≤5 pages.
- Multiple non-technical users will use this — clean UI is essential.
- Near-perfect extraction accuracy is the #1 goal.
- Token cost optimization matters at scale (200 docs/day).

## Architecture decisions (FINAL)

- **Backend**: FastAPI (async, Pydantic-native)
- **Frontend**: React (clean, simple — not Streamlit)
- **Database**: PostgreSQL with SQLAlchemy 2.0 + Alembic migrations
- **Job queue**: arq (Redis-backed) for async extraction jobs
- **Auth**: JWT with roles (admin, operator, viewer)
- **LLM**: Swappable provider (Gemini first, Claude planned). Abstract `LLMProvider` base class.
- **No OpenDataLoader**: Not needed for ≤5 page docs. LLM native PDF/vision is sufficient.

## Extraction pipeline design

Two-step, not single mega-call:
1. **Classify** (~500 tokens, cheap model): Determine policy_type, carrier, state
2. **Extract** (type-filtered registry, capable model): Full structured extraction with only relevant coverage codes sent in prompt
3. **Validate & Repair**: Ontology validation, cross-field consistency, optional repair call if critical fields missing

Key rules:
- `thinking_budget` must be > 0 (let the model reason about ambiguous cases)
- Classification result filters the registry — personal_auto doesn't get GL/Cargo codes
- State context and carrier hints injected into extract prompt
- Every field gets a confidence score (high/medium/low/missing)

## Core extraction philosophy

**Extract what's there. Skip what's not. Never invent.**

- If a field exists in the document → extract it accurately
- If a field doesn't exist → return null, move on
- Never flag missing data as an error — different document types contain different fields
- A GEICO Memorandum won't have premium info — that's normal, not a failure
- A declarations page won't have driver details — that's normal too
- The system extracts, it does not validate completeness or compliance

This rule overrides everything else. No validation rule, state hint, or ontology constraint should ever cause the system to invent data or flag absence as an error.

## Key Documentation

Read these docs for detailed specifications:
- `docs/ARCHITECTURE.md` — Full technical architecture, data models, implementation phases
- `docs/ONTOLOGY.md` — Complete coverage registry, validation rules, endorsement types, naming aliases
- `docs/STATE_RULES.md` — State-specific extraction hints (how UM/UIM, PIP etc. are formatted per state — NOT compliance checks)
- `docs/PROMPTS.md` — Prompt templates, token optimization tactics, testing rules
- `docs/API.md` — All API endpoints, request/response schemas, auth rules
- `docs/DEVELOPMENT.md` — Setup, conventions, testing, deployment, how to add new policy types

## Ontology & schema rules

Critical design decisions:
- **Coverage aliases in ontology, not in a separate dictionary**: Carriers use varied terminology for the same coverage (e.g., "Other Than Collision" = "Comprehensive" = "OTC" = COMP). These aliases live in the ontology and are injected into the LLM prompt — NOT used for regex/dictionary lookup. The LLM handles fuzzy matching natively; a separate normalization engine adds complexity without benefit.
- **No regex parser layer**: The LLM reads the PDF and outputs structured JSON directly. Adding a regex/dictionary parser between them creates two competing normalization systems. If the LLM maps correctly, the parser is redundant. If the LLM maps incorrectly, the parser likely can't fix it anyway.
- **UM/UIM merged family**: Many states (TX especially) treat UM/UIM as combined. New codes: `UMUIM_CSL`, `UMUIM_BI`, `UMUIM_PD`.
- **Vehicle-specific COMP/COLL**: Prompt MUST instruct "one COMP and one COLL per VIN". Validation flags COMP/COLL with null vehicle_vin.
- **Endorsement tracking**: New `Endorsement` model — form_number, title, type, affected coverage.
- **State extraction hints**: State-specific formatting patterns (e.g., TX combines UM/UIM) injected into LLM prompt to improve accuracy. NOT compliance checks — if a coverage isn't in the document, we don't flag it as "missing".
- **Summary fields are COMPUTED, not stored**: No `liability_limit` column on Policy. Computed from coverages at query time.
- **Money in cents**: All monetary values stored as integers (cents) to avoid float issues. Display layer converts to dollars.
- **No legacy columns**: Clean schema, no dual representations.

## File structure

```
insurance-hub/
├── CLAUDE.md                      ← You are here
├── docs/
│   └── ARCHITECTURE.md            ← Full roadmap & technical spec
├── backend/
│   ├── api/
│   │   ├── routes/                ← FastAPI route handlers
│   │   └── deps.py                ← Dependency injection (DB session, auth)
│   ├── core/
│   │   ├── config.py              ← Settings (env vars, API keys)
│   │   └── security.py            ← JWT auth
│   ├── models/
│   │   ├── db.py                  ← SQLAlchemy models
│   │   └── schemas.py             ← Pydantic request/response schemas
│   ├── extraction/
│   │   ├── pipeline.py            ← 2-step orchestrator
│   │   ├── prompts.py             ← Minimal, optimized prompts
│   │   ├── ontology.py            ← Coverage registry + validation
│   │   ├── state_hints.py         ← State-specific extraction hints
│   │   ├── carrier_hints.py       ← Carrier-specific extraction hints
│   │   ├── validator.py           ← Post-extraction validation
│   │   └── providers/
│   │       ├── base.py            ← Abstract LLMProvider
│   │       ├── gemini.py          ← Gemini implementation
│   │       └── claude.py          ← Claude implementation
│   ├── services/
│   │   ├── policy.py              ← Policy CRUD + business logic
│   │   ├── coi.py                 ← COI PDF generation
│   │   ├── usage.py               ← Token/cost tracking
│   │   └── export.py              ← Excel export
│   └── workers/
│       └── extraction.py          ← Background job processor
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Upload.tsx
│       │   ├── Review.tsx         ← Split view: PDF | editable form
│       │   ├── Dashboard.tsx
│       │   ├── Policies.tsx       ← Searchable table
│       │   ├── PolicyDetail.tsx
│       │   └── COI.tsx
│       └── components/
├── tests/
│   ├── golden/                    ← Real PDFs + expected outputs
│   ├── test_extraction.py
│   ├── test_ontology.py
│   └── test_api.py
├── alembic/
├── docker-compose.yml
└── requirements.txt
```

## Common pitfalls from v1 (avoid these)

1. **Don't create a separate DB engine in the pipeline** — use dependency injection from FastAPI
2. **Don't store summary fields on the Policy model** — compute from coverages
3. **Don't send the full coverage registry every call** — filter by policy_type after classification
4. **Don't use `thinking_budget: 0`** — accuracy suffers
5. **Don't mix legacy and new column names** — one representation only
6. **Don't put all services in one file** — separate by domain
7. **Premium is not a string** — store as integer cents

## Implementation phases

Phase 1 (Foundation): FastAPI scaffold, DB models, extraction pipeline, basic upload API
Phase 2 (Core UI): React app, upload, review, policy list, dashboard
Phase 3 (Quality): Expanded ontology, endorsements, state extraction hints, confidence scoring, golden tests
Phase 4 (Polish): COI generation, export, audit trail, multi-user, Docker deployment

## Commands

```bash
# Backend
cd backend && uvicorn main:app --reload

# Frontend
cd frontend && npm run dev

# Database
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests
pytest tests/ -v
pytest tests/golden/ -v  # Accuracy regression tests
```
