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
