DOCUMENT_TYPES = {
    "declarations_page": {
        "display": "Declarations Page",
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Primary insured document showing all coverages and limits"
    },
    "renewal_declarations": {
        "display": "Renewal Declarations Page",
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Renewal version of declarations, same structure as dec page"
    },
    "certificate_of_insurance": {
        "display": "Certificate of Insurance (COI)",
        "extractable": True,
        "extraction_goal": "coi_summary",
        "description": "ACORD 25 or similar certificate, summary only"
    },
    "memorandum": {
        "display": "Memorandum of Insurance",
        "extractable": True,
        "extraction_goal": "coi_summary",
        "description": "Similar to COI, issued by some carriers directly"
    },
    "quote": {
        "display": "Quote / Proposal",
        # Not extractable by default — pre-bind, limits not yet final. The pipeline
        # short-circuits with a non_extractable result so the broker has to opt in
        # via "Try Extraction Anyway", which sets forced_extraction=True so the
        # review/save flow flags it as pre-bind data instead of treating it as
        # active coverage.
        "extractable": False,
        "extraction_goal": "full_policy",
        "description": "Not a bound policy. Use 'Try Extraction Anyway' to extract for review only — saves will be flagged as pre-bind."
    },
    "application": {
        "display": "Application",
        # Same reasoning as quote — pre-bind, coverage not yet active. Force-extract
        # only flow tags forced_extraction=True so saves never land as live policies
        # without a deliberate broker decision.
        "extractable": False,
        "extraction_goal": "full_policy",
        "description": "Pre-bind application. Use 'Try Extraction Anyway' to extract for review only — saves will be flagged as pre-bind."
    },
    "endorsement": {
        "display": "Endorsement",
        "extractable": True,
        "extraction_goal": "endorsement_summary",
        "description": "Policy modification, captured as metadata only"
    },
    "unknown": {
        "display": "Unknown",
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Could not determine document type"
    }
}

EXTRACTION_GOAL_GROUPS = {
    "full_policy": ["declarations_page", "renewal_declarations", "application", "quote", "unknown"],
    "coi_summary": ["certificate_of_insurance", "memorandum"],
    "endorsement_summary": ["endorsement"],
    "skip": []
}
