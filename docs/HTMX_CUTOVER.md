# HTMX Cutover Status

This document tracks the replacement of the Streamlit UI with the Flask + HTMX + Jinja shell under `webapp/`.

## Current HTMX Routes

| Route | Status | Notes |
|---|---|---|
| `/dashboard` | Implemented | Metrics, expirations, carrier distribution, quick lookup, recent activity |
| `/process-policies` | Implemented | Single + batch upload, extraction, durable task creation, retry-anyway, batch-save |
| `/review-queue` | Implemented | Durable task list, detail, save, skip, fail, confidence-gated review form |
| `/compare` | Implemented | Policy selectors, auto-pair hint, scalar diffs, collection sections |
| `/database` | Implemented | Policy/customer search, policy export, policy edit/delete, customer edit/alias add |
| `/renewals` | Implemented | Bucket views, selected-policy draft preview, contact log, draft download |
| `/create-coi` | Implemented | Single COI PDF + bulk ZIP generation, saved-company prefill, lienholder UX |
| `/settings` | Implemented | In-memory Gemini key control, confidence gate, usage reset |

## Cutover Notes

- The HTMX shell now covers the operational workflows end-to-end.
- Streamlit remains in the repository as a legacy reference shell, but the active operational UI is the HTMX app under `webapp/`.

## Backend Safety Rules

The HTMX shell MUST continue reusing the existing core services and extraction code:

- `PolicyService`
- `UsageService`
- `ReviewWorkflowService`
- `ComparisonService`
- `COIService`
- `NotificationService`
- `process_pdf()` / extraction pipeline

No duplicate business logic should be introduced in `webapp/`.

## Run Commands

Install deps:

```bash
pip install -r requirements.txt
```

Run HTMX shell:

```bash
flask --app webapp.app run --debug
```

Legacy Streamlit shell:

```bash
streamlit run app.py
```

## Verification Baseline

Before any cutover claim:

```bash
python -m compileall -q app.py core modules utils views scripts tests alembic webapp
python -m pytest tests/ -v --ignore=tests/test_accuracy.py
python -m pytest tests/test_accuracy.py -v
```
