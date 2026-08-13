"""
Reports page — Professional procurement report with all evaluation sections.
"""

import streamlit as st
import sys, os, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import get_all_suppliers, _get_rfp_info
from evidence_agent import search


def show():
    st.markdown('<h1 style="color:#002B5C;font-size:24px;">📄 Procurement Report</h1>', unsafe_allow_html=True)

    results = st.session_state.get('evaluation_results')

    if not results or not st.session_state.get('evaluation_complete'):
        st.info("⚠️ No evaluation data available. Please run the evaluation first from the **Bid Evaluations** page.")
        return

    rfp = _get_rfp_info()
    ranking = results.get('recommendation', {}).get('supplier_ranking', [])
    rec = results.get('recommendation', {}).get('recommendation', {})
    trade_offs = results.get('recommendation', {}).get('trade_off_analysis', [])
    risk_result = results.get('risk', {})
    human_review = risk_result.get('human_review_required', False)

    if st.button("📄 GENERATE REPORT", type="primary", use_container_width=True):
        st.session_state.show_report = True

    if st.session_state.get('show_report'):
        # ── Report Content ──
        st.markdown('---')
        st.markdown(f'''
        <div class="report-section">
            <div style="text-align:center;margin-bottom:20px;">
                <div style="font-size:10px;color:#8A9BAB;letter-spacing:2px;">ADNOC</div>
                <div style="font-size:20px;font-weight:700;color:#002B5C;letter-spacing:4px;margin:4px 0;">MIZAN</div>
                <div style="font-size:10px;color:#8A9BAB;letter-spacing:2px;">PROCUREMENT INTELLIGENCE</div>
            </div>
            <h3>Supplier Bid Evaluation Report</h3>
            <table style="width:100%;font-size:13px;">
                <tr><td style="font-weight:600;width:150px;">Tender:</td><td>{rfp.get("tender_ref", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Title:</td><td>{rfp.get("title", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Location:</td><td>{rfp.get("location", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Report Date:</td><td>{datetime.now().strftime("%d %B %Y")}</td></tr>
                <tr><td style="font-weight:600;">Status:</td><td>{'HUMAN REVIEW REQUIRED' if human_review else 'AI RECOMMENDATION'}</td></tr>
            </table>
        </div>
        ''', unsafe_allow_html=True)

        # 1. Executive Summary
        st.markdown(f'''
        <div class="report-section">
            <h3>1. Executive Summary</h3>
            <p style="font-size:13px;color:#5A6B7A;">
                This report presents the evaluation of {len(ranking)} supplier bids received for {rfp.get("tender_ref", "")} —
                {rfp.get("title", "")}. The evaluation was conducted using MIZAN's multi-agent AI system, scoring
                suppliers across Technical (40%), Commercial (30%), HSE (15%), and ICV (15%) criteria.
            </p>
            <p style="font-size:13px;color:#5A6B7A;">
                <strong>Final Status:</strong> {rec.get("status", "INSUFFICIENT DATA")}
            </p>
            {f'<p style="font-size:13px;color:#E74C3C;"><strong>Recommended Supplier:</strong> {rec.get("recommended_supplier", "N/A")} (Score: {rec.get("score", 0)}/100)</p>' if rec.get("recommended_supplier") else ''}
            {f'<p style="font-size:13px;color:#E74C3C;"><strong>HUMAN REVIEW REQUIRED</strong> — Critical risks identified requiring procurement engineer review.</p>' if human_review else ''}
        </div>
        ''', unsafe_allow_html=True)

        # 2. Tender Information
        st.markdown(f'''
        <div class="report-section">
            <h3>2. Tender Information</h3>
            <table style="width:100%;font-size:13px;">
                <tr><td style="font-weight:600;width:200px;">Reference</td><td>{rfp.get("tender_ref", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Issue Date</td><td>{rfp.get("issue_date", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Bid Deadline</td><td>{rfp.get("bid_deadline", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Contract Type</td><td>{rfp.get("contract_type", "N/A")}</td></tr>
                <tr><td style="font-weight:600;">Min Capacity</td><td>{rfp.get("min_capacity_m3_per_day", "N/A")} m³/d</td></tr>
                <tr><td style="font-weight:600;">Bids Received</td><td>{len(ranking)}</td></tr>
            </table>
        </div>
        ''', unsafe_allow_html=True)

        # 3. Supplier Overview
        st.markdown(f'''
        <div class="report-section">
            <h3>3. Supplier Overview</h3>
            <table style="width:100%;font-size:13px;border-collapse:collapse;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:8px;text-align:left;font-weight:600;">Supplier</th>
                    <th style="padding:8px;text-align:left;font-weight:600;">Bid Ref</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">Capacity (m³/d)</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">Price (AED)</th>
                </tr>
                {"".join(f'<tr><td style="padding:6px 8px;">{s["company"]}</td><td style="padding:6px 8px;">{s.get("bid_ref", "")}</td><td style="padding:6px 8px;text-align:right;">{s.get("capacity_m3_per_day", "—"):,}</td><td style="padding:6px 8px;text-align:right;">{s.get("price_total", 0):,}</td></tr>' for s in get_all_suppliers())}
            </table>
        </div>
        ''', unsafe_allow_html=True)

        # 4. Supplier Scoring Table
        st.markdown(f'''
        <div class="report-section">
            <h3>4. Evaluation Scores</h3>
            <table style="width:100%;font-size:13px;border-collapse:collapse;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:8px;text-align:left;font-weight:600;">Supplier</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">Tech /40</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">Comm /30</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">HSE /15</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">ICV /15</th>
                    <th style="padding:8px;text-align:right;font-weight:600;">Total /100</th>
                    <th style="padding:8px;text-align:center;font-weight:600;">Risks</th>
                </tr>
                {"".join(f'<tr style="{"background:#F0FFF4;" if i == 0 else ""}"><td style="padding:6px 8px;{("font-weight:700;" if i == 0 else "")}">{s["company"]}</td><td style="padding:6px 8px;text-align:right;">{s.get("technical", 0)}</td><td style="padding:6px 8px;text-align:right;">{s.get("commercial", 0)}</td><td style="padding:6px 8px;text-align:right;">{s.get("hse", 0)}</td><td style="padding:6px 8px;text-align:right;">{s.get("icv", 0)}</td><td style="padding:6px 8px;text-align:right;font-weight:700;">{s.get("total", 0)}</td><td style="padding:6px 8px;text-align:center;">{"⚠️" if s.get("risk_count", 0) > 0 else "✅"}</td></tr>' for i, s in enumerate(ranking))}
            </table>
        </div>
        ''', unsafe_allow_html=True)

        # 5. AI Recommendation
        st.markdown(f'''
        <div class="report-section">
            <h3>5. AI Recommendation</h3>
            {f'<p style="font-size:16px;font-weight:700;color:#002B5C;">Recommended Supplier: {rec.get("recommended_supplier", "N/A")}</p>' if rec.get("recommended_supplier") else ''}
            {f'<p style="font-size:14px;color:#5A6B7A;">Overall Score: {rec.get("score", 0)}/100</p>' if rec.get("score") else ''}
            <p style="font-size:13px;color:#5A6B7A;">
                {rec.get("message", "Insufficient data for recommendation.")}<br>
                <em>AI Recommendation — does not constitute an official contract award. Final decision rests with the Procurement Engineer.</em>
            </p>
            {'<p style="font-size:13px;color:#E74C3C;font-weight:600;">⚠ Human review required — recommendation is paused pending review.</p>' if human_review else ''}
        </div>
        ''', unsafe_allow_html=True)

        # 6. Trade-Off Analysis
        if trade_offs:
            st.markdown(f'''
            <div class="report-section">
                <h3>6. Trade-Off Analysis</h3>
                {"".join(f'<p style="font-size:13px;color:#5A6B7A;">{to}</p>' for to in trade_offs)}
            </div>
            ''', unsafe_allow_html=True)

        # 7. Risk Analysis
        findings = risk_result.get('findings', [])
        risk_level = risk_result.get('risk_level', 'LOW')
        st.markdown(f'''
        <div class="report-section">
            <h3>7. Risk Analysis</h3>
            <p style="font-size:13px;color:#5A6B7A;"><strong>Overall Risk Level:</strong> {risk_level}</p>
            <p style="font-size:13px;color:#5A6B7A;"><strong>Total Risks Identified:</strong> {risk_result.get("total_risks_found", 0)}</p>
            <table style="width:100%;font-size:13px;border-collapse:collapse;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:8px;text-align:left;">Supplier</th>
                    <th style="padding:8px;text-align:right;">Risk Count</th>
                    <th style="padding:8px;text-align:right;">High</th>
                    <th style="padding:8px;text-align:right;">Medium</th>
                </tr>
                {"".join(f'<tr><td style="padding:6px 8px;">{f.get("company", "")}</td><td style="padding:6px 8px;text-align:right;">{f.get("risk_count", 0)}</td><td style="padding:6px 8px;text-align:right;color:{"#E74C3C" if f.get("high_risk_count", 0) > 0 else "#8A9BAB"};">{f.get("high_risk_count", 0)}</td><td style="padding:6px 8px;text-align:right;">{f.get("medium_risk_count", 0)}</td></tr>' for f in findings)}
            </table>
        </div>
        ''', unsafe_allow_html=True)

        # 8. Evidence Trail
        evidence_items = results.get('evidence', {}).get('evidence_items', [])
        with st.expander("📋 Evidence Trail (Click to expand)"):
            for item in evidence_items[:15]:
                fact = item.get('FACT', '')
                source = item.get('SOURCE', '')
                location = item.get('LOCATION', '')
                conf = item.get('CONFIDENCE', '')

                st.markdown(f'''
                <div class="evidence-item">
                    <div class="fact">{fact}</div>
                    <div class="source">📄 {source} | 📍 {location}</div>
                    <span class="confidence {'confidence-verified' if conf == 'Verified' else 'confidence-partial' if conf == 'Partially Verified' else 'confidence-not-found'}">{conf}</span>
                </div>
                ''', unsafe_allow_html=True)

        # 9. Human Decision
        st.markdown(f'''
        <div class="report-section">
            <h3>9. Human Decision</h3>
            <p style="font-size:13px;color:#5A6B7A;">
                This report is an <strong>AI Recommendation</strong> only. The final procurement decision
                must be made by the authorised Procurement Engineer.
            </p>
            <div style="border:2px solid #E8EDF2;border-radius:8px;padding:20px;margin-top:12px;">
                <p style="font-size:14px;font-weight:600;color:#002B5C;">Procurement Engineer Review</p>
                <p style="font-size:13px;color:#8A9BAB;">⬜ Approve Recommendation</p>
                <p style="font-size:13px;color:#8A9BAB;">⬜ Request Clarification</p>
                <p style="font-size:13px;color:#8A9BAB;">⬜ Reject Recommendation</p>
                <p style="font-size:12px;color:#8A9BAB;margin-top:12px;">_________________________</p>
                <p style="font-size:12px;color:#8A9BAB;">Procurement Engineer Signature & Date</p>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        # Footer
        st.markdown(f'''
        <div style="text-align:center;font-size:11px;color:#8A9BAB;padding:20px 0;">
            MIZAN Procurement Intelligence — {datetime.now().strftime("%Y-%m-%d %H:%M")}<br>
            "Balance every bid. Defend every decision."
        </div>
        ''', unsafe_allow_html=True)

    else:
        st.info("👆 Click **GENERATE REPORT** to produce the full procurement report.")