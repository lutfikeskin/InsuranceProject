# Coverage Ontology Reference

This is the single source of truth for all coverage codes, families, limit structures, and validation rules. The extraction pipeline, database schema, and UI all derive from this document.

---

## Coverage Families

| Family | Description | Policy Types |
|--------|-------------|--------------|
| `auto_liability` | Bodily injury & property damage liability for autos | personal_auto, commercial_auto |
| `uninsured_underinsured` | UM, UIM, and combined UM/UIM | personal_auto, commercial_auto |
| `physical_damage` | Comp, collision, and related vehicle coverages | personal_auto, commercial_auto |
| `medical_payments` | Med Pay | personal_auto, commercial_auto |
| `pip` | Personal Injury Protection (state-mandated) | personal_auto, commercial_auto |
| `general_liability` | CGL occurrence, aggregate, products | general_liability, bop, commercial_package |
| `cargo` | Motor truck cargo / freight | commercial_auto (endorsement) |
| `umbrella_excess` | Umbrella and excess liability | umbrella |

---

## Complete Registry

### Auto Liability

| Code | Display Name | Structure | Allowed Limits |
|------|-------------|-----------|----------------|
| `AUTO_LIAB_CSL` | Auto Liability - CSL | `csl` | `combined_single_limit` |
| `AUTO_LIAB_BI` | Bodily Injury Liability | `split` | `per_person`, `per_accident` |
| `AUTO_LIAB_PD` | Property Damage Liability | `per_occurrence` | `per_occurrence` |
| `HIRED_AUTO` | Hired Auto Liability | `csl` | `combined_single_limit`, `per_occurrence` |
| `NON_OWNED_AUTO` | Non-Owned Auto Liability | `csl` | `combined_single_limit`, `per_occurrence` |
| `HIRED_AUTO_PD` | Hired Auto Physical Damage | `deductible_only` | — |
| `TRAILER_INTERCHANGE` | Trailer Interchange | `per_occurrence` | `per_occurrence` |

### Uninsured / Underinsured Motorist

| Code | Display Name | Structure | Allowed Limits | Notes |
|------|-------------|-----------|----------------|-------|
| `UM_BI` | Uninsured Motorist BI | `split` | `per_person`, `per_accident` | |
| `UM_CSL` | Uninsured Motorist CSL | `csl` | `combined_single_limit` | |
| `UM_PD` | Uninsured Motorist PD | `per_occurrence` | `per_occurrence` | Not all states |
| `UIM_BI` | Underinsured Motorist BI | `split` | `per_person`, `per_accident` | |
| `UIM_CSL` | Underinsured Motorist CSL | `csl` | `combined_single_limit` | |
| `UMUIM_CSL` | Combined UM/UIM CSL | `csl` | `combined_single_limit` | TX, OH, and other combined states |
| `UMUIM_BI` | Combined UM/UIM BI | `split` | `per_person`, `per_accident` | TX, OH, and other combined states |
| `UMUIM_PD` | Combined UM/UIM PD | `per_occurrence` | `per_occurrence` | Rare |

**LLM prompt guidance**: If the document shows a single line "UM/UIM" or "Uninsured/Underinsured Motorist" with one limit, use the `UMUIM_*` codes. If it shows separate UM and UIM sections with potentially different limits, use `UM_*` and `UIM_*` separately.

### Physical Damage

| Code | Display Name | Structure | Allowed Limits | Notes |
|------|-------------|-----------|----------------|-------|
| `COMP` | Comprehensive / OTC | `deductible_only` | — | MUST link to `vehicle_vin` |
| `COLL` | Collision | `deductible_only` | — | MUST link to `vehicle_vin` |
| `RENTAL` | Rental Reimbursement | `per_occurrence` | `per_occurrence` | |
| `TOWING` | Towing & Labor | `per_occurrence` | `per_occurrence` | |
| `GAP` | GAP Coverage | `flat` | — | |
| `FULL_SAFETY_GLASS` | Full Safety Glass | `flat` | — | |
| `LOAN_LEASE_COVERAGE` | Loan/Lease Coverage | `flat` | — | |

**Critical rule**: COMP and COLL entries with `vehicle_vin = null` should be flagged during validation. In multi-vehicle policies, each vehicle typically has its own deductible.

### Medical Payments & PIP

| Code | Display Name | Structure | Allowed Limits |
|------|-------------|-----------|----------------|
| `MED_PAY` | Medical Payments | `split` | `per_person` |
| `PIP` | Personal Injury Protection | `csl` | `combined_single_limit`, `per_person` |

### General Liability

| Code | Display Name | Structure | Allowed Limits |
|------|-------------|-----------|----------------|
| `GL_OCCURRENCE` | General Liability - Per Occurrence | `per_occurrence` | `per_occurrence` |
| `GL_AGGREGATE` | General Liability - Aggregate | `aggregate` | `aggregate` |
| `GL_PRODUCTS_COMP_OPS` | Products/Completed Ops Aggregate | `aggregate` | `aggregate` |
| `GL_PERSONAL_ADV_INJURY` | Personal & Advertising Injury | `per_occurrence` | `per_occurrence` |
| `GL_DAMAGE_RENTED_PREM` | Damage to Rented Premises | `per_occurrence` | `per_occurrence` |
| `GL_MEDICAL_EXPENSE` | Medical Expense (Any One Person) | `per_person` | `per_person` |
| `GL_EMPLOYEE_BENEFITS` | Employee Benefits Liability | `per_occurrence` | `per_occurrence` |

### Cargo

| Code | Display Name | Structure | Allowed Limits | Notes |
|------|-------------|-----------|----------------|-------|
| `CARGO_LEGAL_LIAB` | Motor Truck Cargo | `per_occurrence` | `per_occurrence` | Usually endorsement on commercial auto |
| `CARGO_BROAD_FORM` | Broad Form Cargo | `per_occurrence` | `per_occurrence` | |
| `CARGO_REEFER` | Reefer Breakdown | `per_occurrence` | `per_occurrence` | Refrigeration unit failure |

### Umbrella / Excess

| Code | Display Name | Structure | Allowed Limits |
|------|-------------|-----------|----------------|
| `UMBRELLA_OCCURRENCE` | Umbrella - Per Occurrence | `per_occurrence` | `per_occurrence` |
| `UMBRELLA_AGGREGATE` | Umbrella - Aggregate | `aggregate` | `aggregate` |
| `EXCESS_LIABILITY` | Excess Liability | `per_occurrence` | `per_occurrence` |

---

## Naming Aliases (for LLM prompt context)

Coverage names appear in many forms across carriers. These aliases help the LLM map varied terminology to our canonical codes. They are NOT used for regex/dictionary lookup — they are injected into the extraction prompt so the LLM knows which variations map to which code.

```json
{
  "AUTO_LIAB_CSL": {
    "aliases": ["Combined Single Limit", "CSL", "CSL Liability", "Single Limit", "Combined Limit"]
  },
  "AUTO_LIAB_BI": {
    "aliases": ["Bodily Injury", "BI", "BI Liability", "Bodily Injury Liability", "Liability BI", "Bod Inj", "BI Per Person/Per Accident"]
  },
  "AUTO_LIAB_PD": {
    "aliases": ["Property Damage", "PD", "PD Liability", "Property Damage Liability", "Prop Dmg"]
  },
  "HIRED_AUTO": {
    "aliases": ["Hired Auto", "Hired Auto Liability", "Symbol 8", "Hired Car"]
  },
  "NON_OWNED_AUTO": {
    "aliases": ["Non-Owned Auto", "Non Owned Auto Liability", "Symbol 9", "HNOA"]
  },
  "UM_BI": {
    "aliases": ["Uninsured Motorist BI", "UM Bodily Injury", "UMBI", "Uninsured BI"]
  },
  "UM_CSL": {
    "aliases": ["Uninsured Motorist CSL", "UM Combined Single Limit", "Uninsured Motorist"]
  },
  "UM_PD": {
    "aliases": ["Uninsured Motorist PD", "UMPD", "Uninsured Property Damage", "UM Property Damage"]
  },
  "UIM_BI": {
    "aliases": ["Underinsured Motorist BI", "UIM Bodily Injury", "UIMBI", "Underinsured BI"]
  },
  "UIM_CSL": {
    "aliases": ["Underinsured Motorist CSL", "Underinsured Motorist"]
  },
  "UMUIM_CSL": {
    "aliases": ["UM/UIM", "Uninsured/Underinsured Motorist", "UM-UIM Combined", "UM & UIM", "UMUIM", "Un/Underinsured Motorist"]
  },
  "UMUIM_BI": {
    "aliases": ["UM/UIM BI", "Uninsured/Underinsured Motorist BI", "UM/UIM Bodily Injury"]
  },
  "COMP": {
    "aliases": ["Comprehensive", "Comp", "Other Than Collision", "OTC", "Comprehensive Coverage", "Non-Collision Damage", "Fire Theft & Combined Additional Coverage"]
  },
  "COLL": {
    "aliases": ["Collision", "Coll", "Collision Coverage", "Collision Damage", "Auto Collision"]
  },
  "MED_PAY": {
    "aliases": ["Medical Payments", "Med Pay", "MedPay", "Medical Payments Coverage", "Medical Expense Coverage"]
  },
  "PIP": {
    "aliases": ["Personal Injury Protection", "PIP", "PIP Coverage", "No-Fault", "No Fault Coverage"]
  },
  "GL_OCCURRENCE": {
    "aliases": ["Each Occurrence", "Per Occurrence", "General Liability Occurrence", "CGL Per Occurrence", "Occurrence Limit"]
  },
  "GL_AGGREGATE": {
    "aliases": ["General Aggregate", "Aggregate Limit", "CGL Aggregate", "Policy Aggregate"]
  },
  "GL_PRODUCTS_COMP_OPS": {
    "aliases": ["Products/Completed Operations", "Prod/Comp Ops", "Products Aggregate", "Completed Operations Aggregate"]
  },
  "GL_PERSONAL_ADV_INJURY": {
    "aliases": ["Personal & Advertising Injury", "Personal and Advertising Injury", "P&A Injury", "Advertising Injury"]
  },
  "GL_DAMAGE_RENTED_PREM": {
    "aliases": ["Damage to Rented Premises", "Fire Damage", "Damage to Premises Rented to You", "Fire Legal Liability"]
  },
  "GL_MEDICAL_EXPENSE": {
    "aliases": ["Medical Expense", "Med Exp (Any One Person)", "Medical Payments (GL)", "Any One Person"]
  },
  "CARGO_LEGAL_LIAB": {
    "aliases": ["Motor Truck Cargo", "MTC", "Cargo Coverage", "Cargo Legal Liability", "Trucker's Cargo"]
  },
  "UMBRELLA_OCCURRENCE": {
    "aliases": ["Umbrella Each Occurrence", "Umbrella Per Occurrence", "Excess Each Occurrence"]
  },
  "UMBRELLA_AGGREGATE": {
    "aliases": ["Umbrella Aggregate", "Excess Aggregate", "Umbrella Policy Aggregate"]
  }
}
```

**How these are used**: During the extraction step, the aliases for the relevant policy type's coverage codes are appended to the prompt. This helps the LLM recognize variations without needing a separate dictionary lookup layer. The LLM's job is to map whatever it sees to our canonical `coverage_code`. The aliases just give it more context about what to look for.

**How to expand**: When a new carrier's documents consistently use a term not in the aliases (e.g., a carrier that writes "Automobile Liability" instead of "Auto Liability"), add it to the relevant code's alias list here and in `ontology.py`. No pipeline code change needed.

---

## Limit Structures

| Structure | Description | Example |
|-----------|-------------|---------|
| `csl` | Combined Single Limit — one number covers all | $1,000,000 CSL |
| `split` | Split limits — per_person / per_accident | 100/300 |
| `per_occurrence` | Single per-event limit | $1,000,000 each occurrence |
| `aggregate` | Total limit for policy period | $2,000,000 aggregate |
| `deductible_only` | No coverage limit, only deductible applies | COMP $500 ded |
| `flat` | Flat coverage, no numeric limit | GAP Coverage: Included |

---

## Policy Type Constraints

Which families are allowed for each policy type:

```
personal_auto:
  allowed: auto_liability, uninsured_underinsured, physical_damage, 
           medical_payments, pip
  forbidden_codes: CARGO_*, TRAILER_INTERCHANGE, GL_*

commercial_auto:
  allowed: auto_liability, uninsured_underinsured, physical_damage, 
           medical_payments, pip, cargo
  forbidden_codes: GL_* (unless commercial_package)

general_liability:
  allowed: general_liability
  forbidden_codes: AUTO_*, UM_*, UIM_*, UMUIM_*, COMP, COLL, CARGO_*

commercial_package:
  allowed: ALL families
  notes: Must contain at least 2 of: GL, Property, Auto

umbrella:
  allowed: umbrella_excess
```

---

## Validation Rules

These rules check **internal consistency of extracted data**, not document completeness. If a coverage isn't in the document, it won't be extracted and that's fine — no validation rule should flag missing data as an error.

### Tier 1: Instant (Python, no LLM)

1. `coverage_code` must exist in registry
2. `family` must match registry entry for that code
3. `limit_structure` must match registry entry
4. Limit keys must be subset of `allowed_limits`
5. Zero values in limit fields → convert to null (Gemini structured output artifact)
6. COMP/COLL without `vehicle_vin` → log info (may need manual review)

### Tier 2: Cross-Field Consistency

1. CSL and split limits for same family → keep CSL, drop split (CSL supremacy)
2. effective_date >= expiration_date → flag as data error
3. Duplicate coverage codes for same vehicle → deduplicate

---

## Endorsement Types

| Type | Description | Common Forms |
|------|-------------|-------------|
| `additional_insured` | Adds another party as insured | CA 20 48, CG 20 10, CG 20 26 |
| `waiver_of_subrogation` | Waives carrier's right to subrogate | CG 24 04 |
| `primary_noncontributory` | This policy pays first | CG 20 01 |
| `coverage_modification` | Changes limits or terms | Various |
| `coverage_extension` | Adds new coverage | CA 99 17 (Hired Auto PD) |
| `exclusion` | Removes coverage for specific risk | Various |
| `federal_filing` | Regulatory filing | MCS-90, BMC-91 |

---

## Carrier-Specific Hints

These hints are injected into the extraction prompt when a carrier is detected during classification:

```json
{
  "progressive": {
    "hints": [
      "Driver list is typically on the last page",
      "UM/UIM may appear as 'Uninsured/Underinsured Motorist' combined",
      "Vehicle schedule includes stated amount in the same table"
    ]
  },
  "geico": {
    "hints": [
      "NAIC is typically 22055 (Government Employees Insurance Company)",
      "Deductible schedule is on the declarations page"
    ]
  },
  "national_general": {
    "hints": [
      "Policy number format: XXXXXXXXXX-XX",
      "Multiple sub-policies may appear in one document"
    ]
  }
}
```

This file should grow over time as accuracy issues are diagnosed per carrier.
