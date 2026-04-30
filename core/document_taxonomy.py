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
        "extractable": False,
        "extraction_goal": None,
        "description": "Not a bound policy, limits may change"
    },
    "application": {
        "display": "Application",
        "extractable": False,
        "extraction_goal": None,
        "description": "Pre-bind application, not actual coverage"
    },
    "endorsement": {
        "display": "Endorsement",
        "extractable": False,  # Phase 10 will change this
        "extraction_goal": None,
        "description": "Policy modification, needs parent policy context"
    },
    "unknown": {
        "display": "Unknown",
        "extractable": True,
        "extraction_goal": "full_policy",
        "description": "Could not determine document type"
    }
}

EXTRACTION_GOAL_GROUPS = {
    "full_policy": ["declarations_page", "renewal_declarations", "unknown"],
    "coi_summary": ["certificate_of_insurance", "memorandum"],
    "skip": ["quote", "application", "endorsement"]
}
