"""
Pure helpers for the post-batch upload queue UX in process_policies.

A "batch row" is the dict that the upload loop already produces, keyed:
  filename     (str)
  status       ("ok" / "error")
  detail       (str — extraction source on ok rows, error msg on errors)
  source       (str — "cache" / "" / etc.)
  retries      (int — LLM retry count)
  error_class  (str — "rate_limit_or_quota" / "timeout" / "auth" / "parse"
                / "other" / "")

This module deliberately stays free of Streamlit so the helpers are
trivially testable. Render code lives back in process_policies.py.
"""
from __future__ import annotations

import csv
import io
from typing import Iterable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ERROR_CLASS_LABELS = {
    "rate_limit_or_quota": "Rate-limited / quota",
    "timeout": "Timeout",
    "auth": "Authentication",
    "parse": "Parse / format",
    "other": "Other error",
    "": "Unclassified",
}

# Friendly hints rendered next to each error in the summary table so the
# broker knows whether retrying makes sense.
_ERROR_RETRY_HINT = {
    "rate_limit_or_quota": "Likely transient — wait a minute, then retry.",
    "timeout": "Transient — retry should work.",
    "auth": "Check the API key in ⚙️ Settings before retrying.",
    "parse": "PDF may be unusual; retry sometimes fixes it.",
    "other": "Retry once; if it persists, the PDF may be the problem.",
    "": "",
}


# ---------------------------------------------------------------------------
# KPI summary
# ---------------------------------------------------------------------------


def queue_summary_kpis(rows: Iterable[dict]) -> dict:
    """Compute the post-batch KPI strip values.

    Returns a dict with:
      total      — number of rows processed
      ok         — count where status == "ok"
      error      — count where status == "error"
      from_cache — count where source includes "cache"
      total_retries — sum of LLM retries across all rows
      error_class_breakdown — dict[error_class_label, count]
    """
    rows = list(rows)
    total = len(rows)
    ok = sum(1 for r in rows if r.get("status") == "ok")
    error = sum(1 for r in rows if r.get("status") == "error")
    from_cache = sum(
        1
        for r in rows
        if "cache" in (r.get("source") or "")
        and r.get("status") == "ok"
    )
    total_retries = sum(int(r.get("retries") or 0) for r in rows)

    error_class_breakdown: dict[str, int] = {}
    for r in rows:
        if r.get("status") != "error":
            continue
        cls = r.get("error_class") or ""
        label = _ERROR_CLASS_LABELS.get(cls, cls or "Unclassified")
        error_class_breakdown[label] = error_class_breakdown.get(label, 0) + 1

    return {
        "total": total,
        "ok": ok,
        "error": error,
        "from_cache": from_cache,
        "total_retries": total_retries,
        "error_class_breakdown": error_class_breakdown,
    }


# ---------------------------------------------------------------------------
# Row decorations for the table view
# ---------------------------------------------------------------------------


def status_emoji(row: dict) -> str:
    """Quick visual marker for the summary table's leading column."""
    if row.get("status") == "ok":
        if "cache" in (row.get("source") or ""):
            return "💾"  # cached → no API charge
        return "✅"
    return "❌"


def retry_hint(row: dict) -> str:
    """Short broker-friendly hint for failed rows; empty string for ok rows."""
    if row.get("status") != "error":
        return ""
    return _ERROR_RETRY_HINT.get(row.get("error_class") or "", "")


# ---------------------------------------------------------------------------
# Failed-files CSV export
# ---------------------------------------------------------------------------


def failed_rows_csv_bytes(rows: Iterable[dict]) -> bytes:
    """Build a small CSV of the failed rows so the broker can keep a
    record / share with support. Returns UTF-8 encoded bytes ready to be
    fed straight into `st.download_button(data=...)`.

    Empty (zero failed rows) still returns a valid CSV with the header
    row — better than special-casing in the caller, and the download
    button can be hidden upstream if it's truly never useful.
    """
    fieldnames = ["filename", "error_class", "detail", "retries"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        if r.get("status") != "error":
            continue
        writer.writerow(
            {
                "filename": r.get("filename") or "",
                "error_class": r.get("error_class") or "",
                "detail": (r.get("detail") or "")[:1000],  # cap pathological
                "retries": r.get("retries") or 0,
            }
        )
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Retry candidate filtering
# ---------------------------------------------------------------------------


def retryable_filenames(rows: Iterable[dict]) -> list[str]:
    """Return the filenames of rows that failed. Order preserved so the
    UI can render the retry buttons in the same order as the batch ran."""
    return [r["filename"] for r in rows if r.get("status") == "error" and r.get("filename")]
