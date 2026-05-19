# Audit Baseline — 2026-05-11

Captured at the start of the `chore/audit-cleanup` branch (cut from `feat/gemini-caching-optimization` at commit `56bde85`). Used as the before/after reference for the comprehensive audit pass.

## Test Suite (`pytest tests/ -v --ignore=tests/test_accuracy.py`)

- **32 passed, 1 skipped, 0 failed**
- Duration: **3.39s**
- 30 warnings (mostly upstream `google.genai` and `sqlalchemy` deprecation warnings — not our code).
- Files in run:
  - `tests/test_bulk_logic.py` (2 passed)
  - `tests/test_customer_database.py` (4 passed)
  - `tests/test_customer_resolver.py` (2 passed)
  - `tests/test_duplicate_detection.py` (5 passed)
  - `tests/test_extraction.py` (2 passed, 1 skipped)
  - `tests/test_policy_search.py` (3 passed)
  - `tests/test_policy_update_diff.py` (1 passed)
  - `tests/test_prompt_routing.py` (13 passed)
- `tests/test_accuracy.py` is excluded — it requires a live `GEMINI_API_KEY`.

After the audit, the suite **must** still be green and **must** have more tests than this baseline.

## Source Tree Size

Total Python LOC across `app.py` + `core/` + `modules/` + `views/` + `utils/` + `reporting/`: **10,997 lines**.

Files larger than 250 LOC:

| LOC  | File                                          |
|------|-----------------------------------------------|
| 1684 | `core/services.py`                            |
| 1458 | `views/process_policies.py`                   |
|  677 | `modules/extraction/pipeline.py`              |
|  664 | `views/database_page.py`                      |
|  514 | `views/create_coi.py`                         |
|  495 | `core/coverage_ontology.py`                   |
|  458 | `modules/extraction/schemas.py`               |
|  399 | `modules/extraction/prompts.py`               |
|  359 | `core/coverage_normalization.py`              |
|  298 | `views/edit_dialog.py`                        |
|  283 | `core/history_service.py`                     |
|  272 | `core/database.py`                            |
|  253 | `core/customer_resolver.py`                   |
|  251 | `utils/vehicle_utils.py`                      |

File counts by package: `core`: 12, `modules`: 18, `views`: 5, `utils`: 5, `reporting`: 2, `scripts`: 5, `tests`: 12, `alembic`: 8.

## Streamlit Boot

`streamlit run app.py` boots successfully on the baseline (visual confirmation only; no automated UI tests on this branch).

## Branch State

```
chore/audit-cleanup  (just created)
  ← cut from feat/gemini-caching-optimization @ 56bde85
```

Carried over from the previous working tree:
- `CLAUDE.md` modifications (Gemini 3.1 update, expanded Change Blast Radius Map, "Local Run" section, expanded Active Modules list).
- `.gitignore` update adding `.claude/skills/` (so Streamlit-skill scaffolding doesn't leak into commits).

Discarded before branching:
- 88 staged files under `.claude/skills/developing-with-streamlit/` (now gitignored).
- Local `logs/app.log` runtime modifications.
- Deletion of `ACORD 0025 2016-03 - KIMPHO INC COI 3.30.pdf` (a test artifact — restored).

## Out of Scope (Roadmap Items)

These large refactors are intentionally **not** touched on this branch — they are documented in `docs/AUDIT_2026-05.md` as deferred work:

- `core/services.py` split into per-service modules.
- `views/process_policies.py` split into per-step components.
- `modules/extraction/pipeline.py` split per extraction flow.
- `ProductRegistry` / multi-product modularity refactor (deferred — no new product types on the roadmap).
- `prompts.py` / `schemas.py` per-product split (same).
- `COVERAGE_REGISTRY` namespacing by product (same).
