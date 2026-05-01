import json
import os
import shutil
from typing import Dict, List

from core.logger import logger

PROFILES_EXAMPLE_PATH = "data/carrier_profiles.example.json"

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
    HIGH_OVERALL_THRESHOLD = 0.7
    UNRELIABLE_RATIO_THRESHOLD = 0.3

    def __init__(self, kb_path="data/carrier_hints.json", profiles_path="data/carrier_profiles.json"):
        self.kb_path = kb_path
        self.profiles_path = profiles_path
        self._ensure_kb_exists()
        self.hints = self._load_hints()
        self.profiles = self._load_profiles()

    def _ensure_kb_exists(self):
        if not os.path.exists("data"):
            os.makedirs("data", exist_ok=True)
        if not os.path.exists(self.kb_path):
            with open(self.kb_path, 'w') as f:
                json.dump(DEFAULT_HINTS, f, indent=2)
        if not os.path.exists(self.profiles_path):
            if os.path.exists(PROFILES_EXAMPLE_PATH):
                shutil.copyfile(PROFILES_EXAMPLE_PATH, self.profiles_path)
            else:
                with open(self.profiles_path, "w") as f:
                    json.dump({}, f, indent=2)

    def _load_hints(self) -> Dict[str, List[str]]:
        try:
            with open(self.kb_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load Knowledge Base: {e}")
            return DEFAULT_HINTS

    def _load_profiles(self) -> Dict[str, dict]:
        try:
            with open(self.profiles_path, "r") as f:
                payload = json.load(f)
                if isinstance(payload, dict):
                    return payload
                return {}
        except Exception as e:
            logger.error(f"Failed to load carrier profiles: {e}")
            return {}

    def _save_profiles(self):
        try:
            with open(self.profiles_path, "w") as f:
                json.dump(self.profiles, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save carrier profiles: {e}")

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

    def get_hints_capped(self, carrier_name: str, max_bullets: int = 2) -> str:
        """
        Same as get_hints but limits bullets for one-shot prompt token budget.
        Returns empty string if no carrier match or no hints.
        """
        full = self.get_hints(carrier_name)
        if not full.strip():
            return ""
        bullets: List[str] = []
        for line in full.splitlines():
            line = line.strip()
            if line.startswith("- "):
                bullets.append(line)
            if len(bullets) >= max_bullets:
                break
        if not bullets:
            return ""
        return "\nCARRIER HINTS (document-specific):\n" + "\n".join(bullets) + "\n"

    def record_successful_extraction(
        self,
        carrier_name,
        document_type,
        policy_type,
        field_confidences,
    ):
        """
        Called after each successful save when overall confidence is high.
        Accumulates per-carrier field reliability data.
        """
        profile_key = f"{carrier_name}|{document_type}|{policy_type}"

        if profile_key not in self.profiles:
            self.profiles[profile_key] = {
                "carrier_name": carrier_name,
                "document_type": document_type,
                "policy_type": policy_type,
                "reliable_fields": {},
                "unreliable_fields": {},
                "sample_count": 0,
            }

        profile = self.profiles[profile_key]
        profile["sample_count"] += 1

        for field, confidence in (field_confidences or {}).items():
            if confidence == "high":
                profile["reliable_fields"][field] = (
                    profile["reliable_fields"].get(field, 0) + 1
                )
            elif confidence == "low":
                profile["unreliable_fields"][field] = (
                    profile["unreliable_fields"].get(field, 0) + 1
                )

        self._save_profiles()

    def get_profile(self, carrier_name, document_type, policy_type):
        profile_key = f"{carrier_name}|{document_type}|{policy_type}"
        return self.profiles.get(profile_key)

    def get_unreliable_fields(
        self,
        carrier_name,
        document_type,
        policy_type,
        threshold=0.3,
    ):
        """
        Returns fields where unreliable_count / sample_count >= threshold.
        Useful for telling the prompt to pay extra attention.
        """
        profile = self.get_profile(carrier_name, document_type, policy_type)
        if not profile or profile["sample_count"] < 3:
            return []

        unreliable = []
        for field, low_count in profile["unreliable_fields"].items():
            ratio = low_count / profile["sample_count"]
            if ratio >= threshold:
                unreliable.append(
                    {
                        "field": field,
                        "low_confidence_ratio": round(ratio, 2),
                    }
                )
        return unreliable
