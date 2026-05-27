from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import case, func

from core.database import ApiUsage, AppEvent, get_session
from core.telemetry import TelemetryService


RANGE_OPTIONS = {
    "Last 24 hours": 1,
    "Last 7 days": 7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "All time": None,
}

@dataclass
class TelemetryWindow:
    label: str
    days: int | None
    cutoff: datetime | None
    previous_start: datetime | None
    previous_end: datetime | None


@dataclass
class UsageAggregate:
    calls: int = 0
    success: int = 0
    issues: int = 0
    spend: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    avg_latency_ms: int = 0


def _metadata_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _build_window(label: str) -> TelemetryWindow:
    days = RANGE_OPTIONS[label]
    if days is None:
        return TelemetryWindow(label, None, None, None, None)
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    return TelemetryWindow(
        label=label,
        days=days,
        cutoff=cutoff,
        previous_start=cutoff - timedelta(days=days),
        previous_end=cutoff,
    )


def _apply_window(query, model, window: TelemetryWindow):
    if window.cutoff is not None:
        query = query.filter(model.timestamp >= window.cutoff)
    return query


def _apply_previous_window(query, model, window: TelemetryWindow):
    if window.previous_start is None or window.previous_end is None:
        return query.filter(False)
    return query.filter(
        model.timestamp >= window.previous_start,
        model.timestamp < window.previous_end,
    )


def _event_count(
    session,
    event_name: str,
    *,
    window: TelemetryWindow,
    status: str | None = None,
    previous: bool = False,
) -> int:
    query = session.query(func.count(AppEvent.id)).filter(
        AppEvent.event_name == event_name
    )
    query = _apply_previous_window(query, AppEvent, window) if previous else _apply_window(query, AppEvent, window)
    if status is not None:
        query = query.filter(AppEvent.status == status)
    return int(query.scalar() or 0)


def _event_sum_count_value(
    session,
    event_names: list[str],
    *,
    window: TelemetryWindow,
    status: str | None = None,
    previous: bool = False,
) -> int:
    query = session.query(func.sum(AppEvent.count_value)).filter(
        AppEvent.event_name.in_(event_names)
    )
    query = _apply_previous_window(query, AppEvent, window) if previous else _apply_window(query, AppEvent, window)
    if status is not None:
        query = query.filter(AppEvent.status == status)
    return int(query.scalar() or 0)


def _usage_query(session, window: TelemetryWindow, *, previous: bool = False):
    query = session.query(ApiUsage)
    return _apply_previous_window(query, ApiUsage, window) if previous else _apply_window(query, ApiUsage, window)


def _usage_aggregate(session, window: TelemetryWindow, *, previous: bool = False) -> UsageAggregate:
    base = _usage_query(session, window, previous=previous).subquery()
    row = session.query(
        func.count(base.c.id),
        func.sum(case((base.c.status == "success", 1), else_=0)),
        func.sum(case((base.c.status != "success", 1), else_=0)),
        func.sum(base.c.cost),
        func.sum(base.c.input_tokens),
        func.sum(base.c.output_tokens),
        func.avg(base.c.latency_ms),
    ).one()
    return UsageAggregate(
        calls=int(row[0] or 0),
        success=int(row[1] or 0),
        issues=int(row[2] or 0),
        spend=float(row[3] or 0.0),
        input_tokens=int(row[4] or 0),
        output_tokens=int(row[5] or 0),
        avg_latency_ms=int(row[6] or 0),
    )


def _batch_totals(session, window: TelemetryWindow, *, previous: bool = False) -> dict[str, int]:
    query = session.query(AppEvent).filter(
        AppEvent.event_name == "extraction_batch_summary"
    )
    query = _apply_previous_window(query, AppEvent, window) if previous else _apply_window(query, AppEvent, window)
    totals = {
        "cache_hits": 0,
        "retries": 0,
        "successes": 0,
        "failures": 0,
        "total_files": 0,
    }
    for event in query.all():
        metadata = _metadata_dict(event.metadata_json)
        for key in totals:
            try:
                totals[key] += int(metadata.get(key) or 0)
            except (TypeError, ValueError):
                pass
    return totals


def _duration_avg_ms(
    session,
    event_name: str,
    *,
    window: TelemetryWindow,
    status: str | None = None,
    previous: bool = False,
) -> int:
    query = session.query(func.avg(AppEvent.duration_ms)).filter(
        AppEvent.event_name == event_name
    )
    query = _apply_previous_window(query, AppEvent, window) if previous else _apply_window(query, AppEvent, window)
    if status is not None:
        query = query.filter(AppEvent.status == status)
    return int(query.scalar() or 0)


def _safe_metric_count(started: int, completed_total: int, failed: int) -> int:
    return max(started, completed_total + failed)


def _extraction_stats(session, window: TelemetryWindow, *, previous: bool = False) -> dict[str, Any]:
    started = _event_count(session, "extraction_started", window=window, previous=previous)
    completed_success = _event_count(
        session, "extraction_completed", window=window, status="success", previous=previous
    )
    completed_cache = _event_count(
        session, "extraction_completed", window=window, status="cache_hit", previous=previous
    )
    completed_non_extractable = _event_count(
        session, "extraction_completed", window=window, status="non_extractable", previous=previous
    )
    failed = _event_count(session, "extraction_failed", window=window, previous=previous)
    completed_total = completed_success + completed_cache + completed_non_extractable
    total = _safe_metric_count(started, completed_total, failed)
    batch = _batch_totals(session, window, previous=previous)
    cache_hits = completed_cache if completed_cache else batch["cache_hits"]
    return {
        "started": started,
        "completed_success": completed_success,
        "completed_cache": completed_cache,
        "completed_non_extractable": completed_non_extractable,
        "completed_total": completed_total,
        "failed": failed,
        "total": total,
        "failure_rate": (failed / total * 100.0) if total else 0.0,
        "cache_hits": cache_hits,
        "batch": batch,
        "avg_duration_ms": _duration_avg_ms(
            session,
            "extraction_completed",
            window=window,
            status="success",
            previous=previous,
        ),
    }


def _coi_stats(session, window: TelemetryWindow, *, previous: bool = False) -> dict[str, int]:
    single = _event_sum_count_value(
        session, ["coi_generated_single"], window=window, status="success", previous=previous
    )
    bulk = _event_sum_count_value(
        session, ["coi_generated_bulk"], window=window, status="success", previous=previous
    )
    failures = _event_count(
        session, "coi_generated_single", window=window, status="failure", previous=previous
    ) + _event_count(
        session, "coi_generated_bulk", window=window, status="failure", previous=previous
    )
    return {"single": single, "bulk": bulk, "failures": failures, "total": single + bulk}


def _retry_count(session, window: TelemetryWindow, *, previous: bool = False) -> int:
    durable = _event_count(session, "llm_retry", window=window, previous=previous)
    if durable:
        return durable
    return _batch_totals(session, window, previous=previous)["retries"]


def _delta(current: float, previous: float, *, inverse: bool = False, suffix: str = "") -> tuple[str, str]:
    if previous in (0, 0.0):
        if current in (0, 0.0):
            return "0" + suffix, "neutral"
        return "new" if not suffix else f"new {suffix}", "watch"
    change = ((current - previous) / previous) * 100.0
    direction_good = change < 0 if inverse else change >= 0
    tone = "healthy" if direction_good else "critical"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%", tone


def _health_status(failure_rate: float, llm_issues: int, retries: int) -> tuple[str, str, str]:
    if failure_rate >= 15 or llm_issues > 0:
        return "Critical", "critical", "Immediate attention needed"
    if failure_rate >= 5 or retries > 2:
        return "Watch", "watch", "Monitor extraction quality and retry behavior"
    return "Healthy", "healthy", "Telemetry within normal operating bounds"


def _event_dataframe(session, window: TelemetryWindow) -> pd.DataFrame:
    rows = _apply_window(session.query(AppEvent), AppEvent, window).order_by(AppEvent.timestamp.desc()).limit(100).all()
    return pd.DataFrame(
        [
            {
                "timestamp": row.timestamp,
                "event": row.event_name,
                "category": row.category,
                "status": row.status,
                "correlation_id": row.correlation_id,
                "count": row.count_value,
                "duration_ms": row.duration_ms,
                "metadata": row.metadata_json,
            }
            for row in rows
        ]
    )


def _usage_dataframe(session, window: TelemetryWindow) -> pd.DataFrame:
    rows = _usage_query(session, window).order_by(ApiUsage.timestamp.desc()).limit(100).all()
    return pd.DataFrame(
        [
            {
                "timestamp": row.timestamp,
                "model": row.model_name,
                "type": row.request_type,
                "status": row.status,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost": f"${float(row.cost or 0):.5f}",
                "latency_ms": f"{int(row.latency_ms or 0):,}",
                "correlation_id": row.correlation_id,
            }
            for row in rows
        ]
    )


def _incident_dataframe(session, window: TelemetryWindow) -> pd.DataFrame:
    event_rows = (
        _apply_window(session.query(AppEvent), AppEvent, window)
        .filter(
            (AppEvent.event_name == "extraction_failed")
            | (AppEvent.event_name.in_(["coi_generated_single", "coi_generated_bulk"]) & (AppEvent.status == "failure"))
        )
        .order_by(AppEvent.timestamp.desc())
        .limit(40)
        .all()
    )
    usage_rows = (
        _usage_query(session, window)
        .filter(ApiUsage.status != "success")
        .order_by(ApiUsage.timestamp.desc())
        .limit(40)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for event in event_rows:
        meta = _metadata_dict(event.metadata_json)
        rows.append(
            {
                "timestamp": event.timestamp,
                "source": "app_event",
                "event": event.event_name,
                "status": event.status,
                "detail": event.message or meta.get("error") or meta.get("document_type") or "",
                "correlation_id": event.correlation_id,
            }
        )
    for usage in usage_rows:
        rows.append(
            {
                "timestamp": usage.timestamp,
                "source": "llm_usage",
                "event": usage.request_type,
                "status": usage.status,
                "detail": usage.error_message or "",
                "correlation_id": usage.correlation_id,
            }
        )
    rows.sort(key=lambda r: r.get("timestamp") or datetime.min, reverse=True)
    return pd.DataFrame(rows[:50])


def page_telemetry():
    st.title("📡 Telemetry")
    st.markdown("Operational view for document extraction, COI production, cache efficiency, and Gemini usage.")

    range_col, refresh_col = st.columns([2, 3])
    with range_col:
        range_label = st.selectbox(
            "Time range",
            options=list(RANGE_OPTIONS.keys()),
            index=2,
            help="Filters durable telemetry in app_events and api_usage.",
        )
    with refresh_col:
        st.caption(f"Last refresh: {datetime.now().strftime('%I:%M %p')}")
    window = _build_window(range_label)

    session = get_session(st.session_state.db_engine)
    try:
        telemetry = TelemetryService(session)
        extraction = _extraction_stats(session, window)
        extraction_prev = _extraction_stats(session, window, previous=True)
        coi = _coi_stats(session, window)
        coi_prev = _coi_stats(session, window, previous=True)
        usage = _usage_aggregate(session, window)
        usage_prev = _usage_aggregate(session, window, previous=True)
        retries = _retry_count(session, window)
        retries_prev = _retry_count(session, window, previous=True)
        health_label, health_tone, health_note = _health_status(
            extraction["failure_rate"], usage.issues, retries
        )

        if health_tone == "critical":
            st.error(f"Status: {health_label} — {health_note}")
        elif health_tone == "watch":
            st.warning(f"Status: {health_label} — {health_note}")
        else:
            st.success(f"Status: {health_label} — {health_note}")

        d_extractions, _ = _delta(extraction["total"], extraction_prev["total"])
        d_failure, _ = _delta(
            extraction["failure_rate"], extraction_prev["failure_rate"], inverse=True
        )
        d_coi, _ = _delta(coi["total"], coi_prev["total"])
        d_spend, _ = _delta(usage.spend, usage_prev.spend)
        d_cache, _ = _delta(extraction["cache_hits"], extraction_prev["cache_hits"])
        d_retries, _ = _delta(retries, retries_prev, inverse=True)
        d_latency, _ = _delta(
            usage.avg_latency_ms, usage_prev.avg_latency_ms, inverse=True
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Extractions", f"{extraction['total']:,}", delta=d_extractions, help="Started or completed jobs")
        with c2:
            st.metric(
                "Failure Rate",
                f"{extraction['failure_rate']:.1f}%",
                delta=d_failure,
                delta_color="inverse",
                help=f"{extraction['failed']} failures",
            )
        with c3:
            st.metric("COIs Generated", f"{coi['total']:,}", delta=d_coi, help=f"{coi['single']} single · {coi['bulk']} bulk")
        with c4:
            st.metric("LLM Spend", f"${usage.spend:.4f}", delta=d_spend, help=f"{usage.calls} calls")

        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.metric("Cache Hits", f"{extraction['cache_hits']:,}", delta=d_cache, help="Avoided API extraction calls")
        with c6:
            st.metric("LLM Calls", f"{usage.calls:,}", delta=f"{usage.success} ok / {usage.issues} issue", help="api_usage ledger")
        with c7:
            st.metric("Retries", f"{retries:,}", delta=d_retries, delta_color="inverse", help="Retry pressure")
        with c8:
            st.metric(
                "Avg LLM Latency",
                f"{usage.avg_latency_ms:,} ms",
                delta=d_latency,
                delta_color="inverse",
                help="Mean generate_content latency",
            )

        st.divider()
        left, right = st.columns(2)
        with left:
            st.subheader("Extraction Outcomes")
            extraction_df = pd.DataFrame(
                [
                    {"Outcome": "API success", "Count": extraction["completed_success"]},
                    {"Outcome": "Cache hit", "Count": extraction["completed_cache"]},
                    {"Outcome": "Non-extractable", "Count": extraction["completed_non_extractable"]},
                    {"Outcome": "Failed", "Count": extraction["failed"]},
                ]
            ).set_index("Outcome")
            st.bar_chart(extraction_df, color="#005AA9")
            st.caption(f"Average successful extraction duration: {extraction['avg_duration_ms']:,} ms")

        with right:
            st.subheader("COI Production")
            coi_df = pd.DataFrame(
                [
                    {"Type": "Single", "Count": coi["single"]},
                    {"Type": "Bulk", "Count": coi["bulk"]},
                    {"Type": "Failures", "Count": coi["failures"]},
                ]
            ).set_index("Type")
            st.bar_chart(coi_df, color="#005AA9")
            st.caption("Bulk COI count is summed from generated files.")

        st.divider()
        st.subheader("LLM Usage")
        u1, u2, u3 = st.columns(3)
        u1.metric("Input Tokens", f"{usage.input_tokens:,}")
        u2.metric("Output Tokens", f"{usage.output_tokens:,}")
        u3.metric("Cost", f"${usage.spend:.5f}")

        by_type_rows = (
            _usage_query(session, window)
            .with_entities(
                ApiUsage.request_type,
                ApiUsage.status,
                func.count(ApiUsage.id),
                func.sum(ApiUsage.cost),
                func.avg(ApiUsage.latency_ms),
            )
            .group_by(ApiUsage.request_type, ApiUsage.status)
            .all()
        )
        by_type_df = pd.DataFrame(
            [
                {
                    "request_type": request_type,
                    "status": status,
                    "calls": int(count or 0),
                    "cost": f"${float(cost or 0.0):.5f}",
                    "avg_latency_ms": int(avg_latency or 0),
                }
                for request_type, status, count, cost, avg_latency in by_type_rows
            ]
        )
        if not by_type_df.empty:
            st.dataframe(by_type_df, hide_index=True, use_container_width=True)
        else:
            st.info("No LLM usage rows for this range.")

        st.divider()
        st.subheader("Recent Incidents")
        incidents_df = _incident_dataframe(session, window)
        if incidents_df.empty:
            st.success("No incidents in selected range.")
        else:
            st.dataframe(incidents_df, hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("Event Summary")
        summary = telemetry.get_event_summary(days=window.days or 36500)
        summary_df = pd.DataFrame(summary)
        if not summary_df.empty:
            st.dataframe(summary_df, hide_index=True, use_container_width=True)
        else:
            st.info("No telemetry events for this range.")

        with st.expander("Raw recent app events", expanded=False):
            events_df = _event_dataframe(session, window)
            if events_df.empty:
                st.caption("No recent app events.")
            else:
                st.dataframe(events_df, hide_index=True, use_container_width=True)

        with st.expander("Raw recent LLM usage rows", expanded=False):
            usage_df = _usage_dataframe(session, window)
            if usage_df.empty:
                st.caption("No recent usage rows.")
            else:
                st.dataframe(usage_df, hide_index=True, use_container_width=True)

    finally:
        session.close()
