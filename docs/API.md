# API and Integration Reference

This repository currently has one integration surface:
- The in-process Streamlit application services (`core/services.py` + `views/*`)

## In-Process Service Behavior (Streamlit Path)

For the Streamlit app, service calls happen in-process instead of HTTP:

- Dashboard metrics: `PolicyService.get_dashboard_metrics()`
- Policy search/list/count:
  - `search_policies(term, limit, offset)`
  - `count_policies(term)`
- Customer search/list/count:
  - `search_customers(term, orphan_filter, limit, offset)`
  - `count_customers(term, orphan_filter)`
  - `orphan_filter` accepts `active`, `all`, or `orphans`
- Policy retrieval:
  - `get_policy_by_id(policy_id)`
  - `get_policy_by_number(policy_number)`
- Save/update from extraction:
  - `save_policy_from_extraction(extraction_result)`
  - exact policy-number matches update existing policy rows by default
  - `_duplicate_action="create_new"` blocks saving when the same policy number already exists
- Duplicate detection and preview:
  - `detect_duplicate_for_extraction(extraction_result)`
  - `preview_update_from_extraction(existing_policy, extraction_result)`
- Manual update:
  - `update_policy(policy, updated_data)`
- Deletion:
  - `delete_policy(policy)`
  - returns policy deletion metadata and customer cleanup status
  - removes extraction-only customer profiles when the deleted policy was their last policy
  - retains customer profiles with manual aliases or contact data
- Natural language query:
  - `ask_your_data(user_query, api_key)`

## Authentication

- No auth headers or token exchange are implemented in the current Streamlit app.

## Data Shape References

For model fields and persistence shapes, see:
- [`DATABASE_AND_MIGRATIONS.md`](DATABASE_AND_MIGRATIONS.md)
- [`EXTRACTION_PIPELINE.md`](EXTRACTION_PIPELINE.md)
