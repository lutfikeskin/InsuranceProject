"""Synthesize Coverage entries from flat policy limit fields.

Belt-and-braces for the LLM: when the structured `coverages[]` array is
under-reported but `policy.{liability_limit, cargo_limit, ...}` flat fields
are populated, derive the missing rows so review screen, DB, and COI
generation see the same data.
"""


def backfill_coverages_from_flat_limits(existing, flat, policy_type):
    """Return the missing Coverage entries derivable from flat policy fields.

    `existing` is the current coverages list (untouched), `flat` is a dict-like
    object exposing `liability_limit`, `cargo_limit`, `um_uim_limit`, etc.
    Each returned entry carries `_backfill_source`; the caller pops it before
    persisting and uses it for the audit trail.
    """
    have_codes = {
        c.get("coverage_code")
        for c in (existing or [])
        if isinstance(c, dict) and c.get("coverage_code")
    }
    out = []

    def _money(v):
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() == "included":
            return None
        s = s.lstrip("$").replace(",", "").strip()
        # Honour K / M / B suffixes (e.g. "100k" -> 100_000, "1.5m" -> 1_500_000).
        mult = 1
        if s and s[-1].lower() in ("k", "m", "b"):
            mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[s[-1].lower()]
            s = s[:-1].strip()
        try:
            return int(float(s) * mult)
        except ValueError:
            return None

    # liability_limit -> AUTO_LIAB_CSL (most commercial decs print one CSL number)
    if "AUTO_LIAB_BI" not in have_codes and "AUTO_LIAB_CSL" not in have_codes:
        amt = _money(flat.get("liability_limit"))
        if amt:
            out.append({
                "coverage_code": "AUTO_LIAB_CSL",
                "family": "auto_liability",
                "limits": {"combined_single_limit": amt},
                "limit_structure": "csl",
                "_backfill_source": "policy.liability_limit",
            })

    # cargo_limit / cargo_deductible -> CARGO
    if "CARGO" not in have_codes:
        cargo_amt = _money(flat.get("cargo_limit"))
        cargo_ded = _money(flat.get("cargo_deductible"))
        if cargo_amt or cargo_ded is not None:
            out.append({
                "coverage_code": "CARGO",
                "family": "cargo",
                "limits": {"per_occurrence": cargo_amt} if cargo_amt else {},
                "deductible": cargo_ded,
                "_backfill_source": "policy.cargo_limit",
            })

    # um_uim_limit -> UM_BI
    if "UM_BI" not in have_codes and "UIM_BI" not in have_codes:
        amt = _money(flat.get("um_uim_limit"))
        if amt:
            out.append({
                "coverage_code": "UM_BI",
                "family": "uninsured_motorist",
                "limits": {"combined_single_limit": amt},
                "_backfill_source": "policy.um_uim_limit",
            })

    # med_pay_limit -> MED_PAY (also captures "Included")
    if "MED_PAY" not in have_codes:
        v = flat.get("med_pay_limit")
        amt = _money(v)
        v_str = (str(v).strip().lower() if v is not None else "")
        if amt or v_str == "included":
            entry = {
                "coverage_code": "MED_PAY",
                "family": "medical_payments",
                "limits": {"per_person": amt} if amt else {},
                "_backfill_source": "policy.med_pay_limit",
            }
            if not amt and v_str == "included":
                entry["limit_descriptor"] = "Included"
            out.append(entry)

    # pip_limit -> PIP
    if "PIP" not in have_codes:
        amt = _money(flat.get("pip_limit"))
        if amt:
            out.append({
                "coverage_code": "PIP",
                "family": "pip",
                "limits": {"per_person": amt},
                "_backfill_source": "policy.pip_limit",
            })

    # comp_deductible -> COMP, coll_deductible -> COLL (deductible-only rows)
    if "COMP" not in have_codes:
        ded = _money(flat.get("comp_deductible"))
        if ded is not None:
            out.append({
                "coverage_code": "COMP",
                "family": "physical_damage",
                "deductible": ded,
                "limit_structure": "deductible_only",
                "_backfill_source": "policy.comp_deductible",
            })
    if "COLL" not in have_codes:
        ded = _money(flat.get("coll_deductible"))
        if ded is not None:
            out.append({
                "coverage_code": "COLL",
                "family": "physical_damage",
                "deductible": ded,
                "limit_structure": "deductible_only",
                "_backfill_source": "policy.coll_deductible",
            })

    # general_liability_limit -> GL_OCCURRENCE
    gl_eligible = policy_type in ("general_liability", "commercial_package", "bop") or (
        policy_type == "commercial_auto" and flat.get("general_liability_limit")
    )
    if gl_eligible and "GL_OCCURRENCE" not in have_codes:
        amt = _money(flat.get("general_liability_limit"))
        if amt:
            out.append({
                "coverage_code": "GL_OCCURRENCE",
                "family": "general_liability",
                "limits": {"per_occurrence": amt},
                "_backfill_source": "policy.general_liability_limit",
            })

    return out
