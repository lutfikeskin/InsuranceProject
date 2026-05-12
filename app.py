import streamlit as st
import os
from core.database import init_db, get_session
import core.history_model  # noqa: F401  — side-effect import registers PolicyHistory with SQLAlchemy's metadata
import core.notification_model  # noqa: F401  — side-effect import registers NotificationLog with SQLAlchemy's metadata
from core.services import UsageService
from streamlit_option_menu import option_menu
from core.constants import (
    APP_DISPLAY_TAGLINE,
    CONFIDENCE_GATE_DEFAULT,
    CONFIDENCE_GATE_OPTIONS,
    DEFAULT_DAILY_BUDGET,
)

from views.dashboard import page_dashboard
from views.process_policies import page_process_policies
from views.database_page import page_database
from views.create_coi import page_create_coi

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

if 'db_engine' not in st.session_state:
    st.session_state.db_engine = init_db()

api_key = st.session_state.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not api_key:
    # st.secrets raises FileNotFoundError (StreamlitSecretNotFoundError subclass)
    # when no .streamlit/secrets.toml exists. That's the expected fallthrough on
    # local dev — silently let api_key stay empty and the UI will prompt for it.
    # Any other exception during secrets lookup is a real configuration error
    # worth surfacing.
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.session_state["GEMINI_API_KEY"] = api_key
    except FileNotFoundError:
        pass

@st.dialog("⚙️ Application Settings")
def settings_modal():
    st.write("Configure your application settings below.")
    current_key = st.session_state.get("GEMINI_API_KEY", "")
    has_key = bool(current_key)
    st.caption(
        f"API key status: {'✅ configured' if has_key else '⚠️ not configured'}"
    )
    new_key = st.text_input(
        "Gemini API Key",
        value=current_key if current_key else "",
        type="password",
        help="Enter your Google Gemini API Key for policy extraction.",
    )

    save_col, clear_col = st.columns([3, 1])
    if save_col.button("Save", width='stretch', type="primary"):
        if new_key:
            st.session_state["GEMINI_API_KEY"] = new_key
            st.success("Settings saved.")
            st.rerun()
        else:
            st.warning("Please enter a valid key.")
    if clear_col.button(
        "Clear",
        width='stretch',
        disabled=not has_key,
        help="Forget the API key in this session. Browser refresh will re-read from secrets if available.",
    ):
        st.session_state.pop("GEMINI_API_KEY", None)
        st.success("API key cleared from this session.")
        st.rerun()

    st.divider()
    st.markdown("##### 🎯 Extraction Quality Gate")
    # Initialize session-state default once so the selectbox `index=` lookup
    # is stable across reruns. After this, the `key=` binding owns the value.
    if "confidence_gate_threshold" not in st.session_state:
        st.session_state["confidence_gate_threshold"] = CONFIDENCE_GATE_DEFAULT
    _gate_keys = list(CONFIDENCE_GATE_OPTIONS.keys())
    _current_gate = st.session_state["confidence_gate_threshold"]
    if _current_gate not in _gate_keys:
        # Defensive: stale session-state value (e.g. left over from an older
        # version with different threshold names) falls back to the default
        # rather than crashing the selectbox.
        _current_gate = CONFIDENCE_GATE_DEFAULT
        st.session_state["confidence_gate_threshold"] = _current_gate
    st.selectbox(
        "Clear extracted fields below this confidence",
        options=_gate_keys,
        format_func=lambda v: CONFIDENCE_GATE_OPTIONS[v],
        index=_gate_keys.index(_current_gate),
        key="confidence_gate_threshold",
        help=(
            "Soft nudge applied on the review form: fields with confidence "
            "below the chosen level are cleared, so you have to type them in "
            "rather than skim-and-save. Save is never blocked."
        ),
    )

    st.divider()
    st.markdown("##### 📊 Usage Management")
    if st.button("Reset Daily Usage Meter", width='stretch', type="secondary"):
        session = get_session(st.session_state.db_engine)
        usage_svc = UsageService(session)
        success, msg = usage_svc.clear_usage()
        session.close()
        if success:
            st.success("Usage meter reset successfully!")
            st.rerun()
        else:
            st.error(f"Error: {msg}")

with st.sidebar:
    if os.path.exists("assets/logo.png"):
        st.image("assets/logo.png", width=150)
    else:
        st.markdown(
            f'<div class="brand-header"><h3>Truckers National</h3>'
            f'<p style="color: #666; font-size: 0.8rem;">{APP_DISPLAY_TAGLINE}</p></div>',
            unsafe_allow_html=True,
        )
    
    MENU_OPTIONS = ["Dashboard", "Process Policies", "Database", "Create COI"]
    manual_nav = None
    if st.session_state.get("nav_request"):
        req = st.session_state.pop("nav_request", None)
        if req in MENU_OPTIONS:
            manual_nav = MENU_OPTIONS.index(req)

    selected = option_menu(
        menu_title=None,
        options=MENU_OPTIONS,
        icons=["house-fill", "cloud-arrow-up-fill", "database-fill", "file-earmark-pdf-fill"],
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
