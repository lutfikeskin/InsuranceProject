from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
import csv
import io
import json
import os
import re
import zipfile

from flask import Flask, Response, redirect, render_template, request, url_for
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.comparison_service import ComparisonService
from core.constants import APP_DISPLAY_NAME, APP_DISPLAY_TAGLINE, DEFAULT_DAILY_BUDGET, CONFIDENCE_GATE_DEFAULT, CONFIDENCE_GATE_OPTIONS
from core.customer_history_service import (
    CustomerHistoryService,
    SOURCE_MANUAL,
)
from core.customer_resolver import CustomerResolver
from core.database import Customer, CustomerEntity, Policy, PolicyRelationship, get_session
from core.history_service import HistoryService
from core.notification_service import NotificationService
from core.review_model import ReviewTask, UploadedDocument
from core.review_service import ReviewWorkflowService
from core.services import COIService, PolicyService, UsageService
from modules.coi import load_companies
from modules.coi.generator import COIGenerator
from modules.extraction import process_pdf
from modules.extraction.pipeline import POLICY_TYPE_ENUM
from modules.notifications import draft_renewal_email
from utils.exporter import create_excel_report
from utils.naic_utils import get_naic_for_carrier
from views.ui_utils import build_confidence_map, gate_value
SessionFactory = Callable[[], Session]
STATUS_OPTIONS = ("pending", "saved", "skipped", "failed", "all")
UPLOAD_CACHE_DIR = Path(".cache/web_uploads")
COI_PREVIEW_DIR = Path(".cache/coi_previews")
def create_app(
    *,
    db_url: str = "sqlite:///insurance_data.db",
    session_factory: SessionFactory | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["DB_URL"] = db_url
    app.config.setdefault("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    app.config.setdefault("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT)

    if session_factory is None:
        engine = create_engine(db_url)

        def session_factory() -> Session:
            return get_session(engine)

        app.config["DB_ENGINE"] = engine

    @contextmanager
    def session_scope() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def load_queue_context(
        session: Session,
        status: str,
        selected_task_id: int | None = None,
        *,
        detail_error: str | None = None,
        gate_threshold: str = "medium",
    ) -> dict[str, Any]:
        normalized_status = status if status in STATUS_OPTIONS else "pending"
        normalized_gate = gate_threshold if gate_threshold in {"off", "medium", "high"} else "medium"
        service = ReviewWorkflowService(session)
        tasks = service.list_tasks(
            status=None if normalized_status == "all" else normalized_status,
            limit=200,
        )
        selected_task = _select_task(tasks, selected_task_id)
        review_form = _review_form_context(selected_task, normalized_gate)
        return {
            "counts": service.queue_counts(),
            "status_options": STATUS_OPTIONS,
            "selected_status": normalized_status,
            "gate_options": ("off", "medium", "high"),
            "gate_threshold": normalized_gate,
            "tasks": tasks,
            "selected_task": selected_task,
            "review_form": review_form,
            "detail_error": detail_error,
        }

    @app.get("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            action = (request.form.get("action") or "save").strip()
            if action == "clear_key":
                app.config["GEMINI_API_KEY"] = ""
            else:
                api_key = (request.form.get("gemini_api_key") or "").strip()
                if api_key:
                    app.config["GEMINI_API_KEY"] = api_key
                gate = (request.form.get("confidence_gate_threshold") or "").strip()
                if gate in CONFIDENCE_GATE_OPTIONS:
                    app.config["CONFIDENCE_GATE_THRESHOLD"] = gate
            return redirect(url_for("settings"))
        return render_template(
            "settings.html",
            api_key_configured=bool(app.config.get("GEMINI_API_KEY")),
            current_gate=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT),
            gate_options=CONFIDENCE_GATE_OPTIONS,
        )



    @app.post("/settings/reset-usage")
    def settings_reset_usage():
        with session_scope() as session:
            usage_service = UsageService(session)
            usage_service.clear_usage()
        return ("", 204)

    @app.get("/dashboard")
    def dashboard():
        query = (request.args.get("q") or "").strip()
        with session_scope() as session:
            policy_service = PolicyService(session)
            usage_service = UsageService(session)
            total_policies, total_vehicles, total_premium = policy_service.get_dashboard_metrics()
            daily_spend = usage_service.get_daily_usage()
            budget_limit = DEFAULT_DAILY_BUDGET
            expiring_30 = policy_service.get_expiring_policies(days=30)
            expiring_60 = policy_service.get_expiring_policies(days=60)
            expiring_31_60 = [p for p in expiring_60 if p not in expiring_30]
            carrier_data = policy_service.get_carrier_distribution()
            timeline_data = policy_service.get_expiration_timeline(months=6)
            recent_policies = policy_service.get_recent_policies(5) if total_policies > 0 else []
            lookup_policies = policy_service.search_policies(query or None, limit=10) if (query or total_policies > 0) else []
            return render_template(
                "dashboard.html",
                app_display_name=APP_DISPLAY_NAME,
                app_display_tagline=APP_DISPLAY_TAGLINE,
                total_policies=total_policies,
                total_vehicles=total_vehicles,
                total_premium=total_premium,
                daily_spend=daily_spend,
                budget_limit=budget_limit,
                expiring_30=expiring_30,
                expiring_31_60=expiring_31_60,
                carrier_data=carrier_data,
                timeline_data=timeline_data,
                recent_policies=recent_policies,
                lookup_query=query,
                lookup_policies=lookup_policies,
            )

    @app.get("/renewals")
    def renewals():
        selected_id = _int_arg("policy_id")
        with session_scope() as session:
            policy_service = PolicyService(session)
            notification_service = NotificationService(session)
            buckets = policy_service.get_renewal_buckets()
            selected_policy = session.get(Policy, selected_id) if selected_id else None
            related_policy = (
                policy_service.find_related_policy(selected_policy.id)
                if selected_policy is not None
                else None
            )
            draft = draft_renewal_email(selected_policy, agency_name="Truckers National") if selected_policy else None
            last_contact = notification_service.last_contact(selected_id) if selected_id else None
            return render_template(
                "renewals.html",
                overdue=buckets["overdue"],
                urgent=buckets["urgent"],
                warning=buckets["warning"],
                watch=buckets["watch"],
                selected_policy=selected_policy,
                related_policy=related_policy,
                draft=draft,
                last_contact=last_contact,
                form_error=None,
            )

    @app.post("/renewals/log-contact")
    def renewals_log_contact():
        selected_id = int(request.form.get("policy_id"))
        method = (request.form.get("method") or "manual").strip()
        notes = (request.form.get("notes") or "").strip() or None
        with session_scope() as session:
            notification_service = NotificationService(session)
            policy = session.get(Policy, selected_id)
            notification_service.record_contact(
                policy_id=selected_id,
                customer_id=getattr(policy, "customer_id", None) if policy else None,
                method=method,
                notes=notes,
            )
            session.commit()
        return redirect(url_for("renewals", policy_id=selected_id))

    @app.post("/renewals/draft-download")
    def renewals_draft_download():
        policy_id = int(request.form.get("policy_id"))
        body = request.form.get("body") or ""
        filename = request.form.get("download_filename") or f"renewal-{policy_id}.txt"
        return Response(
            body,
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


    @app.post("/renewals/log-draft")
    def renewals_log_draft():
        selected_id = int(request.form.get("policy_id"))
        recipient = (request.form.get("to") or "").strip() or "(no recipient on file)"
        with session_scope() as session:
            notification_service = NotificationService(session)
            policy = session.get(Policy, selected_id)
            notification_service.record_contact(
                policy_id=selected_id,
                customer_id=getattr(policy, "customer_id", None) if policy else None,
                method="email_draft",
                notes=f"Drafted reminder. To: {recipient}",
            )
            session.commit()
        return redirect(url_for("renewals", policy_id=selected_id))

    @app.route("/process-policies", methods=["GET", "POST"])
    def process_policies():
        if request.method == "GET":
            return render_template(
                "process_policies.html",
                policy_type_options=_policy_type_options(),
                form_error=None,
                batch_result=None,
            )
        uploaded_files = [f for f in request.files.getlist("pdf_files") if f and f.filename]
        if not uploaded_files:
            return render_template(
                "process_policies.html",
                policy_type_options=_policy_type_options(),
                form_error="Choose at least one PDF file to extract.",
                batch_result=None,
            ), 400
        api_key = app.config.get("GEMINI_API_KEY") or request.environ.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return render_template(
                "process_policies.html",
                policy_type_options=_policy_type_options(),
                form_error="GEMINI_API_KEY is required for extraction.",
                batch_result=None,
            ), 400
        force_refresh = request.form.get("force_refresh") == "on"
        selected_policy_type = request.form.get("policy_type") or None
        if selected_policy_type == "auto":
            selected_policy_type = None
        batch_result = {"created_tasks": [], "failed_uploads": []}
        with session_scope() as session:
            review_service = ReviewWorkflowService(session)
            for uploaded in uploaded_files:
                file_bytes = uploaded.read()
                storage_uri = _store_uploaded_bytes(uploaded.filename, file_bytes)
                data, usage, error_message = process_pdf(
                    file_bytes,
                    api_key,
                    status_callback=None,
                    force_refresh=force_refresh,
                    user_policy_type=selected_policy_type,
                )
                upload = review_service.create_upload(
                    filename=uploaded.filename,
                    file_bytes=file_bytes,
                    content_type=uploaded.mimetype or "application/pdf",
                    storage_uri=storage_uri,
                )
                if data:
                    run = review_service.record_extraction_run(
                        upload_id=upload.id,
                        status="succeeded",
                        result=data,
                        usage=usage,
                        force_refresh=force_refresh,
                    )
                    task = review_service.create_review_task(
                        upload_id=upload.id,
                        extraction_run_id=run.id,
                        extraction_result=data,
                        notes="Created from HTMX process policies upload.",
                    )
                    batch_result["created_tasks"].append(
                        {
                            "task_id": task.id,
                            "upload_id": upload.id,
                            "filename": uploaded.filename,
                            "document_type": (data.get("classification") or {}).get("document_type"),
                            "policy_type": (data.get("classification") or {}).get("policy_type"),
                            "extractable": data.get("extractable", True),
                        }
                    )
                else:
                    run = review_service.record_extraction_run(
                        upload_id=upload.id,
                        status="failed",
                        usage=usage,
                        error_message=error_message or "Extraction failed",
                        force_refresh=force_refresh,
                    )
                    batch_result["failed_uploads"].append(
                        {
                            "upload_id": upload.id,
                            "run_id": run.id,
                            "filename": uploaded.filename,
                            "error": error_message or "Extraction failed",
                        }
                    )
        return render_template(
            "process_policies.html",
            policy_type_options=_policy_type_options(),
            form_error=None,
            batch_result=batch_result,
        )

    @app.post("/process-policies/save-batch")
    def process_policies_save_batch():
        task_ids = []
        for raw in request.form.getlist("task_ids"):
            try:
                task_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        summary = {"saved": 0, "updated": 0, "review": 0}
        with session_scope() as session:
            review_service = ReviewWorkflowService(session)
            policy_service = PolicyService(session)
            for task_id in task_ids:
                task = review_service.get_task(task_id)
                if task is None or task.status != "pending":
                    continue
                payload = task.extraction_result if isinstance(task.extraction_result, dict) else {}
                if payload.get("extractable") is False:
                    summary["review"] += 1
                    continue
                duplicate_info = policy_service.detect_duplicate_for_extraction(payload)
                if duplicate_info.get("status") == "exact_number_carrier_conflict":
                    summary["review"] += 1
                    continue
                success, _msg = policy_service.save_policy_from_extraction(payload)
                if success:
                    decision = "update_existing" if duplicate_info.get("status") == "exact_policy_match" else "save_new"
                    target_policy_id = (
                        (duplicate_info.get("existing_policy") or {}).get("id")
                        if decision == "update_existing"
                        else None
                    )
                    review_service.record_decision(
                        task_id=task.id,
                        decision=decision,
                        human_edits=payload,
                        target_policy_id=target_policy_id,
                        notes="Saved from HTMX batch save.",
                    )
                    if decision == "update_existing":
                        summary["updated"] += 1
                    else:
                        summary["saved"] += 1
            return render_template(
                "process_policies.html",
                policy_type_options=_policy_type_options(),
                form_error=None,
                batch_result=None,
                save_batch_result=summary,
            )

    @app.post("/process-policies/retry/<int:upload_id>")
    def process_policies_retry(upload_id: int):
        api_key = app.config.get("GEMINI_API_KEY") or request.environ.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return redirect(url_for("process_policies"))
        with session_scope() as session:
            review_service = ReviewWorkflowService(session)
            upload = session.get(UploadedDocument, upload_id)
            if upload is None:
                return redirect(url_for("process_policies"))
            file_bytes = _load_uploaded_bytes(upload.storage_uri)
            data, usage, error_message = process_pdf(
                file_bytes,
                api_key,
                status_callback=None,
                force_refresh=True,
                user_policy_type=None,
                allow_non_extractable=True,
            )
            if data:
                run = review_service.record_extraction_run(
                    upload_id=upload.id,
                    status="succeeded",
                    result=data,
                    usage=usage,
                    force_refresh=True,
                )
                task = review_service.create_review_task(
                    upload_id=upload.id,
                    extraction_run_id=run.id,
                    extraction_result=data,
                    notes="Created from HTMX retry-anyway flow.",
                )
                return redirect(url_for("review_queue", task_id=task.id))
            review_service.record_extraction_run(
                upload_id=upload.id,
                status="failed",
                usage=usage,
                error_message=error_message or "Retry extraction failed",
                force_refresh=True,
            )
            return redirect(url_for("process_policies"))

    @app.get("/compare")
    def compare():
        with session_scope() as session:
            policy_service = PolicyService(session)
            policies = (
                session.query(Policy)
                .order_by(Policy.insured_name.asc(), Policy.expiration_date.desc())
                .all()
            )
            options = {policy.id: f"{policy.policy_number} | {policy.insured_name}" for policy in policies}
            selected_a = _int_arg("policy_a")
            selected_b = _int_arg("policy_b")
            result = None
            policy_a = None
            policy_b = None
            suggested_policy_b = None
            customer_mismatch = False
            if selected_a:
                policy_a = session.get(Policy, selected_a)
                if selected_b is None and policy_a is not None:
                    related = policy_service.find_related_policy(policy_a.id)
                    if related is not None:
                        suggested_policy_b = related.id
                if selected_b:
                    policy_b = session.get(Policy, selected_b)
            if policy_a is not None and policy_b is not None:
                if (
                    policy_a.customer_id is not None
                    and policy_b.customer_id is not None
                    and policy_a.customer_id != policy_b.customer_id
                ):
                    customer_mismatch = True
                result = ComparisonService(session).compare(policy_a, policy_b)
            return render_template(
                "compare.html",
                options=options,
                selected_a=selected_a,
                selected_b=selected_b,
                policy_a=policy_a,
                policy_b=policy_b,
                result=result,
                suggested_policy_b=suggested_policy_b,
                customer_mismatch=customer_mismatch,
            )

    # --- helpers shared by /database routes ---

    CUSTOMER_TABS = ("profile", "entities", "policies", "history", "merge")
    POLICY_TABS = ("overview", "edit", "history", "renewals")

    def _build_customer_activity_feed(session, customer):
        """Reverse-chronological feed of everything that touched this customer.

        Merges real CustomerHistory rows with derived events (entity first_seen,
        policy created_at) so customers created before the audit table still
        get a meaningful timeline.
        """
        history_svc = CustomerHistoryService(session)
        rows = history_svc.list_for_customer(customer.id)
        feed = []
        for row in rows:
            feed.append({
                "kind": "audit",
                "id": row.id,
                "timestamp": row.timestamp,
                "source": row.source,
                "event_type": row.event_type,
                "version": row.customer_version,
                "changes": row.changes,
                "notes": row.notes,
            })
        # Derived: entity first_seen events for entities that have no audit row
        audited_entity_payloads = {
            (c.get("new_value", {}) or {}).get("entity_name")
            for row in rows if row.event_type == "ENTITY_ADDED"
            for c in (row.changes or [])
        }
        for entity in (customer.entities or []):
            if entity.entity_name in audited_entity_payloads:
                continue
            feed.append({
                "kind": "derived",
                "id": f"entity-{entity.id}",
                "timestamp": entity.first_seen or customer.created_at,
                "source": "Extraction" if (entity.source or "") == "extraction" else "Imported",
                "event_type": "ENTITY_ADDED",
                "version": None,
                "changes": [{
                    "field": "entity",
                    "old_value": None,
                    "new_value": {
                        "entity_name": entity.entity_name,
                        "entity_type": entity.entity_type,
                        "is_primary": bool(entity.is_primary),
                    },
                }],
                "notes": None,
            })
        # Derived: customer creation event if no CREATED audit row
        has_created = any(r.event_type == "CREATED" for r in rows)
        if not has_created and customer.created_at is not None:
            feed.append({
                "kind": "derived",
                "id": "created",
                "timestamp": customer.created_at,
                "source": "Imported",
                "event_type": "CREATED",
                "version": None,
                "changes": [{"field": "full_name", "old_value": None, "new_value": customer.full_name}],
                "notes": None,
            })
        # Derived: policy creations under this customer
        for policy in (customer.policies or []):
            if policy.created_at is None:
                continue
            feed.append({
                "kind": "derived",
                "id": f"policy-{policy.id}",
                "timestamp": policy.created_at,
                "source": "PolicyService",
                "event_type": "POLICY_LINKED",
                "version": None,
                "changes": [{
                    "field": "policy_link",
                    "old_value": None,
                    "new_value": {"policy_id": policy.id, "policy_number": policy.policy_number},
                }],
                "notes": None,
            })
        feed.sort(key=lambda e: e["timestamp"] or datetime(1970, 1, 1), reverse=True)
        return feed

    def _customer_detail_context(session, customer, *, tab, status_message=None, form_error=None, merge_candidates=None, merge_query=""):
        return {
            "customer": customer,
            "active_tab": tab,
            "customer_tabs": CUSTOMER_TABS,
            "activity_feed": _build_customer_activity_feed(session, customer),
            "policy_count": len(customer.policies or []),
            "entity_count": len(customer.entities or []),
            "status_message": status_message,
            "form_error": form_error,
            "merge_candidates": merge_candidates or [],
            "merge_query": merge_query,
        }

    def _policy_detail_context(session, policy, *, tab, status_message=None, form_error=None):
        history_rows = HistoryService(session).list_for_policy(policy.id)
        related = (
            session.query(PolicyRelationship)
            .filter(
                (PolicyRelationship.policy_id == policy.id)
                | (PolicyRelationship.related_policy_id == policy.id)
            )
            .order_by(PolicyRelationship.created_at.desc())
            .all()
        )
        related_pairs = []
        for rel in related:
            other_id = rel.related_policy_id if rel.policy_id == policy.id else rel.policy_id
            other = session.get(Policy, other_id) if other_id else None
            if other is not None:
                related_pairs.append({"relationship": rel, "other": other})
        return {
            "policy": policy,
            "active_tab": tab,
            "policy_tabs": POLICY_TABS,
            "history_rows": history_rows,
            "related_pairs": related_pairs,
            "status_message": status_message,
            "form_error": form_error,
        }

    # --- master list ---

    def _database_policy_status(policy: Policy, today=None) -> str:
        today = today or datetime.utcnow().date()
        raw_status = (policy.policy_status or policy.status or "").strip().lower()
        if raw_status in {"lapsed", "cancelled", "canceled", "inactive"}:
            return "lapsed"
        if policy.expiration_date and policy.expiration_date < today:
            return "lapsed"
        if policy.expiration_date and 0 <= (policy.expiration_date - today).days <= 30:
            return "expiring"
        return "active"

    def _filter_database_policies(
        policies: list[Policy],
        *,
        status_filter: str,
        carrier_filter: str,
        type_filter: str,
    ) -> list[Policy]:
        today = datetime.utcnow().date()
        filtered = []
        for policy in policies:
            if status_filter != "all" and _database_policy_status(policy, today) != status_filter:
                continue
            if carrier_filter and (policy.carrier_name or "") != carrier_filter:
                continue
            if type_filter and (policy.policy_type or "") != type_filter:
                continue
            filtered.append(policy)
        return filtered

    @app.get("/database")
    def database():
        # `tab` controls which directory is emphasized; both lists still render
        # so the master database remains scannable from one page.
        tab = (request.args.get("tab") or "policies").strip().lower()
        if tab not in ("customers", "policies"):
            tab = "policies"
        query = (request.args.get("q") or "").strip()
        status_filter = (request.args.get("status") or "all").strip().lower()
        if status_filter not in {"all", "active", "expiring", "lapsed"}:
            status_filter = "all"
        carrier_filter = (request.args.get("carrier") or "").strip()
        type_filter = (request.args.get("policy_type") or "").strip()
        with session_scope() as session:
            policy_service = PolicyService(session)
            customers = policy_service.search_customers(query or None, orphan_filter="all", limit=50)
            base_policies = policy_service.search_policies(query or None, limit=200)
            policies = _filter_database_policies(
                base_policies,
                status_filter=status_filter,
                carrier_filter=carrier_filter,
                type_filter=type_filter,
            )
            option_source = policy_service.search_policies(None, limit=500)
            carrier_options = sorted({policy.carrier_name for policy in option_source if policy.carrier_name})
            type_options = sorted({policy.policy_type for policy in option_source if policy.policy_type})
            return render_template(
                "database.html",
                active_tab=tab,
                query=query,
                customers=customers,
                policies=policies,
                total_policy_matches=len(base_policies),
                total_customer_matches=len(customers),
                status_filter=status_filter,
                carrier_filter=carrier_filter,
                type_filter=type_filter,
                carrier_options=carrier_options,
                type_options=type_options,
                today=datetime.utcnow().date(),
            )

    @app.get("/database/customers/list")
    def database_customers_list():
        query = (request.args.get("q") or "").strip()
        with session_scope() as session:
            customers = PolicyService(session).search_customers(query or None, orphan_filter="all", limit=50)
            return render_template(
                "partials/database/customers_table.html",
                customers=customers,
                query=query,
                today=datetime.utcnow().date(),
            )

    @app.get("/database/policies/list")
    def database_policies_list():
        query = (request.args.get("q") or "").strip()
        status_filter = (request.args.get("status") or "all").strip().lower()
        if status_filter not in {"all", "active", "expiring", "lapsed"}:
            status_filter = "all"
        carrier_filter = (request.args.get("carrier") or "").strip()
        type_filter = (request.args.get("policy_type") or "").strip()
        with session_scope() as session:
            base_policies = PolicyService(session).search_policies(query or None, limit=200)
            policies = _filter_database_policies(
                base_policies,
                status_filter=status_filter,
                carrier_filter=carrier_filter,
                type_filter=type_filter,
            )
            return render_template(
                "partials/database/policies_table.html",
                policies=policies,
                query=query,
                today=datetime.utcnow().date(),
            )

    @app.get("/database/export")
    def database_export():
        query = (request.args.get("q") or "").strip()
        with session_scope() as session:
            policy_service = PolicyService(session)
            policies = policy_service.search_policies(query or None, limit=200)
            payload = [_policy_export_payload(policy) for policy in policies]
            workbook = create_excel_report(payload)
            filename = "policy-export.xlsx" if not query else f"policy-export-{query}.xlsx"
            return Response(
                workbook,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

    @app.get("/database/customers/export.csv")
    def database_customers_export_csv():
        query = (request.args.get("q") or "").strip()
        raw_ids = request.args.get("customer_ids") or ""
        customer_ids: list[int] = []
        for part in raw_ids.split(","):
            try:
                if part.strip():
                    customer_ids.append(int(part.strip()))
            except ValueError:
                continue
        with session_scope() as session:
            if customer_ids:
                customers = (
                    session.query(Customer)
                    .filter(Customer.id.in_(customer_ids))
                    .order_by(Customer.full_name.asc())
                    .all()
                )
            else:
                customers = PolicyService(session).search_customers(query or None, orphan_filter="all", limit=200)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "customer_name",
                "primary_email",
                "primary_phone",
                "aliases",
                "policy_count",
                "active_policies",
                "expiring_policies",
                "last_activity",
                "created_at",
            ])
            today = datetime.utcnow().date()
            for customer in customers:
                policies = list(customer.policies or [])
                writer.writerow([
                    customer.full_name or "",
                    customer.primary_email or "",
                    customer.primary_phone or "",
                    "; ".join(entity.entity_name for entity in (customer.entities or [])),
                    len(policies),
                    sum(1 for policy in policies if _database_policy_status(policy, today) == "active"),
                    sum(1 for policy in policies if _database_policy_status(policy, today) == "expiring"),
                    (customer.updated_at or customer.created_at).isoformat() if (customer.updated_at or customer.created_at) else "",
                    customer.created_at.isoformat() if customer.created_at else "",
                ])
            suffix = "selected" if customer_ids else (query or "all")
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=customer-export-{suffix}.csv"},
            )

    @app.get("/database/export.csv")
    def database_export_csv():
        query = (request.args.get("q") or "").strip()
        raw_ids = request.args.get("policy_ids") or ""
        policy_ids: list[int] = []
        for part in raw_ids.split(","):
            try:
                if part.strip():
                    policy_ids.append(int(part.strip()))
            except ValueError:
                continue
        with session_scope() as session:
            if policy_ids:
                policies = (
                    session.query(Policy)
                    .filter(Policy.id.in_(policy_ids))
                    .order_by(Policy.policy_number.asc())
                    .all()
                )
            else:
                policies = PolicyService(session).search_policies(query or None, limit=200)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "policy_number",
                "insured_name",
                "carrier_name",
                "policy_type",
                "effective_date",
                "expiration_date",
                "premium",
                "vehicles",
                "status",
            ])
            for policy in policies:
                writer.writerow([
                    policy.policy_number or "",
                    policy.insured_name or "",
                    policy.carrier_name or "",
                    policy.policy_type or "",
                    policy.effective_date.isoformat() if policy.effective_date else "",
                    policy.expiration_date.isoformat() if policy.expiration_date else "",
                    policy.premium or "",
                    len(policy.vehicles or []),
                    _database_policy_status(policy),
                ])
            suffix = "selected" if policy_ids else (query or "all")
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=policy-export-{suffix}.csv"},
            )

    # --- customer detail + sub-tabs ---

    @app.get("/database/customer/<int:customer_id>")
    def database_customer_detail(customer_id: int):
        tab = (request.args.get("tab") or "profile").strip().lower()
        if tab not in CUSTOMER_TABS:
            tab = "profile"
        with session_scope() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                return ("Customer not found", 404)
            ctx = _customer_detail_context(session, customer, tab=tab)
            return render_template("database/customer_detail.html", **ctx)

    @app.get("/database/customer/<int:customer_id>/tab/<string:tab>")
    def database_customer_tab(customer_id: int, tab: str):
        if tab not in CUSTOMER_TABS:
            return ("unknown tab", 404)
        with session_scope() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                return ("Customer not found", 404)
            if tab == "merge":
                merge_query = (request.args.get("q") or "").strip()
                candidates = []
                if merge_query:
                    candidates = [
                        c for c in PolicyService(session).search_customers(merge_query, orphan_filter="all", limit=20)
                        if c.id != customer.id
                    ]
                ctx = _customer_detail_context(session, customer, tab=tab, merge_candidates=candidates, merge_query=merge_query)
            else:
                ctx = _customer_detail_context(session, customer, tab=tab)
            return render_template(f"partials/database/customer_{tab}_tab.html", **ctx)

    @app.post("/database/customer/<int:customer_id>/save")
    def database_customer_save(customer_id: int):
        with session_scope() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                return ("Customer not found", 404)
            new_values: dict[str, Any] = {}
            full_name = (request.form.get("full_name") or "").strip()
            if full_name:
                new_values["full_name"] = full_name
                new_values["needs_real_name_entry"] = False
            primary_email = (request.form.get("primary_email") or "").strip() or None
            primary_phone = (request.form.get("primary_phone") or "").strip() or None
            new_values["primary_email"] = primary_email
            new_values["primary_phone"] = primary_phone
            history = CustomerHistoryService(session)
            changes = history.record_field_changes(customer, new_values, source=SOURCE_MANUAL)
            # Combined-form back-compat: if an alias was submitted in the same payload, add it.
            entity_name = (request.form.get("entity_name") or "").strip()
            entity_type = (request.form.get("entity_type") or "").strip() or "business"
            if entity_name:
                CustomerResolver(session).add_entity(customer, entity_name, entity_type, source=SOURCE_MANUAL)
            session.commit()
            session.refresh(customer)
            status = "Customer updated." if (changes or entity_name) else "No changes."
            ctx = _customer_detail_context(session, customer, tab="profile", status_message=status)
            return render_template("partials/database/customer_profile_tab.html", **ctx)

    @app.post("/database/customer/<int:customer_id>/entity/add")
    def database_customer_entity_add(customer_id: int):
        with session_scope() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                return ("Customer not found", 404)
            name = (request.form.get("entity_name") or "").strip()
            etype = (request.form.get("entity_type") or "business").strip()
            error = None
            if not name:
                error = "Entity name is required."
            else:
                CustomerResolver(session).add_entity(customer, name, etype, source=SOURCE_MANUAL)
                session.commit()
                session.refresh(customer)
            ctx = _customer_detail_context(session, customer, tab="entities", form_error=error, status_message=None if error else f"Added '{name}'.")
            return render_template("partials/database/customer_entities_tab.html", **ctx)

    @app.post("/database/customer/<int:customer_id>/entity/<int:entity_id>/remove")
    def database_customer_entity_remove(customer_id: int, entity_id: int):
        with session_scope() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                return ("Customer not found", 404)
            entity = session.get(CustomerEntity, entity_id)
            error = None
            if entity is None or entity.customer_id != customer.id:
                error = "Entity not found on this customer."
            elif entity.is_primary:
                error = "Cannot remove the primary entity."
            else:
                CustomerHistoryService(session).record_entity_removed(customer, entity, source=SOURCE_MANUAL)
                session.delete(entity)
                session.commit()
                session.refresh(customer)
            ctx = _customer_detail_context(session, customer, tab="entities", form_error=error, status_message=None if error else "Entity removed.")
            return render_template("partials/database/customer_entities_tab.html", **ctx)

    @app.post("/database/customer/<int:customer_id>/merge")
    def database_customer_merge(customer_id: int):
        try:
            target_id = int(request.form.get("target_customer_id") or 0)
        except (TypeError, ValueError):
            target_id = 0
        if target_id <= 0 or target_id == customer_id:
            return redirect(url_for("database_customer_detail", customer_id=customer_id, tab="merge"))
        with session_scope() as session:
            resolver = CustomerResolver(session)
            result = resolver.merge_customers(keep_id=target_id, merge_id=customer_id)
            if not result.get("success"):
                return redirect(url_for("database_customer_detail", customer_id=customer_id, tab="merge"))
            return redirect(url_for("database_customer_detail", customer_id=result["kept_customer_id"], tab="history"))

    # --- policy detail + sub-tabs ---

    @app.get("/database/policy/<int:policy_id>")
    def database_policy_detail(policy_id: int):
        tab = (request.args.get("tab") or "overview").strip().lower()
        if tab not in POLICY_TABS:
            tab = "overview"
        with session_scope() as session:
            policy = session.get(Policy, policy_id)
            if policy is None:
                return ("Policy not found", 404)
            ctx = _policy_detail_context(session, policy, tab=tab)
            return render_template("database/policy_detail.html", **ctx)

    @app.get("/database/policy/<int:policy_id>/tab/<string:tab>")
    def database_policy_tab(policy_id: int, tab: str):
        if tab not in POLICY_TABS:
            return ("unknown tab", 404)
        with session_scope() as session:
            policy = session.get(Policy, policy_id)
            if policy is None:
                return ("Policy not found", 404)
            ctx = _policy_detail_context(session, policy, tab=tab)
            return render_template(f"partials/database/policy_{tab}_tab.html", **ctx)

    @app.post("/database/policy/<int:policy_id>/delete")
    def database_policy_delete(policy_id: int):
        with session_scope() as session:
            policy_service = PolicyService(session)
            policy = session.get(Policy, policy_id)
            if policy is not None:
                policy_service.delete_policy(policy)
            customers = policy_service.search_customers(None, orphan_filter="all", limit=50)
            policies = policy_service.search_policies(None, limit=50)
            return render_template(
                "database.html",
                active_tab="policies",
                query="",
                customers=customers,
                policies=policies,
            )

    @app.post("/database/policy/<int:policy_id>/save")
    def database_policy_save(policy_id: int):
        with session_scope() as session:
            policy_service = PolicyService(session)
            policy = session.get(Policy, policy_id)
            if policy is None:
                return ("Policy not found", 404)
            try:
                payload = apply_policy_form_edits(
                    {
                        "policy": {
                            "policy_number": policy.policy_number,
                            "carrier_name": policy.carrier_name,
                            "insured_name": policy.insured_name,
                            "effective_date": str(policy.effective_date) if policy.effective_date else None,
                            "expiration_date": str(policy.expiration_date) if policy.expiration_date else None,
                            "premium": policy.premium,
                        },
                        "vehicles": [
                            {
                                "year": v.year, "make": v.make, "model": v.model, "vin": v.vin,
                                "gvw": v.gvw, "type": v.vehicle_type, "chassis": v.chassis, "body": v.body,
                            }
                            for v in policy.vehicles
                        ],
                        "drivers": [
                            {"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded}
                            for d in policy.drivers
                        ],
                        "coverages": [
                            {
                                "type": c.type, "display_name": c.type, "coverage_code": c.coverage_code,
                                "family": c.family, "vehicle_vin": c.vehicle.vin if c.vehicle else None,
                                "deductible": c.deductible,
                                "limits": {
                                    "per_person": c.per_person, "per_accident": c.per_accident,
                                    "per_occurrence": c.per_occurrence, "combined_single_limit": c.combined_single_limit,
                                    "aggregate": c.aggregate,
                                },
                            }
                            for c in policy.coverages
                        ],
                        "additional_interests": [
                            {"name": a.name, "address": a.address, "interest_type": a.interest_type}
                            for a in policy.additional_interests
                        ],
                    },
                    request.form,
                )
            except ValueError as exc:
                ctx = _policy_detail_context(session, policy, tab="edit", form_error=str(exc))
                return render_template("partials/database/policy_edit_tab.html", **ctx), 400
            success, msg = policy_service.update_policy(policy, payload)
            session.refresh(policy)
            ctx = _policy_detail_context(
                session,
                policy,
                tab="edit",
                form_error=None if success else msg,
                status_message=msg if success else None,
            )
            return render_template("partials/database/policy_edit_tab.html", **ctx)

    def _safe_coi_filename(insured_name: str, holder_name: str, *, bulk: bool = False) -> str:
        safe_insured = (insured_name or "").strip() or "Unknown Insured"
        if bulk:
            filename = f"COIs - {safe_insured} - Bulk.zip"
        else:
            safe_holder = (holder_name or "").strip() or "Unknown Holder"
            filename = f"COI - {safe_insured} - {safe_holder}.pdf"
        filename = re.sub(r'[\\/:*?"<>|]+', " ", filename)
        return re.sub(r"\s+", " ", filename).strip()

    def _default_gl_aggregate(policy: Policy) -> str:
        blob = " ".join(str(part or "") for part in (policy.general_liability_limit, policy.liability_limit)).lower()
        compact = re.sub(r"[\s,$]", "", blob)
        if "2000000" in compact or re.search(r"\b2m\b", blob):
            return "$2,000,000"
        return "$1,000,000"

    def _coi_bool_arg(name: str, default: bool) -> bool:
        if request.method == "POST" or name in request.values:
            return request.values.get(name) == "on"
        return bool(default)

    def _int_form_arg(name: str, default: int, *, min_value: int, max_value: int) -> int:
        try:
            value = int(request.values.get(name) or default)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, value))

    def _build_coi_policy_data(policy: Policy, form_values: dict[str, Any], coi_type: str) -> dict[str, Any]:
        has_gl = _coi_bool_arg("has_general_liability", bool(policy.has_general_liability))
        has_auto = _coi_bool_arg("has_auto_liability", bool(policy.has_auto_liability))
        has_cargo = _coi_bool_arg("has_cargo", bool(policy.cargo_limit)) and coi_type != "Lienholder"
        gl_aggregate = (request.values.get("gl_general_aggregate") or _default_gl_aggregate(policy)).strip()
        return {
            "carrier_name": policy.carrier_name,
            "naic_number": form_values["insured_naic"],
            "policy_number": policy.policy_number,
            "effective_date": policy.effective_date,
            "expiration_date": policy.expiration_date,
            "liability_limit": policy.liability_limit,
            "gl_general_aggregate": gl_aggregate if has_gl else None,
            "cargo_limit": policy.cargo_limit,
            "cargo_deductible": policy.cargo_deductible if policy.cargo_deductible else "1000",
            "comp_deductible": policy.comp_deductible,
            "coll_deductible": policy.coll_deductible,
            "has_general_liability": has_gl,
            "has_auto_liability": has_auto,
            "has_cargo": has_cargo,
            "coi_type": coi_type,
            "insured_name": form_values["insured_name"],
            "insured_address": form_values["insured_address"],
            "insured_city": form_values["insured_city"],
            "insured_state_code": form_values["insured_state"],
            "insured_zip": form_values["insured_zip"],
            "vehicle_list_str": "",
            "driver_list_str": "",
        }

    def _store_coi_preview(pdf: bytes, filename: str) -> str:
        COI_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        token = sha256(pdf + filename.encode("utf-8") + datetime.utcnow().isoformat().encode("ascii")).hexdigest()[:32]
        (COI_PREVIEW_DIR / f"{token}.pdf").write_bytes(pdf)
        (COI_PREVIEW_DIR / f"{token}.json").write_text(json.dumps({"filename": filename}), encoding="utf-8")
        return token

    def _coi_preview_response(token: str, *, attachment: bool) -> Response:
        token = re.sub(r"[^a-f0-9]", "", token.lower())[:32]
        pdf_path = COI_PREVIEW_DIR / f"{token}.pdf"
        meta_path = COI_PREVIEW_DIR / f"{token}.json"
        if not token or not pdf_path.exists():
            return Response("COI preview not found", status=404)
        filename = "coi-preview.pdf"
        if meta_path.exists():
            try:
                filename = json.loads(meta_path.read_text(encoding="utf-8")).get("filename") or filename
            except (OSError, json.JSONDecodeError):
                pass
        disposition = "attachment" if attachment else "inline"
        return Response(
            pdf_path.read_bytes(),
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=3600",
            },
        )

    @app.get("/create-coi/preview/<token>")
    def create_coi_preview(token: str):
        return _coi_preview_response(token, attachment=False)

    @app.get("/create-coi/download/<token>")
    def create_coi_download(token: str):
        return _coi_preview_response(token, attachment=True)

    @app.route("/create-coi", methods=["GET", "POST"])
    def create_coi():
        query = (request.values.get("q") or "").strip()
        selected_raw = request.values.get("policy_id")
        try:
            selected_id = int(selected_raw) if selected_raw else None
        except (TypeError, ValueError):
            selected_id = None

        with session_scope() as session:
            policy_service = PolicyService(session)
            policies = policy_service.search_policies(query or None, limit=50)
            selected_policy = session.get(Policy, selected_id) if selected_id else None
            if selected_policy is not None and all(p.id != selected_policy.id for p in policies):
                policies = [selected_policy] + policies[:49]

            companies = load_companies("data/Additionalinsuredcomps.xlsx")
            company_names = sorted(list(companies.keys()))
            coi_type = (request.values.get("coi_type") or "Additional Insured").strip()
            if coi_type not in {"Additional Insured", "Certificate Holder", "Lienholder"}:
                coi_type = "Additional Insured"
            bulk_mode = request.values.get("bulk_mode") == "on"
            selected_vins = request.values.getlist("selected_vehicle_vins")
            selected_companies = request.values.getlist("selected_companies")
            selected_company = (request.values.get("selected_company") or "").strip()
            holder_name = (request.values.get("holder_name") or "").strip()
            selected_vehicle_objs = [vehicle for vehicle in (selected_policy.vehicles or []) if vehicle.vin in selected_vins] if selected_policy is not None else []

            default_description = _default_coi_description(selected_policy, coi_type, selected_vehicle_objs, holder_name) if selected_policy is not None else ""
            single_company = companies.get(selected_company or "", {}) if selected_company else {}
            default_naic = ""
            if selected_policy is not None:
                default_naic = selected_policy.naic_number or get_naic_for_carrier(selected_policy.carrier_name)
            form_values = {
                "holder_name": holder_name or single_company.get("name", ""),
                "holder_address": (request.values.get("holder_address") or single_company.get("address", "")).strip(),
                "holder_city": (request.values.get("holder_city") or single_company.get("city", "")).strip(),
                "holder_state": (request.values.get("holder_state") or single_company.get("state", "")).strip(),
                "holder_zip": (request.values.get("holder_zip") or single_company.get("zip", "")).strip(),
                "description": (request.values.get("description") or default_description).strip(),
                "desc_font_size": _int_form_arg("desc_font_size", 8, min_value=4, max_value=12),
                "insured_name": (request.values.get("insured_name") or (selected_policy.insured_name if selected_policy else "") or "").strip(),
                "insured_address": (request.values.get("insured_address") or (selected_policy.insured_address if selected_policy else "") or "").strip(),
                "insured_city": (request.values.get("insured_city") or (selected_policy.insured_city if selected_policy else "") or "").strip(),
                "insured_state": (request.values.get("insured_state") or (selected_policy.insured_state_code if selected_policy else "") or "").strip(),
                "insured_zip": (request.values.get("insured_zip") or (selected_policy.insured_zip if selected_policy else "") or "").strip(),
                "insured_naic": (request.values.get("insured_naic") or default_naic or "").strip(),
                "has_general_liability": _coi_bool_arg("has_general_liability", bool(selected_policy.has_general_liability) if selected_policy else False),
                "has_auto_liability": _coi_bool_arg("has_auto_liability", bool(selected_policy.has_auto_liability) if selected_policy else False),
                "has_cargo": _coi_bool_arg("has_cargo", bool(selected_policy.cargo_limit) if selected_policy else False) and coi_type != "Lienholder",
                "gl_general_aggregate": (request.values.get("gl_general_aggregate") or (_default_gl_aggregate(selected_policy) if selected_policy else "$1,000,000")).strip(),
            }

            companies_data = {
                name: {
                    "name": str(data.get("name", name) or ""),
                    "address": str(data.get("address", "") or ""),
                    "city": str(data.get("city", "") or ""),
                    "state": str(data.get("state", "") or ""),
                    "zip": str(data.get("zip", "") or ""),
                }
                for name, data in companies.items()
            }
            context = {
                "query": query, "policies": policies, "selected_policy": selected_policy,
                "companies": company_names, "companies_data": companies_data, "form_error": None, "form_values": form_values,
                "coi_type": coi_type, "bulk_mode": bulk_mode, "selected_vehicle_vins": selected_vins,
                "selected_companies": selected_companies, "selected_company": selected_company,
                "preview_token": None, "preview_filename": None,
            }

            if request.method == "POST" and selected_policy is not None:
                action = (request.form.get("action") or "download").strip()
                if coi_type == "Lienholder" and not selected_vehicle_objs:
                    context["form_error"] = "Lienholder COIs require at least one selected vehicle."
                    return render_template("create_coi.html", **context), 400
                description = form_values["description"]
                generator = COIGenerator()
                policy_data = _build_coi_policy_data(selected_policy, form_values, coi_type)
                if bulk_mode:
                    if not selected_companies:
                        context["form_error"] = "Select at least one company for bulk generation."
                        return render_template("create_coi.html", **context), 400
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w") as zf:
                        for company_name in selected_companies:
                            comp = companies.get(company_name, {})
                            generated_holder_name = comp.get("name", company_name)
                            holder = {
                                "name": generated_holder_name, "address": comp.get("address", ""),
                                "city": comp.get("city", ""), "state": comp.get("state", ""), "zip": comp.get("zip", ""),
                                "description": description.replace("[Certificate Holder Name]", generated_holder_name),
                            }
                            pdf = generator.generate_coi(policy_data, holder, desc_font_size=form_values["desc_font_size"])
                            zf.writestr(_safe_coi_filename(form_values["insured_name"], generated_holder_name), pdf)
                    return Response(zip_buffer.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{_safe_coi_filename(form_values["insured_name"], "", bulk=True)}"'})

                holder = {
                    "name": form_values["holder_name"], "address": form_values["holder_address"],
                    "city": form_values["holder_city"], "state": form_values["holder_state"], "zip": form_values["holder_zip"],
                    "description": description.replace("[Certificate Holder Name]", form_values["holder_name"]),
                }
                if not holder["name"]:
                    context["form_error"] = "Certificate holder name is required."
                    return render_template("create_coi.html", **context), 400
                pdf = generator.generate_coi(policy_data, holder, desc_font_size=form_values["desc_font_size"])
                filename = _safe_coi_filename(form_values["insured_name"], holder["name"])
                if action == "preview":
                    token = _store_coi_preview(pdf, filename)
                    context["preview_token"] = token
                    context["preview_filename"] = filename
                    return render_template("create_coi.html", **context)
                return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

            return render_template("create_coi.html", **context)

    def _review_form_context(selected_task: ReviewTask | None, gate_threshold: str) -> dict[str, Any]:
        if selected_task is None:
            return {}
        extraction = selected_task.extraction_result if isinstance(selected_task.extraction_result, dict) else {}
        policy = extraction.get("policy") if isinstance(extraction.get("policy"), dict) else {}
        confidence_map = build_confidence_map(policy)
        review_form = {
            "policy_number": gate_value(policy.get("policy_number", ""), "policy_number", confidence_map, gate_threshold, blank=""),
            "carrier_name": gate_value(policy.get("carrier_name", ""), "carrier_name", confidence_map, gate_threshold, blank=""),
            "insured_name": gate_value(policy.get("insured_name", ""), "insured_name", confidence_map, gate_threshold, blank=""),
            "effective_date": gate_value(policy.get("effective_date", ""), "effective_date", confidence_map, gate_threshold, blank=""),
            "expiration_date": gate_value(policy.get("expiration_date", ""), "expiration_date", confidence_map, gate_threshold, blank=""),
            "premium": gate_value(policy.get("premium", ""), "premium", confidence_map, gate_threshold, blank=""),
        }
        review_form["gated_fields"] = [
            field_name for field_name in ("policy_number", "carrier_name", "insured_name", "effective_date", "expiration_date", "premium")
            if policy.get(field_name) not in (None, "") and review_form[field_name] == ""
        ]
        return review_form

    def _default_coi_description(policy: Policy, coi_type: str, selected_vehicle_objs: list[Any], holder_name: str) -> str:
        _, desc_lines = COIService.prepare_coi_data(policy)
        radius_line = "Radius of Operation: Unlimited"
        if radius_line not in desc_lines:
            driver_idx = next(
                (idx for idx, line in enumerate(desc_lines) if str(line).startswith("Driver List:")),
                None,
            )
            if driver_idx is None:
                desc_lines.append(radius_line)
            else:
                desc_lines.insert(driver_idx + 1, radius_line)
        if coi_type == "Lienholder":
            desc_lines = [line for line in desc_lines if not line.startswith("Vehicle List:")]
            vehicle_bits = []
            for vehicle in selected_vehicle_objs or []:
                head = " ".join(str(part).strip() for part in (vehicle.year, vehicle.make, vehicle.model) if part)
                vehicle_bits.append(f"{head or 'Vehicle'} (VIN: {vehicle.vin or 'N/A'})")
            if not vehicle_bits:
                vehicle_bits = ["[Selected Vehicles]"]
            holder = holder_name.strip() or "[Certificate Holder Name]"
            comp = str(policy.comp_deductible or "—").strip().lstrip("$")
            coll = str(policy.coll_deductible or "—").strip().lstrip("$")
            desc_lines.append(
                f"{holder} is also listed as a Loss Payee for {' '.join(vehicle_bits)} "
                f"with Comp Ded: ${comp} / Coll Ded: ${coll}"
            )
        elif coi_type == "Additional Insured":
            desc_lines.append("Certificate Holder is also listed as an additional insured")
        return "\n".join(desc_lines)

    @app.get("/review-queue")
    def review_queue():
        status = request.args.get("status", "pending")
        selected = _int_arg("task_id")
        with session_scope() as session:
            context = load_queue_context(session, status, selected, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
            return render_template("review_queue.html", **context)

    @app.get("/review-queue/table")
    def review_queue_table():
        status = request.args.get("status", "pending")
        selected = _int_arg("task_id")
        with session_scope() as session:
            context = load_queue_context(session, status, selected, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
            return render_template("partials/review_tasks_table.html", **context)

    @app.get("/review-queue/<int:task_id>")
    def review_queue_detail(task_id: int):
        status = request.args.get("status", "pending")
        with session_scope() as session:
            context = load_queue_context(session, status, task_id, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
            return render_template("partials/review_task_detail.html", **context)

    @app.get("/review-queue/<int:task_id>/pdf")
    def review_queue_pdf(task_id: int):
        with session_scope() as session:
            task = session.get(ReviewTask, task_id)
            if task is None or task.upload is None or not task.upload.storage_uri:
                return ("PDF not available", 404)
            pdf_path = Path(task.upload.storage_uri)
            if not pdf_path.is_absolute():
                pdf_path = (Path.cwd() / pdf_path).resolve()
            if not pdf_path.exists():
                return ("PDF file missing on disk", 404)
            return Response(
                pdf_path.read_bytes(),
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": f'inline; filename="{task.upload.filename}"',
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "private, max-age=3600",
                },
            )

    @app.post("/review-queue/<int:task_id>/skip")
    def skip_review_task(task_id: int):
        status = request.form.get("status", "pending")
        with session_scope() as session:
            service = ReviewWorkflowService(session)
            service.record_decision(
                task_id=task_id,
                decision="skip",
                notes="Skipped from HTMX review queue.",
            )
            context = load_queue_context(session, status, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
            return render_template("partials/review_tasks_table.html", **context)

    @app.post("/review-queue/<int:task_id>/save")
    def save_review_task(task_id: int):
        status = request.form.get("status", "pending")
        with session_scope() as session:
            review_service = ReviewWorkflowService(session)
            task = review_service.get_task(task_id)
            if task is None:
                context = load_queue_context(session, status, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
                return render_template("partials/review_queue_oob.html", **context), 404
            try:
                result = apply_policy_form_edits(task.extraction_result, request.form)
            except ValueError as exc:
                context = load_queue_context(
                    session,
                    status,
                    task_id,
                    detail_error=str(exc),
                    gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT),
                )
                return render_template("partials/review_queue_oob.html", **context), 400
            policy_service = PolicyService(session)
            duplicate_info = policy_service.detect_duplicate_for_extraction(result)
            decision = (
                "update_existing"
                if duplicate_info.get("status") == "exact_policy_match"
                else "save_new"
            )
            target_policy_id = (
                (duplicate_info.get("existing_policy") or {}).get("id")
                if decision == "update_existing"
                else None
            )
            success, msg = policy_service.save_policy_from_extraction(result)
            if success:
                review_service.record_decision(
                    task_id=task_id,
                    decision=decision,
                    human_edits=result,
                    target_policy_id=target_policy_id,
                    notes="Saved from HTMX review queue.",
                )
                context = load_queue_context(session, status, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
                return render_template("partials/review_queue_oob.html", **context)
            context = load_queue_context(
                session,
                status,
                task_id,
                detail_error=f"Save failed: {msg or 'unknown error'}",
                gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT),
            )
            return render_template("partials/review_queue_oob.html", **context), 400

    @app.post("/review-queue/<int:task_id>/fail")
    def fail_review_task(task_id: int):
        status = request.form.get("status", "pending")
        with session_scope() as session:
            service = ReviewWorkflowService(session)
            service.mark_task_failed(task_id, "Marked failed from HTMX review queue.")
            context = load_queue_context(session, status, gate_threshold=app.config.get("CONFIDENCE_GATE_THRESHOLD", CONFIDENCE_GATE_DEFAULT))
            return render_template("partials/review_tasks_table.html", **context)

    app.jinja_env.globals["policy_summary"] = policy_summary
    app.jinja_env.globals["summarize_collection_item"] = summarize_collection_item

    return app


def _int_arg(name: str) -> int | None:
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _select_task(tasks: list[ReviewTask], selected_task_id: int | None) -> ReviewTask | None:
    if selected_task_id is not None:
        for task in tasks:
            if task.id == selected_task_id:
                return task
    return tasks[0] if tasks else None

def summarize_collection_item(item: Any) -> str:
    if item is None:
        return "—"
    if isinstance(item, dict):
        parts = []
        for key in ("vin", "full_name", "coverage_code", "name", "policy_number", "make", "model", "vehicle_vin"):
            value = item.get(key)
            if value:
                parts.append(str(value))
        return " | ".join(parts) if parts else json.dumps(item, default=str)
    parts = []
    for attr in ("vin", "full_name", "coverage_code", "name", "policy_number", "make", "model"):
        value = getattr(item, attr, None)
        if value:
            parts.append(str(value))
    return " | ".join(parts) if parts else str(item)


def _policy_type_options() -> list[tuple[str, str]]:
    options = [("auto", "Auto-detect (recommended)")]
    options.extend(
        (policy_type, policy_type.replace("_", " ").title())
        for policy_type in POLICY_TYPE_ENUM
        if policy_type != "unknown"
    )
    return options



def apply_policy_form_edits(result: dict[str, Any] | None, form) -> dict[str, Any]:
    edited = dict(result) if isinstance(result, dict) else {}
    policy = dict(edited.get("policy") if isinstance(edited.get("policy"), dict) else {})
    field_map = {
        "policy_number": "policy_number",
        "carrier_name": "carrier_name",
        "insured_name": "insured_name",
        "effective_date": "effective_date",
        "expiration_date": "expiration_date",
        "premium": "premium",
    }
    for form_key, policy_key in field_map.items():
        value = form.get(form_key)
        if value is not None:
            policy[policy_key] = value.strip() or None
    edited["policy"] = policy
    edited["vehicles"] = _load_json_array_field(form, "vehicles_json")
    edited["drivers"] = _load_json_array_field(form, "drivers_json")
    edited["coverages"] = _load_json_array_field(form, "coverages_json")
    edited["additional_interests"] = _load_json_array_field(form, "additional_interests_json")
    return edited


def _load_json_array_field(form, name: str) -> list[dict[str, Any]]:
    raw = form.get(name, "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} contains invalid JSON: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{name} entries must be JSON objects")
        cleaned.append(item)
    return cleaned



def policy_summary(result: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(result, dict):
        result = {}
    policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
    classification = result.get("classification") if isinstance(result.get("classification"), dict) else {}
    return {
        "policy_number": str(policy.get("policy_number") or "—"),
        "carrier": str(policy.get("carrier_name") or "—"),
        "insured": str(policy.get("insured_name") or "—"),
        "document_type": str(classification.get("document_type") or result.get("document_type") or "—"),
        "policy_type": str(classification.get("policy_type") or "—"),
        "policy_data_source": str(result.get("policy_data_source") or "—"),
    }

def _policy_export_payload(policy: Policy) -> dict[str, Any]:
    return {
        "policy": {
            "carrier_name": policy.carrier_name,
            "underwriter_name": getattr(policy, "underwriter_name", None),
            "naic_number": policy.naic_number,
            "policy_number": policy.policy_number,
            "effective_date": str(policy.effective_date) if policy.effective_date else None,
            "expiration_date": str(policy.expiration_date) if policy.expiration_date else None,
            "account_type": policy.account_type,
            "policy_type": policy.policy_type,
            "classification_confidence": policy.classification_confidence,
            "classification_signals": policy.classification_signals,
            "insured_name": policy.insured_name,
            "business_name": policy.business_name,
            "insured_address": policy.insured_address,
            "insured_city": policy.insured_city,
            "insured_state_code": policy.insured_state_code,
            "insured_zip": policy.insured_zip,
            "premium": policy.premium,
            "state": policy.state,
            "financial_responsibility_name": policy.financial_responsibility_name,
            "liability_limit": policy.liability_limit,
            "general_liability_limit": policy.general_liability_limit,
            "cargo_limit": policy.cargo_limit,
            "cargo_deductible": policy.cargo_deductible,
            "has_full_collision": policy.has_full_collision,
            "has_general_liability": policy.has_general_liability,
            "has_auto_liability": policy.has_auto_liability,
        },
        "vehicles": [
            {
                "year": vehicle.year,
                "make": vehicle.make,
                "model": vehicle.model,
                "vin": vehicle.vin,
                "gvw": vehicle.gvw,
                "type": vehicle.vehicle_type,
                "chassis": vehicle.chassis,
                "body": vehicle.body,
            }
            for vehicle in policy.vehicles
        ],
        "coverages": [
            {
                "type": coverage.type,
                "coverage_code": coverage.coverage_code,
                "family": coverage.family,
                "per_person": coverage.per_person,
                "per_accident": coverage.per_accident,
                "per_occurrence": coverage.per_occurrence,
                "combined_single_limit": coverage.combined_single_limit,
                "aggregate": coverage.aggregate,
                "deductible": coverage.deductible,
            }
            for coverage in policy.coverages
        ],
        "drivers": [
            {
                "full_name": driver.full_name,
                "license_number": driver.license_number,
                "is_excluded": driver.is_excluded,
            }
            for driver in policy.drivers
        ],
    }



app = create_app()

def _store_uploaded_bytes(filename: str, file_bytes: bytes) -> str:
    digest = sha256(file_bytes).hexdigest()
    suffix = Path(filename).suffix or ".pdf"
    UPLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_CACHE_DIR / f"{digest}{suffix}"
    path.write_bytes(file_bytes)
    return str(path)


def _load_uploaded_bytes(storage_uri: str | None) -> bytes:
    if not storage_uri:
        raise FileNotFoundError("Stored upload bytes are unavailable.")
    return Path(storage_uri).read_bytes()
