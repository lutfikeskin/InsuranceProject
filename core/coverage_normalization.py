from __future__ import annotations

from typing import Any, Optional
import re

from core.coverage_ontology import COVERAGE_REGISTRY
from core.logger import logger


def _to_int(value: Any) -> Optional[int]:
    """Best-effort integer coercion for numeric-like coverage values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if not s:
        return None
    mult = 1
    if s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return None
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _normalize_text(s: str) -> str:
    """Lowercase text normalization for descriptor and alias matching."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _build_display_from_limits(limits: dict[str, Any]) -> Optional[str]:
    """Return liability display text from normalized limit fields."""
    pp = _to_int(limits.get("per_person"))
    pa = _to_int(limits.get("per_accident"))
    pd = _to_int(limits.get("per_occurrence"))
    csl = _to_int(limits.get("combined_single_limit"))
    if csl:
        return f"{csl:,} CSL"
    if pp and pa:
        if pd:
            return f"{pp // 1000}/{pa // 1000}/{pd // 1000}"
        return f"{pp // 1000}/{pa // 1000}"
    if pd:
        return f"{pd:,} Occ"
    return None


def enrich_statutory_policy_display(final: dict[str, Any]) -> None:
    """
    Enrich policy with statutory liability annotations in-place.

    Contract:
    - Input is the assembled extraction payload (`final`) used by pipeline.
    - Mutates `final["policy"]` by setting:
      - `statutory_auto_liability_display`
      - `statutory_auto_liability_resolved`
    - Never raises on malformed payloads.
    """
    policy = final.get("policy") or {}
    coverages = final.get("coverages") or []

    liability_text = str(policy.get("liability_limit") or "")
    desc = _normalize_text(liability_text)
    state = (policy.get("insured_state_code") or policy.get("state") or "").strip().upper()

    statutory_markers = ("statutory", "state minimum", "minimum limits", "unlimited")
    is_statutory = any(marker in desc for marker in statutory_markers)

    if is_statutory:
        display = f"Statutory ({state})" if state else "Statutory"
        policy["statutory_auto_liability_display"] = display
        policy["statutory_auto_liability_resolved"] = liability_text or "statutory"
        final["policy"] = policy
        return

    auto_limits: dict[str, Any] = {}
    for cov in coverages:
        if cov.get("family") != "auto_liability":
            continue
        limits = cov.get("limits") or {}
        for key in ("combined_single_limit", "per_person", "per_accident", "per_occurrence"):
            if auto_limits.get(key) is None and limits.get(key) is not None:
                auto_limits[key] = limits.get(key)

    display = _build_display_from_limits(auto_limits)
    if display:
        policy["statutory_auto_liability_display"] = display
        policy["statutory_auto_liability_resolved"] = display
    final["policy"] = policy


def enrich_coverage_from_registry(c: dict[str, Any]) -> dict[str, Any]:
    """
    Enrich one coverage row with canonical registry metadata.

    Contract:
    - Input: one coverage dict (possibly partial).
    - Output: coverage dict with best-effort canonical fields populated.
    - Fields enriched when missing: `display_name`, `family`,
      `line_of_business`, `limit_structure`.
    - Unknown coverage codes are returned unchanged.
    """
    if not isinstance(c, dict):
        return c

    code = c.get("coverage_code")
    if not code:
        return c
    reg = COVERAGE_REGISTRY.get(code)
    if not reg:
        logger.debug(f"coverage_normalization: unknown coverage_code={code}")
        return c

    enriched = dict(c)
    if not enriched.get("display_name"):
        enriched["display_name"] = reg.get("display_name")
    if not enriched.get("family"):
        enriched["family"] = reg.get("family")
    if not enriched.get("line_of_business"):
        enriched["line_of_business"] = reg.get("line_of_business")
    if not enriched.get("limit_structure"):
        enriched["limit_structure"] = reg.get("limit_structure")
    return enriched


def apply_alias_resolution(coverages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Resolve common alias coverage codes/names to canonical registry codes.

    Contract:
    - Input/Output: list of coverage rows preserving row structure.
    - Canonicalizes `coverage_code` when a confident alias match is found.
    """
    if not isinstance(coverages, list):
        return []

    alias_map: dict[str, str] = {
        "auto liability csl": "AUTO_LIAB_CSL",
        "automobile liability csl": "AUTO_LIAB_CSL",
        "bodily injury": "AUTO_LIAB_BI",
        "property damage liability": "AUTO_LIAB_PD",
        "uninsured motorist bi": "UM_BI",
        "underinsured motorist bi": "UIM_BI",
        "comprehensive": "COMP",
        "collision": "COLL",
        "medical payments": "MED_PAY",
        "medical payments incl": "MED_PAY",
        "medical payments included": "MED_PAY",
        "med pay": "MED_PAY",
        "med pay incl": "MED_PAY",
        "med pay included": "MED_PAY",
        "motor truck cargo": "CARGO_LEGAL_LIAB",
        "hired auto liability": "HIRED_AUTO",
        "non-owned auto liability": "NON_OWNED_AUTO",
        "general liability per occurrence": "GL_OCCURRENCE",
        "general liability aggregate": "GL_AGGREGATE",
    }

    resolved: list[dict[str, Any]] = []
    for cov in coverages:
        if not isinstance(cov, dict):
            continue
        row = dict(cov)
        code = row.get("coverage_code")
        if code in COVERAGE_REGISTRY:
            resolved.append(row)
            continue

        alias_candidates = [
            _normalize_text(str(code or "")),
            _normalize_text(str(row.get("display_name") or "")),
            _normalize_text(str(row.get("type") or "")),
        ]
        replacement = None
        for alias in alias_candidates:
            if not alias:
                continue
            if alias in alias_map:
                replacement = alias_map[alias]
                break
            if "medical payments" in alias or "med pay" in alias:
                replacement = "MED_PAY"
                break
        if replacement:
            row["coverage_code"] = replacement
        resolved.append(row)
    return resolved


def normalize_limit_descriptors(coverages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parse textual limit descriptors into structured numeric limit fields.

    Contract:
    - Input/Output: list of coverage rows.
    - Leaves already-structured values unchanged.
    - Supports common formats like:
      - `100/300/100`
      - `$1,000,000 CSL`
      - `1M CSL`
    """
    normalized: list[dict[str, Any]] = []
    for cov in coverages or []:
        if not isinstance(cov, dict):
            continue
        row = dict(cov)
        limits = dict(row.get("limits") or {})

        descriptor_sources = [
            row.get("limit_descriptor"),
            row.get("liability_limit"),
            row.get("display_name"),
            row.get("type"),
        ]

        desc = " ".join(str(x) for x in descriptor_sources if x)
        d = _normalize_text(desc)

        if not limits.get("combined_single_limit") and "csl" in d:
            m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[mk]?)", d)
            if m:
                csl_val = _to_int(m.group(1))
                if csl_val:
                    limits["combined_single_limit"] = csl_val

        if not any(limits.get(k) for k in ("per_person", "per_accident", "per_occurrence")):
            split = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?", d)
            if split:
                pp = _to_int(split.group(1))
                pa = _to_int(split.group(2))
                pd = _to_int(split.group(3)) if split.group(3) else None
                if pp and pp < 10_000:
                    pp *= 1_000
                if pa and pa < 10_000:
                    pa *= 1_000
                if pd and pd < 10_000:
                    pd *= 1_000
                limits["per_person"] = limits.get("per_person") or pp
                limits["per_accident"] = limits.get("per_accident") or pa
                if pd:
                    limits["per_occurrence"] = limits.get("per_occurrence") or pd

        row["limits"] = limits
        normalized.append(row)
    return normalized


def merge_autoliability_split_rows(
    coverages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Pair split BI/PD auto liability rows for downstream summary helpers.

    AUTO_LIAB_BI's registry only allows per_person/per_accident, so we cannot
    fold PD's per_occurrence into BI's limits without failing validation.
    Both rows are preserved; summarize_auto_liability reads them independently.
    Audit notes record that a paired BI+PD was detected.

    Contract:
    - Input: list of coverage rows.
    - Output: `(coverages, audit_notes)` with order preserved.
    """
    notes: list[str] = []
    bi_keys: set[tuple[Any, Any, Any]] = set()
    for cov in coverages or []:
        if isinstance(cov, dict) and cov.get("coverage_code") == "AUTO_LIAB_BI":
            bi_keys.add(
                (cov.get("vehicle_vin"), cov.get("hnoa_basis"), cov.get("hnoa_attached_to"))
            )
    for cov in coverages or []:
        if not isinstance(cov, dict):
            continue
        if cov.get("coverage_code") != "AUTO_LIAB_PD":
            continue
        key = (cov.get("vehicle_vin"), cov.get("hnoa_basis"), cov.get("hnoa_attached_to"))
        if key in bi_keys:
            notes.append(
                f"Paired AUTO_LIAB_BI + AUTO_LIAB_PD for vin={key[0] or 'all'}"
            )
    return list(coverages or []), notes


def effective_stacked_um_limit(c: dict[str, Any]) -> Optional[int]:
    """
    Compute effective UM/UIM stacked limit from one UM/UIM coverage row.

    Contract:
    - Returns `None` when stacked inputs are incomplete/invalid.
    - Returns an integer effective limit when computable.
    """
    if not isinstance(c, dict):
        return None
    if not c.get("is_stacked"):
        return None
    count = _to_int(c.get("stacked_vehicle_count"))
    if not count or count <= 0:
        return None
    limits = c.get("limits") or {}

    base = _to_int(limits.get("combined_single_limit"))
    if base is None:
        base = _to_int(limits.get("per_person"))
    if base is None:
        return None
    return base * count


def apply_commercial_auto_audits(
    vehicles: list[dict[str, Any]],
    policy_type: str,
) -> tuple[dict[str, Any], list[str]]:
    """
    Produce commercial/ontology audit flags from vehicle-level extraction.

    Contract:
    - Input: extracted vehicles and classified policy type.
    - Output: `(commercial_flags_dict, ontology_notes_list)`.
    - Must include `symbol1_any_auto_suggested` when symbols suggest it.
    """
    flags: dict[str, Any] = {}
    notes: list[str] = []

    symbols_seen: set[str] = set()
    for v in vehicles or []:
        if not isinstance(v, dict):
            continue
        raw = str(v.get("covered_auto_symbols") or "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        symbols_seen.update(parts)

    symbol1 = "1" in symbols_seen
    if symbol1:
        flags["symbol1_any_auto_suggested"] = True
        notes.append("Covered auto symbol 1 detected in vehicle schedule.")
        if policy_type != "commercial_auto":
            notes.append(
                "Symbol 1 is typically commercial auto context; verify policy_type classification."
            )
    else:
        flags["symbol1_any_auto_suggested"] = False

    if symbols_seen:
        flags["covered_auto_symbols_detected"] = ",".join(sorted(symbols_seen))

    return flags, notes

