# Tactical Roadmap — Insurance Document Platform

Near-term feature ideas that strengthen the existing flow (PDF upload → extract → review → save → search → COI generate) without changing the architectural shape.

**Audience:** product/engineering planning. Not a commitment; sequencing depends on customer signal and the open question (`docs/ENTERPRISE_ROADMAP.md`) of whether to invest in enterprise infrastructure first.

**Source:** distilled from the 2026-05 audit follow-up (`docs/AUDIT_2026-05.md`) and the explorer findings recorded in `.claude/plans/i-am-planning-to-dreamy-puddle.md` under Part C.

---

## Ranking key

- **Effort:** S (≤1 week), M (1–3 weeks), L (1–2 months) — single-engineer pace.
- **Impact:** High = retention/acquisition driver. Medium = quality-of-life. Low = niche.

## Tier 1 — High impact

| # | Feature | Effort | Notes |
|---|---------|--------|-------|
| 1 | **Renewal reminder automation** | M | PolicyHistory + Policy.effective_to already carry the data. Add a scheduled job (`scripts/notify_expirations.py`) that emits 60/30/14-day alerts via email or webhook. New table: `NotificationLog` to prevent double-sends. |
| 2 | **Email-to-extract intake** | M | Forwarding address (`extract@<broker-domain>`); SES/SendGrid inbound webhook → uploads attachments via the existing extraction pipeline. Auth via shared secret in the email subject or DKIM-verified sender. |
| 3 | **OCR fallback for image-only PDFs** | M | When Gemini returns empty/low-confidence extraction, run pytesseract or EasyOCR on rasterized pages and re-prompt with extracted text + page images. Wire into `modules/extraction/pipeline.py` after the first extraction attempt. |

## Tier 2 — Medium impact

| # | Feature | Effort | Notes |
|---|---------|--------|-------|
| 4 | **Policy comparison / diff view** | M | Side-by-side renewal vs. prior view. Reuse PolicyHistory; add a `views/compare_policies.py` page. Field-level diff with confidence badges. |
| ~~5~~ | ~~Bulk export (CSV / Excel)~~ | — | **Already shipped.** `views/database_page.py:591` has "📥 Export Current View" → `utils.exporter.create_excel_report`, plus a "💾 Backup Database" button beside it. Small follow-ups (CSV alternative, per-customer workbook) are nice-to-have but not roadmap-grade. |
| 6 | **Policy notes + attachment linking** | M | New tables: `PolicyNote` (freeform text, author, timestamp), `PolicyAttachment` (file blob or path, type). UI: collapsible section in the policy detail expander. |
| 7 | **COI custom template upload** | M | Today: hardcoded ACORD 25 template in `modules/coi/`. Add a `Template` table + an admin UI for uploading PDF + field-mapping JSON. The generator picks the active template by policy type. |
| 8 | **Per-field confidence threshold gate** | S | Add a setting (default: skip fields where confidence < `medium`). In the review screen, flag skipped fields with a yellow badge and a "Fill manually" link. |
| 9 | **Batch upload UX polish** | S | Drag-and-drop zone, queued progress, per-file retry. The extraction pipeline already supports concurrent processing (3 workers); just surface it cleanly. |

## Tier 3 — Low impact / defer

| # | Feature | Effort | Notes |
|---|---------|--------|-------|
| 10 | **Multi-language input** | M | Detect non-English PDFs; route to a multilingual Gemini prompt variant. Niche; defer until a Spanish/French customer signals demand. |

---

## What NOT to build (until enterprise basics land)

These all look attractive but require auth/multi-tenancy first. They live in `docs/ENTERPRISE_ROADMAP.md`:

- Public REST API (needs auth + rate limiting + per-tenant quotas).
- Webhook subscriptions (needs identity).
- "Share this policy with my underwriter" (needs user accounts + RBAC).
- Customer-facing portal (needs SSO + multi-tenancy).

Build these only **after** at least Tier 1 of `ENTERPRISE_ROADMAP.md` ships.

---

## Sequencing recommendation

If staying in single-tenant mode for the next 1–2 quarters, ship in this order:

1. **GitHub Actions CI** (from `ENTERPRISE_ROADMAP.md` #10, S) — cheap safety net before anything else lands. Runs the same `pytest` and `ruff` the local pre-commit hook does, on every PR, on a server.
2. **#8 Confidence threshold gate** (S, leans on existing extraction signal).
3. **#9 Batch upload UX** (S, polish on the most-used flow).
4. **#1 Renewal reminders** (M, retention-driving; first feature that requires scheduled-job infrastructure — also a prerequisite for any later webhook work).
5. **#3 OCR fallback** (M, removes a recurring failure class — fax/scanned PDFs).
6. **#2 Email intake** (M, dependent on #1 having proven the broker-friction reduction model).

Re-evaluate #4, #6, #7 against customer feedback after the above ships.
