# Development Guide

How to run, test, and extend the current repository.

## Local Setup

### Prerequisites

- Python 3.9+
- Gemini API key for extraction features

### Python App Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Set API key (PowerShell):

```powershell
$env:GEMINI_API_KEY="your_key"
```

Run HTMX/Jinja shell:

```bash
flask --app webapp.app run --debug
```

Run legacy Streamlit shell:

```bash
streamlit run app.py
```

The HTMX shell now covers the operational review, database, COI, compare, renewals, and dashboard workflows. Streamlit remains only as a legacy reference shell.

## Development Workflow

1. Run HTMX shell and verify targeted behavior.
2. Run focused tests first, then `pytest`.
3. Update docs alongside behavior changes.

## Code Conventions

### Python

- Keep service/domain logic in `core/`.
- Keep page orchestration in `views/`.
- Keep extraction-specific logic in `modules/extraction/`.
- Keep COI-specific logic in `modules/coi/`.
- Preserve backward compatibility for payload keys consumed by UI and tests.

## Database and Migrations

- Main DB is SQLite file `insurance_data.db`.
- SQLAlchemy models are in `core/database.py`.
- Alembic is configured in `alembic/`.
- Typical operations:
  - `alembic upgrade head`
  - `alembic revision --autogenerate -m "message"`

See [`DATABASE_AND_MIGRATIONS.md`](DATABASE_AND_MIGRATIONS.md) for details.

## Testing

### Run Tests

```bash
pytest
```

Focused examples:

```bash
pytest tests/test_policy_search.py -v
pytest tests/test_bulk_logic.py -v
pytest tests/test_extraction.py -v
```

### Accuracy Harness

- `tests/test_accuracy.py` compares extraction output against `tests/data/*.json` golden references.
- It is skipped unless `GEMINI_API_KEY` is set.

## Useful Scripts

- `python scripts/check_models.py`
- `python scripts/inspect_pdf.py`

## Container Build

Build image:

```bash
docker build -t insuranceproject .
```

Container command (from `Dockerfile`):
- `streamlit run app.py --server.port 8080 --server.address 0.0.0.0`

## Extending the System

### Add a Coverage Code

1. Update `core/coverage_ontology.py`.
2. Ensure pipeline normalization/summary behavior still works.
3. Update docs:
   - `docs/ONTOLOGY.md`
   - `docs/EXTRACTION_PIPELINE.md`
4. Add or update tests in `tests/`.

### Add a Policy Field

1. Add model field in `core/database.py`.
2. Add migration if needed via Alembic.
3. Update service mapping in `PolicyService.create_policy_from_dict`.
4. Update extraction schema/prompt if field is extracted.
5. Update UI forms in `views/` and docs.
