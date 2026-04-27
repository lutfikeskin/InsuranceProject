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
5. Build extraction prompt with registry JSON.
6. Execute one-shot Gemini structured extraction.
7. Parse JSON, map classification/policy/vehicles/drivers/coverages.
8. Normalize:
   - vehicle refinement
   - zero-value cleanup
   - coverage validation and policy-type filtering
   - summary field computation
9. Save output to local cache.

## Caching

- Local cache directory: `.cache/extraction_cache/`
- Key prefix includes `CACHE_VERSION`.
- Hash-based cache avoids repeated API usage unless `force_refresh=True`.

## Models and Schemas

- Response schema: `COMPLETE_POLICY_SCHEMA`
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

## Error Handling

- Initialization/upload/extraction failures return `(None, None, error_message)`.
- Streamlit upload UI maps technical errors to friendly user messages.

## Related Files

- `modules/extraction/prompts.py`
- `modules/extraction/schemas.py`
- `modules/extraction/pdf_ops.py`
- `modules/extraction/knowledge_base.py`
- `core/coverage_ontology.py`
