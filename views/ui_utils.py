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
