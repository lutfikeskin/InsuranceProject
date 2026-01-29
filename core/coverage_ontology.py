class LineOfBusiness:
    AUTO = "auto"
    GENERAL_LIABILITY = "general_liability"
    PROPERTY = "property"
    WORKERS_COMP = "workers_comp"
    OTHER = "other"

class CoverageFamily:
    AUTO_LIABILITY = "auto_liability"
    UNINSURED_MOTORIST = "uninsured_motorist"
    UNDERINSURED_MOTORIST = "underinsured_motorist"
    PHYSICAL_DAMAGE = "physical_damage"
    GENERAL_LIABILITY = "general_liability"
    CARGO = "cargo"
    MEDICAL_PAYMENTS = "medical_payments"
    PIP = "pip"
    OTHER = "other"

class LimitStructure:
    CSL = "csl"
    SPLIT = "split"
    PER_OCCURRENCE = "per_occurrence"
    AGGREGATE = "aggregate"
    DEDUCTIBLE_ONLY = "deductible_only"
    SCHEDULED = "scheduled"

# Constraints on what families/codes are valid for specific policy classifications
POLICY_TYPE_CONSTRAINTS = {
    "personal_auto": {
        "allowed_families": [
            CoverageFamily.AUTO_LIABILITY, 
            CoverageFamily.UNINSURED_MOTORIST, 
            CoverageFamily.UNDERINSURED_MOTORIST,
            CoverageFamily.PHYSICAL_DAMAGE,
            CoverageFamily.MEDICAL_PAYMENTS,
            CoverageFamily.PIP
        ],
        "forbidden_codes": ["CARGO_LEGAL_LIAB"] # Example
    },
    "commercial_auto": {
        "allowed_families": [
            CoverageFamily.AUTO_LIABILITY, 
            CoverageFamily.UNINSURED_MOTORIST, 
            CoverageFamily.UNDERINSURED_MOTORIST,
            CoverageFamily.PHYSICAL_DAMAGE,
            CoverageFamily.MEDICAL_PAYMENTS,
            CoverageFamily.PIP,
            CoverageFamily.CARGO
        ]
    },
    "general_liability": {
        "allowed_families": [CoverageFamily.GENERAL_LIABILITY]
    }
}

# The Canonical Registry
COVERAGE_REGISTRY = {
    # --- Auto Liability ---
    "AUTO_LIAB_CSL": {
        "display_name": "Auto Liability - Combined Single Limit - Automobile Liability",
        "family": CoverageFamily.AUTO_LIABILITY,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL,
        "allowed_limits": ["combined_single_limit"]
    },
    "AUTO_LIAB_BI": {
        "display_name": "Bodily Injury Liability",
        "family": CoverageFamily.AUTO_LIABILITY,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.SPLIT,
        "allowed_limits": ["per_person", "per_accident"]
    },
    "AUTO_LIAB_PD": {
        "display_name": "Property Damage Liability",
        "family": CoverageFamily.AUTO_LIABILITY,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.PER_OCCURRENCE,
        "allowed_limits": ["per_occurrence"]
    },
    
    # --- UM / UIM (Isolated) ---
    "UM_BI": {
        "display_name": "Uninsured Motorist BI",
        "family": CoverageFamily.UNINSURED_MOTORIST,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.SPLIT,
        "allowed_limits": ["per_person", "per_accident"]
    },
    "UM_CSL": {
        "display_name": "Uninsured Motorist CSL",
        "family": CoverageFamily.UNINSURED_MOTORIST,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL,
        "allowed_limits": ["combined_single_limit"]
    },
    "UM_PD": {
        "display_name": "Uninsured Motorist PD",
        "family": CoverageFamily.UNINSURED_MOTORIST,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.PER_OCCURRENCE, 
        "allowed_limits": ["per_occurrence", "per_accident"] 
    },
    "UIM_BI": {
        "display_name": "Underinsured Motorist BI",
        "family": CoverageFamily.UNDERINSURED_MOTORIST,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.SPLIT,
        "allowed_limits": ["per_person", "per_accident"]
    },
    "UIM_CSL": {
        "display_name": "Underinsured Motorist CSL",
        "family": CoverageFamily.UNDERINSURED_MOTORIST,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL,
        "allowed_limits": ["combined_single_limit"]
    },

    # --- Physical Damage ---
    "COMP": {
        "display_name": "Comprehensive / OTC",
        "family": CoverageFamily.PHYSICAL_DAMAGE,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.DEDUCTIBLE_ONLY,
        "allowed_limits": []
    },
    "COLL": {
        "display_name": "Collision",
        "family": CoverageFamily.PHYSICAL_DAMAGE,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.DEDUCTIBLE_ONLY,
        "allowed_limits": []
    },
    "RENTAL": {
        "display_name": "Rental Reimbursement",
        "family": CoverageFamily.PHYSICAL_DAMAGE,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.PER_OCCURRENCE,
        "allowed_limits": ["per_occurrence"] 
    },
    "TOWING": {
        "display_name": "Towing & Labor",
        "family": CoverageFamily.PHYSICAL_DAMAGE, 
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.PER_OCCURRENCE,
        "allowed_limits": ["per_occurrence"]
    },
    "MED_PAY": {
        "display_name": "Medical Payments",
        "family": CoverageFamily.MEDICAL_PAYMENTS,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.SPLIT, 
        "allowed_limits": ["per_person"]
    },
    "PIP": {
        "display_name": "Personal Injury Protection",
        "family": CoverageFamily.PIP,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL, 
        "allowed_limits": ["combined_single_limit", "per_person"]
    },
    "HIRED_AUTO": {
        "display_name": "Hired Auto Liability",
        "family": CoverageFamily.AUTO_LIABILITY,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL,
        "allowed_limits": ["combined_single_limit", "per_occurrence"]
    },
    "NON_OWNED_AUTO": {
        "display_name": "Non-Owned Auto Liability",
        "family": CoverageFamily.AUTO_LIABILITY,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.CSL,
        "allowed_limits": ["combined_single_limit", "per_occurrence"]
    },

    # --- General Liability ---
    "GL_OCCURRENCE": {
        "display_name": "General Liability - Per Occurrence",
        "family": CoverageFamily.GENERAL_LIABILITY,
        "line_of_business": LineOfBusiness.GENERAL_LIABILITY,
        "limit_structure": LimitStructure.PER_OCCURRENCE,
        "allowed_limits": ["per_occurrence"]
    },
    "GL_AGGREGATE": {
        "display_name": "General Liability - Aggregate",
        "family": CoverageFamily.GENERAL_LIABILITY,
        "line_of_business": LineOfBusiness.GENERAL_LIABILITY,
        "limit_structure": LimitStructure.AGGREGATE,
        "allowed_limits": ["aggregate"]
    },
    "GL_PRODUCTS_COMP_OPS": {
        "display_name": "Products/Completed Operations Aggregate",
        "family": CoverageFamily.GENERAL_LIABILITY,
        "line_of_business": LineOfBusiness.GENERAL_LIABILITY,
        "limit_structure": LimitStructure.AGGREGATE,
        "allowed_limits": ["aggregate"]
    },

    # --- Cargo ---
    "CARGO_LEGAL_LIAB": {
        "display_name": "Motor Truck Cargo",
        "family": CoverageFamily.CARGO,
        "line_of_business": LineOfBusiness.AUTO,
        "limit_structure": LimitStructure.PER_OCCURRENCE,
        "allowed_limits": ["per_occurrence"]
    }
}

def validate_coverage(cov_data):
    """
    STRICT VALIDATION: Enforces Registry Parity.
    Returns (True, None) or (False, ErrorMessage).
    """
    code = cov_data.get("coverage_code")
    if not code or code not in COVERAGE_REGISTRY:
        return False, f"Unknown Code: {code}"

    reg = COVERAGE_REGISTRY[code]
    
    # 1. Enforce Family Parity
    if cov_data.get("family") != reg["family"]:
        return False, f"{code}: Family mismatch. Registry requires {reg['family']}"

    # 2. Enforce Limit Structure Parity
    if cov_data.get("limit_structure") != reg["limit_structure"]:
        return False, f"{code}: Structure mismatch. Registry requires {reg['limit_structure']}"

    # 3. Enforce Allowed Keys (Limits ⊆ Registry.allowed)
    limits = cov_data.get("limits", {}) or {}
    present_keys = {k for k, v in limits.items() if v is not None}
    allowed = set(reg.get("allowed_limits", []))
    
    forbidden = present_keys - allowed
    if forbidden:
        return False, f"{code}: Forbidden limit keys {forbidden}. Allowed: {allowed}"
        
    # 4. Strict Deductible Enforcement for Physical Damage
    if reg["limit_structure"] == LimitStructure.DEDUCTIBLE_ONLY:
        ded = cov_data.get("deductible")
        if ded is None or ded == 0:
             # Exception: If it's explicitly Full Glass or something with 0 ded? 
             # For now, we assume valid Phys Dam requires a deductible or explicit value.
             # "Not purchased" items result in null deductible.
            return False, f"{code}: Deductible is required for {LimitStructure.DEDUCTIBLE_ONLY}"

    return True, None

def is_coverage_allowed_for_policy_type(coverage_code, policy_type):
    """
    Cross-checks if a coverage code belongs in the classified policy type.
    """
    constraints = POLICY_TYPE_CONSTRAINTS.get(policy_type)
    if not constraints:
        return True # Default to allow if policy type not in constraints
        
    reg = COVERAGE_REGISTRY.get(coverage_code)
    if not reg:
        return False
        
    if reg["family"] not in constraints["allowed_families"]:
        return False
        
    if coverage_code in constraints.get("forbidden_codes", []):
        return False
        
    return True

def summarize_auto_liability(coverages):
    """
    RETURNS RAW STRUCTURED DATA, NOT STRINGS.
    Decouples Data Logic from Presentation.
    """
    auto_liab_coverages = [
        c for c in coverages 
        if c.get("family") == CoverageFamily.AUTO_LIABILITY
        and COVERAGE_REGISTRY.get(c.get("coverage_code"), {}).get("line_of_business") == LineOfBusiness.AUTO
    ]

    # --- DETERMINISTIC PRIORITY (Enterprise Safe) ---
    # Priority 1: Explicit CSL
    # Priority 2: Split BI + PD
    
    # 1. Check for CSL
    csl_cov = next((c for c in auto_liab_coverages if c.get("coverage_code") == "AUTO_LIAB_CSL"), None)
    if csl_cov:
        val = csl_cov.get("limits", {}).get("combined_single_limit")
        if val:
            return {"type": "csl", "value": int(val)}
            
    # 2. Check for Split
    bi_cov = next((c for c in auto_liab_coverages if c.get("coverage_code") == "AUTO_LIAB_BI"), None)
    pd_cov = next((c for c in auto_liab_coverages if c.get("coverage_code") == "AUTO_LIAB_PD"), None)
    
    if bi_cov:
        return {
            "type": "split",
            "bi_person": bi_cov.get("limits", {}).get("per_person"),
            "bi_accident": bi_cov.get("limits", {}).get("per_accident"),
            "pd_accident": pd_cov.get("limits", {}).get("per_occurrence") if pd_cov else None
        }

    return None

def summarize_general_liability(coverages):
    """
    Finds the best GL Occurrence limit.
    """
    gl_coverages = [
        c for c in coverages 
        if c.get("family") == CoverageFamily.GENERAL_LIABILITY
        and c.get("coverage_code") == "GL_OCCURRENCE"
    ]
    
    if not gl_coverages:
        return None
        
    # Pick the highest occurrence limit
    best = max(gl_coverages, key=lambda x: x.get("limits", {}).get("per_occurrence") or 0)
    val = best.get("limits", {}).get("per_occurrence")
    
    if val:
        return {"type": "per_occurrence", "value": int(val)}
    return None

def summarize_cargo(coverages):
    """
    Finds the best Cargo limit.
    """
    cargo_coverages = [
        c for c in coverages 
        if c.get("family") == CoverageFamily.CARGO
    ]
    
    if not cargo_coverages:
        return None
        
    # Pick the highest limit
    best = max(cargo_coverages, key=lambda x: x.get("limits", {}).get("per_occurrence") or 0)
    val = best.get("limits", {}).get("per_occurrence")
    ded = best.get("deductible")
    
    if val:
        return {"value": int(val), "deductible": ded}
    return None

def format_liability_limit(structured_data):
    """
    PRESENTATION LAYER HELPER.
    Converts structured data into the standard display format.
    """
    if not structured_data:
        return None
        
    if structured_data.get("type") == "csl":
        val = structured_data["value"]
        return f"{val:,} CSL"
        
    if structured_data.get("type") == "split":
        parts = []
        for key in ["bi_person", "bi_accident", "pd_accident"]:
            val = structured_data.get(key)
            if val:
                parts.append(str(val // 1000 if val >= 1000 else val))
        return "/".join(parts) if parts else None
        
    if structured_data.get("type") == "per_occurrence":
        val = structured_data["value"]
        return f"{val:,} Occ"
        
    return None

def summarize_um_uim(coverages):
    """
    Summarizes Uninsured/Underinsured Motorist limits.
    Returns string directly or structured dict. 
    Here we return structured for consistency, formatted later.
    """
    um_covs = [c for c in coverages if c.get("family") == CoverageFamily.UNINSURED_MOTORIST]
    uim_covs = [c for c in coverages if c.get("family") == CoverageFamily.UNDERINSURED_MOTORIST]
    
    if not um_covs and not uim_covs:
        return None

    def get_limit_str(cov):
        limits = cov.get("limits", {})
        if cov.get("limit_structure") == "csl":
            val = limits.get("combined_single_limit")
            return f"{val:,} CSL" if val else None
        elif cov.get("limit_structure") == "split":
            pp = limits.get("per_person")
            pa = limits.get("per_accident")
            if pp and pa:
                return f"{pp//1000}/{pa//1000}" 
            elif pp:
                return f"{pp//1000} (BI)"
        return None

    # Priority: CSL > Split
    um_str = None
    uim_str = None

    if um_covs:
        # Prefer CSL
        csl = next((c for c in um_covs if c.get("limit_structure") == "csl"), None)
        if csl:
            um_str = get_limit_str(csl)
        else:
            # Prefer BI
            bi = next((c for c in um_covs if "BI" in (c.get("coverage_code") or "")), None) or um_covs[0]
            um_str = get_limit_str(bi)

    if uim_covs:
        csl = next((c for c in uim_covs if c.get("limit_structure") == "csl"), None)
        if csl:
            uim_str = get_limit_str(csl)
        else:
            bi = next((c for c in uim_covs if "BI" in (c.get("coverage_code") or "")), None) or uim_covs[0]
            uim_str = get_limit_str(bi)

    if um_str and uim_str:
        if um_str == uim_str:
            return f"{um_str}" # Implies both
        else:
            return f"UM: {um_str} / UIM: {uim_str}"
    elif um_str:
        return f"UMOnly: {um_str}"
    elif uim_str:
        return f"UIMOnly: {uim_str}"
        
    return None

def summarize_med_pay(coverages):
    meds = [c for c in coverages if c.get("family") == CoverageFamily.MEDICAL_PAYMENTS]
    if not meds: return None
    
    # Almost always split per_person
    best = meds[0]
    val = best.get("limits", {}).get("per_person")
    if val:
        return f"{val:,}"
    return None

def summarize_pip(coverages):
    pips = [c for c in coverages if c.get("family") == CoverageFamily.PIP]
    if not pips: return None
    
    best = pips[0]
    val = best.get("limits", {}).get("combined_single_limit") or best.get("limits", {}).get("per_person")
    if val:
        return f"{val:,}"
    return None

def summarize_physical_damage(coverages):
    """
    Returns dict: {'comp': '500', 'coll': '1000'}
    """
    phys = [c for c in coverages if c.get("family") == CoverageFamily.PHYSICAL_DAMAGE]
    res = {}
    
    comp = next((c for c in phys if "COMP" in (c.get("coverage_code") or "")), None)
    if comp:
        ded = comp.get("deductible")
        if ded is not None:
             res['comp'] = f"{ded}"
        else:
             # Look for "full glass" or similar logic if we had flags, defaulting to just Exists
             res['comp'] = "Exists"

    coll = next((c for c in phys if "COLL" in (c.get("coverage_code") or "")), None)
    if coll:
        ded = coll.get("deductible")
        if ded is not None:
             res['coll'] = f"{ded}"
        else:
             res['coll'] = "Exists"
             
    return res if res else None
