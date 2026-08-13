"""
mizan_styles.py — Shared CSS and styling for MIZAN Procurement Intelligence UI.
"""

MIZAN_CSS = """
<style>
    /* ── MIZAN Brand Font ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* ── ADNOC Splash ── */
    .splash-container {
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: #FAFAFA;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 999999;
        animation: splashFadeOut 0.8s ease-in 2.2s forwards;
    }
    @keyframes splashFadeOut {
        to { opacity: 0; pointer-events: none; }
    }
    .splash-logo {
        opacity: 0;
        animation: fadeIn 0.6s ease-out 0.2s forwards;
        margin-bottom: 30px;
    }
    .splash-logo svg { width: 160px; height: auto; }
    .splash-mizan {
        opacity: 0;
        animation: fadeIn 0.5s ease-out 1.0s forwards;
        text-align: center;
    }
    .splash-mizan h1 {
        font-size: 48px;
        font-weight: 700;
        color: #002B5C;
        letter-spacing: 6px;
        margin-bottom: 8px;
    }
    .splash-mizan .subtitle {
        font-size: 18px;
        color: #5A6B7A;
        font-weight: 400;
        letter-spacing: 3px;
    }
    .splash-mizan .tagline {
        font-size: 14px;
        color: #8A9BAB;
        font-weight: 300;
        margin-top: 12px;
        letter-spacing: 1px;
    }
    @keyframes fadeIn {
        to { opacity: 1; }
    }

    /* ── Main Header ── */
    .mizan-header {
        display: flex;
        align-items: center;
        padding: 8px 20px;
        background: white;
        border-bottom: 1px solid #E8EDF2;
        margin: -70px -60px 16px -60px;
        height: 56px;
    }
    .mizan-header-logo {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .mizan-header-logo svg { width: 36px; height: auto; }
    .mizan-header-brand h2 {
        font-size: 18px;
        font-weight: 700;
        color: #002B5C;
        margin: 0;
        line-height: 1.2;
    }
    .mizan-header-brand span {
        font-size: 10px;
        color: #8A9BAB;
        letter-spacing: 2px;
        text-transform: uppercase;
    }
    .mizan-header-right {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 16px;
        font-size: 13px;
        color: #5A6B7A;
    }
    .status-dot {
        display: inline-block;
        width: 8px; height: 8px;
        border-radius: 50%;
        background: #2ECC71;
        margin-right: 6px;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
    }

    /* ── Sidebar override ── */
    section[data-testid="stSidebar"] {
        background: #002B5C !important;
    }
    section[data-testid="stSidebar"] .st-emotion-cache-1d391kg {
        background: #002B5C;
    }
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label {
        color: #C8D6E5 !important;
    }

    /* ── KPI Cards ── */
    .kpi-card {
        background: white;
        border: 1px solid #E8EDF2;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
        transition: box-shadow 0.2s;
    }
    .kpi-card:hover { box-shadow: 0 4px 12px rgba(0,43,92,0.08); }
    .kpi-card .kpi-value {
        font-size: 32px;
        font-weight: 700;
        color: #002B5C;
    }
    .kpi-card .kpi-label {
        font-size: 12px;
        color: #8A9BAB;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 4px;
    }
    .kpi-card .kpi-icon {
        font-size: 24px;
        margin-bottom: 8px;
    }

    /* ── Agent Pipeline ── */
    .pipeline-node {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 16px;
        background: white;
        border: 1px solid #E8EDF2;
        border-radius: 8px;
        margin-bottom: 4px;
        transition: all 0.2s;
    }
    .pipeline-node.complete {
        border-left: 4px solid #2ECC71;
    }
    .pipeline-node.processing {
        border-left: 4px solid #3498DB;
        background: #F0F7FF;
    }
    .pipeline-node.waiting {
        border-left: 4px solid #D5DDE5;
        opacity: 0.6;
    }
    .pipeline-node.error {
        border-left: 4px solid #E74C3C;
    }
    .pipeline-node .node-icon { font-size: 20px; }
    .pipeline-node .node-name { font-weight: 600; font-size: 14px; color: #002B5C; }
    .pipeline-node .node-status { font-size: 12px; margin-left: auto; }
    .pipeline-arrow {
        text-align: center;
        color: #C8D6E5;
        font-size: 12px;
        margin: -2px 0;
    }

    /* ── Score Cards ── */
    .score-card {
        background: white;
        border: 1px solid #E8EDF2;
        border-radius: 10px;
        padding: 20px;
    }
    .score-card .score-value {
        font-size: 36px;
        font-weight: 700;
        color: #002B5C;
    }
    .score-card .score-max {
        font-size: 18px;
        color: #8A9BAB;
    }
    .score-card .score-label {
        font-size: 12px;
        color: #8A9BAB;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 4px;
    }
    .score-bar {
        height: 6px;
        background: #E8EDF2;
        border-radius: 3px;
        margin-top: 8px;
    }
    .score-bar-fill {
        height: 100%;
        border-radius: 3px;
        background: #002B5C;
        transition: width 0.5s;
    }

    /* ── Evidence Panel ── */
    .evidence-item {
        background: #F8FAFC;
        border: 1px solid #E8EDF2;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .evidence-item .fact { font-weight: 600; color: #002B5C; }
    .evidence-item .source { font-size: 12px; color: #8A9BAB; }
    .evidence-item .confidence {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
    }
    .confidence-verified { background: #D5F5E3; color: #27AE60; }
    .confidence-partial { background: #FEF9E7; color: #F39C12; }
    .confidence-not-found { background: #FDEDEC; color: #E74C3C; }

    /* ── Table styling ── */
    .dataframe {
        font-size: 13px;
    }
    .dataframe th {
        background: #F8FAFC;
        font-weight: 600;
        color: #002B5C;
        padding: 10px 8px;
    }

    /* ── Status badges ── */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-pass { background: #D5F5E3; color: #27AE60; }
    .badge-fail { background: #FDEDEC; color: #E74C3C; }
    .badge-warning { background: #FEF9E7; color: #F39C12; }
    .badge-info { background: #EBF5FB; color: #3498DB; }
    .badge-human { background: #F5EEF8; color: #8E44AD; }

    /* ── General ── */
    .stApp {
        background: #F8FAFC;
    }
    h1, h2, h3 {
        color: #002B5C;
    }
    .stButton button {
        background: #002B5C;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 8px 24px;
        font-weight: 600;
        font-size: 14px;
    }
    .stButton button:hover {
        background: #003D7A !important;
        color: white !important;
    }
    .st-emotion-cache-1rtdyuf {
        padding: 2rem 3rem;
    }

    /* ── File Upload ── */
    .upload-zone {
        border: 2px dashed #C8D6E5;
        border-radius: 12px;
        padding: 40px;
        text-align: center;
        background: #FAFBFC;
    }
    .upload-zone:hover {
        border-color: #002B5C;
        background: #F0F4F8;
    }

    /* ── Compliance checklist ── */
    .checklist-row {
        display: flex;
        align-items: center;
        padding: 6px 0;
        border-bottom: 1px solid #F0F2F5;
    }
    .checklist-row .doc-code {
        font-weight: 600;
        color: #002B5C;
        min-width: 40px;
    }
    .checklist-row .doc-desc {
        flex: 1;
        font-size: 13px;
        color: #5A6B7A;
    }

    /* ── Risk cards ── */
    .risk-card {
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 10px;
        border-left: 4px solid;
    }
    .risk-card.low { background: #F0FFF4; border-color: #2ECC71; }
    .risk-card.medium { background: #FFFDF0; border-color: #F39C12; }
    .risk-card.high { background: #FFF5F5; border-color: #E74C3C; }
    .risk-card .risk-title { font-weight: 600; font-size: 14px; }
    .risk-card .risk-detail { font-size: 13px; color: #5A6B7A; margin-top: 4px; }

    /* Report styles */
    .report-section {
        background: white;
        border: 1px solid #E8EDF2;
        border-radius: 10px;
        padding: 24px;
        margin-bottom: 16px;
    }
    .report-section h3 {
        font-size: 16px;
        font-weight: 700;
        color: #002B5C;
        border-bottom: 2px solid #002B5C;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }
</style>
"""


def get_adnoc_logo_svg():
    """Return ADNOC logo SVG for the splash screen."""
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 60" fill="none">
        <rect x="0" y="0" width="160" height="60" rx="4" fill="#002B5C"/>
        <text x="80" y="38" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-weight="700" font-size="22" letter-spacing="3">ADNOC</text>
        <text x="80" y="52" text-anchor="middle" fill="#A0B8D0" font-family="Arial, sans-serif" font-size="8" letter-spacing="2">ABU DHABI NATIONAL OIL COMPANY</text>
    </svg>'''


def get_small_logo_svg():
    """Return small ADNOC logo for header."""
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 24" fill="none">
        <rect x="0" y="0" width="36" height="24" rx="3" fill="#002B5C"/>
        <text x="18" y="16" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-weight="700" font-size="11" letter-spacing="1">AD</text>
    </svg>'''


def render_header():
    """Render the top navigation header with ADNOC logo and MIZAN branding."""
    import streamlit as st
    st.markdown(f'''
    <div class="mizan-header">
        <div class="mizan-header-logo">
            {get_small_logo_svg()}
            <div class="mizan-header-brand">
                <h2>MIZAN</h2>
                <span>Procurement Intelligence</span>
            </div>
        </div>
        <div class="mizan-header-right">
            <span><span class="status-dot"></span>System Operational</span>
            <span>|</span>
            <span>👤 Procurement Engineer</span>
        </div>
    </div>
    ''', unsafe_allow_html=True)


def render_splash():
    """Render the ADNOC splash screen HTML."""
    import streamlit as st
    splash_html = f'''
    <div class="splash-container" id="mizan-splash">
        <div class="splash-logo">
            {get_adnoc_logo_svg()}
        </div>
        <div class="splash-mizan">
            <h1>MIZAN</h1>
            <div class="subtitle">Procurement Intelligence</div>
            <div class="tagline">Balance every bid. Defend every decision.</div>
        </div>
    </div>
    <script>
        setTimeout(function() {{
            var splash = document.getElementById('mizan-splash');
            if (splash) {{
                splash.style.transition = 'opacity 0.8s ease-in';
                splash.style.opacity = '0';
                setTimeout(function() {{
                    splash.style.display = 'none';
                }}, 800);
            }}
        }}, 2000);
    </script>
    '''
    return splash_html