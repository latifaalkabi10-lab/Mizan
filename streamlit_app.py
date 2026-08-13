"""
MIZAN — Procurement Intelligence
Main entry point for Streamlit Cloud deployment.
"""

import streamlit as st
import sys, os, traceback

# ── Ensure ProcurX root is on the path ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ── Try to catch startup errors so they show in the browser ──
try:
    st.set_page_config(
        page_title="MIZAN — Procurement Intelligence",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    from mizan_app.mizan_styles import MIZAN_CSS, render_header, render_splash

    # ── CSS ──
    st.markdown(MIZAN_CSS, unsafe_allow_html=True)

    # ── Splash screen (first visit only) ──
    if 'splash_shown' not in st.session_state:
        st.session_state.splash_shown = True
        st.markdown(render_splash(), unsafe_allow_html=True)

    # ── Header ──
    render_header()

    # ── Sidebar ──
    st.sidebar.markdown(
        '<div style="padding:12px 0;"><h2 style="color:white;font-size:20px;'
        'letter-spacing:3px;">MIZAN</h2>'
        '<p style="color:#8A9BAB;font-size:10px;letter-spacing:2px;'
        'text-transform:uppercase;">Procurement Intelligence</p></div>',
        unsafe_allow_html=True
    )
    st.sidebar.markdown('<hr style="border-color:#1E4D7A;margin:12px 0;">', unsafe_allow_html=True)

    pages = {
        "📊 Dashboard": "dashboard",
        "📋 Bid Evaluations": "evaluation",
        "🏭 Suppliers": "suppliers",
        "⚠ Risk & Escalations": "risk",
        "⚙ Agent Activity": "agent_activity",
        "📄 Reports": "reports",
    }

    selected = st.sidebar.radio(
        "Navigate", list(pages.keys()), index=0, label_visibility="collapsed"
    )
    st.sidebar.markdown('<hr style="border-color:#1E4D7A;margin:24px 0 12px;">', unsafe_allow_html=True)
    st.sidebar.markdown(
        '<div style="padding:8px 0;"><span style="color:#5A8DB0;font-size:12px;">'
        '🔧 System Status</span><br>'
        '<span style="color:#2ECC71;font-size:12px;">● All Systems Operational</span></div>',
        unsafe_allow_html=True
    )

    st.session_state.page = pages[selected]

    # ── Page routing ──
    page = st.session_state.page
    if page == "dashboard":
        from mizan_app.pages.dashboard import show; show()
    elif page == "evaluation":
        from mizan_app.pages.evaluation import show; show()
    elif page == "suppliers":
        from mizan_app.pages.suppliers import show; show()
    elif page == "risk":
        from mizan_app.pages.risk import show; show()
    elif page == "agent_activity":
        from mizan_app.pages.agent_activity import show; show()
    elif page == "reports":
        from mizan_app.pages.reports import show; show()

except Exception as e:
    st.error(f"### 🚨 MIZAN Startup Error\n\n```\n{traceback.format_exc()}\n```")
    st.info(
        "This usually means a missing file or dependency. "
        "Double-check that **all files** were committed and pushed to GitHub, "
        "especially the `evidence_agent/data/` folder."
    )