from typing import Optional


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


_CONF = {"type": "STRING", "enum": ["high", "medium", "low"]}


def _nstr(description: Optional[str] = None) -> dict:
    """Optional string field. Gemini emits real JSON null instead of the literal "null"."""
    schema = {"type": "STRING", "nullable": True}
    if description:
        schema["description"] = description
    return schema


def _nint() -> dict:
    return {"type": "INTEGER", "nullable": True}


def _nbool() -> dict:
    return {"type": "BOOLEAN", "nullable": True}


# Declarations fields shared by all policy types.
_BASE_DECLARATIONS_FIELDS = {
    "carrier_name": _nstr(),
    "carrier_name_confidence": _CONF,
    "underwriter_name": _nstr(),
    "underwriter_name_confidence": _CONF,
    "naic_number": _nstr(),
    "policy_number": _nstr(),
    "policy_number_confidence": _CONF,
    "effective_date": _nstr(),
    "effective_date_confidence": _CONF,
    "expiration_date": _nstr(),
    "expiration_date_confidence": _CONF,
    "account_type": _nstr(),
    "insured_name": _nstr(),
    "insured_name_confidence": _CONF,
    "insured_address": _nstr(),
    "insured_city": _nstr(),
    "insured_state_code": _nstr(),
    "insured_zip": _nstr(),
    "business_name": _nstr(),
    "premium": _nstr(),
    "premium_confidence": _CONF,
    "financial_responsibility_name": _nstr(),
    "state": _nstr(),
}

_BASE_DECLARATIONS_REQUIRED = [
    "carrier_name_confidence",
    "underwriter_name_confidence",
    "policy_number_confidence",
    "effective_date_confidence",
    "expiration_date_confidence",
    "premium_confidence",
    "insured_name_confidence",
]

# Fields only relevant to commercial-line policies. Excluded from personal auto schema.
_COMMERCIAL_DECLARATIONS_EXTRAS = {
    "liability_limit": _nstr(),
    "liability_limit_confidence": _CONF,
    "cargo_limit": _nstr(),
    "cargo_limit_confidence": _CONF,
    "mcs90_noted": _nstr("yes if MCS-90 endorsement mentioned; else null."),
    "motor_carrier_id": _nstr("MC number if shown."),
    "dot_number": _nstr(),
    "drive_other_car_note": _nstr("DOC / CA 99 10: named individuals if present."),
}

DECLARATIONS_SCHEMA = {
    "type": "OBJECT",
    "properties": {**_BASE_DECLARATIONS_FIELDS, **_COMMERCIAL_DECLARATIONS_EXTRAS},
    "required": _BASE_DECLARATIONS_REQUIRED + [
        "liability_limit_confidence",
        "cargo_limit_confidence",
    ],
}

PERSONAL_AUTO_DECLARATIONS_SCHEMA = {
    "type": "OBJECT",
    "properties": dict(_BASE_DECLARATIONS_FIELDS),
    "required": list(_BASE_DECLARATIONS_REQUIRED),
}


COMPLIANCE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "mcs90_noted": _nstr(),
        "motor_carrier_id": _nstr(),
        "dot_number": _nstr(),
        "doc_endorsement_text": _nstr("Drive Other Car or similar endorsement summary."),
        "doc_endorsements": {
            "type": "ARRAY",
            "description": "Structured CA 99 10 or similar: form id and named individuals.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "form_id": _nstr(),
                    "named_individuals": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    }
                }
            }
        }
    }
}


_LIMIT_STRUCTURE_ENUM = ["csl", "split", "per_occurrence", "aggregate", "deductible_only", "scheduled"]
_FAMILY_ENUM = [
    "auto_liability", "uninsured_motorist", "underinsured_motorist",
    "physical_damage", "general_liability", "cargo",
    "medical_payments", "pip", "other"
]

_BASE_COVERAGE_ITEM_PROPS = {
    "coverage_code": _nstr("Must be one of the explicitly allowed registry codes."),
    "display_name": _nstr(),
    "family": {"type": "STRING", "enum": _FAMILY_ENUM, "nullable": True},
    "limit_structure": {"type": "STRING", "enum": _LIMIT_STRUCTURE_ENUM, "nullable": True},
    "limits": {
        "type": "OBJECT",
        "properties": {
            "per_person": _nint(),
            "per_accident": _nint(),
            "per_occurrence": _nint(),
            "combined_single_limit": _nint(),
            "aggregate": _nint(),
        }
    },
    "deductible": _nint(),
    "vehicle_vin": _nstr("If coverage applies to a specific vehicle/unit, provide the VIN here. Otherwise null."),
}

_COMMERCIAL_COVERAGE_EXTRAS = {
    "limit_descriptor": _nstr("If limits are Statutory/Minimum/Unlimited, set this instead of fabricating numbers."),
    "is_stacked": _nbool(),
    "stacked_vehicle_count": _nint(),
    "hnoa_basis": _nstr("Hired/Non-Owned: primary or excess if stated."),
    "hnoa_attached_to": _nstr("bap or gl if the document states which policy the endorsement attaches to."),
    "full_glass_waiver": _nbool(),
    "deductible_scope": _nstr("per_vehicle or per_occurrence for physical damage if stated."),
    "fl_pip_tier": _nstr("Florida PIP: basic, extended, or additional if stated."),
    "valuation_method": _nstr("ACV, replacement cost, or stated amount for physical damage if shown."),
}

COVERAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "coverages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {**_BASE_COVERAGE_ITEM_PROPS, **_COMMERCIAL_COVERAGE_EXTRAS},
            }
        }
    }
}

PERSONAL_AUTO_COVERAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "coverages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": dict(_BASE_COVERAGE_ITEM_PROPS),
            }
        }
    }
}


_BASE_VEHICLE_ITEM_PROPS = {
    "year": _nint(),
    "make": _nstr(),
    "model": _nstr(),
    "vin": _nstr(),
    "gvw": _nint(),
    "type": _nstr(),
    "chassis": _nstr(),
    "body": _nstr(),
}

_COMMERCIAL_VEHICLE_EXTRAS = {
    "covered_auto_symbols": _nstr("BAP: comma-separated covered auto designation symbols, e.g. 1,2,7."),
    "radius_of_operation": _nstr("local, intermediate, long distance, or as printed."),
    "business_use_class": _nstr(),
    "valuation_basis": _nstr("ACV, replacement cost, or stated value if shown for this unit."),
}

VEHICLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {**_BASE_VEHICLE_ITEM_PROPS, **_COMMERCIAL_VEHICLE_EXTRAS},
            }
        }
    }
}

PERSONAL_AUTO_VEHICLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": dict(_BASE_VEHICLE_ITEM_PROPS),
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
                    "full_name": _nstr(),
                    "license_number": _nstr(),
                    "is_excluded": _nbool(),
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
                },
                "required": ["label", "page"],
            },
        },
        "vehicle_schedule_signals": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "driver_schedule_signals": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "coverage_schedule_signals": {"type": "ARRAY", "items": {"type": "INTEGER"}},
    },
    "required": [
        "premium_signals",
        "vehicle_schedule_signals",
        "driver_schedule_signals",
        "coverage_schedule_signals",
    ],
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

PERSONAL_AUTO_POLICY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "classification": CLASSIFICATION_SCHEMA,
        "policy": PERSONAL_AUTO_DECLARATIONS_SCHEMA,
        "coverages": PERSONAL_AUTO_COVERAGE_SCHEMA["properties"]["coverages"],
        "vehicles": PERSONAL_AUTO_VEHICLE_SCHEMA["properties"]["vehicles"],
        "drivers": DRIVER_SCHEMA["properties"]["drivers"],
    },
    "required": ["classification", "policy", "coverages", "vehicles", "drivers"],
}


def build_complete_policy_schema(policy_type: Optional[str]) -> dict:
    """Return the response schema scoped to the given policy type.

    Personal auto strips commercial-only fields (compliance block, motor_carrier_id,
    hnoa, fl_pip_tier, covered_auto_symbols, etc.) so Gemini doesn't waste output
    tokens emitting null placeholders for fields that never apply.
    """
    if policy_type == "personal_auto":
        return PERSONAL_AUTO_POLICY_SCHEMA
    return COMPLETE_POLICY_SCHEMA


COI_SUMMARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "classification": CLASSIFICATION_SCHEMA,
        "certificate_holder": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "address": {"type": "STRING"},
            },
        },
        "insured": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "address": {"type": "STRING"},
                "city": {"type": "STRING", "nullable": True},
                "state_code": {"type": "STRING", "nullable": True},
                "zip": {"type": "STRING", "nullable": True},
            },
        },
        "producer": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {
                "name": {"type": "STRING", "nullable": True},
                "address": {"type": "STRING", "nullable": True},
                "phone": {"type": "STRING", "nullable": True},
            },
        },
        "policies": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "policy_type": {"type": "STRING"},
                    "carrier_name": {"type": "STRING"},
                    "carrier_name_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "underwriter_name": {"type": "STRING", "nullable": True},
                    "naic_number": {"type": "STRING"},
                    "policy_number": {"type": "STRING"},
                    "policy_number_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "effective_date": {"type": "STRING"},
                    "effective_date_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "expiration_date": {"type": "STRING"},
                    "expiration_date_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "insured_name": {"type": "STRING"},
                    "insured_name_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "business_name": {"type": "STRING", "nullable": True},
                    "business_name_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "premium": {"type": "STRING"},
                    "premium_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "limits": {
                        "type": "OBJECT",
                        "properties": {
                            "liability_limit": {"type": "STRING"},
                            "liability_limit_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                            "general_liability_limit": {"type": "STRING"},
                            "cargo_limit": {"type": "STRING"},
                            "cargo_limit_confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                            "cargo_deductible": {"type": "STRING"},
                            "um_uim_limit": {"type": "STRING"},
                            "med_pay_limit": {"type": "STRING"},
                            "pip_limit": {"type": "STRING"},
                            "comp_deductible": {"type": "STRING"},
                            "coll_deductible": {"type": "STRING"},
                        },
                        "required": [
                            "liability_limit_confidence",
                            "cargo_limit_confidence",
                        ],
                    },
                },
                "required": [
                    "carrier_name_confidence",
                    "policy_number_confidence",
                    "effective_date_confidence",
                    "expiration_date_confidence",
                    "insured_name_confidence",
                    "premium_confidence",
                    "limits",
                ],
            },
        },
        "additional_insured_text": {"type": "STRING", "nullable": True},
        "cancellation_notice_days": {"type": "INTEGER", "nullable": True},
        "description_of_operations": {"type": "STRING", "nullable": True},
        "vehicles": {
            "type": "ARRAY",
            "nullable": True,
            "items": VEHICLE_SCHEMA["properties"]["vehicles"]["items"],
        },
        "drivers": {
            "type": "ARRAY",
            "nullable": True,
            "items": DRIVER_SCHEMA["properties"]["drivers"]["items"],
        },
    },
    "required": ["classification", "certificate_holder", "insured", "producer", "policies"],
}


ENDORSEMENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "parent_policy_number": {"type": "STRING"},
        "endorsement_type": {
            "type": "STRING",
            "enum": [
                "additional_insured",
                "excluded_driver",
                "coverage_change",
                "vehicle_add",
                "vehicle_delete",
                "cargo_amendment",
                "premium_change",
                "other",
            ],
        },
        "endorsement_form_number": {"type": "STRING"},
        "effective_date": {"type": "STRING"},
        "changes_summary": {"type": "STRING"},
    },
    "required": ["parent_policy_number", "endorsement_type", "effective_date"],
}
