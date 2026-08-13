"""
Bid Evaluation page — Live agent pipeline workspace with real execution.
"""

import streamlit as st
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import (
    run_full_pipeline, get_activity_log, _get_rfp_info
)
from evidence_agent import search


# Agent definitions with icons and colors
AGENTS = [
    {"id": "evidence", "icon": "🔎", "name": "Evidence & Retrieval", "color": "#3498DB"},
    {"id": "compliance", "icon": "✓", "name": "Compliance & Screening", "color": "#2ECC71"},
    {"id": "technical", "icon": "🔧", "name": "Technical Evaluation", "color": "#9B59B6"},
    {"id": "commercial", "icon": "💰", "name": "Commercial Evaluation", "color": "#F39C12"},
    {"id": "hse", "icon": "🦺", "name": "HSE Evaluation", "color": "#E67E22"},
    {"id": "icv", "icon": "🇦🇪", "name": "ICV Evaluation", "color": "#1ABC9C"},
    {"id": "risk", "icon": "⚠", "name": "Risk & Escalation", "color": "#E74C3C"},
    {"id": "recommendation", "icon": "📝", "name": "Recommendation & Report", "color": "#002B5C"},
]


def show():
    rfp = _get_rfp_info()
    suppliers = list(search._bid_facts.items())
    bids_count = len(suppliers)

    st.markdown('<h1 style="color:#002B5C;font-size:24px;">MIZAN Evaluation</h1>', unsafe_allow_html=True)
    st.markdown(f'''
    <div style="display:flex;gap:16px;margin-bottom:20px;">
        <div style="background:white;border:1px solid #E8EDF2;border-radius:8px;padding:10px 16px;">
            <span style="font-weight:600;color:#002B5C;">{rfp.get("tender_ref", "")}</span>
        </div>
        <div style="background:white;border:1px solid #E8EDF2;border-radius:8px;padding:10px 16px;">
            <span style="color:#8A9BAB;">📑</span> <span style="font-weight:600;">{bids_count}</span> Bids
        </div>
        <div style="background:white;border:1px solid #E8EDF2;border-radius:8px;padding:10px 16px;">
            <span style="color:#8A9BAB;">📄</span> <span style="font-weight:600;">{bids_count + 1}</span> Documents
        </div>
    </div>
    ''', unsafe_allow_html=True)

    # ── File Upload Section (general-purpose) ──
    with st.expander("📂 Upload RFP & Bid Documents (General Purpose Mode)", expanded=False):
        st.markdown('<p style="color:#5A6B7A;font-size:13px;">Upload your own RFP and bid documents for evaluation. When no files are uploaded, the system uses the built-in ADNOC challenge dataset.</p>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            uploaded_rfp = st.file_uploader("Upload RFP Document (PDF)", type=['pdf'], key="rfp_upload")
        with col2:
            uploaded_bids = st.file_uploader("Upload Bid Documents (PDF)", type=['pdf'], accept_multiple_files=True, key="bids_upload")

        if uploaded_rfp:
            st.success(f"✅ RFP uploaded: {uploaded_rfp.name}")
        if uploaded_bids:
            st.success(f"✅ {len(uploaded_bids)} bid documents uploaded")

        st.markdown('<p style="color:#8A9BAB;font-size:12px;margin-top:8px;">💡 For the demo, the system uses the pre-loaded ADNOC challenge dataset (12 supplier bids for Produced Water Treatment Package).</p>', unsafe_allow_html=True)

    # ── Start / Re-run Evaluation ──
    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button("🚀 RUN EVALUATION", type="primary", use_container_width=True)
    with col2:
        if st.session_state.get('evaluation_complete'):
            st.markdown('<span class="badge badge-pass" style="font-size:14px;padding:6px 16px;">✅ Evaluation Complete</span>', unsafe_allow_html=True)

    # ── Agent Pipeline ──
    st.markdown('<h2 style="font-size:18px;font-weight:600;color:#002B5C;margin-top:20px;">Agent Pipeline</h2>', unsafe_allow_html=True)

    pipeline_container = st.container()

    # Placeholder for pipeline results
    results_placeholder = st.container()

    if run_clicked or st.session_state.get('run_evaluation'):
        st.session_state.run_evaluation = False

        with st.spinner("Running MIZAN multi-agent evaluation pipeline..."):
            results = run_full_pipeline()

        # Store results in session state
        st.session_state.evaluation_results = results
        st.session_state.evaluation_complete = True

        # Check escalation
        risk_result = results.get('risk', {})
        st.session_state.human_review_required = risk_result.get('human_review_required', False)

        st.rerun()

    # ── Display Pipeline Status ──
    if st.session_state.get('evaluation_complete') and st.session_state.get('evaluation_results'):
        results = st.session_state.evaluation_results

        with pipeline_container:
            for agent in AGENTS:
                aid = agent['id']
                result = results.get(aid, {})
                status = result.get('_status', 'pending')

                if status == 'complete':
                    elapsed = result.get('_elapsed', 0)
                    cls = 'complete'
                    status_text = f"✓ Complete ({elapsed:.1f}s)"
                elif status == 'error':
                    cls = 'error'
                    status_text = "✗ Error"
                else:
                    cls = 'waiting'
                    status_text = "⏳ Waiting"

                st.markdown(f'''
                <div class="pipeline-node {cls}">
                    <div class="node-icon">{agent['icon']}</div>
                    <div class="node-name">{agent['name']}</div>
                    <div class="node-status">{status_text}</div>
                </div>
                ''', unsafe_allow_html=True)

                if aid != 'recommendation':
                    st.markdown('<div class="pipeline-arrow">↓</div>', unsafe_allow_html=True)

        # ── Results Summary ──
        with results_placeholder:
            st.markdown('<h2 style="font-size:18px;font-weight:600;color:#002B5C;margin-top:20px;">Evaluation Results</h2>', unsafe_allow_html=True)

            rec = results.get('recommendation', {})
            ranking = rec.get('supplier_ranking', [])

            if ranking:
                # Score comparison table
                st.markdown('<h3 style="font-size:15px;color:#002B5C;margin-bottom:12px;">Supplier Ranking</h3>', unsafe_allow_html=True)

                table_data = []
                for i, s in enumerate(ranking, 1):
                    risk_count = s.get('risk_count', 0)
                    risk_badge = '🟢' if risk_count == 0 else ('🟡' if risk_count <= 2 else '🔴')
                    table_data.append({
                        'Rank': i,
                        'Supplier': s['company'],
                        'Technical /40': s.get('technical', 0),
                        'Commercial /30': s.get('commercial', 0),
                        'HSE /15': s.get('hse', 0),
                        'ICV /15': s.get('icv', 0),
                        'Total /100': s.get('total', 0),
                        'Risk': f"{risk_badge} {risk_count}",
                    })

                # Highlight the top row
                st.dataframe(table_data, use_container_width=True, hide_index=True)

                # Recommendation
                rec_info = rec.get('recommendation', {})
                rec_status = rec_info.get('status', 'INSUFFICIENT DATA')
                recommended = rec_info.get('recommended_supplier')

                if rec_status == 'HUMAN REVIEW REQUIRED':
                    st.error("🚨 **HUMAN REVIEW REQUIRED** — AI recommendation paused. Risk issues identified.")
                elif recommended:
                    score = rec_info.get('score', 0)
                    st.success(f'''
                    ### 🏆 MIZAN RECOMMENDATION
                    **Recommended Supplier:** {recommended}
                    **Overall Score:** {score}/100
                    **Status:** {rec_status}
                    ''')
                else:
                    st.warning("⚠️ Insufficient data to generate a recommendation.")

                # Trade-off analysis
                trade_offs = rec.get('trade_off_analysis', [])
                if trade_offs:
                    with st.expander("📊 Trade-Off Analysis"):
                        for to in trade_offs:
                            st.markdown(f'- {to}')

    else:
        # Show pipeline in waiting state
        with pipeline_container:
            for i, agent in enumerate(AGENTS):
                aid = agent['id']
                cls = 'waiting'
                status_text = "⏳ Waiting"

                st.markdown(f'''
                <div class="pipeline-node {cls}">
                    <div class="node-icon">{agent['icon']}</div>
                    <div class="node-name">{agent['name']}</div>
                    <div class="node-status">{status_text}</div>
                </div>
                ''', unsafe_allow_html=True)

                if aid != 'recommendation':
                    st.markdown('<div class="pipeline-arrow">↓</div>', unsafe_allow_html=True)

        st.info("👆 Click **RUN EVALUATION** to start the multi-agent pipeline. Each agent executes in sequence, passing structured data downstream.")

    # Show evidence explorer
    if st.session_state.get('evaluation_complete'):
        with st.expander("🔎 Evidence Explorer", expanded=False):
            evidence = results.get('evidence', {})
            evidence_items = evidence.get('evidence_items', [])
            for item in evidence_items[:10]:
                fact = item.get('FACT', '')
                source = item.get('SOURCE', '')
                location = item.get('LOCATION', '')
                conf = item.get('CONFIDENCE', '')
                conf_class = {
                    'Verified': 'confidence-verified',
                    'Partially Verified': 'confidence-partial',
                    'Not Found': 'confidence-not-found',
                }.get(conf, '')

                st.markdown(f'''
                <div class="evidence-item">
                    <div class="fact">{fact}</div>
                    <div class="source">📄 {source} | 📍 {location}</div>
                    <span class="confidence {conf_class}">{conf}</span>
                </div>
                ''', unsafe_allow_html=True)

            if not evidence_items:
                st.markdown('<div style="color:#8A9BAB;">No evidence items retrieved.</div>', unsafe_allow_html=True)