import re


# Sentinel strings that, after whitespace compaction, should be treated as "no value".
# Kept in one place so extraction and services agree on the null-coercion rule.
_NULL_SENTINELS = frozenset({"null", "none", "n/a", "-"})


def clean_text(value):
    """
    Canonical text sanitizer used by extraction normalization and service-layer
    save flows. Collapses internal whitespace, strips zero-width spaces, and
    returns None for empty strings or common LLM null sentinels.

    Non-string inputs pass through unchanged (so an int limit value, for
    example, is not coerced to a string).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    compact = " ".join(value.replace("​", "").split()).strip()
    if not compact:
        return None
    if compact.lower() in _NULL_SENTINELS:
        return None
    return compact


def clean_limit_text(value):
    """
    Same as clean_text, plus a small normalization pass for limit strings:
    fixes a known OCR token split for combined cargo + deductible lines.
    """
    text = clean_text(value)
    if text is None:
        return None
    normalized = text.replace("Cargo w/", "Cargo w /").replace("Deductible", "Deductible")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def parse_currency(val):
    """
    Parses a currency string (e.g. '$1,200.00' or '1000') into a float.
    Returns 0.0 if parsing fails or input is None/Empty.
    """
    if not val:
        return 0.0
    
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).lower().strip()
    multiplier = 1.0
    
    if 'k' in s: multiplier = 1000.0
    elif 'm' in s: multiplier = 1000000.0
    
    import re
    clean = re.sub(r'[^\d.]', '', s)
    
    try:
        if not clean:
            return 0.0
        return float(clean) * multiplier
    except (ValueError, TypeError):
        return 0.0

def normalize_string(val):
    """
    Normalizes a string for comparison:
    - None/Empty -> None
    - Strips whitespace
    - Lowercases
    - 'None' string -> None
    """
    if val is None:
        return None
    
    if isinstance(val, bool):
        return val

    if isinstance(val, (int, float)):
        return val

    s = str(val).strip()
    if not s or s.lower() == 'none':
        return None
        
    return s.lower()
