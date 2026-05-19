from collections import defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.variant_tracker import VariantTracker


def _group_by_carrier(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        carrier = item.get("carrier_name") or "unknown"
        grouped[carrier].append(item)
    return dict(sorted(grouped.items(), key=lambda pair: pair[0].lower()))


def _print_grouped(title: str, grouped: dict[str, list[dict]]) -> None:
    print(f"\n{title}")
    if not grouped:
        print("  (none)")
        return
    for carrier, rows in grouped.items():
        print(f"  {carrier}:")
        for row in sorted(
            rows,
            key=lambda item: (
                item.get("document_type") or "",
                item.get("policy_type") or "",
                item.get("variant_key") or "",
            ),
        ):
            variant_key = row.get("variant_key") or row.get("key") or "unknown"
            seen_count = row.get("seen_count", 1)
            document_type = row.get("document_type", "unknown")
            policy_type = row.get("policy_type", "unknown")
            print(
                f"    - seen={seen_count} type={document_type}/{policy_type} key={variant_key}"
            )


def main() -> None:
    tracker = VariantTracker()
    known_variants = tracker.get_known_variants()
    known_rows = [{"key": key, **value} for key, value in known_variants.items()]
    candidate_rows = tracker.get_candidates(min_seen=1)

    _print_grouped("Known Variants", _group_by_carrier(known_rows))
    _print_grouped("Pending Candidates", _group_by_carrier(candidate_rows))


if __name__ == "__main__":
    main()
