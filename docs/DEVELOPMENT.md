# Development Guide

Setup, conventions, and workflow rules for the project.

---

## Local Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 15+
- Redis (for job queue)

### Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your values:
#   DATABASE_URL=postgresql://user:pass@localhost:5432/insurance_hub
#   REDIS_URL=redis://localhost:6379
#   GEMINI_API_KEY=your_key
#   JWT_SECRET=your_secret

# Initialize database
alembic upgrade head

# Run
uvicorn main:app --reload --port 8000
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev   # Starts on port 5173
```

### Docker (Full Stack)
```bash
docker-compose up -d
```

---

## Code Conventions

### Python (Backend)

- **Formatter**: ruff format
- **Linter**: ruff check
- **Type hints**: Required on all function signatures
- **Async**: All API route handlers and DB operations are async
- **Naming**: snake_case for everything. No abbreviations except well-known ones (id, url, db)
- **Imports**: stdlib → third-party → local, separated by blank lines

### TypeScript (Frontend)

- **Formatter**: prettier
- **Linter**: eslint
- **Components**: Functional components with hooks only
- **Naming**: PascalCase for components, camelCase for functions/variables
- **State**: React Query for server state, useState/useReducer for local state

### Database

- **All monetary values**: Stored as integer cents. Display layer converts.
- **All dates**: Proper `Date` or `DateTime` types. Never strings.
- **Soft deletes**: `status = 'deleted'` instead of hard delete. Exception: test data cleanup.
- **Audit trail**: Every mutation to a Policy creates an AuditEntry.
- **No legacy columns**: If a column is superseded, remove it in a migration. Don't keep both.

### Naming Conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Database table | plural snake_case | `policies`, `additional_interests` |
| SQLAlchemy model | singular PascalCase | `Policy`, `AdditionalInterest` |
| Pydantic schema | PascalCase + purpose | `PolicyCreate`, `PolicyResponse` |
| API route | REST plural | `/api/policies`, `/api/policies/{id}` |
| Coverage code | UPPER_SNAKE | `AUTO_LIAB_CSL`, `UMUIM_BI` |
| Family name | lower_snake | `auto_liability`, `uninsured_underinsured` |

---

## Git Workflow

- `main` branch is always deployable
- Feature branches: `feature/description` (e.g., `feature/endorsement-extraction`)
- Bug fixes: `fix/description`
- Commit messages: imperative mood, concise ("Add endorsement model" not "Added endorsement model and stuff")

---

## Testing

### Running Tests
```bash
# All tests
pytest tests/ -v

# Golden accuracy tests only
pytest tests/golden/ -v

# With coverage
pytest tests/ --cov=backend --cov-report=html
```

### Test Structure
```
tests/
├── unit/
│   ├── test_ontology.py          # Registry validation rules
│   ├── test_validator.py         # Post-extraction validation
│   ├── test_state_rules.py       # State-specific logic
│   └── test_summary_compute.py   # Computed summary fields
├── integration/
│   ├── test_api_policies.py      # API endpoint tests
│   ├── test_extraction_flow.py   # Full pipeline with mocked LLM
│   └── test_coi_generation.py    # COI PDF output
├── golden/
│   ├── pdfs/                     # Real policy PDFs (git-lfs)
│   ├── expected/                 # Expected JSON outputs
│   ├── conftest.py
│   └── test_accuracy.py          # Field-by-field accuracy
└── conftest.py
```

### Golden Test Rules
- Golden PDFs are stored in Git LFS (they're large binary files)
- Expected JSONs are manually verified by a human (ground truth)
- Every prompt or ontology change must pass the golden suite
- Accuracy regression = blocked merge
- Minimum accuracy targets: policy_number 99%, dates 98%, coverages 95%, UM/UIM 90%

---

## Deployment

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `GEMINI_API_KEY` | Yes* | Google Gemini API key |
| `ANTHROPIC_API_KEY` | No | Claude API key (if using Claude provider) |
| `JWT_SECRET` | Yes | Secret for JWT token signing |
| `DAILY_BUDGET_CENTS` | No | Daily API spending limit (default: 500 = $5.00) |
| `FILE_STORAGE_PATH` | No | Where uploaded PDFs are stored (default: ./uploads) |
| `CORS_ORIGINS` | No | Allowed CORS origins (default: http://localhost:5173) |

### Docker Compose Services

| Service | Port | Purpose |
|---------|------|---------|
| `api` | 8000 | FastAPI backend |
| `worker` | — | Background extraction job processor |
| `frontend` | 5173 (dev) / 80 (prod) | React UI |
| `postgres` | 5432 | Database |
| `redis` | 6379 | Job queue |

---

## Adding a New Policy Type

When the agency starts selling a new line (e.g., Workers' Comp):

1. **Ontology**: Add new family and codes to `docs/ONTOLOGY.md` and `backend/extraction/ontology.py`
2. **Constraints**: Add policy type constraints (which families are allowed)
3. **State rules**: Add any state-specific rules to `backend/extraction/state_rules.py`
4. **Prompts**: No change needed — the pipeline automatically sends the filtered registry
5. **Classification**: Add the new type to the classification prompt's enum
6. **Tests**: Add 3-5 golden test PDFs for the new type
7. **UI**: No change needed — the review form renders from the schema dynamically

This is the "plugin" architecture: new policy types require only data changes, not pipeline code changes.

---

## Adding a New Coverage Code

1. Add entry to `COVERAGE_REGISTRY` in `ontology.py` with family, structure, allowed_limits
2. Add to the appropriate policy type constraint
3. Update `docs/ONTOLOGY.md`
4. Run `pytest tests/unit/test_ontology.py` to verify consistency
5. No migration needed (coverage_code is a free-text string column)
6. No prompt change needed (registry is dynamically sent)
