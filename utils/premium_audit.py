from typing import Optional

from utils.text_utils import parse_currency

PREMIUM_PER_VEHICLE_FLOOR = 800
PREMIUM_PER_VEHICLE_CEILING = 25000


def audit_premium_vs_fleet(
    premium_str: Optional[str],
    vehicle_count: Optional[int],
    policy_type: str,
) -> dict:
    if policy_type not in ("commercial_auto", "commercial_package"):
        return {"flag": "SKIP", "confidence": "high", "reason": "not commercial auto"}

    premium = parse_currency(premium_str) if premium_str else None

    if not premium or not vehicle_count or vehicle_count <= 0:
        return {
            "flag": "MISSING_DATA",
            "confidence": "low",
            "reason": "missing premium or vehicle count",
        }

    per_vehicle = premium / vehicle_count

    if per_vehicle < PREMIUM_PER_VEHICLE_FLOOR:
        return {
            "flag": "POSSIBLE_INSTALLMENT",
            "confidence": "low",
            "per_vehicle": round(per_vehicle, 2),
            "reason": (
                f"Premium of ${premium:,.0f} / {vehicle_count} vehicles "
                f"= ${per_vehicle:,.0f}/vehicle, below ${PREMIUM_PER_VEHICLE_FLOOR} floor. "
                "Likely an installment amount, not annual."
            ),
        }

    if per_vehicle > PREMIUM_PER_VEHICLE_CEILING:
        return {
            "flag": "UNUSUALLY_HIGH",
            "confidence": "low",
            "per_vehicle": round(per_vehicle, 2),
            "reason": (
                f"Premium of ${per_vehicle:,.0f}/vehicle is unusually high. "
                "Verify it's not a misread."
            ),
        }

    return {
        "flag": "PLAUSIBLE",
        "confidence": "high",
        "per_vehicle": round(per_vehicle, 2),
    }
