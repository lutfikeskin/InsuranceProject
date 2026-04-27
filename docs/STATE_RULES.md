# State Extraction Hints

State context notes used to improve extraction consistency.

## Purpose

- Improve model mapping quality for state-specific wording and coverage naming.
- Guide ambiguous mapping cases (especially UM/UIM family codes).

## Non-Goals

- This file does not define compliance checks.
- This file does not enforce minimum legal limits.
- Missing coverages are not auto-flagged solely from state assumptions.

## Current Hint Set

### Texas (`TX`)
- UM/UIM often appears as one combined item.
- Prefer `UMUIM_*` code family when presented as combined.

### Florida (`FL`)
- PIP is commonly present in auto policy declarations.
- UM and UIM are often shown separately.

### New York (`NY`)
- UIM may appear as `SUM` (Supplementary Uninsured/Underinsured Motorist).
- PIP commonly appears in auto declarations.

### California (`CA`)
- UM and UIM are frequently listed separately.

### Ohio (`OH`)
- UM/UIM combined formatting is common.

### New Jersey (`NJ`)
- Policies may use `Basic` or `Standard` naming variants.

### Pennsylvania (`PA`)
- `Full Tort` or `Limited Tort` selections may appear and should be preserved when present.

## Usage in Pipeline

- State hints are injected into extraction prompt construction when state context is available.
- They are interpreted as extraction guidance only.

See:
- [`PROMPTS.md`](PROMPTS.md)
- [`EXTRACTION_PIPELINE.md`](EXTRACTION_PIPELINE.md)

## Maintenance Rules

When adding new hints:
1. Base the hint on repeated extraction failures from real documents.
2. Keep wording short and extraction-focused.
3. Avoid legal/compliance directives unless the code explicitly enforces them.
4. Update related tests or golden references when behavior intentionally changes.
