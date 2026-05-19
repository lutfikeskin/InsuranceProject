"""
Small UI helpers shared across Streamlit views.

Kept here rather than under utils/ because they are about widget labels and
status badges — concerns that belong with the views layer, not the data layer.
"""

CONFIDENCE_LEVELS = {"high", "medium", "low"}


def build_confidence_map(
    policy_payload: dict | None,
    fallback_map: dict | None = None,
) -> dict[str, str]:
    """
    Collect per-field confidence values into a single dict.

    Two sources are merged (policy payload wins for matching keys):
      - `fallback_map`: an opt-in dict the caller already had (e.g. an earlier
        extraction's confidences carried in session state).
      - `policy_payload`: the freshly-extracted policy dict, where confidence
        rides as sibling keys named `<field>_confidence` (the extraction prompt
        contract).

    Only values in {"high", "medium", "low"} are kept.
    """
    confidence_map: dict[str, str] = {}

    source_map = fallback_map if isinstance(fallback_map, dict) else {}
    for key, value in source_map.items():
        if value in CONFIDENCE_LEVELS:
            confidence_map[str(key)] = value

    if isinstance(policy_payload, dict):
        for key, value in policy_payload.items():
            if not isinstance(key, str) or not key.endswith("_confidence"):
                continue
            base_key = key[:-11]  # strip "_confidence"
            if value in CONFIDENCE_LEVELS:
                confidence_map[base_key] = value

    return confidence_map


def confidence_label(
    base_label: str,
    field_name: str,
    confidence_map: dict[str, str],
) -> str:
    """
    Prefix a widget label with a confidence badge.

    Convention:
      high   → no prefix (the common case stays uncluttered)
      medium → ◐  (half-circle: partial confidence)
      low    → ⚠️ (warning: needs review)

    Missing entries default to "high" so unmarked fields are visually clean.
    The legend caption in process_policies should always be nearby so the
    symbols are not mystery glyphs.
    """
    conf = confidence_map.get(field_name, "high")
    if conf == "low":
        return f"⚠️ {base_label}"
    if conf == "medium":
        return f"◐ {base_label}"
    return base_label


CONFIDENCE_LEGEND_CAPTION = (
    "Field labels prefixed with **◐** are medium-confidence and **⚠️** are "
    "low-confidence extractions — verify these before saving."
)


def should_clear_field(
    field_name: str,
    confidence_map: dict[str, str],
    threshold: str,
) -> bool:
    """
    Soft confidence gate: decide whether an extracted value should be cleared
    from the review form so the user has to type it in by hand.

    `threshold` is the *minimum* confidence the user trusts:
      "off"    — gate disabled; never clear
      "medium" — clear only "low"-confidence fields (default)
      "high"   — clear both "low" and "medium" (strictest)

    Fields not present in `confidence_map` default to "high" (an LLM that
    said nothing is assumed confident — don't wipe values that didn't even
    get a confidence vote). Unknown threshold strings disable the gate to
    avoid surprises from typos in session state.
    """
    if threshold not in ("medium", "high"):
        return False  # "off" or anything unexpected
    conf = confidence_map.get(field_name, "high")
    if conf not in CONFIDENCE_LEVELS:
        return False
    if threshold == "high":
        return conf in ("low", "medium")
    # threshold == "medium"
    return conf == "low"


def gate_value(
    raw_value,
    field_name: str,
    confidence_map: dict[str, str],
    threshold: str,
    *,
    blank,
):
    """
    Convenience wrapper around `should_clear_field`. Returns `blank` if the
    field is below the threshold, otherwise returns `raw_value` unchanged.

    Pass `blank` explicitly so each call site can supply the right empty
    sentinel for its widget type:
      st.text_input  → blank=""
      st.date_input  → blank=None
      st.number_input → blank=None (or 0.0 if min_value=0.0 is set)

    Callers that need to count gated fields (e.g. for a banner) should call
    `should_clear_field` directly and track the boolean themselves.
    """
    if should_clear_field(field_name, confidence_map, threshold):
        return blank
    return raw_value
