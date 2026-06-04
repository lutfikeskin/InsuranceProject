# Insurance Doc Intelligence

Insurance operations workspace for extracting policy data from PDFs, reviewing results, storing structured records, and generating Certificates of Insurance (COIs).

## Contents
- Flask + HTMX operational shell (`webapp/`)
- Legacy Streamlit app (`app.py`, `views/*`)
- Extraction and COI modules under `modules/`
- Service/domain logic under `core/`
- Pytest suite under `tests/`

## Current Architecture
- Primary runtime: Flask + HTMX shell (`webapp/`)
- Database: SQLite (`insurance_data.db`) via SQLAlchemy models in `core/database.py`
- Migrations: Alembic (`alembic/`)
- Extraction engine: Gemini-based pipeline (`modules/extraction/pipeline.py`)
- COI generation: PDF form fill + optional flattening (`modules/coi/generator.py`)

For deeper details, use the docs index: [`docs/README.md`](docs/README.md).

## Repository Layout
- `webapp/` - Flask + HTMX app and templates
- `app.py` - Legacy Streamlit entrypoint
- `views/` - Legacy Streamlit pages
- `core/` - models, services, ontology, history, constants
- `modules/extraction/` - PDF extraction pipeline, schemas, prompts, PDF ops
- `modules/coi/` - COI PDF generator and field mapping
- `utils/` - helper utilities (vehicle typing, NAIC, export, text)
- `tests/` - pytest suite
- `data/` - template PDF and supporting data files
- `docs/` - full project documentation

## Prerequisites
- Python 3.9+ (Dockerfile uses 3.9-slim)
- Gemini API key (`GEMINI_API_KEY`) for extraction and NL query features

## Quickstart
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Set API key:
   - PowerShell: `$env:GEMINI_API_KEY="your_key"`
3. Run app:
   - `flask --app webapp.app run`
4. Open the local Flask URL shown in terminal.

## Configuration Overview
- `GEMINI_API_KEY`
  - Read from environment or `st.secrets` in the legacy Streamlit shell.
- `DEFAULT_DAILY_BUDGET`
  - Daily extraction/query budget in `core/constants.py`.
- Database path
  - Default SQLite file: `insurance_data.db`.

Full configuration details: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Common Commands
### Python app and tests
- Run app: `flask --app webapp.app run`
- Run legacy app: `streamlit run app.py`
- Run all tests: `pytest`
- Run specific test: `pytest tests/test_bulk_logic.py -v`

### Database migrations
- Apply migrations: `alembic upgrade head`
- Create migration: `alembic revision --autogenerate -m "message"`

## Data and Runtime Files
- Template and data assets live in `data/`.
- Extraction cache is written to `.cache/extraction_cache/`.
- Logs are written to `logs/app.log`.

## Deployment
Container image is defined by [`Dockerfile`](Dockerfile) and runs:
- `flask --app webapp.app run --host 0.0.0.0 --port 8080`

Deployment and operations details:
- [`docs/OPERATIONS_AND_TROUBLESHOOTING.md`](docs/OPERATIONS_AND_TROUBLESHOOTING.md)
- [`docs/DATABASE_AND_MIGRATIONS.md`](docs/DATABASE_AND_MIGRATIONS.md)

## Documentation Index
- Docs index: [`docs/README.md`](docs/README.md)
- System architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Development workflow: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- API and integration contract: [`docs/API.md`](docs/API.md)
- Extraction details: [`docs/EXTRACTION_PIPELINE.md`](docs/EXTRACTION_PIPELINE.md)
- COI workflow: [`docs/COI_WORKFLOW.md`](docs/COI_WORKFLOW.md)
- Testing guide: [`docs/TESTING.md`](docs/TESTING.md)
