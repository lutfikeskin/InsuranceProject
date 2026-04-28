# COI Workflow

This document covers Certificate of Insurance generation flow.

## Primary Components

- UI page: `views/create_coi.py`
- Service helper: `core/services.py` (`COIService`)
- Generator: `modules/coi/generator.py`
- PDF mapping: `modules/coi/mapping.json`
- Template: `data/COI Example.pdf`

## User Flow

1. Search and select policy.
2. Provide or quick-fill certificate holder details.
3. Toggle included coverage sections (GL, Auto, Cargo).
4. Optionally customize operations description and font size.
5. Generate PDF (single) or ZIP of PDFs (bulk mode).

## Data Preparation

`views/create_coi.py` constructs:
- `policy_data` from selected policy + overrides
- `holder_data` from manual entry or company list

`COIService.prepare_coi_data(...)` provides helper defaults.

## Generation Mechanics

`COIGenerator.generate_coi(...)`:
- loads field mapping JSON
- reads PDF template
- fills mapped fields
- writes output to memory
- optionally flattens form fields using `pymupdf`

## Coverage Behavior

- GL and Auto sections are controlled by boolean flags.
- Cargo section is enabled when cargo data is present/selected.
- GL aggregate can be selected in UI and passed into payload.

## Bulk Mode

- Multi-select company list.
- Generate one PDF per company.
- Package files into ZIP for download.
- Generated PDF names follow: `COI - Insured Name - Certificate Holder Name.pdf` in both single and bulk flows.

## Dependencies

- `pypdf` for form filling
- `pymupdf` (`fitz`) for flattening

If `pymupdf` is unavailable, filled PDF is returned unflattened.

## Test Coverage

- `tests/test_bulk_logic.py` validates bulk generation and ZIP behavior.
