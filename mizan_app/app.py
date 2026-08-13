"""
MIZAN — Procurement Intelligence
=================================
Streamlit multi-page application for supplier bid evaluation.

Usage:
    streamlit run mizan_app/app.py
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mizan_app.mizan_styles import MIZAN_CSS, render_header, render_splash

st.set_page_config(
    page_title="MIZAN — Procurement Intelligence",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inject CSS ──
st.markdown(MIZAN_CSS, unsafe_allow_html=True)

# ── Splash screen on first load ──
if 'splash_shown' not in st.session_state:
    st.session_state.splash_shown = True
    splash = render_splash()
    st.markdown(splash, unsafe_allow_html=True)

# ── Header ──
render_header()

# ── Sidebar Navigation ──
st.sidebar.markdown('<div style="padding:12px 0;"><h2 style="color:white;font-size:20px;letter-spacing:3px;">MIZAN</h2><p style="color:#8A9BAB;font-size:10px;letter-spacing:2px;text-transform:uppercase;">Procurement Intelligence</p></div>', unsafe_allow_html=True)
st.sidebar.markdown('<hr style="border-color:#1E4D7A;margin:12px 0;">', unsafe_allow_html=True)

# Navigation items
pages = {
    "📊 Dashboard": "dashboard",
    "📋 Bid Evaluations": "evaluation",
    "🏭 Suppliers": "suppliers",
    "⚠ Risk & Escalations": "risk",
    "⚙ Agent Activity": "agent_activity",
    "📄 Reports": "reports",
}

selected = st.sidebar.radio("Navigate", list(pages.keys()), index=0, label_visibility="collapsed")
st.sidebar.markdown('<hr style="border-color:#1E4D7A;margin:24px 0 12px;">', unsafe_allow_html=True)
st.sidebar.markdown('<div style="padding:8px 0;"><span style="color:#5A8DB0;font-size:12px;">🔧 System Status</span><br><span style="color:#2ECC71;font-size:12px;">● All Systems Operational</span></div>', unsafe_allow_html=True)

# Store selected page in session state
st.session_state.page = pages[selected]

# ── Page routing ──
if st.session_state.page == "dashboard":
    from mizan_app.pages.dashboard import show
    show()
elif st.session_state.page == "evaluation":
    from mizan_app.pages.evaluation import show
    show()
elif st.session_state.page == "suppliers":
    from mizan_app.pages.suppliers import show
    show()
elif st.session_state.page == "risk":
    from mizan_app.pages.risk import show
    show()
elif st.session_state.page == "agent_activity":
    from mizan_app.pages.agent_activity import show
    show()
elif st.session_state.page == "reports":
    from mizan_app.pages.reports import show
    show()