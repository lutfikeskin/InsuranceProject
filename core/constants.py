POLICY_TYPES = [
    "personal_auto", 
    "commercial_auto", 
    "general_liability", 
    "bop", 
    "commercial_package", 
    "umbrella", 
    "motor_truck_cargo", 
    "unknown"
]

STATUS_OPTIONS = ["Active", "Pending", "Quote", "Expired", "Cancelled"]

CONFIDENCE_OPTIONS = ["high", "medium", "low"]

VEHICLE_TYPES = ["Private Passenger", "Truck", "Trailer", "Tractor", "Van", "Bus", "Motorcycle", "Unknown"]

INTEREST_TYPES = [
    "Loss Payee", 
    "Additional Insured", 
    "Lienholder", 
    "Certificate Holder", 
    "Mortgagee", 
    "Other"
]

VIN_REGEX = "^[A-HJ-NPR-Z0-9]{17}$"

DEFAULT_DAILY_BUDGET = 2.5

# Confidence gate (review screen).
# Threshold names the *minimum* confidence the user trusts; values below it are
# pre-cleared on the review form so the user has to fill them in by hand. Soft
# nudge only — Save is never blocked.
#   "off"    — clear nothing
#   "medium" — clear "low" (default; only the riskiest values get nuked)
#   "high"   — clear "low" + "medium" (strict; everything but "high" gets nuked)
CONFIDENCE_GATE_DEFAULT = "medium"
CONFIDENCE_GATE_OPTIONS = {
    "off": "Off — trust all extracted values",
    "medium": "Clear low-confidence fields (recommended)",
    "high": "Clear low + medium-confidence fields (strictest)",
}

# Policy list/search (Database, COI, Dashboard)
POLICY_SEARCH_PAGE_LIMIT = 100
POLICY_DELETE_CANDIDATE_LIMIT = 500

# Product name (sidebar / page title should stay in sync in app.py)
APP_DISPLAY_NAME = "Insurance Doc Intelligence"
APP_DISPLAY_TAGLINE = "Policy Intelligence Hub"
