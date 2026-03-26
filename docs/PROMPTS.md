# Prompt Engineering Guide

Rules and patterns for LLM extraction prompts. Every prompt change must be tested against the golden test suite before merging.

---

## Principles

1. **Null over guess — always**: If a field is not explicitly visible in the document, return null. Different document types contain different fields — a memorandum won't have premium, a dec page might not have drivers. This is normal, not an error. Never invent, infer, or estimate.
2. **Brevity over verbosity**: Every token in the prompt costs money × 200 docs/day. Cut ruthlessly.
3. **Specificity over generality**: "Extract the VIN from the vehicle schedule table" beats "Extract vehicle information".
4. **Registry-driven**: The LLM should map to our codes, not invent its own. Always send the filtered registry.
5. **Let the model think**: Never set `thinking_budget: 0`. For extraction calls, allow at least 1024 tokens of thinking.

---

## Prompt Templates

### Classification Prompt

Goal: Cheap, fast, accurate policy type detection. This determines which registry subset gets sent in Step 2.

```
Classify this insurance policy document.

Return ONE policy_type:
- personal_auto
- commercial_auto  
- general_liability
- commercial_package (ONLY if 2+ of: GL, Property, Auto)
- umbrella
- unknown

Also return:
- carrier_name (if visible on declarations page)
- state (2-letter code of the policy state, from declarations)
- confidence (high/medium/low)

Rules:
- Base decision on declarations page and coverage titles.
- Auto + Cargo endorsement = commercial_auto (not commercial_package).
- If unsure, return unknown.
```

Target: ~500 input tokens including schema. Output: ~50 tokens.

### Extraction Prompt

Goal: Full structured extraction with type-filtered context.

```
You are an expert insurance underwriter. Extract ALL data from this policy document.

POLICY TYPE: {policy_type}
STATE: {state}

--- DECLARATIONS ---
Extract: Carrier Name, NAIC, Policy #, Effective Date (YYYY-MM-DD), 
Expiration Date (YYYY-MM-DD), Insured Name, Address, City, State, Zip, 
Business Name, Premium (total, as integer cents — $4,200 = 420000).

Carrier = the risk bearer (insurance company), NOT the agency/broker.
If any field is not present in this document, return null. Not every document type contains every field — that is expected.

--- VEHICLES ---
Extract ALL vehicles: VIN, Year, Make, Model, GVW, Type.
Look in vehicle schedules, declarations, and endorsement pages.

--- DRIVERS ---  
Extract ALL drivers: Full Name, License #, License State, Excluded status.

--- COVERAGES ---
Map each coverage to a code from this registry:
{filtered_registry_json}

Known naming variations (map these to the correct code):
{filtered_aliases_json}

Rules:
- One COMP entry and one COLL entry PER VEHICLE (link via vehicle_vin).
- Check the deductible schedule for per-vehicle deductible amounts.
- If UM and UIM appear as a single combined line, use UMUIM_* codes.
- If they appear separately with different limits, use UM_* and UIM_* codes.
- Return null for any field not explicitly visible. Never guess.

{carrier_hints}
{state_context}

--- ENDORSEMENTS ---
List any endorsements found. For each, extract:
- Form number (e.g., "CA 20 48")
- Title
- Type: additional_insured, waiver_of_subrogation, primary_noncontributory,
        coverage_modification, coverage_extension, exclusion, federal_filing
```

### Repair Prompt

Goal: Surgical fix for specific fields that failed validation. Only called when Tier 1 validation catches a critical issue.

```
The following fields were missing or invalid in the extraction.
Re-examine the document and fix ONLY these fields:

{list_of_issues}

Example issues:
- "policy_number is null — check declarations page header"
- "effective_date format invalid — must be YYYY-MM-DD"
- "COMP coverage has no vehicle_vin — check vehicle schedule for VIN"

Return ONLY the corrected fields in the same schema structure.
```

Target: Minimal tokens — only the specific issue context + document.

---

## Token Optimization Tactics

### Registry Filtering

Instead of sending all ~40 codes every time, filter by policy_type:

| Policy Type | Codes Sent | Approx Tokens |
|-------------|-----------|---------------|
| personal_auto | 18 | ~250 |
| commercial_auto | 24 | ~320 |
| general_liability | 7 | ~100 |
| umbrella | 3 | ~50 |
| Full (unfiltered) | 40+ | ~500 |

### Registry JSON Minification

Use short keys to save tokens:

```json
// FULL (wasteful)
{"AUTO_LIAB_CSL": {"family": "auto_liability", "limit_structure": "csl", "allowed_limits": ["combined_single_limit"]}}

// MINIFIED (use this)
{"AUTO_LIAB_CSL": {"f": "auto_liability", "s": "csl", "l": ["combined_single_limit"]}}
```

Saves ~3 tokens per entry × 40 entries = ~120 tokens per call.

### Carrier Hints

Only inject hints when the carrier is detected in classification. Don't send a generic hint block every time.

### State Context

Only inject state-specific rules when relevant:

```
# Only add this block if state = TX
STATE RULES (Texas):
- UM/UIM is typically combined as a single coverage in TX.
  Use UMUIM_* codes unless clearly separated.
```

---

## Anti-Patterns

1. **Don't repeat instructions**: If the schema already constrains `policy_type` to an enum, don't also list the options in the prompt text.
2. **Don't ask for formatting**: The LLM returns structured JSON via response_schema. Don't add "format as JSON" in the prompt.
3. **Don't use negative examples**: "Don't extract the agency name as carrier" wastes tokens. Instead: "Carrier = risk bearer, not the agency/broker."
4. **Don't send page-by-page instructions**: For ≤5 page docs, the LLM sees the whole document. Don't say "on page 1, look for..." — just say what to find.
5. **Don't over-constrain**: Saying "the policy number is always in the top-right corner" will fail when it's in the top-left. Let the LLM find it.

---

## Testing Prompts

Every prompt change must be validated:

```bash
# Run the golden test suite
pytest tests/golden/ -v

# Run accuracy report
python tests/accuracy_report.py --compare baseline.json current.json
```

The accuracy report shows per-field accuracy across the test corpus. A prompt change that improves UM/UIM accuracy but degrades policy_number accuracy is a regression.

### Golden Test Structure

```
tests/golden/
├── pdfs/
│   ├── progressive_commercial_auto.pdf
│   ├── geico_personal_auto.pdf
│   ├── nationwide_gl.pdf
│   └── ... (30-50 real policies)
├── expected/
│   ├── progressive_commercial_auto.json
│   ├── geico_personal_auto.json
│   ├── nationwide_gl.json
│   └── ...
└── conftest.py
```

Each expected JSON contains the exact output we want. The test compares field-by-field and reports accuracy as a percentage.
