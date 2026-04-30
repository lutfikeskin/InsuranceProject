CARRIER_FIELD_WEIGHTS = {
    "default": {
        "critical": [
            "policy_number",
            "effective_date",
            "expiration_date",
            "carrier_name",
            "insured_name",
            "liability_limit",
        ],
        "variable": ["drivers", "vehicles", "coverages"],
        "skip": [],
    },
    "progressive": {
        "critical": [
            "policy_number",
            "effective_date",
            "expiration_date",
            "liability_limit",
            "carrier_name",
            "insured_name",
        ],
        "variable": ["drivers", "vehicles"],
        "skip": ["um_uim_limit", "pip_limit"],
    },
    "geico": {
        "critical": [
            "policy_number",
            "insured_name",
            "cargo_limit",
            "carrier_name",
            "effective_date",
            "expiration_date",
        ],
        "variable": ["vehicles"],
        "skip": ["insured_zip"],
    },
}

VARIABLE_COUNT_TOLERANCE = 1
