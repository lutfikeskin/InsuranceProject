# Extraction Pipeline

This document describes the implemented extraction path in `modules/extraction/pipeline.py`.

## Entry Point

- Public wrapper: `modules.extraction.process_pdf(file_bytes, api_key, ...)`
- Runtime class: `GeminiExtractionPipeline`
- Main method: `GeminiExtractionPipeline.run(...)`

## Pipeline Stages

1. Build `PdfProcessor` and `ExtractionContext`.
2. Compute file hash and check local extraction cache.
3. Upload PDF to Gemini File API.
4. Optionally create temporary Gemini cached content context.
5. Classify document type and policy type for routing.
6. Build the extraction prompt for the routed document type with registry JSON.
7. Execute one-shot Gemini structured extraction.
8. Parse JSON, map classification/policy/vehicles/drivers/coverages.
9. Normalize:
   - vehicle refinement
   - zero-value cleanup
   - coverage validation and policy-type filtering
   - summary field computation
10. Save output to local cache.

## Document Routing

The pipeline first determines `document_type` and routes to an extraction goal from `core/document_taxonomy.py`:

- `declarations_page`, `renewal_declarations`, `unknown` -> full policy extraction
- `certificate_of_insurance`, `memorandum` -> COI summary extraction
- `endorsement` -> endorsement metadata extraction
- `quote`, `application` -> non-extractable response

When a user manually selects `policy_type`, the pipeline still classifies `document_type` so COIs and endorsements continue to use the smaller, specialized prompts. The selected policy type remains fixed in the final classification.

## COI and Memorandum Normalization

COI/memorandum extraction uses `COI_SUMMARY_SCHEMA` and then normalizes the summary into the standard `policy` shape used by review and save flows.

- `insured.address`, `insured.city`, `insured.state_code`, and `insured.zip` are preserved when the model returns structured fields.
- If a COI returns only one insured address line, normalization splits city/state/ZIP only for clear US endings such as `5074 LINDORA DR COLUMBUS, OH 43232`.
- `MEDICAL PAYMENTS INCL` and similar Med Pay included signals are preserved as a textual `med_pay_limit` instead of being dropped.
- `has_general_liability` and `has_auto_liability` are inferred from visible policy rows/limits and default to `False` when evidence is missing.

## Caching

- Local cache directory: `.cache/extraction_cache/`
- Key prefix includes `CACHE_VERSION`.
- Hash-based cache avoids repeated API usage unless `force_refresh=True`.

## Models and Schemas

- Full policy response schema: `COMPLETE_POLICY_SCHEMA`
- COI/memorandum response schema: `COI_SUMMARY_SCHEMA`
- Endorsement response schema: `ENDORSEMENT_SCHEMA`
- Classification and section schemas are in `modules/extraction/schemas.py`.

## Cost and Usage Controls

- Usage logging: `UsageService.log_usage(...)`
- Budget guard: `UsageService.is_over_budget(...)` against `DEFAULT_DAILY_BUDGET`
- Daily usage stats used in Streamlit sidebar metrics

## Validation and Cleaning Rules

- Coverage eligibility by policy type (`is_coverage_allowed_for_policy_type`)
- Coverage structure validation (`validate_coverage`)
- Auto-liability CSL supremacy cleanup in auto policy types
- Zero-valued structured integer fields converted to null-like values

## Output Shape

The final extraction result includes:
- `policy`
- `coverages`
- `vehicles`
- `drivers`
- `classification`
- `page_dimensions`

Carrier-related policy fields include:

- `policy.carrier_name` (brand)
- `policy.underwriter_name` (legal insurer when present)

## Error Handling

- Initialization/upload/extraction failures return `(None, None, error_message)`.
- Streamlit upload UI maps technical errors to friendly user messages.

## Related Files

- `modules/extraction/prompts.py`
- `modules/extraction/schemas.py`
- `modules/extraction/pdf_ops.py`
- `modules/extraction/knowledge_base.py`
- `core/coverage_ontology.py`
