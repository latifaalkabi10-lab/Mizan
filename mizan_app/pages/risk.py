"""
Risk & Human Review page — Show identified risks, escalation cases, and human review workflow.
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import get_all_suppliers


def show():
    st.markdown('<h1 style="color:#002B5C;font-size:24px;">⚠ Risk & Human Review</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#5A6B7A;margin-bottom:20px;">MIZAN identifies procurement risks and determines when human review is required.</p>', unsafe_allow_html=True)

    results = st.session_state.get('evaluation_results')

    if not results or not st.session_state.get('evaluation_complete'):
        st.info("⚠️ No evaluation data available. Please run the evaluation first from the **Bid Evaluations** page.")
        return

    risk_result = results.get('risk', {})
    findings = risk_result.get('findings', [])
    risk_level = risk_result.get('risk_level', 'LOW')
    human_review = risk_result.get('human_review_required', False)

    # ── Risk Level Banner ──
    if risk_level == 'HIGH' or human_review:
        st.error('''
        ### 🚨 HUMAN REVIEW REQUIRED
        AI recommendation paused. The following risks require manual procurement engineer review.
        ''')
    elif risk_level == 'MEDIUM':
        st.warning('''
        ### ⚠️ Medium Risk Level
        Some risks identified but within assessable range. Review recommended.
        ''')
    else:
        st.success('''
        ### ✅ Low Risk
        No material risks identified. Evaluation proceeding normally.
        ''')

    # ── Summary Stats ──
    col1, col2, col3, col4 = st.columns(4)
    total_risks = risk_result.get('total_risks_found', 0)
    high_count = sum(1 for f in findings for r in f.get('risks', []) if r.get('severity') == 'HIGH')
    med_count = sum(1 for f in findings for r in f.get('risks', []) if r.get('severity') == 'MEDIUM')

    with col1:
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">⚠️</div>
            <div class="kpi-value">{total_risks}</div>
            <div class="kpi-label">Total Risks</div>
        </div>
        ''', unsafe_allow_html=True)
    with col2:
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">🔴</div>
            <div class="kpi-value">{high_count}</div>
            <div class="kpi-label">High Severity</div>
        </div>
        ''', unsafe_allow_html=True)
    with col3:
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">🟡</div>
            <div class="kpi-value">{med_count}</div>
            <div class="kpi-label">Medium Severity</div>
        </div>
        ''', unsafe_allow_html=True)
    with col4:
        affected = len([f for f in findings if f.get('risk_count', 0) > 0])
        st.markdown(f'''
        <div class="kpi-card">
            <div class="kpi-icon">🏭</div>
            <div class="kpi-value">{affected}</div>
            <div class="kpi-label">Affected Suppliers</div>
        </div>
        ''', unsafe_allow_html=True)

    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

    # ── Findings Table ──
    for f in findings:
        risks = f.get('risks', [])
        if not risks:
            continue

        # Risk level for the card
        has_high = any(r['severity'] == 'HIGH' for r in risks)
        has_med = any(r['severity'] == 'MEDIUM' for r in risks)

        if has_high:
            card_class = 'high'
            card_icon = '🚨'
        elif has_med:
            card_class = 'medium'
            card_icon = '⚠️'
        else:
            card_class = 'low'
            card_icon = '✓'

        st.markdown(f'''
        <div class="risk-card {card_class}">
            <div class="risk-title">{card_icon} {f['company']} ({f['bid_ref']}) — {f['risk_count']} risk(s)</div>
        ''', unsafe_allow_html=True)

        for r in risks:
            severity_icon = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(r['severity'], '⚪')
            st.markdown(f'''
            <div style="display:flex;gap:8px;padding:4px 0;">
                <span style="min-width:60px;font-size:12px;font-weight:600;">{severity_icon} {r['severity']}</span>
                <span style="font-size:13px;color:#5A6B7A;"><strong>{r['category']}:</strong> {r['issue']}</span>
            </div>
            ''', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

    # ── Human Escalation Details ──
    escalation = risk_result.get('escalation')
    if escalation:
        st.markdown('---')
        st.markdown('<h2 style="font-size:18px;color:#002B5C;">🚨 Escalation Record</h2>', unsafe_allow_html=True)

        st.markdown(f'''
        <div style="background:#FFF5F5;border:1px solid #E74C3C;border-radius:10px;padding:20px;">
            <div style="font-size:16px;font-weight:600;color:#E74C3C;">HUMAN REVIEW REQUIRED</div>
            <div style="margin-top:12px;">
                <p><strong>Trigger:</strong> {escalation.get('case', {}).get('trigger', 'N/A')}</p>
                <p><strong>Affected Suppliers:</strong> {', '.join(escalation.get('case', {}).get('affected_suppliers', []))}</p>
                <p><strong>Timestamp:</strong> {escalation.get('timestamp', 'N/A')}</p>
                <p><strong>Recommended Action:</strong> {escalation.get('case', {}).get('recommended_action', 'Manual review')}</p>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    # ── Human Review Actions ──
    st.markdown('---')
    st.markdown('<h2 style="font-size:18px;color:#002B5C;">👁️ Human Review Actions</h2>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📋 REVIEW EVIDENCE", use_container_width=True):
            st.session_state.page = "suppliers"
            st.rerun()
    with col2:
        if st.button("👤 ASSIGN REVIEWER", use_container_width=True):
            st.info("Reviewer assignment: Procurement Engineer (auto-assigned)")
    with col3:
        if st.button("▶️ CONTINUE AFTER REVIEW", use_container_width=True):
            if human_review:
                st.warning("Cannot continue — human review still required. Clear risks first.")
            else:
                st.success("Proceeding with recommendation.")

    # ── Low Risk Suppliers ──
    safe_suppliers = [f for f in findings if f.get('risk_count', 0) == 0]
    if safe_suppliers:
        with st.expander("✅ Low Risk Suppliers (No Issues)"):
            for s in safe_suppliers:
                st.markdown(f"- **{s['company']}** — No risks identified")