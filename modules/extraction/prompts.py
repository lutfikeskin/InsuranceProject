from typing import Optional

GLOBAL_EXTRACTION_PRINCIPLES = """
    GLOBAL EXTRACTION PRINCIPLES:
    - Extract from tables, key-value blocks, or prose.
    - Output MUST be valid JSON.
    - Return null for any field not explicitly visible on the page. Never infer or guess.
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
    - List the detected cues used to justify document_type and policy_type in the 'signals' array.

    DISAMBIGUATION (brief):
    - umbrella: primary umbrella/excess liability policy form; not a following-form excess that only amends an underlying policy with no standalone umbrella declarations.
    - bop: Businessowners Policy / BOP as the base form; do not use commercial_package unless CP wording and multi-line package (see package rule).
    - motor_truck_cargo: dedicated motor truck cargo hauler policy as primary; if primary form is commercial auto with a cargo endorsement, use commercial_auto (dominance).
    """


def get_extract_all_prompt(
    registry_text: str,
    user_policy_type: Optional[str] = None,
    carrier_hints_suffix: str = "",
    unreliable_fields: Optional[list[str]] = None,
) -> str:
    if user_policy_type:
        classification_block = f"""
    --- CLASSIFICATION ---
    policy_type is FIXED to "{user_policy_type}" (user or system). Set classification.policy_type to exactly this string,
    confidence to "high", and include "user_selected" in classification.signals. Do not output a different policy_type.
    """
    else:
        classification_block = """
    --- CLASSIFICATION ---
    Choose ONE: personal_auto, commercial_auto, general_liability, bop, commercial_package, umbrella, motor_truck_cargo, unknown.
    - Base decision on explicit wording.
    - PACKAGE RULE: If 'commercial_package', confirm AT LEAST TWO of: General Liability, Property, or Auto.
    - If Auto + Cargo only, classify as 'commercial_auto' (dominance rule).
    """

    declarations_block = """
    --- POLICY DECLARATIONS ---
    - Distinguish between Carrier (Risk Bearer) and Agency (Broker). Extract Carrier only.
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

    core = GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are an expert insurance underwriter and data extraction specialist.
    Extract the COMPLETE policy information from the provided document in a single pass.
    {classification_block}
    {declarations_block}
    {confidence_block}
    {unreliable_block}
    --- VEHICLES ---
    - Extract ALL vehicles (VIN, Year, Make, Model, GVW, Type).
    - Look for explicit schedules and vehicles mentioned in prose.

    --- DRIVERS ---
    - Extract ALL drivers (Name, License #, Excluded status).

    --- COVERAGES ---
    - Map every coverage to a valid coverage_code from the registry below.
    - Link vehicle-specific coverages to vehicle_vin.
    - For COMP and COLL, always extract the deductible amount — check schedules, tables, and endorsement pages.
    - If a row says Included/Yes without a numeric limit, keep limits null; do not invent dollar amounts.
    - Common label hints: BI/LIAB→AUTO_LIAB_BI, PD/Prop Damage→AUTO_LIAB_PD, UM/UIM, PIP, OTC/COMP, COLL, RR→RENTAL, Towing→TOWING.
    - Michigan: Property Protection (PPI in-state) is not the same as PD liability; use code MI_PPI when clearly PPI.
    - Hired/Non-Owned: use HIRED_AUTO / NON_OWNED_AUTO; set hnoa_basis if primary vs excess is stated; hnoa_attached_to bap or gl if the form says which policy it amends.
    - REGISTRY: {registry_text}

    --- VEHICLES (commercial) ---
    - BAP: if a schedule shows covered auto designation symbols, copy them to covered_auto_symbols (comma-separated), e.g. 1,7.

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


def get_extract_coi_prompt(
    user_policy_type: Optional[str] = None,
    carrier_hints_suffix: str = "",
) -> str:
    if user_policy_type:
        classification_block = f"""
    --- CLASSIFICATION ---
    policy_type is FIXED to "{user_policy_type}" (user or system). Set classification.policy_type to exactly this string,
    confidence to "high", and include "user_selected" in classification.signals. Do not output a different policy_type.
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
    - insured: name and address.
    - producer: name, address, and phone if shown.
    - additional_insured_text: copy exact wording when present.
    - cancellation_notice_days: extract integer days if stated.
    - description_of_operations: copy exact text block if present.

    --- POLICIES ARRAY ---
    - Extract every policy row shown in the certificate/memorandum.
    - For each policy include:
      policy_type, carrier_name, naic_number, policy_number, effective_date, expiration_date, limits.
    - For each critical policy field, include sibling confidence values:
      carrier_name_confidence, policy_number_confidence, effective_date_confidence, expiration_date_confidence, insured_name_confidence, premium_confidence.
    - For limits include liability_limit_confidence and cargo_limit_confidence.
    - limits should include only visible limit fields; keep missing limit fields null.

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
