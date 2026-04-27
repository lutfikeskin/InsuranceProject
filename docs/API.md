# API and Integration Reference

This repository currently has one integration surface:
- The in-process Streamlit application services (`core/services.py` + `views/*`)

## In-Process Service Behavior (Streamlit Path)

For the Streamlit app, service calls happen in-process instead of HTTP:

- Dashboard metrics: `PolicyService.get_dashboard_metrics()`
- Policy search/list/count:
  - `search_policies(term, limit, offset)`
  - `count_policies(term)`
- Policy retrieval:
  - `get_policy_by_id(policy_id)`
  - `get_policy_by_number(policy_number)`
- Save/update from extraction:
  - `save_policy_from_extraction(extraction_result)`
- Manual update:
  - `update_policy(policy, updated_data)`
- Natural language query:
  - `ask_your_data(user_query, api_key)`

## Authentication

- No auth headers or token exchange are implemented in the current Streamlit app.

## Data Shape References

For model fields and persistence shapes, see:
- [`DATABASE_AND_MIGRATIONS.md`](DATABASE_AND_MIGRATIONS.md)
- [`EXTRACTION_PIPELINE.md`](EXTRACTION_PIPELINE.md)
