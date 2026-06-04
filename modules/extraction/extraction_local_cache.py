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
        cache_path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r") as f:
                logger.info(f"CACHE HIT: {key}")
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            # Corrupt or unreadable cache entry — log and miss-through so the
            # caller re-extracts. Anything else is a real bug worth raising.
            logger.error(f"Cache Read Error for {key}: {exc}")
            return None

    def save(self, file_hash: str, data: dict, cache_scope: str = "auto"):
        key = self._result_storage_key(file_hash, cache_scope)
        cache_path = os.path.join(self.cache_dir, f"{key}.json")
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"CACHE SAVED: {key}")
        except OSError as exc:
            # Disk full / permission issues should not break extraction itself.
            # TypeError (non-serializable payload) is a real bug — let it raise.
            logger.error(f"Cache Write Error for {key}: {exc}")

    def get_gemini_cache_meta(self, file_hash: str) -> Optional[dict]:
        """Returns persisted Gemini cache metadata for this file hash, if any."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug(f"Gemini cache meta read error: {exc}")
            return None
        return index.get(f"{CACHE_VERSION}_{file_hash}")

    def save_gemini_cache_meta(
        self, file_hash: str, cache_name: str, expire_time, model: str
    ):
        """Persists Gemini cache metadata so repeated runs can reuse active cache.

        expire_time may arrive as a datetime (from the Gemini SDK) or as an
        ISO string. We normalize to ISO string here so JSON serialization
        stays safe and get_reusable_cache can re-parse it consistently.
        """
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug(f"Gemini cache meta read failed before write: {exc}")
            index = {}
        expire_time_str: Optional[str]
        if expire_time is None:
            expire_time_str = None
        elif hasattr(expire_time, "isoformat"):
            expire_time_str = expire_time.isoformat()
        else:
            expire_time_str = str(expire_time)
        index[f"{CACHE_VERSION}_{file_hash}"] = {
            "cache_name": cache_name,
            "expire_time": expire_time_str,
            "model": model,
        }
        try:
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except OSError as exc:
            logger.debug(f"Gemini cache meta write error: {exc}")

    def mark_non_cacheable(self, file_hash: str, reason: str):
        """Remember that this hash should skip cache-create attempts."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug(f"Non-cacheable marker read failed before write: {exc}")
            index = {}
        key = f"{CACHE_VERSION}_{file_hash}_cacheability"
        index[key] = {"non_cacheable": True, "reason": reason}
        try:
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except OSError as exc:
            logger.debug(f"Non-cacheable marker write error: {exc}")

    def is_marked_non_cacheable(self, file_hash: str) -> bool:
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug(f"Non-cacheable marker read error for {file_hash}: {exc}")
            return False
        key = f"{CACHE_VERSION}_{file_hash}_cacheability"
        return bool(index.get(key, {}).get("non_cacheable"))
