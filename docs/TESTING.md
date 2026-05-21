# Testing Guide

## Test Framework

- Pytest
- Primary test directory: `tests/`

## Run Tests

```bash
pytest
```

Focused runs:

```bash
pytest tests/test_policy_search.py -v
pytest tests/test_customer_database.py -v
pytest tests/test_duplicate_detection.py -v
pytest tests/test_policy_update_diff.py -v
pytest tests/test_prompt_routing.py -v
pytest tests/test_customer_resolver.py -v
pytest tests/test_extraction.py -v
pytest tests/test_bulk_logic.py -v
pytest tests/test_accuracy.py -v
```

## Current Test Files

- `tests/test_policy_search.py`
  - search behavior and coverage-to-vehicle VIN linking
- `tests/test_customer_database.py`
  - customer search orphan filters and safe customer cleanup after policy deletion
- `tests/test_duplicate_detection.py`
  - normalized duplicate matching, conflict detection, possible related policies, and duplicate save intent behavior
- `tests/test_policy_update_diff.py`
  - non-mutating update diff previews for policy fields and child collections
- `tests/test_prompt_routing.py`
  - document-type routing with manual policy type, policy-scoped prompt assembly, COI prompt guardrails, and COI normalization edge cases including insured address splitting, Med Pay included, and GL/Auto inference
- `tests/test_customer_resolver.py`
  - DBA/sole-proprietor owner parsing for commercial insured names and corporate false-positive guards
- `tests/test_extraction.py`
  - extraction helper behavior (including auto liability cleanup)
- `tests/test_bulk_logic.py`
  - COI bulk generation and ZIP output behavior, including file naming format (`COI - Insured Name - Certificate Holder Name.pdf`)
- `tests/test_accuracy.py`
  - golden comparison against `tests/data` assets (requires API key)

## Fixtures

- `tests/conftest.py`
  - in-memory SQLite session fixture
  - extraction context fixture

## Accuracy Test Notes

- `test_accuracy.py` is skipped if `GEMINI_API_KEY` is missing.
- It compares extracted vs expected JSON with selective normalization, including classification, critical scalar fields, vehicle signatures, and driver signatures as hard failures; coverage signature drift is reported as warnings for review.
- Set `EXTRACTION_ACCURACY_FORCE_REFRESH=true` to bypass the local extraction cache during live drift checks.
- Carrier/underwriter assertions:
  - Progressive fixtures treat `carrier_name` as brand (`Progressive`).
  - `underwriter_name` is a critical field for Progressive fixtures.


Accuracy report for carrier/product onboarding:

```bash
python scripts/accuracy_report.py --force-refresh
python scripts/accuracy_report.py --case progressive
```

## Test Data

- `tests/data/*.pdf`
- `tests/data/*.json`

Keep PDF/JSON pairs aligned when updating extraction behavior.

## Recommended Validation Sequence

1. Run focused tests for touched area.
2. Run full `pytest`.
3. If extraction prompts or schemas changed, run `tests/test_accuracy.py` with API key and update goldens only when the new output is correct.
