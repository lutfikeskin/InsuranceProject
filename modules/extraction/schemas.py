
# --- SCHEMAS ---

CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "policy_type": {
            "type": "STRING",
            "enum": [
                "personal_auto", "commercial_auto", "general_liability", "bop",
                "commercial_package", "umbrella", "motor_truck_cargo", "unknown"
            ]
        },
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "signals": {"type": "ARRAY", "items": {"type": "STRING"}}
    },
    "required": ["policy_type", "confidence"]
}

SECTION_LOCATOR_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "declarations": {"type": "ARRAY", "items": {"type": "INTEGER"}}, # Page numbers
        "coverages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "vehicles": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "drivers": {"type": "ARRAY", "items": {"type": "INTEGER"}}
    },
    "required": ["declarations", "coverages"]
}

DECLARATIONS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "carrier_name": {"type": "STRING"},
        "naic_number": {"type": "STRING"},
        "policy_number": {"type": "STRING"},
        "effective_date": {"type": "STRING"},
        "expiration_date": {"type": "STRING"},
        "account_type": {"type": "STRING"},
        "insured_name": {"type": "STRING"},
        "insured_address": {"type": "STRING"},
        "insured_city": {"type": "STRING"},
        "insured_state_code": {"type": "STRING"},
        "insured_zip": {"type": "STRING"},
        "business_name": {"type": "STRING"},
        "premium": {"type": "STRING"},
        "financial_responsibility_name": {"type": "STRING"},

        "state": {"type": "STRING"},
        "field_locations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "field": {"type": "STRING"},
                    "page_number": {"type": "INTEGER"},
                    "bbox": {
                        "type": "ARRAY", 
                        "items": {"type": "INTEGER"},
                        "description": "[ymin, xmin, ymax, xmax] in 0-1000 scale"
                    }
                }
            }
        }
    }
}

COVERAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "coverages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "coverage_code": {
                        "type": "STRING", 
                        "description": "Must be one of the explicitly allowed registry codes."
                    },
                    "display_name": {"type": "STRING"},
                    "family": {
                        "type": "STRING",
                        "enum": [
                            "auto_liability", "uninsured_motorist", "underinsured_motorist",
                            "physical_damage", "general_liability", "cargo",
                            "medical_payments", "pip", "other"
                        ]
                    },
                    "limit_structure": {
                        "type": "STRING",
                        "enum": ["csl", "split", "per_occurrence", "aggregate", "deductible_only", "scheduled"]
                    },
                    "limits": {
                        "type": "OBJECT",
                        "properties": {
                            "per_person": {"type": "INTEGER"},
                            "per_accident": {"type": "INTEGER"},
                            "per_occurrence": {"type": "INTEGER"},
                            "combined_single_limit": {"type": "INTEGER"},
                            "aggregate": {"type": "INTEGER"}
                        }
                    },
                    "deductible": {"type": "INTEGER"},
                    "location": {
                        "type": "OBJECT",
                        "properties": {
                            "page_number": {"type": "INTEGER"},
                            "bbox": {"type": "ARRAY", "items": {"type": "INTEGER"}}
                        }
                    }
                }
            }
        }
    }
}

VEHICLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "year": {"type": "INTEGER"},
                    "make": {"type": "STRING"},
                    "model": {"type": "STRING"},
                    "vin": {"type": "STRING"},
                    "gvw": {"type": "INTEGER"},
                    "type": {"type": "STRING"}
                }
            }
        }
    }
}

DRIVER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "drivers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "full_name": {"type": "STRING"},
                    "license_number": {"type": "STRING"},
                    "is_excluded": {"type": "BOOLEAN"}
                }
            }
        }
    }
}


UNIVERSAL_SCOUT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "premium_signals": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "page": {"type": "INTEGER"},
                    "type": {"type": "STRING", "enum": ["gross", "net", "total", "installment", "fee", "unknown"]},
                    "period": {"type": "STRING", "enum": ["annual", "6-month", "monthly", "unknown"]}
                },
                "required": ["label", "page"]
            }
        },
        "vehicle_schedule_signals": {
            "type": "ARRAY",
            "items": {
                "type": "INTEGER"
            }
        },
        "driver_schedule_signals": {
            "type": "ARRAY",
            "items": {
                "type": "INTEGER"
            }
        },
        "coverage_schedule_signals": {
            "type": "ARRAY",
            "items": {
                "type": "INTEGER"
            }
        }
    },
    "required": [
        "premium_signals",
        "vehicle_schedule_signals",
        "driver_schedule_signals",
        "coverage_schedule_signals"
    ]
}
