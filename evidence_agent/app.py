"""
app.py — Streamlit interactive UI for the Procurement Evidence & Retrieval Agent.

Run with:
    python -m streamlit run evidence_agent/app.py
"""

import streamlit as st
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from evidence_agent import evidence as ev
from evidence_agent import package as pkg
from evidence_agent import search

st.set_page_config(
    page_title="Procurement Evidence & Retrieval Agent — ADNOC-LCIG/RFP/2026-0412",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 Procurement Evidence & Retrieval Agent")
st.markdown(
    "**Tender:** ADNOC-LCIG/RFP/2026-0412 — Produced Water Treatment Package, Bu Hasnah CPF-2"
)
st.markdown(
    "**Role:** Retrieve grounded evidence from the challenge dataset. "
    "I do **not** recommend a supplier — I pass the evidence to the Bid Evaluation Agent."
)
st.markdown(
    "**Dataset:** RFP (8 pages) + Bid Submission Tracker (12 bidders) + 12 bid documents 📄"
)

# Query input
col1, col2 = st.columns([3, 1])
with col1:
    query = st.text_input(
        "Enter your evidence retrieval query",
        placeholder="e.g., What is the price of Hanseong?",
    )
with col2:
    save_pkg = st.checkbox("Save downstream package", value=False)

# Example queries
with st.expander("📋 Example queries to try"):
    st.markdown("""
    **Single-supplier queries:**
    - *What is the price of Hanseong?*
    - *Show me Al Manara's ICV score*
    - *What is the capacity of V10 (Bin Sultan)?*
    - *Tell me about Qasr Al Bahr's technical compliance*
    - *What is Petrotech's arithmetic issue?*

    **Cross-cutting queries:**
    - *List all bids with their prices and capacities*
    - *Which bidders have TRIR below 0.3?*
    - *Compare all bids by ICV score*
    - *Show the cheapest bidder*

    **RFP queries:**
    - *What are the mandatory documents D1-D9?*
    - *What is the evaluation methodology?*
    - *What is the minimum capacity requirement?*
    """)

# Search
if query:
    query = query.strip()
    with st.spinner("Retrieving evidence from the dataset..."):
        evidence = ev.build_evidence(query)
        if save_pkg:
            path, package = pkg.save_package(query)

    # Results
    st.subheader("📋 Evidence Results")

    # Display in tabs
    tab1, tab2 = st.tabs(["Evidence Cards", "Structured Package"])

    with tab1:
        if not evidence or (len(evidence) == 1 and evidence[0].get('CONFIDENCE') == 'Not Found'):
            st.warning("Not found in the provided challenge dataset. I cannot verify this from the available evidence.")
        else:
            for i, item in enumerate(evidence):
                with st.container():
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.markdown(f"**FACT:** {item.get('FACT', '')}")
                    with col2:
                        conf = item.get('CONFIDENCE', '')
                        color = "🟢" if conf == "Verified" else "🟡" if conf == "Partially Verified" else "🔴"
                        st.markdown(f"{color} **{conf}**")
                    st.markdown(f"**SOURCE:** {item.get('SOURCE', '—')}  |  **LOCATION:** {item.get('LOCATION', '—')}")
                    st.markdown(f"**EVIDENCE:** {item.get('EVIDENCE', '')}")
                    if i < len(evidence) - 1:
                        st.divider()

    with tab2:
        if save_pkg:
            st.success(f"Downstream evidence package saved to: `{path}`")
            st.json(package)
        else:
            st.info("Check 'Save downstream package' and re-run to see the structured JSON package.")

    # Tracker anomalies summary
    if any('tracker' in str(e.get('SOURCE', '')).lower() for e in evidence):
        with st.expander("📊 Bid Submission Tracker Summary"):
            entries = search.get_tracker_entries()
            for e in entries:
                if e.get('receipt_remarks') and e['receipt_remarks'] != 'Complete on visual check':
                    st.warning(f"**{e.get('bid_ref')}** ({e.get('company')}): {e['receipt_remarks']}")
                if e.get('currency') and e['currency'] != 'AED':
                    st.info(f"**{e.get('bid_ref')}** ({e.get('company')}): Priced in {e['currency']} (commercial deviation)")

    # Supplier eligibility table
    if 'list' in query.lower() or 'all' in query.lower() or 'compare' in query.lower():
        with st.expander("📊 Supplier Eligibility Summary"):
            data = []
            for bref, f in sorted(search._bid_facts.items()):
                elig = search.get_eligibility(bref)
                checklist = f.get('submission_checklist', {})
                all_docs = all(v == 'Enclosed' for v in checklist.values())
                cap_ok = f.get('capacity_m3_per_day', 0) >= 30000
                oiw_ok = f.get('outlet_oiw_mg_per_l', 0) <= 10
                data.append({
                    'Bid Ref': bref,
                    'Company': f['company'],
                    'Capacity (m³/d)': f.get('capacity_m3_per_day', '?'),
                    'OiW (mg/L)': f.get('outlet_oiw_mg_per_l', '?'),
                    'Price': f"{f.get('price_currency', 'AED')} {f.get('price_total', 0):,}",
                    'ICV %': f.get('icv_score_pct', '—'),
                    'TRIR': f.get('trir_3yr_avg', '?'),
                    'MC (weeks)': f.get('mc_weeks_from_loa', '?'),
                    'Docs OK?': '✅' if all_docs else '❌',
                    'Cap ≥ 30k?': '✅' if cap_ok else '❌',
                    'OiW ≤ 10?': '✅' if oiw_ok else '❌',
                    'Issues': '; '.join(elig.get('issues', []))[:100] if elig else '',
                })
            st.dataframe(data, use_container_width=True)
else:
    # Show welcome summary
    st.info("Enter a query above to retrieve evidence from the challenge dataset.")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Documents in Dataset", "14 (RFP + 12 bids + 1 tracker)")
        st.metric("Bidders", "12")
    with col2:
        st.metric("Evaluation Criteria", "Technical 40 | Commercial 30 | HSE 15 | ICV 15")
        st.metric("Minimum Capacity", "30,000 m³/d net continuous")

    # Quick stats
    with st.expander("📊 Quick Stats from Dataset"):
        stats = []
        for bref, f in sorted(search._bid_facts.items()):
            stats.append({
                'Bid Ref': bref,
                'Company': f['company'],
                'Capacity': f"{f.get('capacity_m3_per_day', '?'):,} m³/d",
                'OiW': f"{f.get('outlet_oiw_mg_per_l', '?')} mg/L",
                'Price': f"{f.get('price_currency', 'AED')} {f.get('price_total', 0):,}",
                'MC': f"{f.get('mc_weeks_from_loa', '?')} wks",
                'ICV': f"{f.get('icv_score_pct', '—')}%",
                'TRIR': f"{f.get('trir_3yr_avg', '?')}",
            })
        st.dataframe(stats, use_container_width=True)