# COI Creation Flow Audit + Fix Plan

## Context
- Scope confirmed: current COI creation page only, not upstream extraction/import flow.
- Entry points: sidebar `Create COI`, Dashboard/Database buttons pass `st.session_state["coi_policy_id"]` into `views/create_coi.py`.
- Current flow: select policy → choose COI type → quick-fill/add holder → edit insured details → toggle coverages → build `policy_data`/`holder_data` → `COIGenerator.generate_coi()` fills ACORD PDF → single download/Gmail link or bulk ZIP.
- Target outcome: bug audit, improvement suggestions, and prioritized fix plan.

## Approach
- Keep single policy based flow.
- Fix correctness first: additional-insured codes, GL limits, legal insurer name, required-data validation.
- Improve resilience: holder-library errors, bulk partial failures, session-state staleness.
- Improve UX: completeness warnings, editable coverage fields, clearer email behavior.
- Strengthen tests by asserting PDF text/fields and fixing ineffective bulk test.

## Current architecture
- `views/create_coi.py`
  - UI/state orchestration.
  - Builds default description with `COIService.prepare_coi_data()`.
  - Builds final generation payload with local `prepare_p_data()`.
  - Records telemetry for single/bulk generation.
- `core/services.py` / `COIService.prepare_coi_data()`
  - Generates description lines from vehicles, drivers, compliance, BAP symbols, UM/HNOA details.
  - Also creates a `p_data` payload, but Create COI mostly does not use it.
- `modules/coi/generator.py`
  - Loads `mapping.json` and `data/COI Example.pdf` per generation.
  - Fills PDF with `pypdf`, then flattens with `fitz` if present.
- `modules/coi/holders.py`
  - Loads/appends certificate holder records in `data/coi_holders.json`.
- `modules/coi/mapping.json`
  - Maps logical COI fields to PDF fields.

## Issues found

### High severity
1. **Certificate Holder COI writes `N` into ADDL INSD instead of clearing column**
   - Code: `modules/coi/generator.py:88-94`, `180-183`.
   - UI help says Certificate Holder “clears the ADDL INSD column”. Generator sets `N`.
   - Risk: final ACORD form shows explicit `N`; may be unacceptable or confusing.
   - Fix: use `""` for Certificate Holder; add PDF assertion test.

2. **GL occurrence limit ignores `general_liability_limit`**
   - Code: `views/create_coi.py:493-500`, `modules/coi/generator.py:70-74`, `143-148`.
   - `general_liability_limit` exists and default aggregate inspects it, but generated GL occurrence/person-ad limit uses `liability_limit`.
   - Risk: GL section can show auto liability limit, especially on mixed GL/Auto policies.
   - Fix: add explicit `gl_occurrence_limit`/`general_liability_limit` payload and editable UI field; generator should prefer GL-specific limit for GL rows.

3. **Legal insurer/underwriter rule documented but not implemented in Create COI generation**
   - Docs: `docs/COI_WORKFLOW.md:35-38` says use `underwriter_name` fallback to `carrier_name`.
   - `COIService.prepare_coi_data()` includes `underwriter_name` (`core/services.py:1599-1602`), but `views/create_coi.py:493-495` sends only `carrier_name`; generator uses `carrier_name` (`modules/coi/generator.py:136-138`).
   - Risk: ACORD insurer field may show brand/MGA instead of legal insurer.
   - Fix: payload insurer name = `p.underwriter_name or p.carrier_name`; expose/edit label as “Insurer legal name”.

4. **Generate action allows materially incomplete COIs**
   - Code validates only holder name and lienholder vehicle selection (`views/create_coi.py:519-523`, `618-622`).
   - No blocking/warning for missing carrier, NAIC, policy number, dates, limits, insured address, selected coverage with empty limit, or missing comp/coll deductibles for lienholders.
   - Risk: valid-looking PDFs with blank core ACORD fields.
   - Fix: add validation summary before generation; block critical missing fields or require user override.

5. **Coverage checkbox defaults can silently omit coverage when boolean is `None`**
   - Code: `views/create_coi.py:455-473` uses `bool(p.has_general_liability)` / `bool(p.has_auto_liability)`.
   - Old rows or uncertain data with `None` become unchecked even if limits/policy type imply coverage.
   - Risk: user generates COI missing GL/Auto sections.
   - Fix: default from explicit boolean when not `None`, otherwise infer from limits/coverage rows/policy type and show “inferred” note.

### Medium severity
6. **Bulk generation aborts whole batch on one holder failure**
   - Code: one `try` wraps whole loop (`views/create_coi.py:633-666`).
   - `failed_count` only increments when generator returns falsey; exceptions skip rest and no ZIP download.
   - Fix: per-holder try/except; continue batch; show failed holder list; record partial-success telemetry.

7. **Bulk success message can report `0` generated and still offer ZIP**
   - Code: `views/create_coi.py:667-675`.
   - Fix: if `generated_count == 0`, show error and suppress ZIP download.

8. **Lienholder PDF can show blank comp/coll deductible lines**
   - Code: description uses `—` (`views/create_coi.py:110-119`), but PDF fields use blank values (`modules/coi/generator.py:96-101`, `172-175`).
   - Risk: Other Policy box says `Comp Ded:` / `Coll Ded:` with no values.
   - Fix: validate or display `—` consistently; preferably require missing deductible confirmation.

9. **General aggregate UI is limited to only `$1M` or `$2M`**
   - Code: `GL_AGGREGATE_OPTIONS`, `views/create_coi.py:463-467`.
   - Risk: cannot represent $500k/$5M/custom aggregate.
   - Fix: replace radio with select + custom amount input.

10. **Cargo checkbox can appear checked for non-values like `"null"`, then generator omits cargo**
    - Code: UI uses `bool(p.cargo_limit)` (`views/create_coi.py:476-479`); generator cleans non-money to empty and disables cargo (`modules/coi/generator.py:77-83`).
    - Risk: UI says cargo included, PDF omits it.
    - Fix: normalize nullish strings before checkbox default and show parsed limit preview.

11. **Holder library invalid JSON/non-list can crash or empty page state**
    - `load_coi_holders()` catches JSON decode only; non-list raises `COIHolderError`.
    - `append_coi_holder()` can surface raw JSON errors not caught by page.
    - Fix: catch `COIHolderError`/`JSONDecodeError` on page load and add repair/reload UX.

12. **Holder data quality affects UX/email**
    - Current `data/coi_holders.json`: 161 holders; 24 missing state or zip; 6 have slash-separated email strings.
    - Gmail `to=` may be invalid for slash-separated emails.
    - Fix: add holder validation badges; support multiple emails as comma-separated list; normalize imported data.

13. **Default description can go stale for same policy id**
    - Code: state key only tracks COI type, selected vehicles, holder name (`views/create_coi.py:361-379`, `398-412`).
    - If policy data changes while same id selected, old session description remains.
    - Fix: include policy `updated_at` if added, or a hash of vehicle/driver/compliance fields; add “Reset description from policy” button.

14. **No COI readiness/completeness feedback on Create COI page**
    - `PolicyService.compute_completeness_score()` exists elsewhere, but page does not show it.
    - Risk: user discovers missing data only after PDF review.
    - Fix: show readiness badge and missing fields above Generate.

### Low severity / future risk
15. **`prepare_p_data()` duplicates service payload logic**
    - `COIService.prepare_coi_data()` creates a payload, but Create COI rebuilds another partial payload.
    - Risk: drift already visible with `underwriter_name`.
    - Fix: centralize in `COIService.build_generation_payload(policy, overrides)`.

16. **Generator reloads mapping and template per PDF**
    - Fine for small batches; inefficient for larger holder lists.
    - Fix: cache field map; optionally preload template reader per `COIGenerator` instance.

17. **PDF mapping uses mixed full/terminal field names**
    - Smoke test shows output fills, but direct field validation reports mixed names.
    - Risk: brittle on template changes.
    - Fix: normalize mapping to full field names and add mapping-validation test.

18. **Email body says “attached COI” while Gmail opens without attachment**
    - Warning exists, but body still claims attachment.
    - Fix: keep warning and adjust body or add stronger pre-send note.

19. **No PDF preview/regeneration history**
    - User must download to inspect; generated link disappears on rerun.
    - Fix: optional preview/download state and recent generated output summary.

## Files to modify
- `views/create_coi.py`
- `modules/coi/generator.py`
- `modules/coi/holders.py`
- `modules/coi/mapping.json` (if normalizing field names)
- `core/services.py` (new centralized COI payload helper)
- `docs/COI_WORKFLOW.md`
- `tests/test_bulk_logic.py`
- Add/update tests under `tests/` for PDF field/text behavior and UI helper functions.

## Reuse
- Reuse `COIService.prepare_coi_data()` description logic.
- Reuse `PolicyService.compute_completeness_score()` for readiness banner.
- Reuse `_safe_coi_pdf_filename()` for bulk ZIP entries.
- Reuse `modules/coi/holders.py` normalization functions; extend them for validation.
- Reuse telemetry events; add partial-success metadata.

## Fix plan
- [ ] Create centralized `COIService.build_generation_payload(policy, overrides)` used by Create COI single and bulk paths.
- [ ] Implement legal insurer fallback: `underwriter_name or carrier_name`; update UI label/docs.
- [ ] Add GL-specific fields: occurrence limit, aggregate limit, products aggregate; support custom aggregate.
- [ ] Fix ADDL INSD behavior: Additional Insured = `Y`; Certificate Holder = blank; Lienholder business rule confirmed then `Y` or blank.
- [ ] Normalize nullish coverage values before checkbox defaults.
- [ ] Add pre-generation validation panel with block/warn/override levels.
- [ ] Make bulk loop per-holder fault tolerant; show generated/failed table and suppress empty ZIP.
- [ ] Add holder-library load/append error handling and validation hints.
- [ ] Add “Reset description from policy” button and stale-description detection.
- [ ] Update Gmail body/link UX for missing attachment and multi-recipient emails.
- [ ] Fix `tests/test_bulk_logic.py` so assertions fail normally; add PDF text/field assertions for insurer, insured, ADDL INSD, GL, cargo, lienholder.

## Verification
- Already run: `pytest -q tests/test_coi_holders.py tests/test_coi_vehicle_description.py tests/test_bulk_logic.py` → `13 passed`, but bulk test currently ineffective due swallowed exceptions.
- Add/run tests:
  - Single COI PDF contains legal insurer, insured, holder, policy number, dates.
  - Certificate Holder COI leaves ADDL INSD blank.
  - GL occurrence uses GL-specific limit; aggregate supports custom value.
  - Lienholder requires selected vehicles and handles comp/coll deductibles.
  - Cargo `"null"`/empty values do not default checkbox on.
  - Bulk generation continues after one holder failure and does not offer empty ZIP.
  - Holder JSON invalid/non-list displays recoverable error.
- Manual Streamlit checks:
  - Navigation from Dashboard/Database opens selected policy.
  - Switching policy resets holder/description safely.
  - Single and bulk downloads produce expected filenames.
  - Gmail link opens with correct recipient(s), subject, and warning.

## Implementation completed
- Centralized Create COI PDF payload construction in `COIService.build_generation_payload(...)`.
- Updated Create COI to use legal insurer/underwriter fallback, editable coverage limits, custom GL aggregate, null-safe coverage defaults, validation summaries, reset-description buttons, and normalized Gmail recipients.
- Fixed Certificate Holder ADDL INSD behavior in `COIGenerator` to leave columns blank.
- Updated generator GL logic to prefer GL-specific limits before auto liability limits.
- Hardened bulk generation so per-holder failures do not abort the batch and empty ZIP downloads are suppressed.
- Strengthened tests by fixing the previously swallowed bulk assertions and adding PDF/text/helper coverage for ADDL INSD, GL limits, underwriter fallback, nullish limits, and email normalization.
- Updated `docs/COI_WORKFLOW.md` to reflect the current behavior.

## Verification completed
- `python3 -m py_compile views/create_coi.py core/services.py modules/coi/generator.py` → OK.
- `pytest -q tests/test_bulk_logic.py tests/test_coi_holders.py tests/test_coi_vehicle_description.py` → 17 passed.
- `pytest tests/ -q --ignore=tests/test_accuracy.py` → 58 passed, 1 skipped.
- Final verification: `python3 -m py_compile views/create_coi.py core/services.py modules/coi/generator.py && pytest tests/ -q --ignore=tests/test_accuracy.py` → 58 passed, 1 skipped.
