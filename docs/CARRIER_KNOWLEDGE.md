# Carrier knowledge base and profiles

## Files

| File | Tracked in git | Purpose |
|------|------------------|---------|
| `data/carrier_hints.json` | Yes (created empty/default if missing) | Static prompt hints per carrier name (from `CarrierKnowledgeBase.DEFAULT_HINTS` seed). |
| `data/carrier_profiles.example.json` | Yes | **Reference seed** for the runtime profiles file. Shows the JSON shape only; uses generic carrier names. |
| `data/carrier_profiles.json` | **No** (gitignored) | **Runtime-accumulated** per-carrier field reliability stats from successful high-confidence extractions. |

## Runtime behavior

- On startup, `CarrierKnowledgeBase` in `modules/extraction/knowledge_base.py` ensures `data/` exists.
- If `data/carrier_profiles.json` is missing, it is created by **copying** `data/carrier_profiles.example.json` when that file exists; otherwise an empty object `{}` is written.
- Profile entries are keyed by `carrier_name|document_type|policy_type` and store counts for reliable vs unreliable field confidences (`sample_count`, `reliable_fields`, `unreliable_fields`). This is **statistics only** — no policy numbers, insured names, or other PII.

## Operations

- To reset local stats: delete `data/carrier_profiles.json` and restart the app; the file will be re-seeded from the example (or start empty if the example is removed).
- Do not commit `carrier_profiles.json`; it reflects your local runtime history.

## Related code

- `modules/extraction/knowledge_base.py` — `CarrierKnowledgeBase`, `record_successful_extraction`, `get_unreliable_fields`
