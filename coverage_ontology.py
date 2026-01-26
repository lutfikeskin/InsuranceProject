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
        "display_name": "Auto Liability - Combined Single Limit",
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
    }
    # ... more mapped as needed in same patterns
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

    # Strategy: Find coverage with MAX total payout potential.
    # This handles "Compulsory" (Low Split) vs "Optional" (High CSL) coexistence.
    
    best_limit_val = -1
    best_structure = None
    
    # Check CSL candidates
    csl_candidates = [c for c in auto_liab_coverages if c.get("limit_structure") == LimitStructure.CSL]
    for c in csl_candidates:
        val = c.get("limits", {}).get("combined_single_limit") or 0
        if val > best_limit_val:
            best_limit_val = val
            best_structure = {"type": "csl", "value": int(val)}

    # Check Split candidates (BI + PD pair is implied, but we look at BI usually for the main "Headline" limit)
    # We will treat the BI per-accident limit as the comparable value for sorting.
    bi_candidates = [c for c in auto_liab_coverages if c.get("coverage_code") == "AUTO_LIAB_BI"]
    pd_candidates = [c for c in auto_liab_coverages if c.get("coverage_code") == "AUTO_LIAB_PD"]
    
    # Just take the best BI limit found
    for c in bi_candidates:
        per_acc = c.get("limits", {}).get("per_accident") or 0
        # If per_accident is missing, fallback to per_person * 2 as heuristic? Or just per_person.
        # Let's trust per_accident or per_person.
        if per_acc == 0:
            per_acc = c.get("limits", {}).get("per_person") or 0
            
        if per_acc > best_limit_val:
            # We found a better split limit. Construct the split summary.
            # We need to pair it with the best PD limit we can find (or the one from the same set if we were fancy, but simply picking best PD is usually fine for summary)
            best_pd_limit = 0
            best_pd_cov = None
            for p in pd_candidates:
                l = p.get("limits", {}).get("per_occurrence") or 0
                if l > best_pd_limit:
                    best_pd_limit = l
                    best_pd_cov = p
            
            best_limit_val = per_acc
            best_structure = {
                "type": "split",
                "bi_person": c.get("limits", {}).get("per_person"),
                "bi_accident": c.get("limits", {}).get("per_accident"),
                "pd_accident": best_pd_limit if best_pd_cov else None
            }

    return best_structure

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
        # Shorthand for splits: 100/300/100
        for key in ["bi_person", "bi_accident", "pd_accident"]:
            val = structured_data.get(key)
            if val:
                parts.append(str(val // 1000 if val >= 1000 else val))
        return "/".join(parts) if parts else None
        
    return None
