"""
draft_renewal_email — pure function that turns a Policy into reminder text.

Pure means: no network, no DB writes, no Streamlit. Just policy data in, a
RenewalEmailDraft out. The Renewals page renders the result in a dialog;
the broker copies or downloads it. A future automated-email integration
can call the same function and hand its result to SMTP / SendGrid.

The function accepts anything that exposes the policy attributes via dot
access *or* dict access, so the same code works with SQLAlchemy ORM
objects, SimpleNamespace mocks in tests, and plain dicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from core.logger import logger


@dataclass(frozen=True)
class RenewalEmailDraft:
    """The output of draft_renewal_email().

    Frozen so callers can't accidentally mutate the draft after we hand
    it back. `to` may be empty when the policy has no insured_email on
    file; callers should surface that as "fill in recipient" in the UI.
    """

    to: str
    subject: str
    body: str
    download_filename: str


def _get(policy: Any, field: str, default: Any = None) -> Any:
    """Attribute-or-key access with fallback. Tolerates ORM objects, dicts,
    SimpleNamespace mocks, and None fields without raising."""
    if policy is None:
        return default
    if isinstance(policy, dict):
        return policy.get(field, default)
    return getattr(policy, field, default)


def _format_date(value: Any) -> str:
    """Render a date-ish value as 'MMM DD, YYYY'. Strings are passed through
    if we can't parse them — better to show the raw than nothing."""
    if value is None:
        return "(unknown)"
    if isinstance(value, (date, datetime)):
        return value.strftime("%b %d, %Y")
    s = str(value).strip()
    if not s:
        return "(unknown)"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%b %d, %Y")
        except ValueError:
            continue
    return s


def _format_premium(value: Any) -> str:
    """Format premium as $X,XXX.XX. Falls back to the raw string if the
    value isn't numeric (carriers sometimes print premium as 'See dec
    page' or similar)."""
    if value is None:
        return "(not on file)"
    if isinstance(value, (int, float)):
        return f"${value:,.2f}"
    s = str(value).strip()
    if not s:
        return "(not on file)"
    # Try to coerce strings like "1234.56" or "$1,234.56" or "1,234"
    cleaned = s.replace("$", "").replace(",", "").strip()
    try:
        return f"${float(cleaned):,.2f}"
    except ValueError:
        return s


def _days_until(target: Any, *, today: Optional[date] = None) -> Optional[int]:
    """Compute integer days from `today` to `target`. None when we can't."""
    if target is None:
        return None
    today = today or date.today()
    target_date: Optional[date] = None
    if isinstance(target, datetime):
        target_date = target.date()
    elif isinstance(target, date):
        target_date = target
    else:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                target_date = datetime.strptime(str(target).strip(), fmt).date()
                break
            except ValueError:
                continue
    if target_date is None:
        return None
    return (target_date - today).days


def _slugify_for_filename(text: str) -> str:
    """Cheap-and-cheerful filename sanitizer. Keep ASCII alphanumerics, dash,
    underscore. Anything else becomes underscore. Collapse runs of underscores
    so we don't end up with `_____.txt`."""
    out = []
    last_was_us = False
    for ch in (text or "policy").strip():
        if ch.isalnum() or ch in "-_":
            out.append(ch)
            last_was_us = False
        else:
            if not last_was_us:
                out.append("_")
            last_was_us = True
    cleaned = "".join(out).strip("_")
    return cleaned or "policy"


def draft_renewal_email(
    policy: Any,
    *,
    agency_name: str = "Your agency",
    today: Optional[date] = None,
) -> RenewalEmailDraft:
    """Generate a renewal-reminder draft from a Policy.

    Parameters
    ----------
    policy
        SQLAlchemy Policy object, dict, or any object whose attributes
        match the policy schema.
    agency_name
        Sign-off line. Customize via Settings later if needed; for now a
        single default keeps the function pure.
    today
        Override for the "days remaining" calculation. Mainly here so
        tests don't depend on the wall clock.
    """
    policy_id = _get(policy, "id")
    raw_insured_name = _get(policy, "insured_name")
    raw_carrier = _get(policy, "carrier_name")
    raw_policy_number = _get(policy, "policy_number")
    for field, value in (
        ("insured_name", raw_insured_name),
        ("carrier_name", raw_carrier),
        ("policy_number", raw_policy_number),
    ):
        if not value:
            logger.warning(
                "draft_renewal_email: missing %s for policy %s — using placeholder",
                field,
                policy_id,
            )

    insured_name = raw_insured_name or "Policyholder"
    carrier = raw_carrier or "(carrier on file)"
    policy_number = raw_policy_number or "(policy number on file)"
    effective = _format_date(_get(policy, "effective_date"))
    expiration_raw = _get(policy, "expiration_date")
    expiration = _format_date(expiration_raw)
    premium = _format_premium(_get(policy, "premium"))
    days_left = _days_until(expiration_raw, today=today)
    to_addr = _get(policy, "insured_email") or ""

    if days_left is None:
        days_phrase = "in the near future"
    elif days_left < 0:
        days_phrase = f"{abs(days_left)} day(s) ago"
    elif days_left == 0:
        days_phrase = "today"
    elif days_left == 1:
        days_phrase = "tomorrow"
    else:
        days_phrase = f"in {days_left} days"

    subject = f"Renewal Reminder: {carrier} policy {policy_number} expires {expiration}"

    body = (
        f"Good afternoon {insured_name},\n"
        f"\n"
        f"Your {carrier} insurance policy {policy_number} is scheduled to "
        f"expire on {expiration} ({days_phrase}).\n"
        f"\n"
        f"To ensure continuous coverage, please contact us at your earliest "
        f"convenience to discuss renewal options.\n"
        f"\n"
        f"Policy details:\n"
        f"  Carrier:        {carrier}\n"
        f"  Policy number:  {policy_number}\n"
        f"  Effective date: {effective}\n"
        f"  Expiration:     {expiration}\n"
        f"  Annual premium: {premium}\n"
        f"\n"
        f"Best regards,\n"
        f"{agency_name}\n"
    )

    filename = f"renewal_{_slugify_for_filename(insured_name)}_{_slugify_for_filename(str(policy_number))}.txt"

    return RenewalEmailDraft(
        to=to_addr,
        subject=subject,
        body=body,
        download_filename=filename,
    )
