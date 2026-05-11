import json
import os
from datetime import datetime
from typing import Any

from core.logger import logger

VARIANT_DB_PATH = ".cache/layout_variants.json"

_EMPTY_STATE: dict[str, Any] = {"known_variants": {}, "candidates": []}


def _load_state(path: str) -> dict[str, Any]:
    """
    Load the variant DB from `path`. Returns a fresh empty state if the file
    is missing or corrupt — those are recoverable conditions we log and move on
    from. Unexpected exceptions (permission errors that aren't OSError-typed,
    bugs in callers passing bad input) intentionally propagate.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except FileNotFoundError:
        return {**_EMPTY_STATE, "known_variants": {}, "candidates": []}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            f"VARIANT TRACKER: could not read {path} ({exc}); starting with empty state."
        )
        return {**_EMPTY_STATE, "known_variants": {}, "candidates": []}

    if not isinstance(loaded, dict):
        logger.warning(
            f"VARIANT TRACKER: {path} root was {type(loaded).__name__}, not dict; "
            "starting with empty state."
        )
        return {**_EMPTY_STATE, "known_variants": {}, "candidates": []}

    loaded.setdefault("known_variants", {})
    loaded.setdefault("candidates", [])
    return loaded


def _save_state(path: str, state: dict[str, Any]) -> None:
    """
    Persist state to `path`. Raises OSError on disk errors so the caller knows
    the write did not happen — the previous swallow-and-log pattern hid
    out-of-disk and permission failures behind successful-looking returns.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


class VariantTracker:
    def __init__(self, path: str = VARIANT_DB_PATH) -> None:
        self.path = path
        self.db = _load_state(path)

    def _save(self) -> None:
        """Persist current state. Raises OSError on disk failure."""
        _save_state(self.path, self.db)

    def _make_variant_key(self, fingerprint: str, document_type: str, policy_type: str) -> str:
        return f"{fingerprint}_{document_type}_{policy_type}"

    def check_and_record(
        self,
        fingerprint: str,
        carrier_name: str,
        document_type: str,
        policy_type: str,
        page_count: int,
        file_hash: str,
    ) -> dict[str, str]:
        known = self.db.get("known_variants", {})
        variant_key = self._make_variant_key(fingerprint, document_type, policy_type)
        carrier_name_clean = (carrier_name or "unknown").strip()

        if variant_key in known:
            known_item = known[variant_key]
            known_item["seen_count"] = known_item.get("seen_count", 1) + 1
            known_item["last_seen_hash"] = file_hash
            known_item["last_seen_at"] = datetime.utcnow().isoformat()
            self._save()
            return {"status": "known", "variant_id": variant_key}

        carrier_type_variants = [
            item
            for item in known.values()
            if item.get("carrier_name", "").lower() == carrier_name_clean.lower()
            and item.get("policy_type") == policy_type
        ]
        carrier_only_variants = [
            item
            for item in known.values()
            if item.get("carrier_name", "").lower() == carrier_name_clean.lower()
            and item.get("policy_type") != policy_type
        ]
        if carrier_type_variants:
            status = "new_layout_variant"
        elif carrier_only_variants:
            status = "new_policy_type_variant"
        else:
            status = "new_carrier"

        existing_candidate = next(
            (
                candidate
                for candidate in self.db.get("candidates", [])
                if candidate.get("variant_key") == variant_key
            ),
            None,
        )
        if existing_candidate:
            existing_candidate["seen_count"] = existing_candidate.get("seen_count", 1) + 1
            existing_candidate["last_seen_hash"] = file_hash
            existing_candidate["last_seen_at"] = datetime.utcnow().isoformat()
            self._save()
            return {"status": status, "variant_id": variant_key}

        candidate = {
            "variant_key": variant_key,
            "fingerprint": fingerprint,
            "carrier_name": carrier_name_clean or "unknown",
            "document_type": document_type,
            "policy_type": policy_type,
            "page_count": page_count,
            "file_hash": file_hash,
            "status": status,
            "seen_count": 1,
            "first_seen_at": datetime.utcnow().isoformat(),
            "promoted_to_golden": False,
        }
        self.db.setdefault("candidates", []).append(candidate)
        self._save()
        logger.info(
            "VARIANT TRACKER: "
            f"[{status}] {carrier_name_clean or 'unknown'} / {document_type} / {policy_type} "
            f"(key: {variant_key[:24]}...)"
        )
        return {"status": status, "variant_id": variant_key}

    def promote_to_known(self, variant_key: str, golden_path: str) -> None:
        # Callers (golden-set tooling under scripts/) are short-lived CLI flows;
        # a real OSError or KeyError here should surface so the operator knows
        # the promotion did not land. The previous swallow-and-warn pattern
        # made golden promotion silently no-op when the cache was unwritable.
        candidates = self.db.get("candidates", [])
        match = next(
            (candidate for candidate in candidates if candidate.get("variant_key") == variant_key),
            None,
        )
        if not match:
            return
        self.db.setdefault("known_variants", {})[variant_key] = {
            **match,
            "golden_path": golden_path,
            "promoted_to_golden": True,
        }
        candidates.remove(match)
        self._save()
        logger.info(f"VARIANT TRACKER: Promoted {variant_key[:24]}")

    def get_candidates(self, min_seen: int = 1) -> list[dict[str, Any]]:
        return [
            candidate
            for candidate in self.db.get("candidates", [])
            if candidate.get("seen_count", 1) >= min_seen
        ]

    def get_known_variants(self) -> dict[str, dict[str, Any]]:
        known = self.db.get("known_variants", {})
        if isinstance(known, dict):
            return known
        return {}
