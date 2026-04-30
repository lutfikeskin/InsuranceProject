# Chat Handoff - Phase 13 + Stability Fixes

## Branch Context
- Branch includes Phase 12 completion commit: `d993020`.
- Current uncommitted work in this handoff covers Phase 13 UI + runtime stability fixes discovered while validating the app.

## What Was Implemented

### 1) Phase 13 Customer UI
- Added customer-centric tab to database page.
  - File: `views/database_page.py`
  - `page_database()` now has:
    - `📄 Policies` tab (existing flow preserved)
    - `👥 Customers` tab
- Added customer portfolio rendering:
  - `render_customers_view(session)`
  - `render_customer_row(customer, session)`
- Features implemented:
  - Search by customer name or entity name (case-insensitive substring).
  - Pagination for customers (`CUSTOMER_PAGE_SIZE = 25`) to avoid heavy in-memory rendering.
  - Customer expanders with:
    - active/total policy counts
    - policy types summary
    - grouped policies by status (`active`, `expired`, `canceled`, `replaced`)
    - inline real-name correction flow when `needs_real_name_entry` is true
    - manual entity alias addition (`business`, `dba`, `maiden_name`, `personal`)

### 2) Review Screen Customer Resolution Panel
- File: `views/process_policies.py`
- Added panel before save actions:
  - Shows confirmed customer match and recent policies.
  - Shows suggested match with explicit user choice:
    - `Yes, same customer`
    - `No, different person`
  - For non-personal docs with no match, prompts owner/principal name.
- Review decisions are persisted into payload:
  - `_review_confirm_customer_id`
  - `_review_commercial_owner_name`
  - `_customer_resolution` pass-through

### 3) Save Flow Override Logic
- File: `core/services.py`
- Added review-origin override support in both new-save and update-save paths:
  - If `_review_confirm_customer_id` exists: explicit link to that customer (no auto-linking suggestion behavior).
  - If creating commercial customer and `_review_commercial_owner_name` exists: use owner name as `Customer.full_name`; keep insured/business as entity alias.
- Existing resolver behavior remains fallback when no explicit override is provided.

### 4) Circular Import Fix
- File: `core/services.py`
- Resolved `core.services <-> modules.extraction.pipeline` circular import:
  - Moved `CarrierKnowledgeBase` import from module top-level into method-local import inside `_record_carrier_profile_if_high_confidence`.

### 5) SQLite Runtime Schema Drift Auto-Repair
- File: `core/database.py`
- Extended `init_db()` SQLite bootstrap to auto-add missing columns for legacy DBs:
  - `customers`: `primary_email`, `primary_phone`, `needs_real_name_entry`
  - `customer_entities`: `entity_name`, `entity_type`, `is_primary`, `source`, `first_seen`
  - kept existing `policies.extraction_extras` safeguard
- This resolves runtime errors like:
  - `no such column: customers.primary_email`
  - `no such column: customer_entities.entity_name`

### 6) Phase Status Update
- File: `CLAUDE.md`
- Marked:
  - Phase 12 as completed
  - Phase 13 as completed

## Validation Performed
- Lint diagnostics on edited files: no lints reported.
- Syntax checks passed:
  - `PYTHONPYCACHEPREFIX=.cache/pycache python3 -m py_compile views/database_page.py views/process_policies.py core/services.py`
- Tests:
  - `python3 -m pytest tests/test_extraction.py -q` -> passed previously after Phase 13 implementation.
- Import checks after circular fix:
  - `from core.services import UsageService` -> OK
  - `from modules.extraction.pipeline import process_pdf` -> OK
- DB checks after schema drift repair:
  - querying `Customer` and lazy-loading `customer.entities` now succeeds.

## Known Notes
- Working tree has many unrelated repo changes not part of this handoff (cache/docs/assets/etc). Commit only intended files if making a clean Phase 13 commit.
- Streamlit was restarted and confirmed on `http://localhost:8501`.

## Recommended Next Steps
1. Open app -> Database -> Customers tab and manually verify:
   - search behavior
   - pagination
   - alias add + real-name update flow
2. Process one commercial review item to confirm override behavior:
   - explicit suggested-match confirmation
   - owner-name anchor on new customer creation
3. Commit these files together:
   - `views/database_page.py`
   - `views/process_policies.py`
   - `core/services.py`
   - `core/database.py`
   - `CLAUDE.md`
   - `CHAT_HANDOFF.md`
