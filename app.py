import streamlit as st
import os
import hmac
from core.database import init_db, get_session
import core.history_model # Ensure model is registered
from core.services import UsageService
from core.telemetry import DEFAULT_EVENT_RETENTION_DAYS, TelemetryService, log_event
from streamlit_option_menu import option_menu
from core.constants import DEFAULT_DAILY_BUDGET, APP_DISPLAY_TAGLINE

from views.dashboard import page_dashboard
from views.process_policies import page_process_policies
from views.database_page import page_database
from views.create_coi import page_create_coi
from views.telemetry import page_telemetry
from views.settings_backup import render_unified_backup_section

st.set_page_config(
    page_title="Insurance Doc Intelligence", 
    page_icon="assets/browsericon.ico",
    layout="wide",
    initial_sidebar_state="expanded"
)

def load_css(file_name):
    if os.path.exists(file_name):
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css("assets/style.css")


def ensure_app_password():
    configured = ""
    try:
        configured = (st.secrets.get("APP_PASSWORD") or "").strip()
    except Exception:
        pass
    if not configured:
        configured = (os.getenv("APP_PASSWORD") or "").strip()
    if not configured:
        return
    if st.session_state.get("_app_auth_ok"):
        return

    st.title("Sign in")
    with st.form("app_password_form", clear_on_submit=False):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Continue")
    if submitted:
        if hmac.compare_digest(
            entered.encode("utf-8"), configured.encode("utf-8")
        ):
            st.session_state["_app_auth_ok"] = True
            st.rerun()
        else:
            st.error("Invalid password.")
    st.stop()


ensure_app_password()

if 'db_engine' not in st.session_state:
    st.session_state.db_engine = init_db()

api_key = st.session_state.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not api_key:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.session_state["GEMINI_API_KEY"] = api_key
    except:
        pass

@st.dialog("⚙️ Application Settings")
def settings_modal():
    admin_session = get_session(st.session_state.db_engine)
    telemetry = TelemetryService(admin_session)
    try:
        st.write("Configure your application settings below.")
        current_key = st.session_state.get("GEMINI_API_KEY", "")
        new_key = st.text_input("Gemini API Key", value=current_key if current_key else "", type="password", help="Enter your Google Gemini API Key for policy extraction.")

        if st.button("Save & Refresh", width='stretch', type="primary"):
            if new_key:
                st.session_state["GEMINI_API_KEY"] = new_key
                st.success("Settings saved successfully!")
                st.rerun()
            else:
                st.warning("Please enter a valid key.")

        st.divider()
        st.markdown("##### 📊 Usage Management")
        if st.button("Reset Daily Usage Meter", width='stretch', type="secondary"):
            usage_svc = UsageService(admin_session)
            success, msg = usage_svc.clear_usage()
            telemetry.record_event(
                "admin_usage_reset",
                category="admin",
                status="success" if success else "failure",
                metadata={"message": msg},
            )
            log_event(
                "admin_usage_reset",
                status="success" if success else "failure",
                message=msg,
            )
            if success:
                st.success("Usage meter reset successfully!")
                st.rerun()
            else:
                st.error(f"Error: {msg}")

        if st.button(
            f"Clear telemetry events older than {DEFAULT_EVENT_RETENTION_DAYS} days",
            width='stretch',
            type="secondary",
        ):
            deleted = telemetry.purge_old_events(DEFAULT_EVENT_RETENTION_DAYS)
            telemetry.record_event(
                "admin_telemetry_retention_cleanup",
                category="admin",
                status="success",
                count_value=deleted,
                metadata={"retention_days": DEFAULT_EVENT_RETENTION_DAYS},
            )
            log_event(
                "admin_telemetry_retention_cleanup",
                status="success",
                metadata={"deleted": deleted, "retention_days": DEFAULT_EVENT_RETENTION_DAYS},
            )
            st.success(f"Deleted {deleted} old telemetry events.")
            st.rerun()

        st.divider()
        st.markdown("##### Local backup and restore")
        render_unified_backup_section(telemetry=telemetry)
    finally:
        admin_session.close()

with st.sidebar:
    if os.path.exists("assets/logo.png"):
        st.image("assets/logo.png", width=150)
    else:
        st.markdown(
            f'<div class="brand-header"><h3>Truckers National</h3>'
            f'<p style="color: #666; font-size: 0.8rem;">{APP_DISPLAY_TAGLINE}</p></div>',
            unsafe_allow_html=True,
        )
    
    MENU_OPTIONS = ["Dashboard", "Process Policies", "Database", "Create COI", "Telemetry"]
    manual_nav = None
    if st.session_state.get("nav_request"):
        req = st.session_state.pop("nav_request", None)
        if req in MENU_OPTIONS:
            manual_nav = MENU_OPTIONS.index(req)

    selected = option_menu(
        menu_title=None,
        options=MENU_OPTIONS,
        icons=["house-fill", "cloud-arrow-up-fill", "database-fill", "file-earmark-pdf-fill", "bar-chart-line-fill"],
        menu_icon="cast",
        default_index=0,
        manual_select=manual_nav,
        key="sidebar_nav_menu",
        styles={
            "container": {"padding": "0!important", "background-color": "#fff", "border-radius": "0"},
            "icon": {"color": "#005AA9", "font-size": "18px"}, 
            "nav-link": {
                "font-size": "15px", 
                "text-align": "left", 
                "margin": "5px 0px", 
                "padding": "10px 15px",
                "color": "#444",
                "font-weight": "500",
                "border-radius": "8px"
            },
            "nav-link-selected": {
                "background-color": "#E6F4FF", 
                "color": "#005AA9",
                "font-weight": "600",
                "border-left": "4px solid #005AA9"
            },
        }
    )
    
    st.spacer = st.empty()
    st.markdown("<br>" * 10, unsafe_allow_html=True) 
    
    st.divider()
    if st.button("⚙️ Settings", width='stretch'):
        settings_modal()
    
    if api_key:
        st.success("API Active", icon="✅")

        try:
            from core.services import UsageService
            from zoneinfo import ZoneInfo

            ET = ZoneInfo("America/New_York")
            usage_service = UsageService(get_session(st.session_state.db_engine))
            daily_spend = usage_service.get_daily_usage()
            calls_today = usage_service.get_todays_call_count()
            in_tok, out_tok = usage_service.get_todays_token_stats()
            budget_limit = DEFAULT_DAILY_BUDGET
            progress = min(daily_spend / budget_limit, 1.0) if budget_limit else 0.0

            st.markdown("---")
            st.caption("USAGE TODAY · ET")

            c1, c2 = st.columns(2)
            c1.metric("Spend", f"${daily_spend:.4f}")
            c2.metric("Calls", f"{calls_today}")

            st.progress(progress, text=f"${daily_spend:.4f} / ${budget_limit:.2f}")
            if daily_spend >= budget_limit:
                st.error("Daily limit reached")

            st.caption(f"Tokens — in: {in_tok:,} · out: {out_tok:,}")

            recent_logs = usage_service.get_recent_usage(limit=5)
            if recent_logs:
                with st.expander("Recent activity", expanded=False):
                    for log in recent_logs:
                        ts_et = log.timestamp.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
                        model = (log.model_name or "").replace("gemini-", "")
                        st.caption(
                            f"{ts_et.strftime('%b %d %H:%M')} · {log.request_type} · "
                            f"{model} · ${log.cost:.5f}"
                        )

        except Exception as e:
            st.error(f"Usage Error: {e}")
    else:
        st.warning("API Missing", icon="⚠️")

if selected == "Dashboard":
    page_dashboard()
elif selected == "Process Policies":
    page_process_policies(api_key)
elif selected == "Database":
    page_database(api_key)
elif selected == "Create COI":
    page_create_coi()
elif selected == "Telemetry":
    page_telemetry()
