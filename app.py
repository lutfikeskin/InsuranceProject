import streamlit as st
import os
from core.database import init_db, get_session
import core.history_model # Ensure model is registered
from core.services import UsageService
from streamlit_option_menu import option_menu
from core.constants import DEFAULT_DAILY_BUDGET

# Import Views
from views.dashboard import page_dashboard
from views.process_policies import page_process_policies
from views.database_page import page_database
from views.create_coi import page_create_coi

# Page Config
st.set_page_config(
    page_title="Insurance Doc Intelligence", 
    page_icon="assets/browsericon.ico",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load External CSS
def load_css(file_name):
    if os.path.exists(file_name):
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css("assets/style.css")

# Initialize DB
if 'db_engine' not in st.session_state:
    st.session_state.db_engine = init_db()

# --- Global Logic / Settings Helper ---
api_key = st.session_state.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not api_key:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.session_state["GEMINI_API_KEY"] = api_key
    except:
        pass

# --- Settings Dialog ---
@st.dialog("⚙️ Application Settings")
def settings_modal():
    st.write("Configure your application settings below.")
    current_key = st.session_state.get("GEMINI_API_KEY", "")
    new_key = st.text_input("Gemini API Key", value=current_key if current_key else "", type="password", help="Enter your Google Gemini API Key for policy extraction.")
    
    if st.button("Save & Refresh", use_container_width=True, type="primary"):
        if new_key:
            st.session_state["GEMINI_API_KEY"] = new_key
            st.success("Settings saved successfully!")
            st.rerun()
        else:
            st.warning("Please enter a valid key.")

# --- Sidebar Navigation ---
with st.sidebar:
    if os.path.exists("assets/logo.png"):
        st.image("assets/logo.png", width=150)
    else:
        st.markdown('<div class="brand-header"><h3>Truckers National</h3><p style="color: #666; font-size: 0.8rem;">Policy Intelligence Hub</p></div>', unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title=None,
        options=["Dashboard", "Process Policies", "Database", "Create COI"],
        icons=["house-fill", "cloud-arrow-up-fill", "database-fill", "file-earmark-pdf-fill"],
        menu_icon="cast",
        default_index=0,
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
    if st.button("⚙️ Settings", use_container_width=True):
        settings_modal()
    
    if api_key:
        st.success("API Active", icon="✅")
        
        # --- BUDGET METER (NEW) ---
        try:
            from core.services import UsageService
            usage_service = UsageService(get_session(st.session_state.db_engine))
            daily_spend = usage_service.get_daily_usage()
            budget_limit = DEFAULT_DAILY_BUDGET
            
            progress = min(daily_spend / budget_limit, 1.0)
            
            st.markdown(f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #eee; margin-top: 10px;">
                <p style="margin:0; font-size: 0.8rem; color: #666;">Daily Budget ($2.50)</p>
                <h4 style="margin:5px 0;">${daily_spend:.4f}</h4>
                <div style="background: #eee; height: 8px; border-radius: 4px;">
                    <div style="background: {'#ff4b4b' if progress > 0.8 else '#005AA9'}; width: {progress*100}%; height: 100%; border-radius: 4px;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if daily_spend >= budget_limit:
                st.error("Quota Exceeded! 🛑")
        except Exception as e:
            st.error(f"Usage Error: {e}")
    else:
        st.warning("API Missing", icon="⚠️")

# --- Main Routing ---
if selected == "Dashboard":
    page_dashboard()
elif selected == "Process Policies":
    page_process_policies(api_key)
elif selected == "Database":
    page_database(api_key)
elif selected == "Create COI":
    page_create_coi()
