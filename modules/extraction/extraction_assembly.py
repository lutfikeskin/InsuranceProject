"""Build validated extraction payload returned to callers."""

from core.logger import logger
from core.coverage_ontology import (
    format_liability_limit,
    is_coverage_allowed_for_policy_type,
    summarize_auto_liability,
    summarize_cargo,
    summarize_general_liability,
    summarize_med_pay,
    summarize_physical_damage,
    summarize_pip,
    summarize_um_uim,
    validate_coverage,
)
from core.coverage_normalization import (
    apply_alias_resolution,
    apply_commercial_auto_audits,
    effective_stacked_um_limit,
    enrich_coverage_from_registry,
    enrich_statutory_policy_display,
    merge_autoliability_split_rows,
    normalize_limit_descriptors,
)
from utils.premium_audit import audit_premium_vs_fleet
from utils.vehicle_utils import refine_vehicle_type

from .extraction_types import ExtractionContext
from .extraction_response import clean_coverage_zeros
from .pdf_ops import PdfProcessor
from .coverage_backfill import backfill_coverages_from_flat_limits


def apply_auto_liability_rules(coverages, policy_type):
    """Enforces CSL Supremacy and other checks."""
    if policy_type not in ["personal_auto", "commercial_auto"]:
        return

    auto_liabs = [c for c in coverages if c.get("family") == "auto_liability"]
    has_csl = any(c.get("limit_structure") == "csl" for c in auto_liabs)
    has_split = any(c.get("limit_structure") == "split" for c in auto_liabs)

    if has_csl and has_split:
        logger.info("Refactor: Pruning Split limits in favor of CSL.")
        coverages[:] = [
            c
            for c in coverages
            if not (
                c.get("family") == "auto_liability"
                and c.get("limit_structure") == "split"
            )
        ]


def compute_summaries(final):
    raw_summary = summarize_auto_liability(final["coverages"])
    if raw_summary:
        final["policy"]["liability_limit"] = format_liability_limit(raw_summary)

    raw_gl = summarize_general_liability(final["coverages"])
    if raw_gl:
        final["policy"]["general_liability_limit"] = format_liability_limit(raw_gl)

    raw_cargo = summarize_cargo(final["coverages"])
    if raw_cargo:
        final["policy"]["cargo_limit"] = f"${raw_cargo['value']:,}"
        if raw_cargo.get("deductible"):
            final["policy"]["cargo_deductible"] = str(raw_cargo["deductible"])

    covs = final["coverages"]

    final["policy"]["um_uim_limit"] = summarize_um_uim(covs)
    final["policy"]["med_pay_limit"] = summarize_med_pay(covs)
    final["policy"]["pip_limit"] = summarize_pip(covs)
    for c in covs:
        if (
            c.get("family") in ("uninsured_motorist", "underinsured_motorist")
            and c.get("is_stacked")
        ):
            eff = effective_stacked_um_limit(c)
            if eff is not None:
                final["policy"]["um_stacked_effective_limit"] = str(eff)
                break

    phys_dam = summarize_physical_damage(covs)
    if phys_dam:
        final["policy"]["comp_deductible"] = phys_dam.get("comp")
        final["policy"]["coll_deductible"] = phys_dam.get("coll")

    final["policy"]["has_auto_liability"] = any(
        c.get("family") == "auto_liability" for c in covs
    )
    final["policy"]["has_general_liability"] = any(
        c.get("family") == "general_liability" for c in covs
    )
    final["policy"]["has_full_collision"] = any(
        c.get("family") == "physical_damage" for c in covs
    )


def assemble_extraction_result(ctx: ExtractionContext, processor: PdfProcessor) -> dict:
    comp = ctx.extracted_data.get("compliance") or {}
    pol_decl = ctx.extracted_data.get("policy", {}) or {}
    for k in ("mcs90_noted", "motor_carrier_id", "dot_number", "drive_other_car_note"):
        v = pol_decl.get(k)
        if v and not comp.get(k):
            comp = {**comp, k: v}
    final = {
        "policy": pol_decl,
        "compliance": comp,
        "coverages": [],
        "vehicles": [],
        "drivers": ctx.extracted_data.get("drivers", {}).get("drivers", []),
        "audits": {},
        "classification": ctx.classification,
        "page_dimensions": processor.get_dimensions(),
        "extraction_audit": {
            "errors": list(ctx.errors),
            "rejected_coverages": [],
            "classification_warnings": list(ctx.classification_warnings),
        },
    }
    if ctx.user_selected_policy_type:
        final["extraction_audit"]["user_selected_policy_type"] = (
            ctx.user_selected_policy_type
        )

    raw_vehs = ctx.extracted_data.get("vehicles", {}).get("vehicles", [])
    for v in raw_vehs:
        refined = refine_vehicle_type(
            year=v.get("year"),
            make=v.get("make"),
            model=v.get("model"),
            vin=v.get("vin"),
            extracted_type=v.get("type"),
            extracted_chassis=v.get("chassis"),
            extracted_body=v.get("body"),
            gvw=v.get("gvw"),
        )
        v["type"] = refined["final_type"]
        v["make"] = refined["make"]
        v["model"] = refined["model"]
        v["chassis"] = refined.get("chassis") or v.get("chassis")
        v["body"] = refined.get("body") or v.get("body")
        final["vehicles"].append(v)

    raw_covs = clean_coverage_zeros(
        ctx.extracted_data.get("coverages", {}).get("coverages", [])
    )
    raw_covs = apply_alias_resolution(raw_covs)
    raw_covs = normalize_limit_descriptors(raw_covs)
    raw_covs, liab_notes = merge_autoliability_split_rows(raw_covs)
    for ln in liab_notes:
        final["extraction_audit"].setdefault("liability_normalization", []).append(ln)
    cflags, cnotes = apply_commercial_auto_audits(final["vehicles"], ctx.policy_type)
    if cflags:
        final["extraction_audit"]["commercial_flags"] = cflags
    for note in cnotes:
        final["extraction_audit"].setdefault("ontology_notes", []).append(note)

    for c in raw_covs:
        c = enrich_coverage_from_registry(c)
        code = c.get("coverage_code")
        if not code:
            final["extraction_audit"]["rejected_coverages"].append(
                {"coverage_code": None, "reason": "missing_coverage_code"}
            )
            continue

        if not is_coverage_allowed_for_policy_type(code, ctx.policy_type):
            final["extraction_audit"]["rejected_coverages"].append(
                {
                    "coverage_code": code,
                    "reason": f"not_allowed_for_policy_type:{ctx.policy_type}",
                }
            )
            continue
        is_valid, msg = validate_coverage(c)
        if is_valid:
            final["coverages"].append(c)
        else:
            final["extraction_audit"]["rejected_coverages"].append(
                {"coverage_code": code, "reason": msg}
            )

    apply_auto_liability_rules(final["coverages"], ctx.policy_type)
    if ctx.usage_metadata.get("policy_data_source") != "coi_summary":
        compute_summaries(final)

    # Safety net: when the LLM under-reports `coverages[]` but flat policy
    # fields are populated (own LLM output OR derived by compute_summaries),
    # synthesize the missing entries so review screen, DB, and COI all see
    # the same data. Skipped for coi_summary because per-policy backfill
    # happens later in the save flow (one shared coverages[] vs many policies).
    if ctx.usage_metadata.get("policy_data_source") != "coi_summary":
        synthesized = backfill_coverages_from_flat_limits(
            existing=final["coverages"],
            flat=final["policy"],
            policy_type=ctx.policy_type,
        )
        for entry in synthesized:
            src = entry.pop("_backfill_source", None)
            final["coverages"].append(entry)
            final["extraction_audit"].setdefault(
                "backfilled_coverages", []
            ).append({
                "coverage_code": entry.get("coverage_code"),
                "source": src,
            })

    enrich_statutory_policy_display(final)

    final["policy"]["has_full_collision"] = any(
        c.get("family") == "physical_damage" for c in final["coverages"]
    )
    final["audits"]["premium"] = audit_premium_vs_fleet(
        premium_str=final["policy"].get("premium"),
        vehicle_count=len(final["vehicles"]),
        policy_type=ctx.policy_type,
    )

    return final
