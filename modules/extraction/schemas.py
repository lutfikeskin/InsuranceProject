
CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "document_type": {
            "type": "STRING",
            "enum": [
                "declarations_page",
                "renewal_declarations",
                "certificate_of_insurance",
                "memorandum",
                "quote",
                "application",
                "endorsement",
                "unknown",
            ]
        },
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
    "required": ["document_type", "policy_type", "confidence"]
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
        "mcs90_noted": {
            "type": "STRING",
            "description": "yes if MCS-90 endorsement mentioned; else null."
        },
        "motor_carrier_id": {"type": "STRING", "description": "MC number if shown."},
        "dot_number": {"type": "STRING"},
        "drive_other_car_note": {
            "type": "STRING",
            "description": "DOC / CA 99 10: named individuals if present."
        }
    }
}

COMPLIANCE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "mcs90_noted": {"type": "STRING"},
        "motor_carrier_id": {"type": "STRING"},
        "dot_number": {"type": "STRING"},
        "doc_endorsement_text": {
            "type": "STRING",
            "description": "Drive Other Car or similar endorsement summary."
        },
        "doc_endorsements": {
            "type": "ARRAY",
            "description": "Structured CA 99 10 or similar: form id and named individuals.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "form_id": {"type": "STRING"},
                    "named_individuals": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
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
                    "vehicle_vin": {
                        "type": "STRING",
                        "description": "If coverage applies to a specific vehicle/unit, provide the VIN here. Otherwise null."
                    },
                    "limit_descriptor": {
                        "type": "STRING",
                        "description": "If limits are Statutory/Minimum/Unlimited, set this instead of fabricating numbers."
                    },
                    "is_stacked": {"type": "BOOLEAN", "description": "UM/UIM: stacked when permitted."},
                    "stacked_vehicle_count": {"type": "INTEGER"},
                    "hnoa_basis": {
                        "type": "STRING",
                        "description": "Hired/Non-Owned: primary or excess if stated."
                    },
                    "hnoa_attached_to": {
                        "type": "STRING",
                        "description": "bap or gl if the document states which policy the endorsement attaches to."
                    },
                    "full_glass_waiver": {"type": "BOOLEAN"},
                    "deductible_scope": {
                        "type": "STRING",
                        "description": "per_vehicle or per_occurrence for physical damage if stated."
                    },
                    "fl_pip_tier": {
                        "type": "STRING",
                        "description": "Florida PIP: basic, extended, or additional if stated."
                    },
                    "valuation_method": {
                        "type": "STRING",
                        "description": "ACV, replacement cost, or stated amount for physical damage if shown."
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
                    "type": {"type": "STRING"},
                    "chassis": {"type": "STRING"},
                    "body": {"type": "STRING"},
                    "covered_auto_symbols": {
                        "type": "STRING",
                        "description": "BAP: comma-separated covered auto designation symbols, e.g. 1,2,7."
                    },
                    "radius_of_operation": {
                        "type": "STRING",
                        "description": "local, intermediate, long distance, or as printed."
                    },
                    "business_use_class": {"type": "STRING"},
                    "valuation_basis": {
                        "type": "STRING",
                        "description": "ACV, replacement cost, or stated value if shown for this unit."
                    }
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




COMPLETE_POLICY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "classification": CLASSIFICATION_SCHEMA,
        "policy": DECLARATIONS_SCHEMA,
        "compliance": COMPLIANCE_SCHEMA,
        "coverages": COVERAGE_SCHEMA["properties"]["coverages"],
        "vehicles": VEHICLE_SCHEMA["properties"]["vehicles"],
        "drivers": DRIVER_SCHEMA["properties"]["drivers"]
    },
    "required": ["classification", "policy", "compliance", "coverages", "vehicles", "drivers"]
}
