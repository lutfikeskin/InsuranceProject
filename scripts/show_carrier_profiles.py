from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.extraction.knowledge_base import CarrierKnowledgeBase


def _safe_ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 2)


def main() -> None:
    kb = CarrierKnowledgeBase()
    profiles = kb.profiles or {}
    if not profiles:
        print("No carrier profiles recorded yet.")
        return

    grouped: dict[str, list[dict]] = {}
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        carrier = profile.get("carrier_name") or "Unknown"
        grouped.setdefault(carrier, []).append(profile)

    for carrier in sorted(grouped.keys()):
        print(f"\n=== {carrier} ===")
        carrier_profiles = sorted(
            grouped[carrier],
            key=lambda p: (
                str(p.get("document_type") or ""),
                str(p.get("policy_type") or ""),
            ),
        )
        for profile in carrier_profiles:
            sample_count = int(profile.get("sample_count") or 0)
            document_type = profile.get("document_type") or "unknown"
            policy_type = profile.get("policy_type") or "unknown"
            print(f"- {document_type} | {policy_type} | samples={sample_count}")

            reliable = profile.get("reliable_fields") or {}
            unreliable = profile.get("unreliable_fields") or {}
            fields = sorted(set(reliable.keys()) | set(unreliable.keys()))
            if not fields:
                print("  (no field confidence history)")
                continue

            for field in fields:
                hi_count = int(reliable.get(field) or 0)
                low_count = int(unreliable.get(field) or 0)
                print(
                    f"  - {field}: "
                    f"high={hi_count} ({_safe_ratio(hi_count, sample_count)}), "
                    f"low={low_count} ({_safe_ratio(low_count, sample_count)})"
                )


if __name__ == "__main__":
    main()
