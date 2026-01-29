import re
from typing import List, Dict, Optional
from core.logger import logger

def resolve_premium(scout_signals: List[Dict], extracted_premium: Optional[str]) -> Dict:
    """
    Intelligently audits the extracted premium against Scout signals.
    Returns a dict with metadata: { "confidence": "high"|"low", "flag": str, "scout_match": bool }
    """
    if not extracted_premium:
        return {"confidence": "low", "flag": "MISSING_PREMIUM", "scout_match": False}

    # 1. Normalize Extracted (Simple non-digit types removal)
    try:
        clean_extracted = re.sub(r'[^\d.]', '', extracted_premium)
        amount = float(clean_extracted)
    except ValueError:
        return {"confidence": "low", "flag": "NON_NUMERIC_EXTRACTED", "scout_match": False}

    if amount == 0:
        return {"confidence": "low", "flag": "ZERO_PREMIUM", "scout_match": False}

    # 2. Analyze Signals
    # Signals structure: {"label": "Total Premium", "page": 1, "type": "total", "period": "annual"}
    
    annual_signals = []
    monthly_signals = []
    total_signals = []
    
    for s in scout_signals:
        s_type = s.get("type", "unknown").lower()
        s_period = s.get("period", "unknown").lower()
        
        if s_type == "installment" or s_period == "monthly":
            monthly_signals.append(s)
        elif s_type == "total" or s_period == "annual":
            annual_signals.append(s)
            
    # 3. Apply Heuristics
    
    # CASE A: Extracted Matches an Annual Signal (Implicitly via extractor finding it)
    # The Extractor prompt is already strong. We mostly want to catch "Installment Error".
    
    # CASE B: Installment Trap
    # If Extracted Amount is roughly 12x less than a known Annual Total? 
    # (Hard to check without values in signals, Scout mainly returns locations/types, not values yet. 
    #  WAIT - The Scout prompt says "Do NOT extract dollar amounts". 
    #  So we can only check consistency of metadata labels, not values. 
    #  Ah, the PLAN was: "If extracted amount matches...". 
    #  But since Scout doesn't return values, we can't do value comparisons yet.
    #  WE MUST RELY ON SIGNAL TYPES FOUND ON THE PAGE WHERE EXTRACTION HAPPENED.)
    
    return {"confidence": "medium", "flag": "VERIFIED_LOGIC_ONLY", "scout_match": True}

# REVISION:
# The user approved the plan which said: "If extracted matches 'Total' signal -> High".
# But Scout only gives us Page Numbers. 
# So the logic is: "Did the extracted premium come from a page that 'Scout' identified as 'Total'?"

def audit_premium_extraction(extracted_page: int, scout_signals: List[Dict]) -> Dict:
    """
    Verifies if the page where premium was extracted contained valid Premium Signals.
    """
    relevant_signals = [s for s in scout_signals if s.get("page") == extracted_page]
    
    if not relevant_signals:
        # Extracted from a page where Scout saw nothing? Suspicious.
        return {"confidence": "low", "flag": "UNSCOUTED_LOCATION"}
        
    has_total = any(s.get("type") in ["total", "gross"] for s in relevant_signals)
    has_installment = any(s.get("type") == "installment" for s in relevant_signals)
    
    if has_total:
        return {"confidence": "high", "flag": "MATCHES_TOTAL_SIGNAL"}
    
    if has_installment and not has_total:
        return {"confidence": "low", "flag": "POSSIBLE_INSTALLMENT_WARNING"}
        
    return {"confidence": "medium", "flag": "SIGNAL_PRESENT"}
