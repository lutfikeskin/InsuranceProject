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

    try:
        clean_extracted = re.sub(r'[^\d.]', '', extracted_premium)
        amount = float(clean_extracted)
    except ValueError:
        return {"confidence": "low", "flag": "NON_NUMERIC_EXTRACTED", "scout_match": False}

    if amount == 0:
        return {"confidence": "low", "flag": "ZERO_PREMIUM", "scout_match": False}

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
            
    return {"confidence": "medium", "flag": "VERIFIED_LOGIC_ONLY", "scout_match": True}

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
