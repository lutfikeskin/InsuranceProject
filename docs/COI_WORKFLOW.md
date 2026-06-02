# COI Workflow

This document covers Certificate of Insurance generation flow.

## Primary Components

- UI page: `views/create_coi.py`
- Service helper: `core/services.py` (`COIService`)
- Generator: `modules/coi/generator.py`
- PDF mapping: `modules/coi/mapping.json`
- Template: `data/COI Example.pdf`

## Holder Library

- Source file: `data/coi_holders.json` (loaded via `modules/coi/holders.py`)
- Create COI quick-fill reads this file; new holders can be added from **Add new certificate holder** on the Create COI page (saved to `data/coi_holders.json` on disk).
- Export, import/merge, and reload the holder library from **Settings** (sidebar) under **COI holder library**.

## User Flow

1. Search and select policy.
2. Provide or quick-fill certificate holder details from the holder library.
3. Review/edit insurer legal name, insured details, and selected coverage limits.
4. Toggle included coverage sections (GL, Auto, Cargo; lienholder reuses Other Policy for Comp/Coll deductibles).
5. Optionally customize operations description and font size, or reset it from policy data.
6. Generate PDF (single) or ZIP of PDFs (bulk mode).

## Data Preparation

`views/create_coi.py` constructs:
- `policy_data` from selected policy + UI overrides via `COIService.build_generation_payload(...)`
- `holder_data` from manual entry or holder library (`coi_holders.json`)

`COIService.prepare_coi_data(...)` provides default operations-description lines.

ACORD insurer behavior:

- UI still shows brand (`carrier_name`) as the primary user-facing insurer label.
- COI insurer field uses legal entity first: `underwriter_name` fallback to `carrier_name`.

## Generation Mechanics

`COIGenerator.generate_coi(...)`:
- loads field mapping JSON
- reads PDF template
- fills mapped fields
- writes output to memory
- optionally flattens form fields using `pymupdf`

## Coverage Behavior

- GL and Auto sections are controlled by stored booleans when available; null booleans fall back to limit evidence.
- GL occurrence uses `general_liability_limit`/`gl_occurrence_limit` before falling back to auto liability.
- Cargo section is enabled only when a meaningful cargo limit is present/selected.
- GL aggregate supports standard values or a custom amount.
- Certificate Holder COIs leave ADDL INSD columns blank; Additional Insured and Lienholder mark them with `Y`.

## Bulk Mode

- Multi-select company list.
- Generate one PDF per company.
- Per-holder failures no longer abort the entire batch; the page shows generated/failed counts and issue rows.
- ZIP download is suppressed if zero PDFs are generated.
- Generated PDF names follow: `COI - Insured Name - Certificate Holder Name.pdf` in both single and bulk flows.

## Dependencies

- `pypdf` for form filling
- `pymupdf` (`fitz`) for flattening

If `pymupdf` is unavailable, filled PDF is returned unflattened.

## Test Coverage

- `tests/test_bulk_logic.py` validates bulk generation and ZIP behavior.
