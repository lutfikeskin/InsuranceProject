# Coverage Ontology Reference

This document describes the current coverage ontology behavior used by extraction and summarization logic.

## Source of Truth

- Runtime coverage rules and summaries are implemented in `core/coverage_ontology.py`.
- This document must remain aligned with that file.

## Coverage Families

- `auto_liability`
- `uninsured_underinsured`
- `physical_damage`
- `medical_payments`
- `pip`
- `general_liability`
- `cargo`
- `umbrella_excess`

## Canonical Coverage Code Groups

### Auto Liability

- `AUTO_LIAB_CSL`
- `AUTO_LIAB_BI`
- `AUTO_LIAB_PD`
- `HIRED_AUTO`
- `NON_OWNED_AUTO`
- `HIRED_AUTO_PD`
- `TRAILER_INTERCHANGE`

### UM/UIM

- `UM_BI`
- `UM_CSL`
- `UM_PD`
- `UIM_BI`
- `UIM_CSL`
- `UMUIM_CSL`
- `UMUIM_BI`
- `UMUIM_PD`

### Physical Damage

- `COMP`
- `COLL`
- `RENTAL`
- `TOWING`
- `GAP`
- `FULL_SAFETY_GLASS`
- `LOAN_LEASE_COVERAGE`

### Medical/PIP

- `MED_PAY`
- `PIP`

### General Liability

- `GL_OCCURRENCE`
- `GL_AGGREGATE`
- `GL_PRODUCTS_COMP_OPS`
- `GL_PERSONAL_ADV_INJURY`
- `GL_DAMAGE_RENTED_PREM`
- `GL_MEDICAL_EXPENSE`
- `GL_EMPLOYEE_BENEFITS`

### Cargo

- `CARGO_LEGAL_LIAB`
- `CARGO_BROAD_FORM`
- `CARGO_REEFER`

### Umbrella/Excess

- `UMBRELLA_OCCURRENCE`
- `UMBRELLA_AGGREGATE`
- `EXCESS_LIABILITY`

## Applied Rules

### Allowed-by-Policy-Type

The pipeline checks whether a coverage is allowed for the detected `policy_type` before finalizing results (`is_coverage_allowed_for_policy_type`).

### Coverage Structure Validation

Coverage entries are validated against ontology constraints (`validate_coverage`) before inclusion in final output.

### Auto Liability CSL Supremacy

For `personal_auto` and `commercial_auto`:
- If both CSL and split auto liability entries exist, split entries are pruned in favor of CSL (`_apply_auto_liability_rules`).

### Summary Generation

Policy-level summary fields are computed from coverage entries:
- auto liability summary
- general liability summary
- cargo summary
- UM/UIM summary
- Med Pay/PIP summary
- physical damage deductible summary

These are assigned into policy fields during extraction assembly.

## Vehicle-Linked Coverages

- Coverage rows may include `vehicle_vin` and are linked to `Vehicle` objects during policy creation.
- Physical damage coverages (`COMP`, `COLL`) should typically map to specific vehicles when present in source documents.

## Maintenance Guidelines

When adjusting ontology:
1. Update `core/coverage_ontology.py`.
2. Re-run tests in `tests/` (especially extraction and policy linking tests).
3. Update:
   - `docs/ONTOLOGY.md`
   - `docs/EXTRACTION_PIPELINE.md`
   - `docs/STATE_RULES.md` if mapping behavior changes by state.
