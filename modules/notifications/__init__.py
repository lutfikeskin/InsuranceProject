"""
Notification drafting and delivery hooks.

Today this module is text-only — it generates draft reminder emails that
brokers copy/paste or download. Actual SMTP / SendGrid / webhook delivery
is left to IT to wire in later; the existing function signatures stay
stable so plugging in real send paths is a single-method change.
"""
from .renewal_email import RenewalEmailDraft, draft_renewal_email

__all__ = ["RenewalEmailDraft", "draft_renewal_email"]
