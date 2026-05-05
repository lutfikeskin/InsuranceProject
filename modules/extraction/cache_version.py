"""Auto-derived extraction cache version (prompt + schema hash)."""

import hashlib
import json
from typing import Tuple

from core.logger import logger

from .schemas import (
    CLASSIFICATION_SCHEMA,
    COMPLETE_POLICY_SCHEMA,
    COI_SUMMARY_SCHEMA,
    ENDORSEMENT_SCHEMA,
)
from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    get_extract_all_prompt,
    get_extract_coi_prompt,
    get_extract_endorsement_prompt,
)

POLICY_TYPE_ENUM: Tuple[str, ...] = tuple(
    CLASSIFICATION_SCHEMA["properties"]["policy_type"]["enum"]
)


def _compute_cache_version() -> str:
    full_prompt_variants = "".join(
        get_extract_all_prompt(
            "__REGISTRY_PLACEHOLDER__",
            scoped_policy_type=policy_type,
            unreliable_fields=["__UNRELIABLE_FIELD__"],
        )
        for policy_type in POLICY_TYPE_ENUM
    )
    content = (
        CLASSIFY_POLICY_PROMPT
        + get_extract_coi_prompt()
        + get_extract_endorsement_prompt()
        + full_prompt_variants
        + json.dumps(COMPLETE_POLICY_SCHEMA, sort_keys=True)
        + json.dumps(COI_SUMMARY_SCHEMA, sort_keys=True)
        + json.dumps(ENDORSEMENT_SCHEMA, sort_keys=True)
    )
    return hashlib.md5(content.encode()).hexdigest()[:8]


CACHE_VERSION = f"v_auto_{_compute_cache_version()}"
logger.info(f"Extraction cache version: {CACHE_VERSION}")
