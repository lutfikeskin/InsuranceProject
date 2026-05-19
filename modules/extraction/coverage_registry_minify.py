"""Token-compact coverage registry JSON for prompts."""

import json
from functools import lru_cache

from core.coverage_ontology import COVERAGE_REGISTRY, POLICY_TYPE_CONSTRAINTS


@lru_cache(maxsize=16)
def get_cached_registry_json(policy_type: str) -> str:
    """Cached generation of the registry JSON string to save tokens/CPU."""
    filtered_registry = {}
    constraints = POLICY_TYPE_CONSTRAINTS.get(policy_type)

    def _minify(entry):
        return {
            "f": entry["family"],
            "s": entry["limit_structure"],
            "l": entry.get("allowed_limits", []),
        }

    if constraints:
        allowed = set(constraints.get("allowed_families", []))
        forbidden = set(constraints.get("forbidden_codes", []))
        for code, entry in COVERAGE_REGISTRY.items():
            if entry["family"] in allowed and code not in forbidden:
                filtered_registry[code] = _minify(entry)
    else:
        for code, entry in COVERAGE_REGISTRY.items():
            filtered_registry[code] = _minify(entry)

    return json.dumps(filtered_registry, separators=(",", ":"))
