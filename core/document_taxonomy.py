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
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Not a bound policy; extracted via full_policy prompt — limits may change"
    },
    "application": {
        "display": "Application",
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Pre-bind application; extracted via full_policy prompt — coverage may not be bound"
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
