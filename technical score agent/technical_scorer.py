"""
Technical Scoring Engine — pure, framework-free module for the ADNOC Upstream
Procurement Evaluation System workflow (Step 3: Technical Score, 40 points).

DESIGNED FOR WORKFLOW INJECTION
-------------------------------
This module has ZERO dependencies (no Streamlit, no Flask, no pandas). It can be:
  - imported directly into your main webapp's codebase
  - wrapped in a FastAPI/Flask endpoint and called over HTTP
  - called by the RISK / REPORT agents downstream
  - unit-tested in isolation

CONTRACT (JSON in / JSON out)
-----------------------------
Input — one evidence dict (as produced by the Procurement Evidence &
         Retrieval Agent + Compliance Agent):
{
    "supplier": "Gulf WaterTech FZE",
    "eligibility_status": "Eligible for award consideration",
        # OR "Not eligible ..." -> returns the exact not-scored message
    "t1": {                                     # T1 — Process capacity & performance guarantee
        "capacity_m3d": 33000,                  # Offered net capacity in m³/d
        "capacity_evidence_present": True,
        "oiw_mgL": 5,                           # Guaranteed outlet OiW in mg/L
        "oiw_evidence_present": True,
    },
    "t2": {                                     # T2 — Technology track record (GCC references)
        "gcc_references": 8,                    # Number of installed references ≥ 20,000 m³/d in GCC, last 10 yrs
        "evidence_present": True,
    },
    "t3": {                                     # T3 — Company experience & organisation
        "years_experience": 15,                 # Years of produced-water treatment experience
        "evidence_present": True,
    },
    "t4": {                                     # T4 — Delivery schedule
        "weeks_to_completion": 52,              # Weeks from LOA to mechanical completion
        "evidence_present": True,
    },
    "evidence_sources": [
        "D2 Technical proposal p.12 — capacity 33,000 m³/d, OiW 5 mg/L",
        "D2 Reference list p.34 — 8 GCC references ≥ 20,000 m³/d",
        "D1 Company profile p.5 — 15 years PWT experience",
        "D4 Level 2 schedule — 52 weeks to mechanical completion",
    ],
}
    (missing keys are treated conservatively: no evidence -> no points. Never guessed.)

Output — JSON-serializable dict:
{
    "supplier": ...,
    "eligibility_status": ...,
    "scored": True|False,
    "technical_score": 36.0,
    "technical_max": 40,
    "t1": {"band": 5, "band_text": "Capacity ≥ 33,000 m³/d AND OiW ≤ 5 mg/L",
           "points": 15.0, "capacity": 33000, "oiw": 5, ...},
    "t2": {"band": 5, ..., "points": 10.0, ...},
    "t3": {"band": 5, ..., "points": 8.0, ...},
    "t4": {"band": 5, ..., "points": 7.0, ...},
    "report_markdown": "..."   # ready-to-render report (rulebook OUTPUT FORMAT)
}

RULES ENFORCED (verbatim from AGENTS.md rulebook + RFP Sec 6.1)
--------------------------------------------------------------
- Uses ONLY the RFP numerical bands; points = (band / 5) x weight.
- Never estimates performance; missing evidence -> "Insufficient evidence to calculate this criterion."
- T1 band 0: capacity < 30,000 m³/d OR OiW > 10 mg/L -> technically non-compliant, bid rejected
- T4 band 1: > 76 weeks -> subject to rejection as non-compliant with Section 2
- Not eligible -> exactly: "Not scored — supplier is not eligible for award consideration."
- Never computes Commercial / HSE / ICV / total scores.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# RFP SCORING BANDS — VERBATIM FROM RFP ADNOC-LCIG/RFP/2026-0412 REV 0, SEC 6.1
# Do not edit; these are the official numerical bands. points = (band/5) × weight
# ─────────────────────────────────────────────────────────────────────────────
RFP_TITLE = "ADNOC-LCIG/RFP/2026-0412 Rev 0 — Section 6.1 Technical — 40 points"

# T1 — Process capacity & performance guarantee (weight 15)
T1_WEIGHT = 15
T1_BANDS = [
    (5, "Offered net capacity ≥ 33,000 m³/d and guaranteed outlet OiW ≤ 5 mg/L", 15.00),
    (4, "Capacity ≥ 31,500 m³/d and OiW ≤ 8 mg/L", 12.00),
    (3, "Capacity ≥ 30,000 m³/d and OiW ≤ 10 mg/L (meets specification)", 9.00),
    (0, "Capacity < 30,000 m³/d or OiW > 10 mg/L — technically non-compliant, bid rejected", 0.00),
]

# T2 — Technology track record (GCC references) (weight 10)
T2_WEIGHT = 10
T2_BANDS = [
    (5, "≥ 8 installed references of the offered technology at ≥ 20,000 m³/d in GCC, last 10 years", 10.00),
    (4, "5 – 7 such references", 8.00),
    (3, "3 – 4 such references", 6.00),
    (2, "1 – 2 such references", 4.00),
    (1, "No comparable GCC reference", 2.00),
]

# T3 — Company experience & organisation (weight 8)
T3_WEIGHT = 8
T3_BANDS = [
    (5, "≥ 15 years produced-water treatment experience", 8.00),
    (4, "10 – 14 years", 6.40),
    (3, "6 – 9 years", 4.80),
    (2, "3 – 5 years", 3.20),
    (1, "< 3 years", 1.60),
]

# T4 — Delivery schedule (weight 7) — weeks from LOA to mechanical completion
T4_WEIGHT = 7
T4_BANDS = [
    (5, "≤ 52 weeks", 7.00),
    (4, "53 – 60 weeks", 5.60),
    (3, "61 – 68 weeks", 4.20),
    (2, "69 – 76 weeks (contractual maximum)", 2.80),
    (1, "> 76 weeks — subject to rejection as non-compliant with Section 2", 1.40),
]

TECHNICAL_MAX = 40

RFP_TECHNICAL_REFERENCE_MARKDOWN = """**RFP ADNOC-LCIG/RFP/2026-0412 Rev 0 — Section 6.1 Technical — 40 points** (verbatim)

> **T1 — Process capacity & performance guarantee (weight 15)**
>
>     5     Offered net capacity ≥ 33,000 m³/d and guaranteed outlet OiW ≤ 5 mg/L
>     4     Capacity ≥ 31,500 m³/d and OiW ≤ 8 mg/L
>     3     Capacity ≥ 30,000 m³/d and OiW ≤ 10 mg/L (meets specification)
>     0     Capacity < 30,000 m³/d or OiW > 10 mg/L — technically non-compliant, bid rejected
>
> **T2 — Technology track record (GCC references) (weight 10)**
>
>     5     ≥ 8 installed references of the offered technology at ≥ 20,000 m³/d in GCC, last 10 years
>     4     5 – 7 such references
>     3     3 – 4 such references
>     2     1 – 2 such references
>     1     No comparable GCC reference
>
> **T3 — Company experience & organisation (weight 8)**
>
>     5     ≥ 15 years produced-water treatment experience
>     4     10 – 14 years
>     3     6 – 9 years
>     2     3 – 5 years
>     1     < 3 years
>
> **T4 — Delivery schedule (weight 7) — weeks from LOA to mechanical completion**
>
>     5     ≤ 52 weeks
>     4     53 – 60 weeks
>     3     61 – 68 weeks
>     2     69 – 76 weeks (contractual maximum)
>     1     > 76 weeks — subject to rejection as non-compliant with Section 2
>
> *Section 6 intro: Sub-criteria scored on 0–5 bands convert to points as:
> points = (band / 5) × weight. All bands are defined numerically below and are
> applied without discretion.*

Worked example (RFP 6.5): 32,000 m³/d at OiW 6 mg/L → T1 band 4 → 12.00 pts;
6 GCC references → T2 band 4 → 8.00 pts; 12 years' experience → T3 band 4 → 6.40 pts;
58-week schedule → T4 band 4 → 5.60 pts."""


# ─────────────────────────────────────────────────────────────────────────────
# SCORING FUNCTIONS — pure, deterministic, no UI, no I/O
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_float(value, default=None):
    """Safely convert a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value, default=None):
    """Safely convert a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def score_t1(capacity_m3d, capacity_evidence_present, oiw_mgL, oiw_evidence_present):
    """Apply RFP T1 bands. Returns (band, band_text, points, note).

    band is None when evidence is missing/insufficient.
    """
    if not capacity_evidence_present or not oiw_evidence_present:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Both capacity and OiW guarantee must be documented per RFP D2 (Technical proposal).")

    c = _coerce_float(capacity_m3d)
    o = _coerce_float(oiw_mgL)

    if c is None or o is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Capacity and/or OiW values could not be interpreted from the evidence.")

    # Band 0 — technically non-compliant
    if c < 30000 or o > 10:
        return (0, "Capacity < 30,000 m³/d or OiW > 10 mg/L — technically non-compliant, bid rejected", 0.00,
                f"RFP T1 band 0: capacity {c:.0f} m³/d, OiW {o:.1f} mg/L. "
                f"Capacity < 30,000 m³/d or OiW > 10 mg/L → technically non-compliant, bid rejected.")

    # Band 5
    if c >= 33000 and o <= 5:
        return (5, "Offered net capacity ≥ 33,000 m³/d and guaranteed outlet OiW ≤ 5 mg/L", 15.00,
                f"RFP T1 band 5 → points = (5/5) × 15 = 15.00. "
                f"Capacity {c:.0f} m³/d ≥ 33,000 AND OiW {o:.1f} mg/L ≤ 5.")

    # Band 4
    if c >= 31500 and o <= 8:
        return (4, "Capacity ≥ 31,500 m³/d and OiW ≤ 8 mg/L", 12.00,
                f"RFP T1 band 4 → points = (4/5) × 15 = 12.00. "
                f"Capacity {c:.0f} m³/d ≥ 31,500 AND OiW {o:.1f} mg/L ≤ 8.")

    # Band 3 (meets specification)
    if c >= 30000 and o <= 10:
        return (3, "Capacity ≥ 30,000 m³/d and OiW ≤ 10 mg/L (meets specification)", 9.00,
                f"RFP T1 band 3 → points = (3/5) × 15 = 9.00. "
                f"Capacity {c:.0f} m³/d ≥ 30,000 AND OiW {o:.1f} mg/L ≤ 10 (meets spec).")

    # Fallback — should not be reached if thresholds above are exhaustive
    return (0, "Capacity < 30,000 m³/d or OiW > 10 mg/L — technically non-compliant, bid rejected", 0.00,
            f"RFP T1 band 0: capacity {c:.0f} m³/d, OiW {o:.1f} mg/L. Technically non-compliant.")


def score_t2(gcc_references, evidence_present):
    """Apply RFP T2 bands. Returns (band, band_text, points, note).

    band is None when evidence is missing/insufficient.
    """
    if not evidence_present or gcc_references is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "GCC reference list must be documented per RFP D2 (Technical proposal).")

    refs = _coerce_int(gcc_references)
    if refs is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "GCC reference count could not be interpreted from the evidence.")

    if refs >= 8:
        return (5, "≥ 8 installed references of the offered technology at ≥ 20,000 m³/d in GCC, last 10 years", 10.00,
                f"RFP T2 band 5 → points = (5/5) × 10 = 10.00. {refs} GCC references ≥ 8.")
    if refs >= 5:
        return (4, "5 – 7 such references", 8.00,
                f"RFP T2 band 4 → points = (4/5) × 10 = 8.00. {refs} GCC references (5–7 range).")
    if refs >= 3:
        return (3, "3 – 4 such references", 6.00,
                f"RFP T2 band 3 → points = (3/5) × 10 = 6.00. {refs} GCC references (3–4 range).")
    if refs >= 1:
        return (2, "1 – 2 such references", 4.00,
                f"RFP T2 band 2 → points = (2/5) × 10 = 4.00. {refs} GCC reference(s) (1–2 range).")
    return (1, "No comparable GCC reference", 2.00,
            "RFP T2 band 1 → points = (1/5) × 10 = 2.00. No comparable GCC reference.")


def score_t3(years_experience, evidence_present):
    """Apply RFP T3 bands. Returns (band, band_text, points, note).

    band is None when evidence is missing/insufficient.
    """
    if not evidence_present or years_experience is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Company experience in produced-water treatment must be documented per RFP D1 (Company profile).")

    years = _coerce_float(years_experience)
    if years is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Years of experience could not be interpreted from the evidence.")

    if years >= 15:
        return (5, "≥ 15 years produced-water treatment experience", 8.00,
                f"RFP T3 band 5 → points = (5/5) × 8 = 8.00. {years:.0f} years ≥ 15.")
    if years >= 10:
        return (4, "10 – 14 years", 6.40,
                f"RFP T3 band 4 → points = (4/5) × 8 = 6.40. {years:.0f} years (10–14 range).")
    if years >= 6:
        return (3, "6 – 9 years", 4.80,
                f"RFP T3 band 3 → points = (3/5) × 8 = 4.80. {years:.0f} years (6–9 range).")
    if years >= 3:
        return (2, "3 – 5 years", 3.20,
                f"RFP T3 band 2 → points = (2/5) × 8 = 3.20. {years:.0f} years (3–5 range).")
    return (1, "< 3 years", 1.60,
            f"RFP T3 band 1 → points = (1/5) × 8 = 1.60. {years:.0f} years < 3.")


def score_t4(weeks_to_completion, evidence_present):
    """Apply RFP T4 bands. Returns (band, band_text, points, note).

    band is None when evidence is missing/insufficient.
    """
    if not evidence_present or weeks_to_completion is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Delivery schedule must be documented per RFP D4 (Level 2 schedule).")

    weeks = _coerce_float(weeks_to_completion)
    if weeks is None:
        return (None, "N/A", None,
                "Insufficient evidence to calculate this criterion. "
                "Weeks to completion could not be interpreted from the evidence.")

    if weeks <= 52:
        return (5, "≤ 52 weeks", 7.00,
                f"RFP T4 band 5 → points = (5/5) × 7 = 7.00. {weeks:.0f} weeks ≤ 52.")
    if weeks <= 60:
        return (4, "53 – 60 weeks", 5.60,
                f"RFP T4 band 4 → points = (4/5) × 7 = 5.60. {weeks:.0f} weeks (53–60 range).")
    if weeks <= 68:
        return (3, "61 – 68 weeks", 4.20,
                f"RFP T4 band 3 → points = (3/5) × 7 = 4.20. {weeks:.0f} weeks (61–68 range).")
    if weeks <= 76:
        return (2, "69 – 76 weeks (contractual maximum)", 2.80,
                f"RFP T4 band 2 → points = (2/5) × 7 = 2.80. {weeks:.0f} weeks (69–76 range).")
    return (1, "> 76 weeks — subject to rejection as non-compliant with Section 2", 1.40,
            f"RFP T4 band 1 → points = (1/5) × 7 = 1.40. {weeks:.0f} weeks > 76. "
            "Subject to rejection as non-compliant with Section 2.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT — evaluate_technical(evidence_dict) -> result_dict (JSON-safe)
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_technical(evidence: dict) -> dict:
    """Full Technical evaluation for one supplier bid. Tolerant of missing keys
    (treated as absent evidence — never guessed)."""
    supplier = str(evidence.get("supplier", "")).strip()
    eligibility = str(evidence.get("eligibility_status", "Eligible for award consideration")).strip()

    # ---- Eligibility gate (from Compliance Agent) ----
    if eligibility.lower().startswith("not eligible"):
        return {
            "supplier": supplier,
            "eligibility_status": eligibility,
            "scored": False,
            "technical_score": None,
            "technical_max": TECHNICAL_MAX,
            "result": "Not scored — supplier is not eligible for award consideration.",
            "report_markdown": "**Not scored — supplier is not eligible for award consideration.**",
            "missing_information": [],
            "uncertainties": [],
            "risks": [],
        }

    # ---- T1 evidence (RFP D2 — Technical proposal) ----
    t1_block = evidence.get("t1") or {}
    if isinstance(t1_block, dict):
        capacity_m3d = t1_block.get("capacity_m3d")
        capacity_evidence_present = bool(t1_block.get("capacity_evidence_present", False))
        oiw_mgL = t1_block.get("oiw_mgL")
        oiw_evidence_present = bool(t1_block.get("oiw_evidence_present", False))
    else:
        capacity_m3d = None
        capacity_evidence_present = False
        oiw_mgL = None
        oiw_evidence_present = False

    # ---- T2 evidence (RFP D2 — Reference list) ----
    t2_block = evidence.get("t2") or {}
    if isinstance(t2_block, dict):
        gcc_references = t2_block.get("gcc_references")
        t2_evidence_present = bool(t2_block.get("evidence_present", False))
    else:
        gcc_references = None
        t2_evidence_present = False

    # ---- T3 evidence (RFP D1 — Company profile) ----
    t3_block = evidence.get("t3") or {}
    if isinstance(t3_block, dict):
        years_experience = t3_block.get("years_experience")
        t3_evidence_present = bool(t3_block.get("evidence_present", False))
    else:
        years_experience = None
        t3_evidence_present = False

    # ---- T4 evidence (RFP D4 — Level 2 schedule) ----
    t4_block = evidence.get("t4") or {}
    if isinstance(t4_block, dict):
        weeks_to_completion = t4_block.get("weeks_to_completion")
        t4_evidence_present = bool(t4_block.get("evidence_present", False))
    else:
        weeks_to_completion = None
        t4_evidence_present = False

    # ---- Evidence sources ----
    evidence_sources = evidence.get("evidence_sources", [])
    if isinstance(evidence_sources, str):
        evidence_sources = [evidence_sources]
    evidence_sources = [str(s) for s in evidence_sources if str(s).strip()]
    evidence_text = "; ".join(evidence_sources) if evidence_sources else "None recorded"

    # ---- Score T1–T4 ----
    t1_band, t1_band_text, t1_points, t1_note = score_t1(
        capacity_m3d, capacity_evidence_present, oiw_mgL, oiw_evidence_present)
    t2_band, t2_band_text, t2_points, t2_note = score_t2(gcc_references, t2_evidence_present)
    t3_band, t3_band_text, t3_points, t3_note = score_t3(years_experience, t3_evidence_present)
    t4_band, t4_band_text, t4_points, t4_note = score_t4(weeks_to_completion, t4_evidence_present)

    # ---- Diagnostics ----
    missing_information, uncertainties, risks = [], [], []

    if t1_band is None:
        missing_information.append(
            "T1 — Process capacity & performance guarantee (RFP D2 Technical proposal): "
            "capacity and/or OiW guarantee not documented. Insufficient evidence to calculate this criterion.")
    if t2_band is None:
        missing_information.append(
            "T2 — Technology track record (RFP D2 Reference list): "
            "GCC reference count not documented. Insufficient evidence to calculate this criterion.")
    if t3_band is None:
        missing_information.append(
            "T3 — Company experience & organisation (RFP D1 Company profile): "
            "years of produced-water treatment experience not documented. Insufficient evidence to calculate this criterion.")
    if t4_band is None:
        missing_information.append(
            "T4 — Delivery schedule (RFP D4 Level 2 schedule): "
            "weeks to mechanical completion not documented. Insufficient evidence to calculate this criterion.")
    if not evidence_sources:
        missing_information.append(
            "No evidence sources recorded — every score must be traceable to a specific supplier evidence source.")

    # T1 band 0 — technically non-compliant risk
    if t1_band == 0:
        risks.append(
            f"T1 band 0: capacity {_coerce_float(capacity_m3d, 'N/A'):.0f} m³/d, "
            f"OiW {_coerce_float(oiw_mgL, 'N/A'):.1f} mg/L — "
            "technically non-compliant, bid rejected. "
            "The bid is excluded from award consideration per RFP Section 6.1.")

    # T4 band 1 — schedule risk
    if t4_band == 1:
        risks.append(
            f"T4 band 1: {_coerce_float(weeks_to_completion, 'N/A'):.0f} weeks to completion — "
            "> 76 weeks, subject to rejection as non-compliant with Section 2.")

    if not missing_information:
        missing_information.append("None identified.")

    # ---- Calculate total ----
    points_list = [t1_points, t2_points, t3_points, t4_points]
    if all(p is not None for p in points_list):
        technical_total = round(sum(points_list), 2)
    else:
        # If any criterion is unscored due to missing evidence, total is partial
        scored = [p for p in points_list if p is not None]
        technical_total = round(sum(scored), 2) if scored else 0.0
        if not any(p is None for p in points_list):
            pass  # all scored, fine
        elif any(p is not None for p in points_list):
            uncertainties.append(
                "Partial technical score calculated — some criteria could not be scored due to "
                "insufficient evidence. The total score reflects only scored criteria.")

    # ---- Report (rulebook OUTPUT FORMAT) ----
    report = _build_report(
        supplier, eligibility,
        capacity_m3d, capacity_evidence_present, oiw_mgL, oiw_evidence_present,
        t1_band, t1_band_text, t1_points, t1_note,
        gcc_references, t2_evidence_present,
        t2_band, t2_band_text, t2_points, t2_note,
        years_experience, t3_evidence_present,
        t3_band, t3_band_text, t3_points, t3_note,
        weeks_to_completion, t4_evidence_present,
        t4_band, t4_band_text, t4_points, t4_note,
        technical_total, evidence_text,
        missing_information, uncertainties, risks,
    )

    return {
        "supplier": supplier,
        "eligibility_status": eligibility,
        "scored": True,
        "t1": {
            "band": t1_band,
            "band_text": t1_band_text,
            "points": t1_points,
            "capacity_m3d": capacity_m3d,
            "oiw_mgL": oiw_mgL,
            "capacity_evidence_present": capacity_evidence_present,
            "oiw_evidence_present": oiw_evidence_present,
            "insufficient": t1_band is None,
            "note": t1_note,
        },
        "t2": {
            "band": t2_band,
            "band_text": t2_band_text,
            "points": t2_points,
            "gcc_references": gcc_references,
            "evidence_present": t2_evidence_present,
            "insufficient": t2_band is None,
            "note": t2_note,
        },
        "t3": {
            "band": t3_band,
            "band_text": t3_band_text,
            "points": t3_points,
            "years_experience": years_experience,
            "evidence_present": t3_evidence_present,
            "insufficient": t3_band is None,
            "note": t3_note,
        },
        "t4": {
            "band": t4_band,
            "band_text": t4_band_text,
            "points": t4_points,
            "weeks_to_completion": weeks_to_completion,
            "evidence_present": t4_evidence_present,
            "insufficient": t4_band is None,
            "note": t4_note,
        },
        "technical_score": technical_total,
        "technical_max": TECHNICAL_MAX,
        "missing_information": missing_information,
        "uncertainties": uncertainties,
        "risks": risks,
        "evidence_sources": evidence_sources,
        "report_markdown": report,
    }


# ─────────────────────────────────────────────────────────────────────────────
# REPORT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def _format_val(v, precision=0):
    """Format a numeric value for display, or return 'Not documented'."""
    if isinstance(v, (int, float)):
        if precision == 0:
            return f"{v:.0f}"
        return f"{v:.{precision}f}"
    return "Not documented — evidence missing/insufficient"


def _t1_score_line(t1_band, t1_points):
    if t1_band is None:
        return "Insufficient evidence to calculate this criterion."
    return f"{t1_points:.2f} / 15.00"


def _t1_contrib(t1_band, t1_points):
    if t1_band is None:
        return "Not scored (no points awarded — evidence insufficient)"
    return f"{t1_points:.2f}"


def _build_report(
    supplier, eligibility,
    capacity_m3d, capacity_evidence_present, oiw_mgL, oiw_evidence_present,
    t1_band, t1_band_text, t1_points, t1_note,
    gcc_references, t2_evidence_present,
    t2_band, t2_band_text, t2_points, t2_note,
    years_experience, t3_evidence_present,
    t3_band, t3_band_text, t3_points, t3_note,
    weeks_to_completion, t4_evidence_present,
    t4_band, t4_band_text, t4_points, t4_note,
    technical_total, evidence_text,
    missing_information, uncertainties, risks,
):

    lines = [
        f"### Technical Evaluation Report — {supplier}" if supplier else "### Technical Evaluation Report",
        "",
        f"**Eligibility Status:** {eligibility}",
        "",
        "---",
        "",
        "**T1 — Process Capacity & Performance Guarantee:**",
        f"- **Offered Capacity:** {_format_val(capacity_m3d)} m³/d",
        f"- **Guaranteed Outlet OiW:** {_format_val(oiw_mgL, 1)} mg/L",
        f"- **RFP Scoring Band:** {f'Band {t1_band} — {t1_band_text}' if t1_band is not None else 'N/A'}",
        f"- **Supplier Evidence:** {evidence_text}",
        f"- **Score:** {_t1_score_line(t1_band, t1_points)}",
        f"- **Reason:** {t1_note}",
        "",
        "**T2 — Technology Track Record:**",
        f"- **GCC References (≥ 20,000 m³/d, last 10 years):** {_format_val(gcc_references)}",
        f"- **RFP Scoring Band:** {f'Band {t2_band} — {t2_band_text}' if t2_band is not None else 'N/A'}",
        f"- **Supplier Evidence:** {evidence_text}",
        f"- **Score:** {t2_points:.2f} / 10.00" if t2_band is not None else "- **Score:** Insufficient evidence to calculate this criterion.",
        f"- **Reason:** {t2_note}",
        "",
        "**T3 — Company Experience & Organisation:**",
        f"- **Produced-Water Treatment Experience:** {_format_val(years_experience)} years",
        f"- **RFP Scoring Band:** {f'Band {t3_band} — {t3_band_text}' if t3_band is not None else 'N/A'}",
        f"- **Supplier Evidence:** {evidence_text}",
        f"- **Score:** {t3_points:.2f} / 8.00" if t3_band is not None else "- **Score:** Insufficient evidence to calculate this criterion.",
        f"- **Reason:** {t3_note}",
        "",
        "**T4 — Delivery Schedule:**",
        f"- **Weeks from LOA to Mechanical Completion:** {_format_val(weeks_to_completion)} weeks",
        f"- **RFP Scoring Band:** {f'Band {t4_band} — {t4_band_text}' if t4_band is not None else 'N/A'}",
        f"- **Supplier Evidence:** {evidence_text}",
        f"- **Score:** {t4_points:.2f} / 7.00" if t4_band is not None else "- **Score:** Insufficient evidence to calculate this criterion.",
        f"- **Reason:** {t4_note}",
        "",
        "---",
        "",
        f"**Technical Score:** {technical_total:.2f} / 40",
        f"(T1 {_t1_contrib(t1_band, t1_points)}/15.00 + T2 {t2_points if t2_band is not None else 'N/A'}/10.00 + "
        f"T3 {t3_points if t3_band is not None else 'N/A'}/8.00 + T4 {t4_points if t4_band is not None else 'N/A'}/7.00)",
        "",
        "**Missing Information:**",
    ]
    for m in missing_information:
        lines.append(f"- {m}")
    lines += [
        "",
        "**Uncertainties:**",
    ]
    lines += [f"- {u}" for u in uncertainties] if uncertainties else ["- None identified."]
    lines += [
        "",
        "**Risks:**",
    ]
    lines += [f"- {r}" for r in risks] if risks else ["- None identified."]
    lines += [
        "",
        "**Evidence Sources:**",
        f"- {evidence_text}",
        "",
        f"**Scoring Basis:** {RFP_TITLE}. Points = (band / 5) × weight, applied without discretion.",
    ]
    return "\n".join(lines)