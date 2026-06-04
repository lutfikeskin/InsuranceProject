"""
Unit tests for views/upload_queue.py.

Pure-Python module so no Streamlit harness needed.
"""

import csv
import io


from views.upload_queue import (
    failed_rows_csv_bytes,
    queue_summary_kpis,
    retry_hint,
    retryable_filenames,
    status_emoji,
    upsert_row,
)


# Convenient row builders -------------------------------------------------


def _ok(filename: str, source: str = "", retries: int = 0) -> dict:
    return {
        "filename": filename,
        "status": "ok",
        "detail": "extracted",
        "source": source,
        "retries": retries,
        "error_class": "",
    }


def _err(
    filename: str,
    error_class: str = "other",
    detail: str = "boom",
    retries: int = 0,
) -> dict:
    return {
        "filename": filename,
        "status": "error",
        "detail": detail,
        "source": "",
        "retries": retries,
        "error_class": error_class,
    }


# queue_summary_kpis -------------------------------------------------------


class TestQueueSummaryKpis:
    def test_empty_batch(self):
        result = queue_summary_kpis([])
        assert result == {
            "total": 0,
            "ok": 0,
            "error": 0,
            "from_cache": 0,
            "total_retries": 0,
            "error_class_breakdown": {},
        }

    def test_counts_ok_vs_error(self):
        rows = [_ok("a.pdf"), _ok("b.pdf"), _err("c.pdf"), _err("d.pdf")]
        result = queue_summary_kpis(rows)
        assert result["total"] == 4
        assert result["ok"] == 2
        assert result["error"] == 2

    def test_from_cache_counts_only_ok_cached_rows(self):
        # A cache hit must also be a success; otherwise the count is wrong.
        rows = [
            _ok("a.pdf", source="cache"),
            _ok("b.pdf", source="cache_warm"),  # any source containing "cache"
            _ok("c.pdf", source=""),
            _err("d.pdf"),
        ]
        result = queue_summary_kpis(rows)
        assert result["from_cache"] == 2
        assert result["ok"] == 3

    def test_total_retries_is_sum(self):
        rows = [_ok("a.pdf", retries=2), _ok("b.pdf", retries=0), _err("c.pdf", retries=3)]
        result = queue_summary_kpis(rows)
        assert result["total_retries"] == 5

    def test_error_class_breakdown_uses_friendly_labels(self):
        rows = [
            _err("a.pdf", error_class="rate_limit_or_quota"),
            _err("b.pdf", error_class="rate_limit_or_quota"),
            _err("c.pdf", error_class="timeout"),
            _err("d.pdf", error_class=""),  # unclassified
        ]
        result = queue_summary_kpis(rows)
        assert result["error_class_breakdown"] == {
            "Rate-limited / quota": 2,
            "Timeout": 1,
            "Unclassified": 1,
        }

    def test_ok_rows_dont_appear_in_error_breakdown(self):
        rows = [_ok("a.pdf"), _err("b.pdf", error_class="timeout")]
        result = queue_summary_kpis(rows)
        assert result["error_class_breakdown"] == {"Timeout": 1}


# status_emoji -------------------------------------------------------------


class TestStatusEmoji:
    def test_ok_no_cache(self):
        assert status_emoji(_ok("a.pdf")) == "✅"

    def test_ok_from_cache(self):
        assert status_emoji(_ok("a.pdf", source="cache")) == "💾"

    def test_error(self):
        assert status_emoji(_err("a.pdf")) == "❌"


# retry_hint ---------------------------------------------------------------


class TestRetryHint:
    def test_ok_row_has_no_hint(self):
        assert retry_hint(_ok("a.pdf")) == ""

    def test_rate_limit_hint_mentions_waiting(self):
        hint = retry_hint(_err("a.pdf", error_class="rate_limit_or_quota"))
        assert "wait" in hint.lower()

    def test_auth_hint_mentions_settings(self):
        hint = retry_hint(_err("a.pdf", error_class="auth"))
        assert "API key" in hint or "Settings" in hint

    def test_unknown_class_returns_empty_or_neutral(self):
        # Unknown error_class should not crash; return empty string.
        hint = retry_hint(_err("a.pdf", error_class="something_new"))
        assert hint == ""


# failed_rows_csv_bytes ----------------------------------------------------


class TestFailedRowsCsv:
    def test_returns_bytes(self):
        out = failed_rows_csv_bytes([_err("a.pdf")])
        assert isinstance(out, bytes)

    def test_header_always_present_even_when_empty(self):
        out = failed_rows_csv_bytes([])
        text = out.decode("utf-8")
        # Header row only.
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        assert header == ["filename", "error_class", "detail", "retries"]
        # No data rows.
        assert list(reader) == []

    def test_only_includes_error_rows(self):
        rows = [_ok("ok.pdf"), _err("bad.pdf", error_class="timeout")]
        out = failed_rows_csv_bytes(rows)
        text = out.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        records = list(reader)
        assert len(records) == 1
        assert records[0]["filename"] == "bad.pdf"
        assert records[0]["error_class"] == "timeout"

    def test_detail_is_truncated_at_1000_chars(self):
        rows = [_err("a.pdf", detail="x" * 5000)]
        out = failed_rows_csv_bytes(rows)
        text = out.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        record = next(reader)
        assert len(record["detail"]) == 1000

    def test_round_trip_preserves_fields(self):
        rows = [
            _err("policy_2024.pdf", error_class="parse", detail="bad JSON", retries=2),
            _err("policy_2025.pdf", error_class="timeout", detail="60s", retries=1),
        ]
        out = failed_rows_csv_bytes(rows)
        text = out.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        records = list(reader)
        assert records[0]["filename"] == "policy_2024.pdf"
        assert records[0]["retries"] == "2"
        assert records[1]["filename"] == "policy_2025.pdf"


# retryable_filenames ------------------------------------------------------


class TestRetryableFilenames:
    def test_returns_failed_filenames_in_order(self):
        rows = [
            _ok("ok1.pdf"),
            _err("bad1.pdf"),
            _ok("ok2.pdf"),
            _err("bad2.pdf"),
        ]
        assert retryable_filenames(rows) == ["bad1.pdf", "bad2.pdf"]

    def test_excludes_ok_rows(self):
        rows = [_ok("a.pdf"), _ok("b.pdf")]
        assert retryable_filenames(rows) == []

    def test_drops_rows_without_filename(self):
        rows = [_err("a.pdf"), {**_err(""), "filename": ""}]
        assert retryable_filenames(rows) == ["a.pdf"]


# upsert_row --------------------------------------------------------------


class TestUpsertRow:
    def test_empty_input_returns_single_row(self):
        new = _ok("a.pdf")
        assert upsert_row([], new) == [new]

    def test_replaces_matching_filename_preserving_order(self):
        old = [_err("a.pdf"), _ok("b.pdf"), _err("c.pdf")]
        new = _ok("b.pdf", source="cache", retries=1)
        result = upsert_row(old, new)
        assert [r["filename"] for r in result] == ["a.pdf", "b.pdf", "c.pdf"]
        assert result[1] is new

    def test_appends_when_no_filename_matches(self):
        old = [_ok("a.pdf"), _err("b.pdf")]
        new = _err("c.pdf", error_class="timeout")
        result = upsert_row(old, new)
        assert [r["filename"] for r in result] == ["a.pdf", "b.pdf", "c.pdf"]
        assert result[2] is new

    def test_does_not_mutate_input(self):
        old = [_err("a.pdf"), _ok("b.pdf")]
        snapshot = [dict(r) for r in old]
        upsert_row(old, _ok("a.pdf"))
        assert old == snapshot
