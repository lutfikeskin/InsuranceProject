from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_compliance(raw: dict[str, Any]) -> dict[str, Any]:
    comp = _safe_dict(raw).copy()
    return {
        "mcs90": comp.get("mcs90") or comp.get("mcs90_noted"),
        "motor_carrier_id": comp.get("motor_carrier_id"),
        "dot": comp.get("dot") or comp.get("dot_number"),
        "doc_endorsements": _safe_list(comp.get("doc_endorsements")),
    }


def _compute_um_stacked_effective_limit(
    policy: dict[str, Any],
    coverages: list[dict[str, Any]],
) -> int | None:
    direct = policy.get("um_stacked_effective_limit")
    if isinstance(direct, int):
        return direct
    for row in coverages:
        if not isinstance(row, dict):
            continue
        if not row.get("is_stacked"):
            continue
        limits = _safe_dict(row.get("limits"))
        per_person = limits.get("per_person")
        count = row.get("stacked_vehicle_count")
        if isinstance(per_person, int) and isinstance(count, int) and count > 0:
            return per_person * count
    return None


def build_acord_view(policy_dict: dict) -> dict:
    payload = _safe_dict(policy_dict)
    policy = _safe_dict(payload.get("policy"))
    compliance = _normalize_compliance(_safe_dict(payload.get("compliance")))
    coverages = [c for c in _safe_list(payload.get("coverages")) if isinstance(c, dict)]
    vehicles = [v for v in _safe_list(payload.get("vehicles")) if isinstance(v, dict)]
    extraction_audit = _safe_dict(payload.get("extraction_audit"))

    carrier_name = policy.get("carrier_name")
    underwriter_name = policy.get("underwriter_name")
    insurer = underwriter_name or carrier_name

    policy_ontology = {
        "um_stacked_effective_limit": _compute_um_stacked_effective_limit(policy, coverages),
        "statutory_auto_liability_display": policy.get("statutory_auto_liability_display"),
        "statutory_auto_liability_resolved": policy.get("statutory_auto_liability_resolved"),
    }

    coverages_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in coverages:
        family = row.get("family") or "other"
        coverages_by_family[family].append(row)

    acord_127_vehicles = []
    for row in vehicles:
        acord_127_vehicles.append(
            {
                "vin": row.get("vin"),
                "year": row.get("year"),
                "make": row.get("make"),
                "model": row.get("model"),
                "covered_auto_symbols": row.get("covered_auto_symbols"),
                "radius_of_operation": row.get("radius_of_operation"),
                "business_use_class": row.get("business_use_class"),
            }
        )

    acord_25_automobile_liability = {
        "insurer_affording_coverage": insurer,
        "um_stacked_effective": policy_ontology.get("um_stacked_effective_limit"),
        "liability_limit": policy.get("liability_limit"),
    }

    return {
        "carrier_name": carrier_name,
        "underwriter_name": underwriter_name,
        "insurer_affording_coverage": insurer,
        "compliance": compliance,
        "policy_ontology": policy_ontology,
        "commercial_flags": _safe_dict(extraction_audit.get("commercial_flags")),
        "acord_127_vehicles": acord_127_vehicles,
        "acord_25_automobile_liability": acord_25_automobile_liability,
        "coverages_by_family": dict(coverages_by_family),
    }


def build_acord_view_from_orm_policy(policy: Any) -> dict:
    extras_raw = getattr(policy, "extraction_extras", None)
    extras: dict[str, Any] = {}
    if isinstance(extras_raw, str) and extras_raw.strip():
        try:
            extras = _safe_dict(json.loads(extras_raw))
        except Exception:
            extras = {}

    policy_payload = {
        "policy": {
            "carrier_name": getattr(policy, "carrier_name", None),
            "underwriter_name": getattr(policy, "underwriter_name", None),
            "policy_number": getattr(policy, "policy_number", None),
            "effective_date": str(getattr(policy, "effective_date", "") or ""),
            "expiration_date": str(getattr(policy, "expiration_date", "") or ""),
            "liability_limit": getattr(policy, "liability_limit", None),
            "um_stacked_effective_limit": _safe_dict(extras.get("policy_ontology")).get(
                "um_stacked_effective_limit"
            ),
            "statutory_auto_liability_display": _safe_dict(
                extras.get("policy_ontology")
            ).get("statutory_auto_liability_display"),
            "statutory_auto_liability_resolved": _safe_dict(
                extras.get("policy_ontology")
            ).get("statutory_auto_liability_resolved"),
        },
        "compliance": _safe_dict(extras.get("compliance")),
        "extraction_audit": {"commercial_flags": _safe_dict(extras.get("audits")).get("commercial_flags", {})},
        "vehicles": [],
        "coverages": [],
    }

    vehicles_ontology = _safe_list(extras.get("vehicles_ontology"))
    by_vin = {
        (v.get("vin") or "").strip().upper(): v
        for v in vehicles_ontology
        if isinstance(v, dict) and v.get("vin")
    }
    for v in getattr(policy, "vehicles", []) or []:
        vin = (getattr(v, "vin", None) or "").strip().upper()
        ont = by_vin.get(vin, {})
        policy_payload["vehicles"].append(
            {
                "vin": getattr(v, "vin", None),
                "year": getattr(v, "year", None),
                "make": getattr(v, "make", None),
                "model": getattr(v, "model", None),
                "covered_auto_symbols": ont.get("covered_auto_symbols"),
                "radius_of_operation": ont.get("radius_of_operation"),
                "business_use_class": ont.get("business_use_class"),
            }
        )

    coverage_ontology_rows = _safe_list(extras.get("coverages_ontology"))
    by_code: dict[str, dict[str, Any]] = {}
    for row in coverage_ontology_rows:
        if not isinstance(row, dict):
            continue
        code = row.get("coverage_code")
        if isinstance(code, str) and code:
            by_code[code] = row
    for c in getattr(policy, "coverages", []) or []:
        code = getattr(c, "coverage_code", None)
        ont = by_code.get(code, {})
        policy_payload["coverages"].append(
            {
                "coverage_code": code,
                "family": getattr(c, "family", None),
                "display_name": getattr(c, "type", None),
                "hnoa_basis": ont.get("hnoa_basis"),
                "hnoa_attached_to": ont.get("hnoa_attached_to"),
                "vehicle_vin": ont.get("vehicle_vin"),
                "limits": {
                    "per_person": getattr(c, "per_person", None),
                    "per_accident": getattr(c, "per_accident", None),
                    "per_occurrence": getattr(c, "per_occurrence", None),
                    "combined_single_limit": getattr(c, "combined_single_limit", None),
                    "aggregate": getattr(c, "aggregate", None),
                },
            }
        )

    return build_acord_view(policy_payload)
