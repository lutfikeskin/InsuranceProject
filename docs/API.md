# API Design Reference

All endpoints, request/response shapes, and auth rules.

---

## Authentication

JWT-based. Token in `Authorization: Bearer <token>` header.

### Roles

| Role | Can Upload | Can Edit | Can Delete | Can Manage Users | Can View Usage |
|------|-----------|---------|-----------|-----------------|---------------|
| `viewer` | No | No | No | No | No |
| `operator` | Yes | Yes | No | No | Yes |
| `admin` | Yes | Yes | Yes | Yes | Yes |

### Auth Endpoints

```
POST /api/auth/login
  Body: { email, password }
  Response: { access_token, user: { id, email, name, role } }

POST /api/auth/register          (admin only)
  Body: { email, password, name, role }
  Response: { id, email, name, role }

GET /api/auth/me
  Response: { id, email, name, role }
```

---

## Extraction

```
POST /api/extraction/upload
  Auth: operator+
  Body: multipart/form-data (files[]: PDF[])
  Response: { jobs: [{ job_id, filename, status: "queued" }] }

GET /api/extraction/status/{job_id}
  Auth: operator+
  Response: {
    job_id, filename, status: "queued|processing|completed|failed",
    progress: { step: "classify|extract|validate", percent: 0-100 },
    result: ExtractionResult | null,
    error: string | null
  }
  Also available as SSE stream: GET /api/extraction/status/{job_id}/stream

POST /api/extraction/approve/{job_id}
  Auth: operator+
  Body: { edits: { field_name: new_value, ... } }  (optional manual corrections)
  Response: { policy_id }
  Notes: Saves extraction result to database. Edits create audit entries.

POST /api/extraction/retry/{job_id}
  Auth: operator+
  Body: { force_refresh: bool }
  Response: { job_id, status: "queued" }

POST /api/extraction/batch
  Auth: operator+
  Body: multipart/form-data (files[]: PDF[], auto_approve: bool)
  Response: { jobs: [{ job_id, filename }] }
  Notes: auto_approve=true saves high-confidence results without review.
```

---

## Policies

```
GET /api/policies
  Auth: viewer+
  Query: ?page=1&per_page=25&search=&carrier=&status=&type=&expiring_within_days=
  Response: {
    items: [PolicySummary],
    total: int,
    page: int,
    pages: int
  }

GET /api/policies/{id}
  Auth: viewer+
  Response: PolicyDetail (includes vehicles, drivers, coverages, endorsements)

GET /api/policies/{id}/summary
  Auth: viewer+
  Response: PolicyComputedSummary (liability_display, um_uim_display, etc.)

PUT /api/policies/{id}
  Auth: operator+
  Body: { field_name: new_value, ... }
  Response: PolicyDetail
  Notes: Every field change creates an AuditEntry.

DELETE /api/policies/{id}
  Auth: admin only
  Response: { success: true }
  Notes: Soft delete (status → "deleted"). Never hard delete.

GET /api/policies/{id}/documents
  Auth: viewer+
  Response: [{ id, filename, uploaded_at, page_count }]

GET /api/policies/{id}/audit
  Auth: viewer+
  Response: [AuditEntry]
```

---

## COI Generation

```
GET /api/coi/holders
  Auth: viewer+
  Response: [{ id, name, address }]

POST /api/coi/holders
  Auth: operator+
  Body: { name, address }
  Response: { id, name, address }

POST /api/coi/generate
  Auth: operator+
  Body: { policy_id, holder_id | holder: { name, address }, options: {} }
  Response: PDF file (application/pdf)
```

---

## Dashboard

```
GET /api/dashboard/metrics
  Auth: viewer+
  Response: {
    total_policies: int,
    total_vehicles: int,
    total_premium_cents: int,
    active_policies: int,
    policies_by_type: { commercial_auto: N, personal_auto: N, ... },
    policies_by_carrier: { "Progressive": N, "GEICO": N, ... }
  }

GET /api/dashboard/expiring
  Auth: viewer+
  Query: ?days=30
  Response: [PolicySummary]

GET /api/dashboard/recent
  Auth: viewer+
  Query: ?limit=10
  Response: [{ policy_id, policy_number, carrier, action, timestamp, user }]
```

---

## Usage & Monitoring

```
GET /api/usage/today
  Auth: operator+
  Response: {
    total_cost_cents: int,
    total_input_tokens: int,
    total_output_tokens: int,
    documents_processed: int,
    budget_limit_cents: int,
    budget_remaining_cents: int
  }

GET /api/usage/history
  Auth: admin
  Query: ?days=30
  Response: [{ date, cost_cents, input_tokens, output_tokens, documents }]
```

---

## Export

```
GET /api/export/excel
  Auth: operator+
  Query: ?policy_ids=1,2,3 (optional, default: all)
  Response: XLSX file

GET /api/export/csv
  Auth: operator+
  Response: CSV file
```

---

## Chat / Natural Language Query

```
POST /api/chat/query
  Auth: operator+
  Body: { question: "How many policies expire next month?" }
  Response: {
    sql: "SELECT ...",
    results: [{ ... }],
    answer: "There are 12 policies expiring next month."
  }
  Notes: Only SELECT queries allowed. No mutations.
```

---

## Data Shapes

### PolicySummary (list views)
```json
{
  "id": 1,
  "policy_number": "PA-12345",
  "policy_type": "commercial_auto",
  "carrier_name": "Progressive",
  "insured_name": "ABC Trucking LLC",
  "effective_date": "2024-01-15",
  "expiration_date": "2025-01-15",
  "premium_display": "$4,200.00",
  "status": "active",
  "vehicle_count": 3,
  "liability_display": "1,000,000 CSL"
}
```

### PolicyDetail (single view)
```json
{
  "id": 1,
  "policy_number": "PA-12345",
  "policy_type": "commercial_auto",
  "carrier_name": "Progressive",
  "naic_number": "24260",
  "effective_date": "2024-01-15",
  "expiration_date": "2025-01-15",
  "insured_name": "ABC Trucking LLC",
  "insured_address": "123 Main St",
  "insured_city": "Dallas",
  "insured_state": "TX",
  "insured_zip": "75201",
  "premium_cents": 420000,
  "status": "active",
  "classification_confidence": "high",
  "extraction_source": "gemini-2.5-flash",
  "created_at": "2024-06-15T10:30:00Z",
  "vehicles": [...],
  "drivers": [...],
  "coverages": [...],
  "endorsements": [...],
  "additional_interests": [...]
}
```

### ExtractionResult (review screen)
```json
{
  "policy": { ... },
  "vehicles": [...],
  "drivers": [...],
  "coverages": [...],
  "endorsements": [...],
  "confidence": {
    "policy_number": "high",
    "premium": "medium",
    "naic_number": "low"
  },
  "flags": [
    "COMP deductible differs across vehicles — verify schedule",
    "Policy number format unusual — verify manually"
  ]
}
```
