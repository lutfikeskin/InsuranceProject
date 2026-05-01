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
pytest tests/test_extraction.py -v
pytest tests/test_bulk_logic.py -v
pytest tests/test_accuracy.py -v
```

## Current Test Files

- `tests/test_policy_search.py`
  - search behavior and coverage-to-vehicle VIN linking
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
- It compares extracted vs expected JSON, with selective normalization and key exclusions.
- Carrier/underwriter assertions:
  - Progressive fixtures treat `carrier_name` as brand (`Progressive`).
  - `underwriter_name` is a critical field for Progressive fixtures.

## Test Data

- `tests/data/*.pdf`
- `tests/data/*.json`

Keep PDF/JSON pairs aligned when updating extraction behavior.

## Recommended Validation Sequence

1. Run focused tests for touched area.
2. Run full `pytest`.
3. If extraction logic changed, run `tests/test_accuracy.py` with API key.
