# Operations and Troubleshooting

## Runtime Commands

- Start app: `streamlit run app.py`
- Run tests: `pytest`
- Build container: `docker build -t insuranceproject .`

## Operational Files

- Database: `insurance_data.db`
- Logs: `logs/app.log`
- Extraction cache: `.cache/extraction_cache/`

## Observability

- Sidebar usage monitor reads from `api_usage` table through `UsageService`.
- Usage reset is available in Streamlit settings dialog.
- Extraction cache hit/miss behavior is logged.

## Common Issues

### Missing Gemini API key

Symptoms:
- extraction fails
- NL query fails

Fix:
- set `GEMINI_API_KEY`
- or provide key through Streamlit settings dialog

### Daily budget exceeded

Symptoms:
- extraction halts with budget/quota error

Fix:
- increase `DEFAULT_DAILY_BUDGET` in `core/constants.py`
- or clear usage logs via settings dialog

### JSON parse/extraction errors

Symptoms:
- extraction result parsing fails

Fix:
- retry with force refresh in Process Policies page
- process PDFs one-by-one for diagnosis
- inspect logs for parser error details

### COI generation failure

Symptoms:
- COI PDF not generated

Fix:
- confirm `data/COI Example.pdf` exists
- confirm `modules/coi/mapping.json` mappings are valid
- check holder/policy data completeness
- ensure `pypdf` and `pymupdf` are installed

### Migration/schema issues

Symptoms:
- model mismatch, missing columns, migration errors

Fix:
- run `alembic upgrade head`
- verify `alembic/env.py` URL and batch mode settings
- confirm model registration in metadata

## Deployment Notes

- Docker image runs Streamlit on port `8080`.
- Any production deployment should persist DB and data paths as needed.
- If running stateless containers, plan externalized storage for DB and files.

## Backup Guidance

- Back up `insurance_data.db` and `data/coi_holders.json` regularly via **Settings** in the sidebar.
- Preserve `data/` and any curated holder files.
- Back up logs and cache only if needed for diagnostics.

## Settings: Database backup and restore

Open **Settings** from the sidebar, section **Database backup and restore**:

1. **Backup database (.db)** — download the current `insurance_data.db`.
2. Upload another `insurance_data.db` and click **Merge imported database**.

Merge behavior:

- Imports policies whose `policy_number` is not already in the live database.
- Skips duplicates by policy number (does not overwrite existing rows).
- Copies related vehicles, drivers, coverages, endorsements, and history for imported policies.
- Matches customers by `full_name` (case-insensitive); creates a new customer when no match exists.
- Does not import API usage/token history.

## Settings: COI holder library

In the same **Settings** dialog, section **COI holder library**:

- **Export holder library (JSON)** — download `coi_holders.json`.
- **Import holder library (.json)** + **Merge imported holder library** — append new holders; skip duplicate names.
- **Reload holder library** — refresh in-memory quick-fill after external edits.

New holders are still added on the **Create COI** page via **Add new certificate holder**; backup/import lives only in Settings.
