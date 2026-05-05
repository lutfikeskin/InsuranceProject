from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any


CRITICAL_POLICY_FIELDS = (
    "policy_number",
    "insured_name",
    "carrier_name",
    "effective_date",
    "expiration_date",
    "premium",
    "liability_limit",
    "cargo_limit",
    "med_pay_limit",
    "insured_address",
    "insured_city",
    "insured_state_code",
    "insured_zip",
)


FIELD_LABELS = {
    "policy_number": "Policy Number",
    "insured_name": "Insured Name",
    "carrier_name": "Carrier",
    "effective_date": "Effective Date",
    "expiration_date": "Expiration Date",
    "premium": "Premium",
    "liability_limit": "Auto Liability",
    "cargo_limit": "Cargo Limit",
    "med_pay_limit": "Medical Payments",
    "insured_address": "Insured Address",
    "insured_city": "Insured City",
    "insured_state_code": "Insured State",
    "insured_zip": "Insured ZIP",
}


@dataclass(frozen=True)
class LocatorStatus:
    status: str
    message: str = ""


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\u200b", "").split()).strip()
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
        return None
    return text


def normalize_search_text(value: Any) -> str:
    """Normalize text for dedupe/ranking, not for changing extracted values."""
    text = _clean_text(value) or ""
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def value_search_variants(value: Any) -> list[str]:
    """Return conservative text variants for local PDF search."""
    clean = _clean_text(value)
    if not clean:
        return []

    variants: list[str] = [clean]

    compact_money = re.sub(r"[$,]", "", clean)
    if compact_money != clean and compact_money:
        variants.append(compact_money)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean):
        try:
            parsed = datetime.strptime(clean, "%Y-%m-%d")
            variants.extend(
                [
                    parsed.strftime("%m/%d/%Y"),
                    parsed.strftime("%m-%d-%Y"),
                    f"{parsed.month}/{parsed.day}/{parsed.year}",
                ]
            )
        except ValueError:
            pass
    elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", clean):
        variants.append(clean.replace("/", "-"))

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        variant = _clean_text(variant)
        key = normalize_search_text(variant)
        if variant and key not in seen:
            seen.add(key)
            deduped.append(variant)
    return deduped


def extract_review_field_values(policy_payload: dict[str, Any]) -> dict[str, str]:
    """Pick only review-critical scalar policy values."""
    if not isinstance(policy_payload, dict):
        return {}
    values: dict[str, str] = {}
    for field in CRITICAL_POLICY_FIELDS:
        clean = _clean_text(policy_payload.get(field))
        if clean:
            values[field] = clean
    return values


def _normalized_bbox(rect: Any, page_width: float, page_height: float) -> list[float]:
    return [
        max(0.0, min(1000.0, rect.y0 / page_height * 1000)),
        max(0.0, min(1000.0, rect.x0 / page_width * 1000)),
        max(0.0, min(1000.0, rect.y1 / page_height * 1000)),
        max(0.0, min(1000.0, rect.x1 / page_width * 1000)),
    ]


def _normalized_bbox_from_coords(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_width: float,
    page_height: float,
) -> list[float]:
    return [
        max(0.0, min(1000.0, y0 / page_height * 1000)),
        max(0.0, min(1000.0, x0 / page_width * 1000)),
        max(0.0, min(1000.0, y1 / page_height * 1000)),
        max(0.0, min(1000.0, x1 / page_width * 1000)),
    ]


def _tokenize_for_match(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize_search_text(value))


def _word_window_matches(page: Any, target: str) -> list[dict[str, Any]]:
    target_tokens = _tokenize_for_match(target)
    if not target_tokens:
        return []
    words = page.get_text("words") or []
    normalized_words = [_tokenize_for_match(word[4])[0] if _tokenize_for_match(word[4]) else "" for word in words]
    matches: list[dict[str, Any]] = []
    window_size = len(target_tokens)
    for start in range(0, max(0, len(normalized_words) - window_size + 1)):
        if normalized_words[start : start + window_size] != target_tokens:
            continue
        window = words[start : start + window_size]
        x0 = min(w[0] for w in window)
        y0 = min(w[1] for w in window)
        x1 = max(w[2] for w in window)
        y1 = max(w[3] for w in window)
        matches.append(
            {
                "bbox": _normalized_bbox_from_coords(x0, y0, x1, y1, page.rect.width, page.rect.height),
                "snippet": " ".join(w[4] for w in window),
            }
        )
    return matches


def locate_policy_field_sources(
    pdf_bytes: bytes,
    policy_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Locate already-extracted policy values in the local PDF text layer.

    This is intentionally UI provenance only:
    - no Gemini/API calls
    - no extraction schema or cache-version impact
    - no OCR fallback for scanned PDFs
    """
    try:
        import fitz
    except ImportError:
        return {
            "status": LocatorStatus("fitz_unavailable", "PyMuPDF is unavailable.").__dict__,
            "locations": [],
        }

    field_values = extract_review_field_values(policy_payload)
    if not field_values:
        return {"status": LocatorStatus("no_values", "No scalar values to locate.").__dict__, "locations": []}

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return {"status": LocatorStatus("pdf_error", str(exc)).__dict__, "locations": []}

    try:
        has_text = any((page.get_text("text") or "").strip() for page in doc)
        if not has_text:
            return {
                "status": LocatorStatus("no_text_layer", "No searchable text layer found.").__dict__,
                "locations": [],
            }

        locations: list[dict[str, Any]] = []
        for field, value in field_values.items():
            matches: list[dict[str, Any]] = []
            seen_rects: set[tuple[int, int, int, int, int]] = set()
            for variant in value_search_variants(value):
                for page_index, page in enumerate(doc):
                    rects = page.search_for(variant)
                    for rect in rects:
                        key = (
                            page_index,
                            round(rect.x0),
                            round(rect.y0),
                            round(rect.x1),
                            round(rect.y1),
                        )
                        if key in seen_rects:
                            continue
                        seen_rects.add(key)
                        bbox = _normalized_bbox(rect, page.rect.width, page.rect.height)
                        matches.append(
                            {
                                "field": field,
                                "label": FIELD_LABELS.get(field, field),
                                "value": value,
                                "matched_text": variant,
                                "snippet": variant,
                                "page": page_index + 1,
                                "page_number": page_index + 1,
                                "bbox": bbox,
                            }
                        )
                    if rects:
                        continue
                    for word_match in _word_window_matches(page, variant):
                        key = (
                            page_index,
                            round(word_match["bbox"][1]),
                            round(word_match["bbox"][0]),
                            round(word_match["bbox"][3]),
                            round(word_match["bbox"][2]),
                        )
                        if key in seen_rects:
                            continue
                        seen_rects.add(key)
                        matches.append(
                            {
                                "field": field,
                                "label": FIELD_LABELS.get(field, field),
                                "value": value,
                                "matched_text": variant,
                                "snippet": word_match["snippet"],
                                "page": page_index + 1,
                                "page_number": page_index + 1,
                                "bbox": word_match["bbox"],
                            }
                        )
            if not matches:
                continue
            quality = "ambiguous" if len(matches) > 1 else "exact"
            chosen = matches[0]
            chosen["match_quality"] = quality
            chosen["match_count"] = len(matches)
            locations.append(chosen)
        return {"status": LocatorStatus("ok").__dict__, "locations": locations}
    finally:
        doc.close()

