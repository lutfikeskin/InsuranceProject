# Insurance Policy Intelligence Hub — v2 Architecture & Roadmap

## Executive Summary

Complete rewrite of the insurance document extraction platform. Three core policy types: Commercial Auto, Personal Auto, General Liability. Designed for ~200 documents/day, multi-user, near-perfect extraction accuracy.

---

## 1. Ontology & Schema Overhaul

### 1.1 Current Problems

The existing ontology has 21 coverage codes. This is insufficient and causes three specific failures:

**UM/UIM confusion**: The current schema treats UM and UIM as entirely separate families (`uninsured_motorist` vs `underinsured_motorist`). In reality, many states and carriers combine them as "UM/UIM" with a single limit. The schema forces the LLM to split what the document presents as one line item, leading to duplications or missed entries. Additionally, states like Texas have "UMUIM" as a single statutory coverage, while Florida separates them completely. The ontology doesn't account for this state-level variation.

**Deductible schedule (vehicle-specific)**: The Coverage model has a single `deductible` integer field. But real policies have different COMP/COLL deductibles per vehicle. While the schema supports `vehicle_vin` linking, the prompt doesn't strongly guide the LLM to create separate COMP/COLL entries per VIN — it tends to extract one COMP and one COLL for the whole policy.

**Endorsement blindness**: The current system has zero endorsement tracking. Endorsements modify coverage — "Additional Insured", "Waiver of Subrogation", "Hired Auto Physical Damage" — and they're critical for COI generation. The system extracts from endorsement pages but doesn't know *what* the endorsement is.

### 1.2 Expanded Coverage Registry

```
COVERAGE FAMILIES (v2):
├── auto_liability
│   ├── AUTO_LIAB_CSL          (existing)
│   ├── AUTO_LIAB_BI           (existing)
│   ├── AUTO_LIAB_PD           (existing)
│   ├── HIRED_AUTO              (existing)
│   ├── NON_OWNED_AUTO          (existing)
│   ├── HIRED_AUTO_PD           (NEW — physical damage for hired autos)
│   └── TRAILER_INTERCHANGE     (NEW — common in trucking)
│
├── uninsured_underinsured       ← MERGED FAMILY (was two separate)
│   ├── UM_BI                   (existing)
│   ├── UM_CSL                  (existing)
│   ├── UM_PD                   (existing)
│   ├── UIM_BI                  (existing)
│   ├── UIM_CSL                 (existing)
│   ├── UMUIM_CSL               (NEW — combined UM/UIM single limit)
│   ├── UMUIM_BI                (NEW — combined UM/UIM split)
│   └── UMUIM_PD                (NEW — combined UM/UIM property damage)
│
├── physical_damage
│   ├── COMP                    (existing — now MUST link to vehicle)
│   ├── COLL                    (existing — now MUST link to vehicle)
│   ├── RENTAL                  (existing)
│   ├── TOWING                  (existing)
│   ├── GAP                     (NEW)
│   ├── FULL_SAFETY_GLASS       (NEW)
│   └── LOAN_LEASE_COVERAGE     (NEW)
│
├── medical_payments
│   └── MED_PAY                 (existing)
│
├── pip
│   └── PIP                     (existing)
│
├── general_liability
│   ├── GL_OCCURRENCE           (existing)
│   ├── GL_AGGREGATE            (existing)
│   ├── GL_PRODUCTS_COMP_OPS    (existing)
│   ├── GL_PERSONAL_ADV_INJURY  (NEW)
│   ├── GL_DAMAGE_RENTED_PREM   (NEW)
│   ├── GL_MEDICAL_EXPENSE      (NEW)
│   └── GL_EMPLOYEE_BENEFITS    (NEW)
│
├── cargo
│   ├── CARGO_LEGAL_LIAB        (existing)
│   ├── CARGO_BROAD_FORM        (NEW)
│   └── CARGO_REEFER            (NEW — refrigeration breakdown)
│
└── umbrella_excess              (NEW FAMILY)
    ├── UMBRELLA_OCCURRENCE     (NEW)
    ├── UMBRELLA_AGGREGATE      (NEW)
    └── EXCESS_LIABILITY        (NEW)
```

### 1.3 Endorsement Tracking (New Model)

```python
class Endorsement:
    id: int
    policy_id: FK
    form_number: str          # e.g., "CA 20 48", "CG 20 10"
    title: str                # e.g., "Designated Insured"
    endorsement_type: enum    # additional_insured, waiver_of_sub, 
                              # coverage_modification, exclusion, 
                              # coverage_extension
    effective_date: date | None
    description: str | None   # Free-text summary of what it does
    affects_coverage: str | None  # Which coverage_code it modifies
```

Key endorsement types to extract:
- Additional Insured (CA 20 48, CG 20 10, CG 20 26, etc.)
- Waiver of Subrogation (CG 24 04)
- Primary & Non-Contributory (CG 20 01)
- Hired Auto Physical Damage (CA 99 17 or similar)
- MCS-90 (federal filing for trucking)
- Drive Other Car (CA 99 10)

### 1.4 State Extraction Hints

Some states format coverages differently. These hints are injected into the extraction prompt to help the LLM pick the correct coverage code — NOT for compliance validation.

```python
STATE_EXTRACTION_HINTS = {
    "TX": "UM/UIM is typically combined as a single line item. Use UMUIM_* codes unless clearly separated.",
    "FL": "UM and UIM are typically listed separately. PIP usually appears on declarations page.",
    "NY": "UIM may be labeled 'SUM' (Supplementary Uninsured/Underinsured Motorist). Map to UIM_* codes.",
    "OH": "UM/UIM is typically combined. Use UMUIM_* codes unless clearly separated.",
}
```

See `docs/STATE_RULES.md` for full list. These are purely for extraction accuracy — if a coverage isn't in the document, we don't extract it and we don't flag it as "missing".

---

## 2. Extraction Pipeline v2

### 2.1 Two-Step Architecture

```
PDF Upload
    │
    ▼
┌─────────────────────────────────────┐
│  STEP 1: CLASSIFY (cheap, fast)     │
│  Input:  PDF + short prompt         │
│  Output: policy_type, carrier_name, │
│          state, page_count          │
│  Cost:   ~500 input tokens          │
│  Model:  Flash/Haiku (cheapest)     │
└─────────────────────────────────────┘
    │
    │  Now we know the type → filter registry
    │  Now we know the state → add state rules
    │  Now we know the carrier → add carrier hints
    ▼
┌─────────────────────────────────────┐
│  STEP 2: EXTRACT (the real work)    │
│  Input:  PDF + filtered prompt      │
│  Output: Full structured data       │
│  Cost:   ~2-4K input tokens (prompt)│
│          + PDF token cost           │
│  Model:  Flash/Sonnet (capable)     │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STEP 3: VALIDATE & REPAIR         │
│  - Ontology validation (instant)    │
│  - Cross-field consistency          │
│  - If critical failure → retry with │
│    surgical prompt (1 extra call)   │
└─────────────────────────────────────┘
```

### 2.2 Token Optimization Details

**Current waste in single-call approach:**
- Full registry (21 codes × ~20 tokens each) = ~420 tokens EVERY call
- Classification instructions repeated = ~150 tokens wasted
- Schema definition overhead = ~500 tokens (unavoidable but only once)

**v2 savings per document:**
| Step | Input Tokens | Output Tokens | Notes |
|------|-------------|---------------|-------|
| Classify | ~500 | ~50 | Minimal prompt, small schema |
| Extract (personal_auto) | ~1,200 | ~800 | 14 codes, no GL/Cargo |
| Extract (commercial_auto) | ~1,400 | ~1,200 | 17 codes + cargo |
| Extract (GL) | ~800 | ~400 | Only 7 codes |
| Repair (if needed, ~10%) | ~600 | ~200 | Surgical prompt |

**Net effect**: Similar or slightly more total tokens per document, but significantly better accuracy because:
1. The LLM isn't confused by irrelevant coverage codes
2. State-specific hints reduce hallucination
3. Carrier-specific hints ("Progressive puts UM/UIM on page 3") improve recall
4. `thinking_budget` > 0 allows the model to reason about ambiguous cases

### 2.3 Confidence Scoring

Every extracted field gets a confidence indicator:

```python
class FieldConfidence(str, Enum):
    HIGH = "high"       # Clear, unambiguous value found
    MEDIUM = "medium"   # Value found but formatting/context ambiguous
    LOW = "low"         # Value partially visible or hard to read

class ExtractionResult:
    policy: PolicyData
    coverages: list[CoverageData]
    vehicles: list[VehicleData]
    drivers: list[DriverData]
    endorsements: list[EndorsementData]
    
    confidence: dict[str, FieldConfidence]  # field_name → confidence
    # Only for fields that WERE extracted. Null fields aren't tracked.
    # e.g., {"policy_number": "high", "premium": "medium", "naic_number": "low"}
    
    flags: list[str]  # Data quality notes (not completeness warnings)
    # e.g., ["COMP deductible differs across vehicles — verify schedule",
    #        "Policy number format unusual — verify manually"]
```

The review UI highlights extracted fields by confidence: green for high, yellow for medium, red for low. Null fields are simply empty — not flagged as errors.

### 2.4 LLM Provider Abstraction

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    async def classify(self, pdf_bytes: bytes) -> ClassificationResult:
        """Cheap, fast classification call."""
        pass
    
    @abstractmethod
    async def extract(
        self, 
        pdf_bytes: bytes, 
        policy_type: str,
        registry_json: str,
        carrier_hints: str,
        state_hint: str
    ) -> RawExtractionResult:
        """Full extraction with type-filtered context."""
        pass
    
    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Returns estimated cost in USD."""
        pass

class GeminiProvider(LLMProvider):
    # Uses google-genai SDK, File API for PDF upload
    # Supports structured output via response_schema
    pass

class ClaudeProvider(LLMProvider):
    # Uses anthropic SDK, base64 PDF in message
    # Supports tool_use for structured output
    pass
```

---

## 3. Data Model (Clean, No Legacy)

### 3.1 Core Models

```python
# All monetary values are integers (cents) to avoid float precision issues
# All dates are proper Date types
# No legacy columns, no dual representations

class Policy:
    id: int (PK)
    
    # Identity
    policy_number: str (unique, not null)
    policy_type: enum  # commercial_auto, personal_auto, general_liability
    account_type: str  # "Commercial" or "Personal" (derived from type)
    
    # Carrier
    carrier_name: str
    naic_number: str | None
    
    # Dates
    effective_date: date
    expiration_date: date
    
    # Insured
    insured_name: str
    business_name: str | None
    insured_address: str
    insured_city: str
    insured_state: str   # 2-letter code
    insured_zip: str
    
    # Financials
    premium_cents: int | None   # Store in cents, display as dollars
    
    # Classification metadata
    classification_confidence: str
    extraction_source: str      # "gemini-2.5-flash", "claude-sonnet-4"
    
    # Status
    status: enum  # active, expired, cancelled, pending_review
    
    # Audit
    created_at: datetime
    updated_at: datetime
    created_by: int (FK → users.id)
    
    # Relationships
    vehicles: list[Vehicle]
    drivers: list[Driver]
    coverages: list[Coverage]
    endorsements: list[Endorsement]
    additional_interests: list[AdditionalInterest]
    documents: list[Document]    # Link to source PDFs
    audit_log: list[AuditEntry]


class Coverage:
    id: int (PK)
    policy_id: int (FK)
    vehicle_id: int | None (FK)    # For vehicle-specific coverages
    
    # Ontology
    coverage_code: str              # Must exist in COVERAGE_REGISTRY
    family: str                     # Denormalized from registry for queries
    limit_structure: str            # csl, split, per_occurrence, etc.
    
    # Limits (only the relevant fields will be populated)
    per_person_cents: int | None
    per_accident_cents: int | None
    per_occurrence_cents: int | None
    combined_single_limit_cents: int | None
    aggregate_cents: int | None
    
    # Deductible
    deductible_cents: int | None
    
    # Premium (per coverage, if available)
    premium_cents: int | None
    
    # Extraction confidence
    confidence: str  # high, medium, low


class Vehicle:
    id: int (PK)
    policy_id: int (FK)
    
    vin: str
    year: int | None
    make: str | None
    model: str | None
    gvw: int | None
    vehicle_type: str | None    # Tractor, Straight Truck, Cargo Van, etc.
    
    # Vehicle-level financial
    stated_amount_cents: int | None   # For stated amount policies
    
    # Relationships
    coverages: list[Coverage]    # Vehicle-specific coverages


class Driver:
    id: int (PK)
    policy_id: int (FK)
    
    full_name: str
    license_number: str | None
    license_state: str | None    # NEW — 2-letter code
    date_of_birth: date | None   # NEW — sometimes on declarations
    is_excluded: bool


class Document:
    """Links source PDFs to policies for reference and re-extraction."""
    id: int (PK)
    policy_id: int | None (FK)  # Null until extraction completes
    
    filename: str
    file_hash: str              # SHA-256 for dedup
    file_size_bytes: int
    page_count: int
    storage_path: str           # Where the file is stored
    
    uploaded_at: datetime
    uploaded_by: int (FK → users.id)
    extraction_status: enum     # pending, processing, completed, failed
    
    # Extraction metadata
    extraction_duration_ms: int | None
    token_usage: JSON | None    # {input: N, output: N, cost: N}


class AuditEntry:
    """Tracks every change to a policy for compliance."""
    id: int (PK)
    policy_id: int (FK)
    
    action: enum       # created, updated, field_edited, approved, deleted
    field_name: str | None
    old_value: str | None
    new_value: str | None
    
    performed_by: int (FK → users.id)
    performed_at: datetime
    source: str        # "extraction", "manual_edit", "re-extraction"


class User:
    id: int (PK)
    email: str (unique)
    name: str
    role: enum       # admin, operator, viewer
    is_active: bool
    created_at: datetime
```

### 3.2 Summary Views (Computed, Not Stored)

The old design stored summary fields on the Policy model (`liability_limit`, `cargo_limit`, `um_uim_limit`, etc.). This creates data duplication and sync issues.

In v2, summaries are **computed at query time** from the coverages table:

```python
class PolicySummary:
    """Computed from related coverages, never stored."""
    
    liability_display: str       # "1,000,000 CSL" or "100/300/100"
    um_uim_display: str | None   # "100/300" or "1,000,000 CSL"
    gl_display: str | None       # "1,000,000 Occ / 2,000,000 Agg"
    cargo_display: str | None    # "$100,000 / $1,000 Ded"
    
    has_comp: bool
    has_coll: bool
    comp_deductible_display: str | None  # "500" or "Varies by vehicle"
    coll_deductible_display: str | None
    
    vehicle_count: int
    driver_count: int
    endorsement_count: int
```

---

## 4. Backend Architecture

### 4.1 Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | FastAPI | Async, auto-docs, Pydantic native |
| Database | PostgreSQL | Multi-user, proper constraints, JSON support |
| ORM | SQLAlchemy 2.0 | Async support, mature |
| Migrations | Alembic | Already familiar |
| Job Queue | `arq` (Redis-backed) | Lightweight async queue for extraction jobs |
| Auth | JWT + simple role system | Admin, Operator, Viewer |
| File Storage | Local disk (S3-ready interface) | Start simple, swap later |
| PDF Processing | pypdf + LLM native vision | No OpenDataLoader needed for ≤5pg docs |

### 4.2 API Routes

```
POST   /api/auth/login
POST   /api/auth/register            (admin only)

POST   /api/extraction/upload        → returns job_id
GET    /api/extraction/status/{id}   → job progress via SSE/WebSocket
POST   /api/extraction/approve/{id}  → saves to database
POST   /api/extraction/retry/{id}    → re-run extraction

GET    /api/policies                 → list with filters, pagination
GET    /api/policies/{id}            → full policy with relations
PUT    /api/policies/{id}            → update (creates audit entry)
DELETE /api/policies/{id}            → soft delete

GET    /api/policies/{id}/summary    → computed summary view
GET    /api/policies/{id}/documents  → linked source PDFs
GET    /api/policies/{id}/audit      → change history

POST   /api/coi/generate             → returns PDF bytes
GET    /api/coi/holders               → saved certificate holders

GET    /api/dashboard/metrics
GET    /api/dashboard/expiring
GET    /api/dashboard/recent

POST   /api/chat/query               → natural language → SQL
GET    /api/export/excel              → full database export

GET    /api/usage/today               → token/cost metrics
GET    /api/usage/history             → daily/weekly trends
```

### 4.3 Extraction Job Flow

```
User uploads PDF(s)
    │
    ▼
API creates Document record(s) + Job(s) in queue
    │ Returns job_id(s) immediately
    │
    ▼
Background Worker picks up job
    │
    ├─ 1. Hash check (duplicate PDF?)
    ├─ 2. Cache check (already extracted?)
    ├─ 3. Classify (LLM call #1)
    ├─ 4. Extract (LLM call #2)
    ├─ 5. Validate + optional repair (LLM call #3 if needed)
    ├─ 6. Save to "pending_review" state
    │
    ▼
WebSocket pushes progress to frontend
    │
    ▼
User reviews in side-by-side view (PDF | Extracted Data)
    │
    ├─ Can edit any field (creates audit entry)
    ├─ Can flag confidence issues
    │
    ▼
User clicks "Approve" → saves to database as "active"
```

---

## 5. Frontend Design

### 5.1 Pages

| Page | Purpose | Key Features |
|------|---------|--------------|
| **Login** | Authentication | Simple email/password |
| **Dashboard** | Overview | Policy count, premium total, expiring soon, recent activity |
| **Upload** | Document ingestion | Drag-drop zone, batch upload, real-time progress per file |
| **Review** | Post-extraction QA | Split view: PDF on left, editable form on right. Confidence highlighting. |
| **Policies** | Database browser | Sortable/filterable table, search, status badges |
| **Policy Detail** | Single policy view | All data, coverages table, vehicles, drivers, endorsements, audit log |
| **COI Generator** | Certificate creation | Policy selector, holder input, auto-filled preview, PDF download |
| **Settings** | Admin panel | API keys, users, usage metrics, carrier hints management |

### 5.2 Review Page (Most Critical UX)

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back to Upload            Policy #PA-12345          Approve  │
├────────────────────────────┬─────────────────────────────────────┤
│                            │  Classification: Commercial Auto   │
│                            │  Confidence: HIGH ●                │
│     PDF Viewer             │                                    │
│     (embedded,             │  ── Policy Details ──────────────  │
│      scrollable,           │  Carrier:    [Progressive      ]   │
│      page navigation)      │  Policy #:   [PA-12345         ] ● │
│                            │  Eff Date:   [2024-01-15       ] ● │
│                            │  Exp Date:   [2025-01-15       ] ● │
│                            │  Premium:    [$4,200.00        ] ◐ │
│                            │                                    │
│                            │  ── Coverages ──────────────────   │
│                            │  ┌─────────┬──────────┬────────┐  │
│                            │  │ Code    │ Limit    │ Ded    │  │
│                            │  ├─────────┼──────────┼────────┤  │
│                            │  │ CSL   ● │ 1,000K   │ —      │  │
│                            │  │ COMP  ◐ │ —        │ 500    │  │
│                            │  │ COLL  ◐ │ —        │ 1,000  │  │
│                            │  └─────────┴──────────┴────────┘  │
│                            │                                    │
│                            │  ● = high   ◐ = medium  ○ = low   │
└────────────────────────────┴─────────────────────────────────────┘
```

---

## 6. Production Readiness Checklist

### 6.1 Must-Have for Launch

- [ ] **Idempotent extraction**: Same PDF → same result. File hash-based dedup.
- [ ] **Audit trail**: Every field edit tracked with who/when/what.
- [ ] **Error recovery**: Failed extraction doesn't lose the uploaded file.
- [ ] **Rate limiting**: Per-user and global API budget enforcement.
- [ ] **Input validation**: Max file size (25MB), PDF-only, page limit (50).
- [ ] **HTTPS**: TLS everywhere, even internal.
- [ ] **Backup**: Automated daily DB backup + file storage.
- [ ] **Logging**: Structured JSON logs, correlation IDs per request.

### 6.2 Quality Assurance

- [ ] **Golden test suite**: 30-50 real policies with expected outputs.
         Run on every code change. Accuracy regression = blocked deploy.
- [ ] **Per-field accuracy tracking**: Not just "did extraction succeed" 
         but "was policy_number correct? was premium correct?"
- [ ] **A/B testing framework**: Compare Gemini vs Claude on same docs.
- [ ] **Edge case collection**: Maintain a list of documents that 
         historically caused failures. Auto-include in test suite.

### 6.3 Future-Proofing

- [ ] **Schema versioning**: Ontology changes tracked in migrations.
- [ ] **Plugin architecture for new policy types**: Adding Workers' Comp 
         should require only: new registry entries + new state rules + 
         new prompt template. No pipeline code changes.
- [ ] **Webhook support**: Notify external systems when policy saved/updated.
- [ ] **API-first design**: Everything the UI does, an API client can do.
         Enables future integrations with AMS (Agency Management Systems).
- [ ] **Multi-tenant ready**: User → Organization → Policies. 
         Not needed now but schema should not prevent it.

---

## 7. Implementation Phases

### Phase 1: Foundation (Week 1-2)
- FastAPI project scaffold with auth
- PostgreSQL + SQLAlchemy models (clean, v2 schema)
- Alembic migrations
- Extraction pipeline: classify → extract → validate
- LLM provider abstraction (Gemini first)
- Basic file upload API + background job

### Phase 2: Core UI (Week 3-4)
- React project with routing
- Upload page with drag-drop + progress
- Review page (split PDF viewer + editable form)
- Policy list with search/filter
- Dashboard with metrics

### Phase 3: Quality (Week 5-6)
- Expanded ontology (all coverage codes listed above)
- Endorsement extraction
- State-aware UM/UIM validation
- Confidence scoring in extraction prompt
- Golden test suite (start with 20 policies)
- Carrier knowledge base expansion

### Phase 4: Polish (Week 7-8)
- COI generation (port from v1)
- Excel export
- Audit trail UI
- Usage monitoring dashboard
- Multi-user testing
- Docker compose for deployment
- Documentation

### Phase 5: Optimization (Ongoing)
- Claude provider implementation + comparison
- Prompt tuning based on accuracy metrics
- Cost optimization (caching, batch strategies)
- Workers' Comp / BOP support (new ontology entries)
- AMS integration research
