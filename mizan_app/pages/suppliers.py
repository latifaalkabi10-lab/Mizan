"""
Suppliers page — Comparison table, detail view, and "WHY THIS SUPPLIER?" experience.
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import (
    get_all_suppliers, get_supplier_detail, search_supplier_by_name
)
from evidence_agent import search


def show():
    st.markdown('<h1 style="color:#002B5C;font-size:24px;">🏭 Supplier Comparison</h1>', unsafe_allow_html=True)

    results = st.session_state.get('evaluation_results')
    suppliers = get_all_suppliers()

    if not results or not st.session_state.get('evaluation_complete'):
        st.info("⚠️ No evaluation data available. Please run the evaluation first from the **Bid Evaluations** page.")
        # Still show basic supplier list
        st.markdown('<h3 style="font-size:16px;color:#002B5C;margin-top:16px;">Registered Suppliers</h3>', unsafe_allow_html=True)
        table_data = []
        for s in suppliers:
            table_data.append({
                'Bid Ref': s.get('bid_ref', ''),
                'Supplier': s.get('company', ''),
                'Capacity': f"{s.get('capacity_m3_per_day', '?'):,} m³/d" if s.get('capacity_m3_per_day') else '—',
                'Price': f"{s.get('price_currency', 'AED')} {s.get('price_total', 0):,}" if s.get('price_total') else '—',
                'ICV': f"{s.get('icv_score_pct', '—')}%",
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)
        return

    ranking = results.get('recommendation', {}).get('supplier_ranking', [])

    # ── Supplier Comparison Table ──
    st.markdown('<h3 style="font-size:16px;color:#002B5C;margin-bottom:12px;">Full Evaluation Comparison</h3>', unsafe_allow_html=True)

    table_data = []
    for i, s in enumerate(ranking, 1):
        risk_count = s.get('risk_count', 0)
        high_risk = s.get('high_risk_count', 0)
        if high_risk > 0:
            risk_badge = '🚨'
        elif risk_count > 0:
            risk_badge = '⚠️'
        else:
            risk_badge = '✅'

        table_data.append({
            'Rank': i,
            'Supplier': s['company'],
            'Compliance': '✅' if s.get('high_risk_count', 0) == 0 else '⚠️',
            'Technical /40': s.get('technical', 0),
            'Commercial /30': s.get('commercial', 0),
            'HSE /15': s.get('hse', 0),
            'ICV /15': s.get('icv', 0),
            'Total /100': s.get('total', 0),
            'Risk': risk_badge,
        })

    st.dataframe(table_data, use_container_width=True, hide_index=True)

    # ── Highlight Top Supplier ──
    if ranking:
        top = ranking[0]
        st.markdown('---')
        st.markdown(f'''
        <div style="background:#F0F8F0;border:2px solid #2ECC71;border-radius:12px;padding:20px;margin:16px 0;">
            <div style="font-size:12px;color:#27AE60;text-transform:uppercase;letter-spacing:2px;font-weight:600;">🏆 MIZAN RECOMMENDATION</div>
            <div style="font-size:24px;font-weight:700;color:#002B5C;margin-top:8px;">{top['company']}</div>
            <div style="font-size:36px;font-weight:700;color:#002B5C;margin:8px 0;">{top['total']}<span style="font-size:18px;color:#8A9BAB;">/100</span></div>
            <div style="color:#5A6B7A;font-size:14px;">Highest-ranked supplier based on evaluation methodology</div>
        </div>
        ''', unsafe_allow_html=True)

        # ── WHY THIS SUPPLIER? ──
        with st.expander("💡 WHY THIS SUPPLIER? — Evidence-backed reasoning", expanded=True):
            sup = top

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("#### ✅ Technical Strengths")
                for s in sup.get('tech_strengths', []):
                    st.markdown(f"- {s}")
                if not sup.get('tech_strengths'):
                    st.markdown("*No specific strengths identified*")

                st.markdown("#### 💰 Commercial Position")
                price = sup.get('price')
                currency = sup.get('currency', 'AED')
                comm = sup.get('commercial', 0)
                st.markdown(f"- Price: {currency} {price:,}" if price else "- Price: N/A")
                st.markdown(f"- Commercial Score: {comm}/30")
                st.markdown(f"- {sup.get('commercial_notes', '')}")

            with col2:
                st.markdown("#### 🦺 HSE")
                hse = sup.get('hse', 0)
                st.markdown(f"- HSE Score: {hse}/15")
                hse_risks = sup.get('hse_risks', [])
                for hr in hse_risks[:2]:
                    st.markdown(f"- ⚠️ {hr}")

                st.markdown("#### 🇦🇪 ICV Contribution")
                icv = sup.get('icv', 0)
                icv_pct = sup.get('icv_pct')
                if icv_pct:
                    st.markdown(f"- ICV Score: {icv}/15")
                    st.markdown(f"- Certified ICV: {icv_pct}%")
                    st.markdown(f"- Capped at 60%: {min(float(icv_pct), 60)}%")
                else:
                    st.markdown(f"- ICV Score: {icv}/15")
                    st.markdown("- ICV certificate not in dataset")

            st.markdown("---")
            st.markdown("#### 📋 Evidence Trail")
            ev_cols = st.columns(4)
            criteria = [
                ("Technical", sup.get('technical', 0), "/40"),
                ("Commercial", sup.get('commercial', 0), "/30"),
                ("HSE", sup.get('hse', 0), "/15"),
                ("ICV", sup.get('icv', 0), "/15"),
            ]
            for i, (label, score, mx) in enumerate(criteria):
                with ev_cols[i]:
                    pct = (score / float(mx.replace('/', ''))) * 100 if mx else 0
                    st.markdown(f'''
                    <div class="score-card" style="text-align:center;">
                        <div class="score-label">{label}</div>
                        <div class="score-value" style="font-size:24px;">{score}<span class="score-max">{mx}</span></div>
                        <div class="score-bar"><div class="score-bar-fill" style="width:{pct}%;"></div></div>
                    </div>
                    ''', unsafe_allow_html=True)

    # ── Trade-Off Analysis ──
    trade_offs = results.get('recommendation', {}).get('trade_off_analysis', [])
    if trade_offs:
        st.markdown("#### ⚖️ Trade-Off Analysis")
        for to in trade_offs:
            st.info(to)

    # ── ICV Visual Experience ──
    st.markdown('---')
    st.markdown('<h2 style="font-size:18px;color:#002B5C;">🇦🇪 MIZAN In-Country Value</h2>', unsafe_allow_html=True)

    icv_data = []
    for s in ranking:
        icv_pct = s.get('icv_pct')
        icv_score = s.get('icv', 0)
        icv_data.append({
            'Supplier': s['company'],
            'ICV Score /15': icv_score,
            'Certified ICV %': f"{icv_pct}%" if icv_pct else 'Not Available',
            'ICV Status': '✅ Verified' if icv_pct else '❌ Not Found',
        })
    st.dataframe(icv_data, use_container_width=True, hide_index=True)

    # ── Supplier Detail Selector ──
    st.markdown('---')
    st.markdown('<h2 style="font-size:18px;color:#002B5C;">🔍 Supplier Detail View</h2>', unsafe_allow_html=True)

    supplier_names = [s['company'] for s in ranking]
    selected_name = st.selectbox("Select a supplier to inspect:", supplier_names)

    if selected_name:
        sup_detail = search_supplier_by_name(selected_name)
        sup_scores = next((s for s in ranking if s['company'] == selected_name), None)

        if sup_scores:
            col1, col2, col3, col4, col5 = st.columns(5)
            cols_data = [
                ("Technical", sup_scores.get('technical', 0), "/40"),
                ("Commercial", sup_scores.get('commercial', 0), "/30"),
                ("HSE", sup_scores.get('hse', 0), "/15"),
                ("ICV", sup_scores.get('icv', 0), "/15"),
                ("Total", sup_scores.get('total', 0), "/100"),
            ]
            for i, (label, score, mx) in enumerate(cols_data):
                with [col1, col2, col3, col4, col5][i]:
                    try:
                        max_val = float(mx.replace('/', ''))
                    except ValueError:
                        max_val = 100
                    pct = (score / max_val) * 100 if max_val else 0
                    st.markdown(f'''
                    <div class="score-card" style="text-align:center;padding:12px;">
                        <div class="score-label">{label}</div>
                        <div class="score-value" style="font-size:20px;">{score}<span class="score-max">{mx}</span></div>
                        <div class="score-bar"><div class="score-bar-fill" style="width:{pct}%;"></div></div>
                    </div>
                    ''', unsafe_allow_html=True)

            # Evidence panel
            with st.expander("📋 Evidence Panel"):
                detail = get_supplier_detail(sup_detail.get('bid_ref', '')) if sup_detail else None
                if detail and detail.get('facts'):
                    facts = detail['facts']
                    st.json({
                        'Capacity (m³/d)': facts.get('capacity_m3_per_day'),
                        'OiW (mg/L)': facts.get('outlet_oiw_mg_per_l'),
                        'Price': f"{facts.get('price_currency', 'AED')} {facts.get('price_total', 0):,}",
                        'MC (weeks)': facts.get('mc_weeks_from_loa'),
                        'Warranty (months)': facts.get('warranty_months'),
                        'TRIR': facts.get('trir_3yr_avg'),
                        'ICV %': facts.get('icv_score_pct'),
                        'GCC References': facts.get('gcc_references_count'),
                        'Experience (years)': facts.get('experience_years'),
                        'ISO 14001': facts.get('has_iso_14001'),
                        'ISO 45001': facts.get('has_iso_45001'),
                        'Scheme': facts.get('scheme'),
                    })

                    elig = detail.get('eligibility')
                    if elig and elig.get('issues'):
                        st.warning("#### ⚠️ Compliance Issues")
                        for issue in elig['issues']:
                            st.markdown(f"- {issue}")