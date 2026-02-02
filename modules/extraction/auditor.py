
from typing import Dict, List, Tuple, Any
import requests
import re
from datetime import datetime
from core.logger import logger
from .prompts import GLOBAL_EXTRACTION_PRINCIPLES

class Auditor:
    """
    Tiered Verification System.
    
    Tier 1 (Free): Python-based logic checks (Nulls, Regex, Consistency).
    Tier 2 (Paid): Generates specific prompts for LLM correction.
    """

    @staticmethod
    def quick_validate(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        TIER 1 CHECK: Fast, Free, Python-based.
        Returns: (passed: bool, errors: list[str])
        """
        errors = []
        policy = data.get("policy", {})
        
        # 1. Critical Policy Fields
        if not policy.get("policy_number"):
            errors.append("Missing Policy Number")
        
        # 2. Insured Info (Specific to the "Target Memo" issue)
        if not policy.get("insured_name"):
             errors.append("Missing Insured Name")
        
        # Check for address completeness if address is present
        addr = policy.get("insured_address")
        if addr and len(addr) < 5:
             errors.append("Insured Address seems invalid or too short")

        # 3. Dates
        eff = policy.get("effective_date")
        curr_year = datetime.now().year
        if eff:
            try:
                # Basic sanity check (Are we extracting a year 1900 or 2100?)
                # Assuming YYYY-MM-DD
                year = int(eff.split("-")[0])
                if year < 2000 or year > (curr_year + 5):
                    errors.append(f"Suspicious Effective Year: {year}")
            except:
                pass # Date parsing is handled elsewhere, we just sanity check here
        else:
             errors.append("Missing Effective Date")

        # 4. Coverages (Logical Consistency)
        # If policy type is Auto, we EXPECT Auto Liability
        p_type = data.get("classification", {}).get("policy_type", "unknown")
        if "auto" in p_type:
            has_al = any(c.get("family") == "auto_liability" for c in data.get("coverages", []))
            if not has_al:
                 errors.append("Auto Policy missing Auto Liability Coverage")

        # 5. Vehicles (Validation)
        # If we have vehicles, check VIN structure
        for v in data.get("vehicles", []):
            vin = v.get("vin")
            if vin:
                # Basic VIN regex (exclude I, O, Q) - relaxed for now
                if len(vin) != 17:
                     errors.append(f"Invalid VIN Length ({len(vin)}): {vin}")

        if errors:
            logger.warning(f"AUDITOR TIER 1 FAILED: {errors}")
            return False, errors
            
        return True, []

    @staticmethod
    def generate_repair_prompt(errors: List[str], current_section_json: Dict) -> str:
        """
        TIER 2 PROMPT: Generates a surgical prompt to fix specific errors.
        """
        error_text = "\n- ".join(errors)
        
        return GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are a QA Auditor fixing a failed extraction.
    
    The previous extraction resulted in the following ERRORS:
    - {error_text}
    
    CURRENT JSON DATA (Incomplete/Incorrect):
    {current_section_json}
    
    TASK:
    1. Re-examine the document specifically looking for the MISSING or INCORRECT items above.
    2. Correct the JSON.
    3. Return the COMPLETE, CORRECTED JSON object.
    
    IF the information is TRULY missing from the document, keep the field as null, but double-check headers, footers, and sidebars first.
    """
