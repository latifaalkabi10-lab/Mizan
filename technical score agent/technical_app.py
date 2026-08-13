"""
Technical Scoring Agent — Streamlit demo wrapper (Step 3 of the ADNOC Upstream
Procurement Evaluation System).

THIS IS ONLY A DEMO UI. All scoring logic lives in technical_scorer.py (pure,
framework-free module) so the same engine can be injected into the main
webapp's codebase / called by other agents in the workflow.

    RFP + BIDS -> EVIDENCE AGENT -> COMPLIANCE AGENT -> [TECHNICAL AGENT] -> ...
                                                          (this app / engine)
"""
import streamlit as st

from technical_scorer import RFP_TECHNICAL_REFERENCE_MARKDOWN, evaluate_technical

# ── UI ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Technical Scoring Agent", page_icon="🔧", layout="wide")
st.title("🔧 Technical Scoring Agent")
st.caption("ADNOC Upstream Procurement Evaluation System — **Step 3 only**: Technical Score (40 points) for eligible supplier bids.")
st.markdown(
    "Calculates **only** the Technical Score using the exact numerical scoring bands of "
    "**RFP ADNOC-LCIG/RFP/2026-0412 Rev 0, Section 6.1**. "
    "This agent does **not** calculate Commercial, HSE, ICV or total scores, and does not determine the winning supplier."
)

with st.expander("📜 Official RFP reference — Section 6.1 Technical scoring bands (verbatim)"):
    st.markdown(RFP_TECHNICAL_REFERENCE_MARKDOWN)

st.divider()

# ── Supplier & eligibility ──────────────────────────────────────────────────
st.subheader("1. Supplier & Eligibility")
col_sup1, col_sup2 = st.columns(2)
with col_sup1:
    supplier_name = st.text_input("Supplier name", value="", placeholder="e.g. Gulf WaterTech FZE")
with col_sup2:
    eligibility = st.selectbox(
        "Eligibility status (from Compliance Agent — RFP Sec. 4 / ITB clause 5)",
        options=[
            "Eligible for award consideration",
            "Not eligible — conditionally non-compliant (mandatory document missing)",
        ],
        index=0,
    )

st.divider()

# ── T1 inputs ───────────────────────────────────────────────────────────────
st.subheader("2. T1 — Process Capacity & Performance Guarantee (max 15 points)")
st.caption("RFP D2 requires Technical proposal with equipment list and datasheets: capacity (m³/d) and guaranteed outlet OiW (mg/L).")

col_t1_1, col_t1_2 = st.columns(2)
with col_t1_1:
    t1_capacity_mode = st.radio(
        "Is documented capacity evidence available?",
        options=[
            "Yes — capacity documented in technical proposal (RFP D2)",
            "No — capacity evidence missing / insufficient",
        ],
        index=0,
        key="t1_cap_mode",
        horizontal=True,
    )
    t1_capacity = None
    if t1_capacity_mode.startswith("Yes"):
        t1_capacity = st.number_input(
            "Offered net capacity (m³/d)",
            min_value=0, max_value=100000, value=33000, step=100, format="%d",
        )

with col_t1_2:
    t1_oiw_mode = st.radio(
        "Is documented OiW guarantee evidence available?",
        options=[
            "Yes — OiW guarantee documented in technical proposal (RFP D2)",
            "No — OiW evidence missing / insufficient",
        ],
        index=0,
        key="t1_oiw_mode",
        horizontal=True,
    )
    t1_oiw = None
    if t1_oiw_mode.startswith("Yes"):
        t1_oiw = st.number_input(
            "Guaranteed outlet OiW (mg/L)",
            min_value=0.0, max_value=100.0, value=5.0, step=0.5, format="%.1f",
        )

st.divider()

# ── T2 inputs ───────────────────────────────────────────────────────────────
st.subheader("3. T2 — Technology Track Record / GCC References (max 10 points)")
st.caption("RFP requires installed references of the offered technology at ≥ 20,000 m³/d in GCC, last 10 years.")

t2_mode = st.radio(
    "Is a documented GCC reference list available?",
    options=[
        "Yes — reference list documented in technical proposal (RFP D2)",
        "No — GCC reference evidence missing / insufficient",
    ],
    index=0,
    key="t2_mode",
    horizontal=True,
)
t2_references = None
if t2_mode.startswith("Yes"):
    t2_references = st.number_input(
        "Number of installed GCC references ≥ 20,000 m³/d, last 10 years",
        min_value=0, max_value=50, value=8, step=1, format="%d",
    )

st.divider()

# ── T3 inputs ───────────────────────────────────────────────────────────────
st.subheader("4. T3 — Company Experience & Organisation (max 8 points)")
st.caption("RFP D1 requires Company profile: years of produced-water treatment experience.")

t3_mode = st.radio(
    "Is documented company experience evidence available?",
    options=[
        "Yes — experience documented in company profile (RFP D1)",
        "No — experience evidence missing / insufficient",
    ],
    index=0,
    key="t3_mode",
    horizontal=True,
)
t3_years = None
if t3_mode.startswith("Yes"):
    t3_years = st.number_input(
        "Years of produced-water treatment experience",
        min_value=0, max_value=60, value=15, step=1, format="%d",
    )

st.divider()

# ── T4 inputs ───────────────────────────────────────────────────────────────
st.subheader("5. T4 — Delivery Schedule (max 7 points)")
st.caption("RFP D4 requires Level 2 schedule showing weeks from LOA to mechanical completion.")

t4_mode = st.radio(
    "Is a documented delivery schedule (Level 2) available?",
    options=[
        "Yes — Level 2 schedule documented (RFP D4)",
        "No — delivery schedule evidence missing / insufficient",
    ],
    index=0,
    key="t4_mode",
    horizontal=True,
)
t4_weeks = None
if t4_mode.startswith("Yes"):
    t4_weeks = st.number_input(
        "Weeks from LOA to mechanical completion",
        min_value=0, max_value=120, value=52, step=1, format="%d",
    )

st.divider()

# ── Evidence sources ────────────────────────────────────────────────────────
st.subheader("6. Evidence Sources (from the Procurement Evidence & Retrieval Agent)")
evidence_sources = st.text_area(
    "List the exact evidence documents and locations, e.g. "
    "“D2 Technical proposal p.12 — capacity 33,000 m³/d, OiW 5 mg/L; "
    "D2 Reference list p.34 — 8 GCC references; "
    "D1 Company profile p.5 — 15 years PWT experience; "
    "D4 Level 2 schedule — 52 weeks to mechanical completion”",
    value="", height=100,
)

st.divider()

# ── Score button ────────────────────────────────────────────────────────────
scored = st.button("🧮 Calculate Technical Score", type="primary", use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# BUILD EVIDENCE DICT AND DELEGATE TO THE PURE ENGINE (same code as the
# main webapp will call)
# ─────────────────────────────────────────────────────────────────────────────
if scored:
    if not supplier_name.strip():
        st.warning("Enter a supplier name before scoring.")
        st.stop()

    evidence = {
        "supplier": supplier_name.strip(),
        "eligibility_status": eligibility,
        "t1": {
            "capacity_m3d": t1_capacity,
            "capacity_evidence_present": t1_capacity_mode.startswith("Yes"),
            "oiw_mgL": t1_oiw,
            "oiw_evidence_present": t1_oiw_mode.startswith("Yes"),
        },
        "t2": {
            "gcc_references": t2_references,
            "evidence_present": t2_mode.startswith("Yes"),
        },
        "t3": {
            "years_experience": t3_years,
            "evidence_present": t3_mode.startswith("Yes"),
        },
        "t4": {
            "weeks_to_completion": t4_weeks,
            "evidence_present": t4_mode.startswith("Yes"),
        },
        "evidence_sources": [s.strip() for s in evidence_sources.splitlines() if s.strip()],
    }

    result = evaluate_technical(evidence)

    st.divider()
    if not result["scored"]:
        st.error(result["result"])
    else:
        st.markdown(result["report_markdown"])
        st.code(result["report_markdown"], language="markdown")
        st.download_button(
            "⬇️ Download Technical Evaluation Report (.md)",
            data=result["report_markdown"],
            file_name=f"Technical_Report_{supplier_name.strip().replace(' ', '_')}.md",
            mime="text/markdown",
        )