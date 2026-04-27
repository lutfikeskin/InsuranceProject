# Database and Migrations

## Active Database

- Engine: SQLite
- Default file: `insurance_data.db`
- ORM: SQLAlchemy (declarative models in `core/database.py`)

## Core Tables/Models

- `policies`
- `vehicles`
- `drivers`
- `coverages`
- `additional_interests`
- `api_usage`
- `policy_history` (registered via `core/history_model.py`)

## Initialization Behavior

- `init_db()` in `core/database.py` calls `Base.metadata.create_all(engine)`.
- Streamlit app initializes DB engine in session state on startup.

## Alembic

- Config files: `alembic.ini`, `alembic/env.py`
- Current migration files are under `alembic/versions/`.
- `alembic/env.py` sets DB URL to `sqlite:///insurance_data.db` and enables `render_as_batch=True`.

## Common Migration Commands

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

## Operational Guidance

- Prefer migration-driven schema evolution for existing environments.
- Keep model changes and migration scripts in the same commit/change set.
- Validate migration + startup compatibility after schema edits.

## Data Conventions

- Premiums are currently persisted as strings on policy model.
- Many coverage limits are stored as integer columns.
- Dates are parsed in services before persistence.

## Testing Notes

- `tests/conftest.py` uses in-memory SQLite for test session fixtures.
- Model metadata is created per test session fixture.
