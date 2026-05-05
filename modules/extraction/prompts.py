from typing import Optional

GLOBAL_EXTRACTION_PRINCIPLES = """
    GLOBAL EXTRACTION PRINCIPLES:
    - Extract from tables, key-value blocks, or prose.
    - Output MUST be valid JSON.
    - If a field is not explicitly visible, return JSON null. Never use "null", "N/A", or "" as placeholders.
    - Never infer or guess.
"""

NULL_HANDLING_RULE = """
    --- NULL HANDLING ---
    Missing field example: "premium": null. Do not output "null", "N/A", "-", or "".
"""

CLASSIFICATION_SIGNAL_RULE = """
    Keep classification.signals to at most 3 short explicit cues from the document.
"""

CLASSIFY_POLICY_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    You are an insurance document taxonomy and policy classification system.
    Determine BOTH the document_type and the primary policy_type of the provided PDF.

    document_type: choose ONE value:
    - declarations_page
    - renewal_declarations
    - certificate_of_insurance
    - memorandum
    - quote
    - application
    - endorsement
    - unknown

    policy_type: choose ONE value:
    - personal_auto
    - commercial_auto
    - general_liability
    - bop
    - commercial_package
    - umbrella
    - motor_truck_cargo
    - unknown

    Document type signals:
    - certificate_of_insurance: ACORD logo, Certificate Holder section, and/or "this certificate is issued as a matter of information only".
    - memorandum: title includes "Memorandum of Insurance" and often carrier letterhead format.
    - quote: "Quote", "Proposal", "Indication", or "Not a binder".
    - application: "Application", applicant signature blocks, pre-bind underwriting questions.
    - endorsement: "Endorsement", "Amendment", or form numbers such as "CA 20 01".
    - declarations_page: policy number + named insured + coverage schedule + effective/expiration dates.
    - renewal_declarations: declarations-like structure with explicit renewal language.

    Rules:
    - Base decisions on explicit wording and structure.
    - Prefer declarations and coverage titles for policy_type.
    - If unsure, return "unknown" for either field.

    DOMINANCE RULE (policy_type):
    - Classify based on the PRIMARY policy form, not endorsements.
    - If multiple coverage types exist, choose the base policy (e.g., Commercial Auto + Cargo endorsement -> commercial_auto).

    PACKAGE CONFIRMATION:
    - If you choose 'commercial_package', you MUST confirm that it contains AT LEAST TWO of: General Liability, Property, or Auto.
    - If it only has Auto + Cargo, classify as 'commercial_auto' (dominance rule).
    - List up to 3 short detected cues used to justify document_type and policy_type in the 'signals' array.

    DISAMBIGUATION (brief):
    - umbrella: primary umbrella/excess liability policy form; not a following-form excess that only amends an underlying policy with no standalone umbrella declarations.
    - bop: Businessowners Policy / BOP as the base form; do not use commercial_package unless CP wording and multi-line package (see package rule).
    - motor_truck_cargo: dedicated motor truck cargo hauler policy as primary; if primary form is commercial auto with a cargo endorsement, use commercial_auto (dominance).
    """


def get_extract_all_prompt(
    registry_text: str,
    user_policy_type: Optional[str] = None,
    scoped_policy_type: Optional[str] = None,
    carrier_hints_suffix: str = "",
    unreliable_fields: Optional[list[str]] = None,
) -> str:
    prompt_policy_type = user_policy_type or scoped_policy_type or "unknown"
    if user_policy_type:
        classification_block = f"""
    --- CLASSIFICATION ---
    policy_type is FIXED to "{user_policy_type}" (user or system). Set classification.policy_type to exactly this string,
    confidence to "high", and include "user_selected" in classification.signals. Do not output a different policy_type.
    {CLASSIFICATION_SIGNAL_RULE}
    """
    else:
        classification_block = """
    --- CLASSIFICATION ---
    Choose ONE: personal_auto, commercial_auto, general_liability, bop, commercial_package, umbrella, motor_truck_cargo, unknown.
    - Base decision on explicit wording.
    - PACKAGE RULE: If 'commercial_package', confirm AT LEAST TWO of: General Liability, Property, or Auto.
    - If Auto + Cargo only, classify as 'commercial_auto' (dominance rule).
    - Keep classification.signals to at most 3 short explicit cues.
    """

    declarations_block = """
    --- POLICY DECLARATIONS ---
    - Distinguish between Carrier (Risk Bearer) and Agency (Broker). Extract Carrier only.
    - carrier_name: The brand name shown prominently on the document (e.g. "Progressive", "GEICO", "Allstate"). This is what the customer recognizes.
    - underwriter_name: The legal underwriting entity, often shown in smaller text near declarations as "Underwritten by:" or in fine print.
      Examples:
      - Progressive commercial auto -> "United Financial Casualty Company"
      - Progressive personal auto -> "Progressive Direct Insurance Company" (or similar Progressive subsidiary)
      - GEICO commercial auto -> "GEICO Casualty Company" (or similar)
    - If only one name appears, populate carrier_name with it and leave underwriter_name null.
    - If both appear, populate both.
    - Never invent an underwriter; return null if unsure.
    - naic_number: insurer NAIC from declarations/schedules only; do not use producer/agency license numbers.
    - effective_date / expiration_date: use YYYY-MM-DD when the document shows a full parseable date; otherwise use the string as printed.
    - premium: copy the grand total as printed (string); do not compute or invent totals.
    - Fields: Carrier Name, NAIC, Policy #, Effective/Expiration Dates, Insured Name, Address, City, State, Zip, Business Name, Premium (GRAND TOTAL).
    """

    confidence_block = """
    --- FIELD CONFIDENCE ---
    For each critical field below, also return a sibling <fieldname>_confidence value:
    - policy_number
    - effective_date
    - expiration_date
    - liability_limit
    - cargo_limit
    - premium
    - insured_name
    - carrier_name
    - underwriter_name
    Confidence scale:
    - high: value is clearly stated and unambiguous
    - medium: value is present but partial, abbreviated, or required interpretation
    - low: value is implied, inferred, or you are uncertain
    If the value is null/absent, set confidence to "low". Do not fabricate values.
    """

    unreliable_block = ""
    if unreliable_fields:
        formatted = ", ".join(sorted({f for f in unreliable_fields if f}))
        if formatted:
            unreliable_block = f"""
    --- RELIABILITY GUIDANCE ---
    Note: For this carrier and document type, the following fields have historically been difficult to extract correctly.
    Pay special attention: {formatted}.
    """

    policy_scope_block = _get_policy_scope_block(prompt_policy_type)

    core = GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are an expert insurance underwriter and data extraction specialist.
    Extract the COMPLETE policy information from the provided document in a single pass.
    {classification_block}
    {NULL_HANDLING_RULE}
    {declarations_block}
    {confidence_block}
    {unreliable_block}
    {policy_scope_block}

    --- COVERAGE MAPPING ---
    - Map every visible coverage to a valid coverage_code from the registry below.
    - If a row says Included/Yes without a numeric limit, keep limits null; do not invent dollar amounts.
    - REGISTRY: {registry_text}

    --- COMPLIANCE (optional) ---
    - If MCS-90, MC #, USDOT, or Drive Other Car (e.g. CA 99 10) is visible, set compliance and/or policy motor_carrier_id / mcs90_noted / drive_other_car_note. For multiple DOC individuals/forms, set compliance.doc_endorsements as a list of {{ "form_id", "named_individuals" }}.

    OUTPUT: Return a single JSON object with exactly these top-level keys:
    classification, policy, compliance, coverages, vehicles, drivers
    Use "compliance": {{}} if nothing applies.
    """
    suffix = (carrier_hints_suffix or "").strip()
    if suffix:
        return core + "\n" + suffix + "\n"
    return core


def _get_policy_scope_block(policy_type: Optional[str]) -> str:
    policy_type = policy_type or "unknown"
    auto_block = """
    --- AUTO POLICY DETAILS ---
    - Extract ALL visible vehicles: VIN, Year, Make, Model, GVW, Type.
    - Extract ALL visible drivers: Name, License #, Excluded status.
    - Link vehicle-specific coverages to vehicle_vin.
    - Extract COMP/COLL deductibles from schedules, tables, and endorsement pages.
    - Common labels: BI/LIAB→AUTO_LIAB_BI, PD/Prop Damage→AUTO_LIAB_PD, UM/UIM, PIP, OTC/COMP, COLL, RR→RENTAL, Towing→TOWING.
    - Michigan PPI is not PD liability; use MI_PPI when clearly PPI.
    """
    commercial_auto_block = """
    - BAP: copy covered auto designation symbols to covered_auto_symbols when visible, e.g. 1,7.
    - Hired/Non-Owned: use HIRED_AUTO / NON_OWNED_AUTO; set hnoa_basis and hnoa_attached_to only when stated.
    """
    gl_block = """
    --- LIABILITY POLICY DETAILS ---
    - Focus on General Liability, BOP, package, or umbrella limits explicitly shown.
    - Extract vehicles/drivers only when a schedule is actually present; otherwise return empty arrays.
    - For GL: capture occurrence, aggregate, products/completed operations, and medical payments when visible.
    """
    cargo_block = """
    --- MOTOR TRUCK CARGO DETAILS ---
    - Focus on cargo limit, cargo deductible, covered commodities, radius/territory, and scheduled vehicles when visible.
    - Capture DOT/MC/MCS-90 details only if explicitly shown.
    - Do not convert cargo endorsements into a separate auto liability policy.
    """
    umbrella_block = """
    --- UMBRELLA / EXCESS DETAILS ---
    - Focus on umbrella/excess liability limits and underlying policy references.
    - Do not treat following-form endorsements as standalone umbrella policies unless declarations clearly say so.
    - Extract vehicles/drivers only when a schedule is actually present; otherwise return empty arrays.
    """
    default_block = """
    --- SCHEDULE DETAILS ---
    - Extract visible vehicles and drivers only when shown; otherwise return empty arrays.
    - Extract visible coverages, limits, deductibles, and vehicle links when explicitly present.
    """

    if policy_type in {"personal_auto", "commercial_auto"}:
        return auto_block + (commercial_auto_block if policy_type == "commercial_auto" else "")
    if policy_type in {"general_liability", "bop", "commercial_package"}:
        return gl_block
    if policy_type == "motor_truck_cargo":
        return cargo_block
    if policy_type == "umbrella":
        return umbrella_block
    return default_block


def get_extract_coi_prompt(
    user_policy_type: Optional[str] = None,
    carrier_hints_suffix: str = "",
) -> str:
    if user_policy_type:
        classification_block = f"""
    --- CLASSIFICATION ---
    policy_type is FIXED to "{user_policy_type}" (user or system). Set classification.policy_type to exactly this string,
    confidence to "high", and include "user_selected" in classification.signals. Do not output a different policy_type.
    {CLASSIFICATION_SIGNAL_RULE}
    """
    else:
        classification_block = """
    --- CLASSIFICATION ---
    Keep document_type from routing context and classify policy_type from explicit wording only.
    """

    core = GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are an expert insurance document extraction specialist.
    This is a COI or memorandum summary document for third-party evidence of coverage.
    Extract only explicitly visible information.

    {classification_block}
    {NULL_HANDLING_RULE}
    --- FIELD CONFIDENCE ---
    For each critical field below, also return a sibling <fieldname>_confidence value:
    - policy_number
    - effective_date
    - expiration_date
    - liability_limit
    - cargo_limit
    - premium
    - insured_name
    - carrier_name
    Confidence scale:
    - high: value is clearly stated and unambiguous
    - medium: value is present but partial, abbreviated, or required interpretation
    - low: value is implied, inferred, or you are uncertain
    If the value is null/absent, set confidence to "low". Do not fabricate values.

    --- CERTIFICATE FIELDS ---
    - certificate_holder: name and address.
    - insured: name, street address, city, state_code, and zip when visible. If printed as one line, split only obvious US forms like "5074 LINDORA DR COLUMBUS, OH 43232".
    - producer: extract only from a dedicated PRODUCER box/section; never fall back to carrier/insurer.
    - additional_insured_text: copy exact wording when present.
    - cancellation_notice_days: extract integer days if stated.
    - description_of_operations: copy exact text block if present.

    --- POLICIES ARRAY ---
    - Extract every policy row shown in the certificate/memorandum.
    - For each policy include:
      policy_type, carrier_name, underwriter_name, naic_number, policy_number, effective_date, expiration_date, limits.
    - carrier_name is the customer-facing brand: Progressive, GEICO, Allstate.
    - underwriter_name is the legal insurer shown, e.g. United Financial Casualty Company, GEICO Marine Insurance Company, Allstate Insurance Company.
    - If one visible name is a full legal insurer containing a brand, split it: carrier_name = brand, underwriter_name = full legal name.
    - If only a brand/logo is visible and no legal insurer is shown, set underwriter_name null.
    - Never invent an underwriter.
    - For each critical policy field, include sibling confidence values:
      carrier_name_confidence, policy_number_confidence, effective_date_confidence, expiration_date_confidence, insured_name_confidence, premium_confidence.
    - For limits include liability_limit_confidence and cargo_limit_confidence.
    - limits should include only visible limit fields; keep missing limit fields null.
    - If Medical Payments / Med Pay is marked INCL or Included with no dollar amount, set limits.med_pay_limit to "Included".

    --- VEHICLES / DRIVERS ---
    - Extract vehicle and driver schedules if present.
    - Some formats (e.g., ACORD 25) may not include this detail; return null for vehicles/drivers in that case.
    - Never invent vehicle or driver data.

    OUTPUT: Return one JSON object with top-level keys:
    classification, certificate_holder, insured, producer, policies,
    additional_insured_text, cancellation_notice_days, description_of_operations, vehicles, drivers
    """
    suffix = (carrier_hints_suffix or "").strip()
    if suffix:
        return core + "\n" + suffix + "\n"
    return core


def get_extract_endorsement_prompt(
    user_policy_type: Optional[str] = None,
    carrier_hints_suffix: str = "",
) -> str:
    if user_policy_type:
        classification_block = f"""
    --- CLASSIFICATION ---
    policy_type is FIXED to "{user_policy_type}" (user or system). Set classification.policy_type to exactly this string,
    confidence to "high", and include "user_selected" in classification.signals. Do not output a different policy_type.
    {CLASSIFICATION_SIGNAL_RULE}
    """
    else:
        classification_block = """
    --- CLASSIFICATION ---
    Keep document_type from routing context and classify policy_type from explicit wording only.
    """

    core = GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are an insurance endorsement metadata extraction specialist.
    Extract only lightweight endorsement metadata that is explicitly visible.

    {classification_block}
    {NULL_HANDLING_RULE}
    --- ENDORSEMENT METADATA ---
    - parent_policy_number: the policy number this endorsement modifies.
    - endorsement_type: choose one from the allowed enum based on explicit content.
    - endorsement_form_number: endorsement form id if visible (example: CA 20 01).
    - effective_date: the date this endorsement change takes effect.
    - changes_summary: brief factual summary of what changed.

    Rules:
    - Do NOT extract full policy details.
    - Do NOT extract vehicle, driver, or coverage schedules as structured rows.
    - Do not infer missing values. Use null-equivalent omissions per schema behavior.

    OUTPUT: Return one JSON object with top-level keys:
    parent_policy_number, endorsement_type, endorsement_form_number, effective_date, changes_summary
    """
    suffix = (carrier_hints_suffix or "").strip()
    if suffix:
        return core + "\n" + suffix + "\n"
    return core
