from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_DIR))

from modules.extraction import process_pdf
from test_accuracy import compare_extraction, force_refresh_enabled, get_golden_pairs


def _case_key(golden: dict) -> tuple[str, str, str]:
    meta = golden.get("_meta") or {}
    return (
        str(meta.get("carrier") or "default"),
        str(meta.get("document_type") or "unknown"),
        str(meta.get("policy_type") or "unknown"),
    )


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _selected_pairs(case_filter: str | None) -> list[tuple[str, str]]:
    pairs = get_golden_pairs()
    if not case_filter:
        return pairs
    needle = case_filter.lower()
    return [pair for pair in pairs if needle in pair[0].lower() or needle in pair[1].lower()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run live extraction against golden PDFs and print an onboarding accuracy report."
    )
    parser.add_argument("--case", help="Substring filter for a PDF/JSON path.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass local extraction cache for live model drift checks.",
    )
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required.")

    pairs = _selected_pairs(args.case)
    if not pairs:
        raise SystemExit("No golden PDF/JSON pairs matched.")

    grouped = defaultdict(lambda: {"cases": 0, "passed": 0, "critical": 0, "warnings": 0})
    force_refresh = args.force_refresh or force_refresh_enabled()

    for pdf_path, json_path in pairs:
        golden = _load_json(json_path)
        with open(pdf_path, "rb") as handle:
            pdf_bytes = handle.read()

        result, _, error = process_pdf(
            pdf_bytes,
            api_key=api_key,
            force_refresh=force_refresh,
        )
        key = _case_key(golden)
        bucket = grouped[key]
        bucket["cases"] += 1

        if error:
            bucket["critical"] += 1
            print(f"FAIL {pdf_path}: extraction error: {error}")
            continue

        critical_errors, warnings = compare_extraction(result or {}, golden)
        bucket["critical"] += len(critical_errors)
        bucket["warnings"] += len(warnings)
        if not critical_errors:
            bucket["passed"] += 1
            status = "PASS"
        else:
            status = "FAIL"
        print(
            f"{status} {pdf_path}: critical={len(critical_errors)} warnings={len(warnings)}"
        )
        for item in critical_errors[:10]:
            print(f"  {item}")
        for item in warnings[:10]:
            print(f"  {item}")

    print("\nSummary by carrier/document/product:")
    total_cases = total_passed = total_critical = total_warnings = 0
    for key in sorted(grouped):
        bucket = grouped[key]
        total_cases += bucket["cases"]
        total_passed += bucket["passed"]
        total_critical += bucket["critical"]
        total_warnings += bucket["warnings"]
        carrier, document_type, policy_type = key
        print(
            f"{carrier}/{document_type}/{policy_type}: "
            f"passed={bucket['passed']}/{bucket['cases']} "
            f"critical={bucket['critical']} warnings={bucket['warnings']}"
        )

    print(
        f"\nOverall: passed={total_passed}/{total_cases} "
        f"critical={total_critical} warnings={total_warnings} "
        f"force_refresh={force_refresh}"
    )
    return 0 if total_critical == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
