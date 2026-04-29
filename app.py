import streamlit as st
import os
from core.database import init_db, get_session
import core.history_model # Ensure model is registered
from core.services import UsageService
from streamlit_option_menu import option_menu
from core.constants import DEFAULT_DAILY_BUDGET, APP_DISPLAY_TAGLINE

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
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.session_state["GEMINI_API_KEY"] = api_key
    except:
        pass

@st.dialog("⚙️ Application Settings")
def settings_modal():
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
            import pandas as pd
            
            usage_service = UsageService(get_session(st.session_state.db_engine))
            daily_spend = usage_service.get_daily_usage()
            budget_limit = DEFAULT_DAILY_BUDGET
            progress = min(daily_spend / budget_limit, 1.0)
            
            st.markdown("---")
            st.markdown("### 📊 Cost Monitor")
            
            with st.container():
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.metric("Today's Spend", f"${daily_spend:.4f}")
                with col_b:
                     st.caption(f"Limit: ${budget_limit}")
                
                st.progress(progress, text=f"{progress*100:.1f}% Used")
                if daily_spend >= budget_limit:
                    st.error("Quota Exceeded! 🛑")

            with st.expander("Details", expanded=True):
                in_tok, out_tok = usage_service.get_todays_token_stats()
                st.markdown(f"""
                <div style="font-size: 0.8rem; color: #555;">
                    <div>📥 <b>Input:</b> {in_tok:,} toks</div>
                    <div>📤 <b>Output:</b> {out_tok:,} toks</div>
                    <div style="margin-top:5px; font-weight:bold; color: #005AA9;">Verified Accurate ✅</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("##### Recent Activity")
            recent_logs = usage_service.get_recent_usage(limit=5)
            if recent_logs:
                for log in recent_logs:
                     st.markdown(f"""
                     <div style="
                        background: #f8f9fa; 
                        padding: 8px; 
                        border-radius: 6px; 
                        border-left: 3px solid #28a745; 
                        margin-bottom: 6px; 
                        font-size: 0.75rem;">
                        <div style="display:flex; justify-content:space-between;">
                            <b>{log.model_name.replace('gemini-', '')}</b>
                            <span>${log.cost:.5f}</span>
                        </div>
                        <div style="color: #666; font-size: 0.7rem;">
                            {log.timestamp.strftime('%H:%M:%S')} • {log.request_type}
                        </div>
                     </div>
                     """, unsafe_allow_html=True)
            else:
                st.caption("No activity yet.")

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
