"""
Dashboard page — MIZAN Procurement Intelligence overview with KPIs and active tender.
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import get_all_suppliers, _get_rfp_info
from evidence_agent import search


def show():
    st.markdown('<h1 style="color:#002B5C;margin-bottom:4px;">MIZAN</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#5A6B7A;font-size:16px;margin-bottom:24px;">Evaluate supplier bids with evidence, not assumptions.</p>', unsafe_allow_html=True)

    # ── KPI Cards ──
    rfp = _get_rfp_info()
    suppliers = get_all_suppliers()
    bids_count = len(suppliers)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">📋</div>
            <div class="kpi-value">1</div>
            <div class="kpi-label">Active Tenders</div>
        </div>
        ''', unsafe_allow_html=True)
    with col2:
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">📑</div>
            <div class="kpi-value">{bids_count}</div>
            <div class="kpi-label">Bids Received</div>
        </div>
        ''', unsafe_allow_html=True)
    with col3:
        eval_status = st.session_state.get('evaluation_complete', False)
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">{'✅' if eval_status else '⏳'}</div>
            <div class="kpi-value">{'1' if eval_status else '0'}</div>
            <div class="kpi-label">Evaluations {'Done' if eval_status else 'In Progress'}</div>
        </div>
        ''', unsafe_allow_html=True)
    with col4:
        human_review = st.session_state.get('human_review_required', None)
        if human_review is True:
            badge = '🚨 <span class="badge badge-human">REQUIRED</span>'
        elif human_review is False:
            badge = '✅ <span class="badge badge-pass">NONE</span>'
        else:
            badge = '⏳ <span class="badge badge-info">PENDING</span>'
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">👁️</div>
            <div class="kpi-value">{badge}</div>
            <div class="kpi-label" style="margin-top:12px;">Human Reviews</div>
        </div>
        ''', unsafe_allow_html=True)

    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)

    # ── Featured Tender ──
    st.markdown('<h2 style="font-size:20px;font-weight:600;color:#002B5C;">Featured Evaluation</h2>', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f'''
        <div class="score-card" style="padding:24px;">
            <div style="font-size:12px;color:#8A9BAB;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Active Tender</div>
            <div style="font-size:22px;font-weight:700;color:#002B5C;">{rfp.get("tender_ref", "N/A")}</div>
            <div style="font-size:15px;color:#5A6B7A;margin:8px 0;">
                {rfp.get("title", "Supply & Installation of Produced Water Treatment Package")}
            </div>
            <div style="font-size:13px;color:#8A9BAB;">
                📍 {rfp.get("location", "Bu Hasnah Field — CPF-2")}
            </div>
            <div style="display:flex;gap:24px;margin-top:16px;">
                <div><span style="font-weight:600;color:#002B5C;">{bids_count}</span> <span style="color:#8A9BAB;">Supplier Bids</span></div>
                <div><span style="font-weight:600;color:#002B5C;">{bids_count + 2}</span> <span style="color:#8A9BAB;">Documents</span></div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    with col2:
        st.markdown('<div style="padding:24px;text-align:center;">', unsafe_allow_html=True)
        if st.button("🚀 START AI EVALUATION", use_container_width=True, type="primary"):
            st.session_state.run_evaluation = True
            st.session_state.page = "evaluation"
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # Quick stats
        with_capacity = sum(1 for s in suppliers if s.get('capacity_m3_per_day') is not None)
        with_icv = sum(1 for s in suppliers if s.get('icv_score_pct') is not None)
        st.markdown(f'''
        <div style="background:#F8FAFC;border-radius:8px;padding:12px;margin-top:8px;">
            <div style="font-size:12px;color:#8A9BAB;">📊 Quick Stats</div>
            <div style="font-size:13px;color:#5A6B7A;margin-top:6px;">
                ✅ {with_capacity}/{bids_count} with capacity data<br>
                ✅ {with_icv}/{bids_count} with ICV data<br>
                📅 Deadline: {rfp.get("bid_deadline", "N/A")}
            </div>
        </div>
        ''', unsafe_allow_html=True)

    # ── Supplier Overview Table ──
    st.markdown('<h2 style="font-size:18px;font-weight:600;color:#002B5C;margin-top:24px;">Supplier Bids Overview</h2>', unsafe_allow_html=True)

    table_data = []
    for s in suppliers:
        cap = s.get('capacity_m3_per_day')
        price = s.get('price_total')
        currency = s.get('price_currency', 'AED')
        icv = s.get('icv_score_pct')
        trir = s.get('trir_3yr_avg')
        mc = s.get('mc_weeks_from_loa')

        table_data.append({
            'Bid Ref': s.get('bid_ref', ''),
            'Supplier': s.get('company', ''),
            'Capacity (m³/d)': f"{cap:,}" if cap else '—',
            'Price': f"{currency} {price:,}" if price else '—',
            'ICV %': f"{icv}%" if icv else '—',
            'TRIR': f"{trir}" if trir else '—',
            'MC (weeks)': f"{mc}" if mc else '—',
        })

    st.dataframe(table_data, use_container_width=True, hide_index=True)

    # ── Evaluation methodology summary ──
    with st.expander("📊 Evaluation Methodology (RFP Section 6)"):
        st.markdown(f'''
        | Criterion | Weight | Max Score |
        |---|---|---|
        | **Technical** (T1-T4) | 40% | 40 |
        | **Commercial** (Pricing) | 30% | 30 |
        | **HSE** (Safety & Certifications) | 15% | 15 |
        | **ICV** (In-Country Value) | 15% | 15 |
        | **Total** | **100%** | **100** |
        ''')
        st.markdown(f'''
        **Evaluation Formula:**
        - Commercial: C = 30 × (Lowest Price / Supplier Price)
        - ICV: ICV = 15 × min(ICV%, 60) / 60
        - Total = Technical + Commercial + HSE + ICV
        ''')