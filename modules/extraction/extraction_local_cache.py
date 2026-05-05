"""Local JSON extraction cache and Gemini cached-content bookkeeping."""

import json
import os
from typing import Optional

from core.logger import logger

from .cache_version import CACHE_VERSION


def extraction_result_cache_scope(user_policy_type: Optional[str]) -> str:
    """Scope segment for local JSON extraction cache (auto vs manual selection)."""
    if not user_policy_type:
        return "auto"
    return f"manual_{user_policy_type}"


class ExtractionCache:
    def __init__(self, cache_dir=".cache/extraction_cache"):
        self.cache_dir = cache_dir
        self.index_file = os.path.join(cache_dir, "index.json")
        self._ensure_cache_exists()

    def _ensure_cache_exists(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        if not os.path.exists(self.index_file):
            with open(self.index_file, "w") as f:
                json.dump({}, f)

    @staticmethod
    def _result_storage_key(file_hash: str, cache_scope: str) -> str:
        """Filesystem-safe key for cached extraction JSON (scope avoids cross-mode hits)."""
        return f"{CACHE_VERSION}_{cache_scope}_{file_hash}"

    def get(self, file_hash: str, cache_scope: str = "auto") -> Optional[dict]:
        key = self._result_storage_key(file_hash, cache_scope)
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            if os.path.exists(cache_path):
                with open(cache_path, "r") as f:
                    logger.info(f"CACHE HIT: {key}")
                    return json.load(f)
        except Exception as e:
            logger.error(f"Cache Read Error: {e}")
        return None

    def save(self, file_hash: str, data: dict, cache_scope: str = "auto"):
        key = self._result_storage_key(file_hash, cache_scope)
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"CACHE SAVED: {key}")
        except Exception as e:
            logger.error(f"Cache Write Error: {e}")

    def get_gemini_cache_meta(self, file_hash: str) -> Optional[dict]:
        """Returns persisted Gemini cache metadata for this file hash, if any."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            return index.get(f"{CACHE_VERSION}_{file_hash}")
        except Exception as e:
            logger.debug(f"Gemini cache meta read error: {e}")
            return None

    def save_gemini_cache_meta(
        self, file_hash: str, cache_name: str, expire_time: Optional[str], model: str
    ):
        """Persists Gemini cache metadata so repeated runs can reuse active cache."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            index[f"{CACHE_VERSION}_{file_hash}"] = {
                "cache_name": cache_name,
                "expire_time": expire_time,
                "model": model,
            }
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except Exception as e:
            logger.debug(f"Gemini cache meta write error: {e}")

    def mark_non_cacheable(self, file_hash: str, reason: str):
        """Remember that this hash should skip cache-create attempts."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            key = f"{CACHE_VERSION}_{file_hash}_cacheability"
            index[key] = {"non_cacheable": True, "reason": reason}
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except Exception as e:
            logger.debug(f"Non-cacheable marker write error: {e}")

    def is_marked_non_cacheable(self, file_hash: str) -> bool:
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            key = f"{CACHE_VERSION}_{file_hash}_cacheability"
            return bool(index.get(key, {}).get("non_cacheable"))
        except Exception:
            return False
