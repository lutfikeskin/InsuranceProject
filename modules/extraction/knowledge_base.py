
import json
import os
from typing import Dict, List
from core.logger import logger

DEFAULT_HINTS = {
    "GEICO": [
        "Effective dates for GEICO are often found on the top right corner of the 'Declarations' page.",
        "Drivers are often listed on a separate page titled 'Driver Information' or 'Operator Schedule'."
    ],
    "PROGRESSIVE": [
        "Vehicle VINs are often listed in a horizontal table on the first page.",
        "Policy number usually starts with 0 or 1 and is 8-10 digits."
    ],
    "LIBERTY MUTUAL": [
        "Differentiate between 'Policy Mailing Date' and 'Policy Effective Date'.",
        "Coverages are often split across 'Auto' and 'General Liability' sections clearly."
    ]
}

class CarrierKnowledgeBase:
    def __init__(self, kb_path="data/carrier_hints.json"):
        self.kb_path = kb_path
        self._ensure_kb_exists()
        self.hints = self._load_hints()

    def _ensure_kb_exists(self):
        if not os.path.exists("data"):
            os.makedirs("data", exist_ok=True)
        if not os.path.exists(self.kb_path):
            with open(self.kb_path, 'w') as f:
                json.dump(DEFAULT_HINTS, f, indent=2)

    def _load_hints(self) -> Dict[str, List[str]]:
        try:
            with open(self.kb_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load Knowledge Base: {e}")
            return DEFAULT_HINTS

    def get_hints(self, carrier_name: str) -> str:
        """
        Returns a formatted string of hints for the prompt, or empty string.
        """
        if not carrier_name:
            return ""
            
        normalized_target = carrier_name.lower()
        
        found_hints = []
        for name, hints in self.hints.items():
            if name.lower() in normalized_target or normalized_target in name.lower():
                found_hints.extend(hints)
                
        if not found_hints:
            return ""
            
        return "\nCARRIER KNOWLEDGE BASE HINTS:\n" + "\n".join([f"- {h}" for h in found_hints]) + "\n"
