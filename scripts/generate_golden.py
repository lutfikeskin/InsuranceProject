from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.extraction import process_pdf


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")


def _carrier_bucket(carrier_name: str | None) -> str:
    if not carrier_name:
        return "generic"
    low = carrier_name.lower()
    if "progressive" in low:
        return "progressive"
    if "geico" in low:
        return "geico"
    return "generic"


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required.")

    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/generate_golden.py <pdf_path> [<pdf_path> ...]")

    for raw_path in sys.argv[1:]:
        pdf_path = Path(raw_path)
        if not pdf_path.exists():
            print(f"Skipping missing file: {pdf_path}")
            continue

        file_bytes = pdf_path.read_bytes()
        result, _, error = process_pdf(file_bytes, api_key=api_key)
        if error:
            print(f"Extraction failed for {pdf_path.name}: {error}")
            continue

        classification = result.get("classification", {}) if isinstance(result, dict) else {}
        policy = result.get("policy", {}) if isinstance(result, dict) else {}
        document_type = classification.get("document_type") or "unknown"
        policy_type = classification.get("policy_type") or "unknown"
        carrier_name = policy.get("carrier_name")
        carrier_bucket = _carrier_bucket(carrier_name)

        out_dir = Path("tests/data") / carrier_bucket / document_type
        out_dir.mkdir(parents=True, exist_ok=True)

        base_name = _slug(f"{policy_type}_{pdf_path.stem}") or _slug(pdf_path.stem) or "golden"
        out_pdf = out_dir / f"{base_name}.pdf"
        out_json = out_dir / f"{base_name}.json"
        out_pdf.write_bytes(file_bytes)

        state = input(f"[{pdf_path.name}] state (optional): ").strip()
        covers_variants_raw = input(f"[{pdf_path.name}] covers_variants comma list (optional): ").strip()
        known_issues_raw = input(f"[{pdf_path.name}] known_issues comma list (optional): ").strip()
        covers_variants = [item.strip() for item in covers_variants_raw.split(",") if item.strip()]
        known_issues = [item.strip() for item in known_issues_raw.split(",") if item.strip()]

        payload = dict(result)
        payload["_meta"] = {
            "carrier": carrier_bucket if carrier_bucket != "generic" else "default",
            "document_type": document_type,
            "policy_type": policy_type,
            "layout_fingerprint": (
                result.get("variant_fingerprint")
                or result.get("layout_fingerprint")
                or ""
            ),
            "state": state,
            "covers_variants": covers_variants,
            "known_issues": known_issues,
        }

        out_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"Generated: {out_json}")


if __name__ == "__main__":
    main()
