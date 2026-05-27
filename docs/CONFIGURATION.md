# Configuration and Secrets

## Environment Variables

### Required for extraction features

- `GEMINI_API_KEY`
  - Used by extraction pipeline and NL query features.
  - Read from:
    - Streamlit session state
    - process environment
    - `st.secrets`

### Optional telemetry/privacy controls

- `APP_EVENT_RETENTION_DAYS`
  - Number of days to keep durable `app_events` when cleanup is run from Settings.
  - Default: `90`.
- `TELEMETRY_HASH_SALT`
  - Optional salt for hashing policy numbers, VINs, names, and addresses in telemetry.
  - Recommended for shared or deployed environments.

## In-Code Configuration

- `core/constants.py`
  - `DEFAULT_DAILY_BUDGET`
  - policy search limits
  - UI labels and enums

- `modules/extraction/pipeline.py`
  - `ROUTING_MODEL`
  - `EXTRACTION_MODEL`
  - `CACHE_VERSION`

## File-Based Configuration/Data

- `modules/coi/mapping.json` - PDF field mapping
- `data/carrier_hints.json` - carrier extraction hints
- `data/coi_holders.json` - active certificate holder library (Create COI quick-fill + UI add form)
- `data/Additionalinsuredcomps.xlsx` - legacy reference sheet (not loaded by the app at runtime)
- `.streamlit/config.toml` - Streamlit UI/theming config (if present)

## Runtime Paths

- DB: `insurance_data.db`
- Cache: `.cache/extraction_cache/`
- Logs: `logs/app.log`
- Durable events/metrics: `app_events` table in the database

## Deployment Configuration

- Container command from `Dockerfile`:
  - `streamlit run app.py --server.port 8080 --server.address 0.0.0.0`

## Security Notes

- Never commit real API keys.
- Prefer environment variables or `st.secrets` for secrets.
- Review logs, metrics, and cache content before sharing environments.
- Treat logs and `app_events` as operational telemetry; avoid storing raw customer content.
