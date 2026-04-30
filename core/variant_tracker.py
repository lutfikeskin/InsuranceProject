import json
import os
from datetime import datetime
from typing import Any

from core.logger import logger

VARIANT_DB_PATH = ".cache/layout_variants.json"


class VariantTracker:
    def __init__(self) -> None:
        self._ensure_exists()
        self.db = self._load()

    def _ensure_exists(self) -> None:
        try:
            os.makedirs(".cache", exist_ok=True)
            if os.path.exists(VARIANT_DB_PATH):
                return
            with open(VARIANT_DB_PATH, "w", encoding="utf-8") as handle:
                json.dump({"known_variants": {}, "candidates": []}, handle, indent=2)
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: failed to initialize db file: {exc}")

    def _load(self) -> dict[str, Any]:
        try:
            with open(VARIANT_DB_PATH, encoding="utf-8") as handle:
                loaded = json.load(handle)
                if not isinstance(loaded, dict):
                    raise ValueError("variant db root must be an object")
                loaded.setdefault("known_variants", {})
                loaded.setdefault("candidates", [])
                return loaded
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: failed to load db, using empty state: {exc}")
            return {"known_variants": {}, "candidates": []}

    def _save(self) -> bool:
        try:
            with open(VARIANT_DB_PATH, "w", encoding="utf-8") as handle:
                json.dump(self.db, handle, indent=2)
            return True
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: failed to save db: {exc}")
            return False

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
        try:
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
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: check_and_record fallback due to error: {exc}")
            return {"status": "known", "variant_id": "untracked"}

    def promote_to_known(self, variant_key: str, golden_path: str) -> None:
        try:
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
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: failed to promote variant {variant_key}: {exc}")

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
