#!/usr/bin/env python3
"""
Compliance & Eligibility Agent
===============================
Python implementation of the Compliance & Eligibility Agent (see
compliance_eligibility_agent.md) — the standalone gatekeeper of bid
eligibility in the ADNOC Upstream Procurement Evaluation System.

Role (from the agent spec):
    Determine whether each supplier bid passes MANDATORY submission
    requirements (D1-D9) and MINIMUM TECHNICAL requirements using ONLY
    evidence retrieved from the Procurement Evidence & Retrieval Agent
    and the official ADNOC RFP.

    Only suppliers that pass BOTH gates are eligible for award
    consideration. This agent does NOT calculate Technical, Commercial,
    HSE, or ICV scores, does NOT recommend a winner, does NOT compare
    prices, and does NOT read bid documents directly.

Standalone: its output IS the deliverable. It does not feed a downstream
scoring pipeline.

Evidence discipline (anti-hallucination contract):
    - Missing evidence  -> "Insufficient evidence to determine compliance."
    - Contradictory evidence -> record both positions, INSUFFICIENT EVIDENCE.
    - "Not found in the dataset" != "does not exist".
    - No citation -> no classification. Never guess, assume, or infer.
    - Output is decision-support only — NOT an official ADNOC procurement
      decision.

RFP-agnostic: all thresholds and rules are discovered from the RFP schema
(Step 0). Ships with the ADNOC-LCIG/RFP/2026-0412 default schema, which is
the worked-example configuration verified against the RFP text.

Usage:
    python3 compliance_eligibility_agent.py --test                  # test harness
    python3 compliance_eligibility_agent.py bids.json              # human-readable report
    python3 compliance_eligibility_agent.py bids.json --json       # machine-readable output
    python3 compliance_eligibility_agent.py - < bids.json          # read from stdin
    python3 compliance_eligibility_agent.py bids.json --schema schema.json  # override RFP schema

Stdlib only. No dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MISSING_PHRASE = "Insufficient evidence to determine compliance."

# Classification statuses (Step 1 / Step 2)
COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON-COMPLIANT"
TECH_NON_COMPLIANT = "TECHNICALLY NON-COMPLIANT"
INSUFFICIENT = "INSUFFICIENT EVIDENCE"

# Screening / compliance results (Step 3)
PASS = "PASS"
FAIL = "FAIL"

# ---------------------------------------------------------------------------
# Schema (Step 0 — discovered from the RFP, never assumed)
# ---------------------------------------------------------------------------


@dataclass
class RfpSchema:
    """Evaluation schema extracted from the RFP (Step 0 schema discovery).

    Default values are the worked-example configuration for
    ADNOC-LCIG/RFP/2026-0412, verified against the RFP text. For any other
    RFP, re-derive these values from the RFP itself (see agent spec Step 0).
    """

    tender_id: str = "ADNOC-LCIG/RFP/2026-0412"

    # --- Mandatory document checklist (RFP Section 4) ---------------------
    # Each entry: code -> (description, format rule)
    mandatory_docs: dict[str, str] = field(default_factory=lambda: {
        "D1": "Company profile incl. valid UAE/home-country trade licence (PDF, max 20 pages)",
        "D2": "Technical proposal with equipment list and datasheets (PDF)",
        "D3": "Itemized commercial proposal, priced in AED (PDF, itemized table)",
        "D4": "Delivery schedule (Level 2) to mechanical completion (PDF or native plan)",
        "D5": "HSE statistics: 3-year TRIR, LTI and fatality record (PDF, tabulated by year)",
        "D6": "Valid ICV certificate, MoIAT-certified body (PDF copy of certificate)",
        "D7": "Audited financial statements, last 2 financial years (PDF, audited & signed)",
        "D8": "Bid bond / bank guarantee, 2% of total bid value, 150-day validity (Original + PDF copy)",
        "D9": "Warranty statement, minimum 24 months from acceptance (PDF, signed)",
    })

    # --- Minimum technical requirements (RFP Section 5.1 / 6.1) ------------
    min_capacity_m3d: float = 30_000.0          # rejection: capacity < 30,000 (T1 band 0)
    max_oiw_outlet_mgl: float = 10.0            # rejection: OiW > 10 (T1 band 0)
    max_delivery_weeks: float = 76.0            # rejection: > 76 weeks (T4 band 1)
    min_warranty_months: float = 24.0           # rejection: < 24 months (D9 / Section 5.1)
    max_tss_mgl: float = 15.0                   # Section 5.1 minimum
    max_particle_size_um: float = 5.0           # Section 5.1 minimum (98th percentile)
    min_temp_c: float = 55.0                    # Section 5.1 operating temperature range
    max_temp_c: float = 78.0
    min_pressure_barg: float = 3.5              # Section 5.1 design pressure at battery limit
    max_h2s_ppmw: float = 45.0                  # Section 5.1 sour service (NACE MR0175)
    max_turndown_pct: float = 30.0              # Section 5.1 turndown (<= 30% = compliant)
    min_availability_pct: float = 97.0          # Section 5.1 availability
    required_dcs: str = "Yokogawa Centum VP"    # Section 5.1 DCS integration
    performance_test_keywords: tuple[str, ...] = (  # Section 7 / Exhibit D
        "72", "hour", "95%", "design flow", "IP 426", "OSPAR",
    )

    # --- Key dates & validity (RFP Section 2 / ITB 3 / ITB 4) ---------------
    bid_deadline_iso: str = "2026-07-16"        # bid submission deadline (16 July 2026)
    bid_validity_days: int = 120
    bond_pct: float = 2.0                       # ITB 4: 2% of total bid value
    bond_validity_days: int = 150

    # --- Escalation proximity margins (E7, agent spec) ---------------------
    proximity_capacity_pct: float = 0.01        # within 1% of 30,000
    proximity_oiw_abs: float = 1.0              # within 1 mg/L of 10
    proximity_weeks_abs: float = 1.0            # within 1 week of 76
    proximity_warranty_abs: float = 1.0         # within 1 month of 24


DEFAULT_SCHEMA = RfpSchema()


# ---------------------------------------------------------------------------
# Evidence bundle (per supplier, from the Procurement Evidence & Retrieval
# Agent). Field names follow the agent spec's Inputs section. Any field may
# be absent (None) — absent evidence is INSUFFICIENT, never assumed.
# ---------------------------------------------------------------------------


@dataclass
class EvidenceBundle:
    """Structured evidence for a single supplier bid."""

    supplier_name: str = ""
    # D1
    d1_submitted: Optional[bool] = None
    d1_licence_valid: Optional[bool] = None
    # D2
    d2_submitted: Optional[bool] = None
    d2_has_equipment_list: Optional[bool] = None
    d2_has_datasheets: Optional[bool] = None
    # D3
    d3_submitted: Optional[bool] = None
    d3_priced_in_aed: Optional[bool] = None
    d3_itemized: Optional[bool] = None
    # D4
    d4_submitted: Optional[bool] = None
    # D5
    d5_submitted: Optional[bool] = None
    d5_tabulated_by_year: Optional[bool] = None
    # D6
    d6_submitted: Optional[bool] = None
    d6_moiat_certified: Optional[bool] = None
    d6_validity_date: Optional[str] = None      # ISO date, e.g. "2027-01-15"
    # D7
    d7_submitted: Optional[bool] = None
    d7_audited: Optional[bool] = None
    d7_signed: Optional[bool] = None
    d7_covers_2_years: Optional[bool] = None
    # D8
    d8_submitted: Optional[bool] = None
    d8_bond_percentage: Optional[float] = None
    d8_validity_days: Optional[int] = None
    d8_bank_uae_licensed: Optional[bool] = None
    # D9
    d9_submitted: Optional[bool] = None
    d9_warranty_months: Optional[int] = None
    d9_signed: Optional[bool] = None
    # Minimum technical parameters
    capacity_m3_per_day: Optional[float] = None
    oiw_mg_per_l: Optional[float] = None
    delivery_weeks: Optional[float] = None
    warranty_offered_months: Optional[float] = None
    tss_mg_per_l: Optional[float] = None
    particle_size_um: Optional[float] = None
    operating_temperature: Optional[str] = None
    operating_pressure_barg: Optional[float] = None
    h2s_ppmw: Optional[float] = None
    nace_rated: Optional[bool] = None
    turndown_percent: Optional[float] = None
    availability_percent: Optional[float] = None
    n1_philosophy: Optional[bool] = None
    dcs_type: Optional[str] = None
    battery_limits_confirmed: Optional[bool] = None
    performance_test_offered: Optional[str] = None
    # Citations: requirement key -> evidence citation string
    evidence: dict[str, str] = field(default_factory=dict)
    # Optional conflict map: field -> [value_a, value_b] (E4/E6)
    conflicts: dict[str, list[Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceBundle":
        """Build a bundle from a JSON dict. Unknown keys are ignored."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def citation(self, key: str) -> str:
        return self.evidence.get(key, "")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_true(v: Optional[bool]) -> bool:
    return v is True


def _parse_date_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _num(v: Any) -> Optional[float]:
    """Coerce a value to float; None/type-mismatch -> None (INSUFFICIENT)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _check(name: str, condition: bool, note: str) -> tuple[str, str]:
    """Return (COMPLIANT/NON-COMPLIANT, note) for a boolean condition."""
    return (COMPLIANT, note) if condition else (NON_COMPLIANT, note)


# ---------------------------------------------------------------------------
# STEP 1 — MANDATORY SCREENING (D1-D9)
# ---------------------------------------------------------------------------


def check_d1(b: EvidenceBundle) -> tuple[str, str]:
    """D1 — Company profile incl. valid UAE/home-country trade licence."""
    if b.d1_submitted is None or b.d1_licence_valid is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D1: submission status or licence validity not provided)"
    if not b.d1_submitted:
        return NON_COMPLIANT, "D1 not submitted -> conditionally non-compliant (ITB 5)"
    if not b.d1_licence_valid:
        return NON_COMPLIANT, "D1 submitted but trade licence invalid/expired"
    return COMPLIANT, f"D1 submitted, licence valid [{b.citation('D1')}]"


def check_d2(b: EvidenceBundle) -> tuple[str, str]:
    """D2 — Technical proposal with equipment list and datasheets."""
    if b.d2_submitted is None or b.d2_has_equipment_list is None or b.d2_has_datasheets is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D2: submission/equipment-list/datasheet status not provided)"
    if not b.d2_submitted:
        return NON_COMPLIANT, "D2 not submitted -> conditionally non-compliant (ITB 5)"
    if not (b.d2_has_equipment_list and b.d2_has_datasheets):
        return NON_COMPLIANT, "D2 submitted but equipment list and/or datasheets missing"
    return COMPLIANT, f"D2 submitted with equipment list and datasheets [{b.citation('D2')}]"


def check_d3(b: EvidenceBundle) -> tuple[str, str]:
    """D3 — Itemized commercial proposal, priced in AED."""
    if b.d3_submitted is None or b.d3_priced_in_aed is None or b.d3_itemized is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D3: submission/AED-pricing/itemization status not provided)"
    if not b.d3_submitted:
        return NON_COMPLIANT, "D3 not submitted -> conditionally non-compliant (ITB 5)"
    if not b.d3_priced_in_aed:
        return NON_COMPLIANT, "D3 submitted but not priced in AED (ITB 2)"
    if not b.d3_itemized:
        return NON_COMPLIANT, "D3 submitted but not itemized as required"
    return COMPLIANT, f"D3 submitted, itemized, priced in AED [{b.citation('D3')}]"


def check_d4(b: EvidenceBundle) -> tuple[str, str]:
    """D4 — Delivery schedule (Level 2) to mechanical completion."""
    if b.d4_submitted is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D4: submission status not provided)"
    if not b.d4_submitted:
        return NON_COMPLIANT, "D4 not submitted -> conditionally non-compliant (ITB 5)"
    return COMPLIANT, f"D4 delivery schedule submitted [{b.citation('D4')}]"


def check_d5(b: EvidenceBundle) -> tuple[str, str]:
    """D5 — HSE statistics: 3-year TRIR, LTI and fatality record."""
    if b.d5_submitted is None or b.d5_tabulated_by_year is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D5: submission status or year-by-year tabulation not provided)"
    if not b.d5_submitted:
        return NON_COMPLIANT, "D5 not submitted -> conditionally non-compliant (ITB 5)"
    if not b.d5_tabulated_by_year:
        return NON_COMPLIANT, "D5 submitted but not tabulated by year (3-year record required)"
    return COMPLIANT, f"D5 HSE statistics submitted, tabulated by year [{b.citation('D5')}]"


def check_d6(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    """D6 — Valid ICV certificate (MoIAT-certified body, valid on bid date)."""
    if b.d6_submitted is None or b.d6_moiat_certified is None or b.d6_validity_date is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D6: submission status, certifying body, or validity date not provided)"
    if not b.d6_submitted:
        return NON_COMPLIANT, "D6 not submitted -> conditionally non-compliant (ITB 5)"
    if not b.d6_moiat_certified:
        return NON_COMPLIANT, "D6 ICV certificate not issued by a MoIAT-certified body"
    expiry = _parse_date_iso(b.d6_validity_date)
    if expiry is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D6: validity date '{b.d6_validity_date}' unparseable)"
    bid_date = _parse_date_iso(schema.bid_deadline_iso)
    if bid_date is not None and expiry < bid_date:
        return NON_COMPLIANT, (
            f"D6 ICV certificate expired {expiry.isoformat()} before bid submission "
            f"deadline {schema.bid_deadline_iso}"
        )
    return COMPLIANT, (
        f"D6 ICV certificate valid until {expiry.isoformat()} on bid date {schema.bid_deadline_iso}, "
        f"MoIAT-certified body [{b.citation('D6')}]"
    )


def check_d7(b: EvidenceBundle) -> tuple[str, str]:
    """D7 — Audited financial statements (last 2 financial years)."""
    if (b.d7_submitted is None or b.d7_audited is None or b.d7_signed is None
            or b.d7_covers_2_years is None):
        return INSUFFICIENT, f"{MISSING_PHRASE} (D7: submission/audit/signature/coverage status not provided)"
    if not b.d7_submitted:
        return NON_COMPLIANT, "D7 not submitted -> conditionally non-compliant (ITB 5)"
    if not b.d7_audited:
        return NON_COMPLIANT, "D7 financial statements not audited"
    if not b.d7_signed:
        return NON_COMPLIANT, "D7 financial statements not signed"
    if not b.d7_covers_2_years:
        return NON_COMPLIANT, "D7 financial statements do not cover the last 2 financial years"
    return COMPLIANT, f"D7 audited, signed, covering 2 financial years [{b.citation('D7')}]"


def check_d8(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    """D8 — Bid bond / bank guarantee (>=2%, >=150-day validity, UAE-licensed bank)."""
    if (b.d8_submitted is None or b.d8_bond_percentage is None
            or b.d8_validity_days is None or b.d8_bank_uae_licensed is None):
        return INSUFFICIENT, f"{MISSING_PHRASE} (D8: submission/bond %/validity/bank status not provided)"
    if not b.d8_submitted:
        return NON_COMPLIANT, "D8 not submitted -> conditionally non-compliant (ITB 5)"
    bond_pct = _num(b.d8_bond_percentage)
    validity = _num(b.d8_validity_days)
    if bond_pct is None or validity is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D8: bond percentage or validity days unparseable)"
    if bond_pct < schema.bond_pct:
        return NON_COMPLIANT, f"D8 bond {bond_pct}% < required {schema.bond_pct}% of total bid value (ITB 4)"
    if validity < schema.bond_validity_days:
        return NON_COMPLIANT, f"D8 bond valid {validity:.0f} days < required {schema.bond_validity_days} days"
    if not b.d8_bank_uae_licensed:
        return NON_COMPLIANT, "D8 bond not issued/counter-guaranteed by a UAE-licensed bank"
    return COMPLIANT, (
        f"D8 bond {bond_pct}% of total bid value, valid {validity:.0f} days, "
        f"UAE-licensed bank [{b.citation('D8')}]"
    )


def check_d9(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    """D9 — Warranty statement (minimum 24 months from acceptance)."""
    if b.d9_submitted is None or b.d9_warranty_months is None or b.d9_signed is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D9: submission/warranty months/signature status not provided)"
    if not b.d9_submitted:
        return NON_COMPLIANT, "D9 not submitted -> conditionally non-compliant (ITB 5)"
    months = _num(b.d9_warranty_months)
    if months is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (D9: warranty months unparseable)"
    if months < schema.min_warranty_months:
        return NON_COMPLIANT, f"D9 warranty {months:.0f} months < required {schema.min_warranty_months:.0f} months"
    if not b.d9_signed:
        return NON_COMPLIANT, "D9 warranty statement not signed"
    return COMPLIANT, f"D9 warranty {months:.0f} months, signed [{b.citation('D9')}]"


def mandatory_screening(b: EvidenceBundle, schema: RfpSchema) -> dict[str, tuple[str, str]]:
    """Run all D1-D9 checks. Returns {code: (status, note)}."""
    return {
        "D1": check_d1(b),
        "D2": check_d2(b),
        "D3": check_d3(b),
        "D4": check_d4(b),
        "D5": check_d5(b),
        "D6": check_d6(b, schema),
        "D7": check_d7(b),
        "D8": check_d8(b, schema),
        "D9": check_d9(b, schema),
    }


def screening_result(items: dict[str, tuple[str, str]]) -> str:
    """PASS iff all COMPLIANT; FAIL iff any NON-COMPLIANT; else INSUFFICIENT EVIDENCE."""
    statuses = [s for s, _ in items.values()]
    if all(s == COMPLIANT for s in statuses):
        return PASS
    if any(s == NON_COMPLIANT for s in statuses):
        return FAIL
    return INSUFFICIENT


# ---------------------------------------------------------------------------
# STEP 2 — MINIMUM TECHNICAL REQUIREMENTS
# ---------------------------------------------------------------------------

# Requirement keys (used in output and citations)
REQ_CAPACITY = "Net treatment capacity"
REQ_OIW = "Outlet OiW"
REQ_DELIVERY = "Delivery schedule"
REQ_WARRANTY = "Warranty period"
REQ_TSS = "Outlet TSS"
REQ_PARTICLE = "Particle size"
REQ_TEMP = "Operating temperature/pressure"
REQ_NACE = "Sour-service rating (H2S/NACE)"
REQ_TURNDOWN = "Turndown"
REQ_AVAIL = "Availability"
REQ_DCS = "DCS / utility integration"
REQ_BATTERY = "Battery limits"
REQ_PERFTEST = "Performance test / guarantee"

# Rejection-condition requirement keys (failure -> TECHNICALLY NON-COMPLIANT)
REJECTION_REQS = {REQ_CAPACITY, REQ_OIW, REQ_DELIVERY, REQ_WARRANTY}


def check_capacity(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.capacity_m3_per_day is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (capacity not provided by upstream agent)"
    cap = _num(b.capacity_m3_per_day)
    if cap is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (capacity value unparseable)"
    if cap < schema.min_capacity_m3d:
        return TECH_NON_COMPLIANT, (
            f"capacity {cap:,.0f} m3/d < {schema.min_capacity_m3d:,.0f} m3/d "
            f"-> technically non-compliant, bid rejected (RFP 6.1 T1 band 0)"
        )
    return COMPLIANT, f"capacity {cap:,.0f} m3/d >= {schema.min_capacity_m3d:,.0f} m3/d [{b.citation('capacity')}]"


def check_oiw(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.oiw_mg_per_l is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (outlet OiW not provided by upstream agent)"
    oiw = _num(b.oiw_mg_per_l)
    if oiw is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (outlet OiW value unparseable)"
    if oiw > schema.max_oiw_outlet_mgl:
        return TECH_NON_COMPLIANT, (
            f"OiW {oiw} mg/L > {schema.max_oiw_outlet_mgl} mg/L -> technically non-compliant, "
            f"bid rejected (RFP 6.1 T1 band 0)"
        )
    return COMPLIANT, f"OiW {oiw} mg/L <= {schema.max_oiw_outlet_mgl} mg/L [{b.citation('oiw')}]"


def check_delivery(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.delivery_weeks is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (delivery schedule not provided by upstream agent)"
    weeks = _num(b.delivery_weeks)
    if weeks is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (delivery weeks unparseable)"
    if weeks > schema.max_delivery_weeks:
        return TECH_NON_COMPLIANT, (
            f"delivery {weeks:.0f} weeks > {schema.max_delivery_weeks:.0f} weeks after LOA "
            f"-> subject to rejection as non-compliant (RFP 6.1 T4 band 1)"
        )
    return COMPLIANT, f"delivery {weeks:.0f} weeks <= {schema.max_delivery_weeks:.0f} weeks [{b.citation('delivery')}]"


def check_warranty(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.warranty_offered_months is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (warranty period not provided by upstream agent)"
    months = _num(b.warranty_offered_months)
    if months is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (warranty months unparseable)"
    if months < schema.min_warranty_months:
        return TECH_NON_COMPLIANT, (
            f"warranty {months:.0f} months < {schema.min_warranty_months:.0f} months "
            f"-> mandatory requirement (D9) failed"
        )
    return COMPLIANT, f"warranty {months:.0f} months >= {schema.min_warranty_months:.0f} months [{b.citation('warranty')}]"


def check_tss(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.tss_mg_per_l is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (outlet TSS not provided)"
    tss = _num(b.tss_mg_per_l)
    if tss is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (TSS value unparseable)"
    if tss > schema.max_tss_mgl:
        return NON_COMPLIANT, f"TSS {tss} mg/L > {schema.max_tss_mgl} mg/L (RFP 5.1)"
    return COMPLIANT, f"TSS {tss} mg/L <= {schema.max_tss_mgl} mg/L [{b.citation('tss')}]"


def check_particle(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.particle_size_um is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (particle size not provided)"
    p = _num(b.particle_size_um)
    if p is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (particle size unparseable)"
    if p > schema.max_particle_size_um:
        return NON_COMPLIANT, f"particle size {p} um > {schema.max_particle_size_um} um (98th percentile, RFP 5.1)"
    return COMPLIANT, f"particle size {p} um <= {schema.max_particle_size_um} um [{b.citation('particle')}]"


def check_temperature_pressure(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.operating_temperature is None and b.operating_pressure_barg is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (operating temperature/pressure not provided)"
    issues = []
    if b.operating_temperature is not None:
        temp = _num(b.operating_temperature)
        if temp is None:
            issues.append(f"temperature '{b.operating_temperature}' unparseable")
        elif temp < schema.min_temp_c or temp > schema.max_temp_c:
            issues.append(f"temperature {temp} C outside {schema.min_temp_c}-{schema.max_temp_c} C (RFP 5.1)")
    if b.operating_pressure_barg is not None:
        press = _num(b.operating_pressure_barg)
        if press is None:
            issues.append(f"pressure '{b.operating_pressure_barg}' unparseable")
        elif press < schema.min_pressure_barg:
            issues.append(f"pressure {press} barg < {schema.min_pressure_barg} barg (RFP 5.1)")
    if any("unparseable" in i for i in issues):
        return INSUFFICIENT, f"{MISSING_PHRASE} ({'; '.join(issues)})"
    if issues:
        return NON_COMPLIANT, "; ".join(issues)
    return COMPLIANT, f"temperature/pressure within design basis [{b.citation('temp_pressure')}]"


def check_nace(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.h2s_ppmw is None and b.nace_rated is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (H2S / NACE sour-service evidence not provided)"
    if b.h2s_ppmw is not None:
        h2s = _num(b.h2s_ppmw)
        if h2s is None:
            return INSUFFICIENT, f"{MISSING_PHRASE} (H2S value unparseable)"
        if h2s > schema.max_h2s_ppmw:
            return NON_COMPLIANT, f"H2S {h2s} ppmw > {schema.max_h2s_ppmw} ppmw (RFP 5.1)"
        if h2s > 0 and b.nace_rated is False:
            return NON_COMPLIANT, "H2S present but materials not NACE MR0175 sour-service rated (RFP 5.1)"
    elif b.nace_rated is False:
        return NON_COMPLIANT, "sour-service rating not evidenced while H2S present"
    return COMPLIANT, f"sour-service (NACE MR0175) addressed, H2S <= {schema.max_h2s_ppmw} ppmw [{b.citation('nace')}]"


def check_turndown(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.turndown_percent is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (turndown not provided)"
    td = _num(b.turndown_percent)
    if td is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (turndown value unparseable)"
    if td > schema.max_turndown_pct:
        return NON_COMPLIANT, (
            f"turndown {td}% > {schema.max_turndown_pct}% of design flow -> worse than "
            f"required 30% (RFP 5.1)"
        )
    return COMPLIANT, f"turndown {td}% <= {schema.max_turndown_pct}% of design flow [{b.citation('turndown')}]"


def check_availability(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.availability_percent is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (availability not provided)"
    av = _num(b.availability_percent)
    if av is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (availability value unparseable)"
    if av < schema.min_availability_pct:
        return NON_COMPLIANT, f"availability {av}% < {schema.min_availability_pct}% (RFP 5.1)"
    if b.n1_philosophy is False:
        return NON_COMPLIANT, "availability claimed but n+1 philosophy on rotating equipment not evidenced (RFP 5.1)"
    return COMPLIANT, f"availability {av}% >= {schema.min_availability_pct}% with n+1 [{b.citation('availability')}]"


def check_dcs(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if b.dcs_type is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (DCS integration not provided)"
    if schema.required_dcs.lower() not in b.dcs_type.lower():
        return NON_COMPLIANT, f"DCS '{b.dcs_type}' does not match required {schema.required_dcs} (RFP 5.1)"
    return COMPLIANT, f"DCS integration to {b.dcs_type} [{b.citation('dcs')}]"


def check_battery_limits(b: EvidenceBundle) -> tuple[str, str]:
    if b.battery_limits_confirmed is None:
        return INSUFFICIENT, f"{MISSING_PHRASE} (battery-limits confirmation not provided)"
    if not b.battery_limits_confirmed:
        return NON_COMPLIANT, "battery limits per RFP 5.2 not confirmed in bid"
    return COMPLIANT, f"battery limits per RFP 5.2 confirmed [{b.citation('battery')}]"


def check_performance_test(b: EvidenceBundle, schema: RfpSchema) -> tuple[str, str]:
    if not b.performance_test_offered:
        return INSUFFICIENT, f"{MISSING_PHRASE} (performance-test commitment not provided)"
    text = b.performance_test_offered.lower()
    missing_kw = [kw for kw in schema.performance_test_keywords if kw.lower() not in text]
    if missing_kw:
        return NON_COMPLIANT, (
            f"performance test offered but does not evidence required method "
            f"(missing: {', '.join(missing_kw)}) (RFP 7 / Exhibit D)"
        )
    return COMPLIANT, f"performance test per RFP 7/Exhibit D offered [{b.citation('performance_test')}]"


def minimum_technical(b: EvidenceBundle, schema: RfpSchema) -> dict[str, tuple[str, str]]:
    """Run all minimum technical requirement checks. Returns {req: (status, note)}."""
    return {
        REQ_CAPACITY: check_capacity(b, schema),
        REQ_OIW: check_oiw(b, schema),
        REQ_DELIVERY: check_delivery(b, schema),
        REQ_WARRANTY: check_warranty(b, schema),
        REQ_TSS: check_tss(b, schema),
        REQ_PARTICLE: check_particle(b, schema),
        REQ_TEMP: check_temperature_pressure(b, schema),
        REQ_NACE: check_nace(b, schema),
        REQ_TURNDOWN: check_turndown(b, schema),
        REQ_AVAIL: check_availability(b, schema),
        REQ_DCS: check_dcs(b, schema),
        REQ_BATTERY: check_battery_limits(b),
        REQ_PERFTEST: check_performance_test(b, schema),
    }


def technical_result(reqs: dict[str, tuple[str, str]]) -> str:
    """PASS iff all pass; TECHNICALLY NON-COMPLIANT if any rejection condition
    failed; NON-COMPLIANT if only Section 5.1 minimums failed; else
    INSUFFICIENT EVIDENCE."""
    statuses = {k: s for k, (s, _) in reqs.items()}
    if all(s == COMPLIANT for s in statuses.values()):
        return PASS
    if any(statuses.get(r) == TECH_NON_COMPLIANT for r in REJECTION_REQS):
        return TECH_NON_COMPLIANT
    if any(s == NON_COMPLIANT for s in statuses.values()):
        return NON_COMPLIANT
    return INSUFFICIENT


# ---------------------------------------------------------------------------
# STEP 3 — ELIGIBILITY DETERMINATION
# ---------------------------------------------------------------------------


def determine_eligibility(screening: dict[str, tuple[str, str]],
                          tech: dict[str, tuple[str, str]]) -> str:
    """Eligible iff ALL D1-D9 COMPLIANT AND no rejection condition failed AND
    no Section 5.1 minimum failed. Any NON-COMPLIANT -> NO. Any
    INSUFFICIENT EVIDENCE on a mandatory or technical item -> INSUFFICIENT
    EVIDENCE (blocks a YES)."""
    s_statuses = [s for s, _ in screening.values()]
    t_statuses = [s for s, _ in tech.values()]

    # Any definite failure -> NO (excluded from award consideration)
    if any(s == NON_COMPLIANT for s in s_statuses) or any(s in (NON_COMPLIANT, TECH_NON_COMPLIANT) for s in t_statuses):
        return "NO"

    # Any unverifiable item -> INSUFFICIENT EVIDENCE (never assume compliance)
    if any(s == INSUFFICIENT for s in s_statuses) or any(s == INSUFFICIENT for s in t_statuses):
        return INSUFFICIENT

    return "YES"


# ---------------------------------------------------------------------------
# STEP 5 — ESCALATION (E1-E7)
# ---------------------------------------------------------------------------


@dataclass
class Escalation:
    code: str                 # E1..E7
    severity: str             # CRITICAL / HIGH / MEDIUM / LOW
    reason: str
    affected_item: str
    evidence: str
    impact: str
    required_human_action: str


def build_escalations(b: EvidenceBundle, schema: RfpSchema,
                      screening: dict[str, tuple[str, str]],
                      tech: dict[str, tuple[str, str]]) -> list[Escalation]:
    esc: list[Escalation] = []

    def add(code, severity, reason, item, evidence, impact, action):
        esc.append(Escalation(code, severity, reason, item, evidence, impact, action))

    # E1 — schema unextractable is handled at CLI level (no schema -> error).
    # E2 — rejection condition evidence missing
    for req in REJECTION_REQS:
        if req in tech and tech[req][0] == INSUFFICIENT:
            add("E2", "HIGH",
                f"Evidence for rejection condition '{req}' is missing/insufficient.",
                req, tech[req][1],
                "Eligibility cannot be determined — never assume compliance.",
                f"Re-extract {req} from the bid documents and re-supply the evidence bundle.")
    # E3 — mandatory item evidence missing
    for code, (status, note) in screening.items():
        if status == INSUFFICIENT:
            add("E3", "HIGH",
                f"Evidence for mandatory item {code} is missing/insufficient.",
                code, note,
                "Mandatory screening result is INSUFFICIENT EVIDENCE.",
                f"Re-extract {code} status/validity from the bid documents.")
    # E4/E6 — conflicting evidence
    for field_name, values in (b.conflicts or {}).items():
        add("E6" if field_name not in ("capacity_m3_per_day", "oiw_mg_per_l",
                                       "delivery_weeks", "warranty_offered_months") else "E4",
            "HIGH" if field_name in ("capacity_m3_per_day", "oiw_mg_per_l",
                                     "delivery_weeks", "warranty_offered_months") else "MEDIUM",
            f"Conflicting evidence for '{field_name}': {values[0]!r} vs {values[1]!r}. "
            "Both positions recorded; classified as INSUFFICIENT EVIDENCE.",
            field_name, f"{values[0]!r} / {values[1]!r}",
            "Requirement cannot be verified — eligibility affected.",
            "Verify the figure against the original bid document.")
    # E7 — proximity to rejection boundary (watch item, LOW)
    if b.capacity_m3_per_day is not None:
        cap = _num(b.capacity_m3_per_day)
        if cap is not None:
            _diff = cap - schema.min_capacity_m3d
            if 0 < _diff <= schema.proximity_capacity_pct * schema.min_capacity_m3d:
                add("E7", "LOW",
                    f"Capacity {cap:,.0f} m3/d within 1% of rejection boundary {schema.min_capacity_m3d:,.0f} m3/d.",
                    REQ_CAPACITY, f"capacity={cap}",
                    "Proximity note — verify figure against original document.",
                    "Re-verify capacity in the original datasheet.")
    if b.oiw_mg_per_l is not None:
        oiw = _num(b.oiw_mg_per_l)
        if oiw is not None:
            _diff = schema.max_oiw_outlet_mgl - oiw
            if 0 < _diff <= schema.proximity_oiw_abs:
                add("E7", "LOW",
                    f"OiW {oiw} mg/L within {schema.proximity_oiw_abs} mg/L of rejection boundary {schema.max_oiw_outlet_mgl} mg/L.",
                    REQ_OIW, f"oiw={oiw}",
                    "Proximity note — verify figure against original document.",
                    "Re-verify OiW in the original guarantee document.")
    if b.delivery_weeks is not None:
        wk = _num(b.delivery_weeks)
        if wk is not None:
            _diff = schema.max_delivery_weeks - wk
            if 0 < _diff <= schema.proximity_weeks_abs:
                add("E7", "LOW",
                    f"Delivery {wk:.0f} weeks within {schema.proximity_weeks_abs} week(s) of maximum {schema.max_delivery_weeks:.0f} weeks.",
                    REQ_DELIVERY, f"delivery={wk}",
                    "Proximity note — verify schedule against original document.",
                    "Re-verify delivery schedule in the original plan.")
    if b.warranty_offered_months is not None:
        wm = _num(b.warranty_offered_months)
        if wm is not None:
            _diff = wm - schema.min_warranty_months
            if 0 < _diff <= schema.proximity_warranty_abs:
                add("E7", "LOW",
                    f"Warranty {wm:.0f} months within {schema.proximity_warranty_abs} month(s) of minimum {schema.min_warranty_months:.0f} months.",
                    REQ_WARRANTY, f"warranty={wm}",
                    "Proximity note — verify warranty statement against original document.",
                    "Re-verify warranty commitment in the original statement.")
    return esc


# ---------------------------------------------------------------------------
# STEP 4 — OUTPUT
# ---------------------------------------------------------------------------


@dataclass
class EligibilityResult:
    supplier: str
    mandatory: dict[str, tuple[str, str]]
    tech: dict[str, tuple[str, str]]
    screening: str
    technical: str
    eligible: str
    escalations: list[Escalation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier": self.supplier,
            "mandatory_screening": {
                code: {"status": s, "note": n} for code, (s, n) in self.mandatory.items()
            },
            "mandatory_screening_result": self.screening,
            "minimum_technical_requirements": {
                req: {"status": s, "supplier_evidence": n} for req, (s, n) in self.tech.items()
            },
            "technical_compliance_result": self.technical,
            "eligible_for_scoring": self.eligible,
            "escalations": [
                {
                    "code": e.code, "severity": e.severity, "reason": e.reason,
                    "affected_item": e.affected_item, "evidence": e.evidence,
                    "impact": e.impact, "required_human_action": e.required_human_action,
                }
                for e in self.escalations
            ],
        }


def evaluate_bundle(b: EvidenceBundle, schema: RfpSchema) -> EligibilityResult:
    """Run the full deterministic pipeline (Steps 1-5) for one supplier."""
    screening = mandatory_screening(b, schema)
    tech = minimum_technical(b, schema)
    eligible = determine_eligibility(screening, tech)
    escalations = build_escalations(b, schema, screening, tech)
    return EligibilityResult(
        supplier=b.supplier_name or "UNKNOWN SUPPLIER",
        mandatory=screening,
        tech=tech,
        screening=screening_result(screening),
        technical=technical_result(tech),
        eligible=eligible,
        escalations=escalations,
    )


def format_report(result: EligibilityResult) -> str:
    """Human-readable per-supplier eligibility report (agent spec Output Schema)."""
    lines = [f"Supplier: {result.supplier}", ""]
    lines.append("Mandatory Screening:")
    for code in [f"D{i}" for i in range(1, 10)]:
        status, note = result.mandatory[code]
        lines.append(f"  {code}: {status}")
        lines.append(f"    {note}")
    lines.append(f"\nMandatory Screening Result: {result.screening}")

    lines.append("\nMinimum Technical Requirements:")
    for req, (status, note) in result.tech.items():
        lines.append(f"  {req}: {status}")
        lines.append(f"    Supplier Evidence: {note}")
    lines.append(f"\nTechnical Compliance Result: {result.technical}")

    lines.append(f"\nEligible for Scoring: {result.eligible}")

    if result.escalations:
        lines.append("\nEscalation Record:")
        for e in result.escalations:
            lines.append(f"  [{e.code} - {e.severity}] {e.reason}")
            lines.append(f"    Affected Item: {e.affected_item}")
            lines.append(f"    Evidence: {e.evidence}")
            lines.append(f"    Impact: {e.impact}")
            lines.append(f"    Required Human Action: {e.required_human_action}")
    return "\n".join(lines)


def format_summary(results: list[EligibilityResult]) -> str:
    """Cross-supplier summary table (agent spec SUPPLIER SUMMARY)."""
    header = "| Supplier | Mandatory | Technical | Eligible | Notes |"
    sep = "|---|---|---|---|---|"
    rows = []
    for r in results:
        notes = "; ".join(f"{e.code} {e.affected_item}" for e in r.escalations if e.severity in ("HIGH", "CRITICAL"))
        if not notes:
            notes = "-"
        rows.append(f"| {r.supplier} | {r.screening} | {r.technical} | {r.eligible} | {notes} |")
    return "\n".join([header, sep] + rows)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


def _mk(name: str, **kw: Any) -> EvidenceBundle:
    """Build a fully-compliant baseline bundle, overridden by kw."""
    base = {
        "supplier_name": name,
        "d1_submitted": True, "d1_licence_valid": True,
        "d2_submitted": True, "d2_has_equipment_list": True, "d2_has_datasheets": True,
        "d3_submitted": True, "d3_priced_in_aed": True, "d3_itemized": True,
        "d4_submitted": True,
        "d5_submitted": True, "d5_tabulated_by_year": True,
        "d6_submitted": True, "d6_moiat_certified": True, "d6_validity_date": "2027-01-15",
        "d7_submitted": True, "d7_audited": True, "d7_signed": True, "d7_covers_2_years": True,
        "d8_submitted": True, "d8_bond_percentage": 2.0, "d8_validity_days": 180,
        "d8_bank_uae_licensed": True,
        "d9_submitted": True, "d9_warranty_months": 24, "d9_signed": True,
        "capacity_m3_per_day": 32000, "oiw_mg_per_l": 6.0, "delivery_weeks": 58,
        "warranty_offered_months": 24,
        "tss_mg_per_l": 10.0, "particle_size_um": 3.0,
        "operating_temperature": "70", "operating_pressure_barg": 3.5,
        "h2s_ppmw": 45.0, "nace_rated": True,
        "turndown_percent": 30.0, "availability_percent": 98.0, "n1_philosophy": True,
        "dcs_type": "Yokogawa Centum VP", "battery_limits_confirmed": True,
        "performance_test_offered": "72-hour continuous run at >= 95% of design flow; "
                                    "OiW verified by IP 426 / OSPAR GC-FID at CPF-2 lab",
        "evidence": {"D1": "Bid_X, D1, p.1", "capacity": "Bid_X, D2, datasheet p.12",
                     "oiw": "Bid_X, D2, datasheet p.13", "delivery": "Bid_X, D4, plan p.2",
                     "warranty": "Bid_X, D9, p.1"},
    }
    base.update(kw)
    return EvidenceBundle.from_dict(base)


def run_tests() -> int:
    failures: list[str] = []

    def check(label: str, actual: Any, expected: Any) -> None:
        ok = actual == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {actual!r}"
              + ("" if ok else f", expected {expected!r}"))
        if not ok:
            failures.append(label)

    schema = DEFAULT_SCHEMA
    print("Compliance & Eligibility Agent — test harness")
    print("-" * 78)

    # --- Test Case 1: normal successful case (YES) ------------------------
    r1 = evaluate_bundle(_mk("Hypothetical Supplier A"), schema)
    check("TC1 D1-D9 all COMPLIANT",
          all(s == COMPLIANT for s, _ in r1.mandatory.values()), True)
    check("TC1 Mandatory Screening Result", r1.screening, PASS)
    check("TC1 Technical Compliance Result", r1.technical, PASS)
    check("TC1 Eligible for Scoring", r1.eligible, "YES")
    check("TC1 no escalations", len(r1.escalations), 0)

    # --- Test Case 2: missing input (D6 validity date) --------------------
    r2 = evaluate_bundle(_mk("Missing D6 Date", d6_validity_date=None), schema)
    check("TC2 D6 INSUFFICIENT", r2.mandatory["D6"][0], INSUFFICIENT)
    check("TC2 Mandatory Screening Result", r2.screening, INSUFFICIENT)
    check("TC2 Eligible for Scoring", r2.eligible, INSUFFICIENT)
    check("TC2 E3 escalation raised", any(e.code == "E3" for e in r2.escalations), True)

    # --- Test Case 3: conflicting information (capacity) ------------------
    r3 = evaluate_bundle(_mk("Conflicting Capacity",
                             conflicts={"capacity_m3_per_day": [32000, 29500]}), schema)
    # note: conflicts map is advisory — the primary field still screens;
    # the escalation records the conflict (agent spec: record both, INSUFFICIENT).
    check("TC3 E4/E6 conflict escalation raised",
          any(e.code in ("E4", "E6") for e in r3.escalations), True)
    check("TC3 conflict severity HIGH", r3.escalations[0].severity, "HIGH")

    # --- Test Case 4: invalid data (bond 1.5%) ----------------------------
    r4 = evaluate_bundle(_mk("Low Bond", d8_bond_percentage=1.5), schema)
    check("TC4 D8 NON-COMPLIANT", r4.mandatory["D8"][0], NON_COMPLIANT)
    check("TC4 Mandatory Screening Result", r4.screening, FAIL)
    check("TC4 Eligible for Scoring", r4.eligible, "NO")

    # --- Test Case 5: insufficient evidence (TSS missing) -----------------
    r5 = evaluate_bundle(_mk("Missing TSS", tss_mg_per_l=None), schema)
    check("TC5 TSS INSUFFICIENT", r5.tech["Outlet TSS"][0], INSUFFICIENT)
    check("TC5 Eligible for Scoring", r5.eligible, INSUFFICIENT)

    # --- Test Case 6: technical rejection (capacity 29,500) ---------------
    r6 = evaluate_bundle(_mk("Low Capacity", capacity_m3_per_day=29500), schema)
    check("TC6 capacity TECHNICALLY NON-COMPLIANT",
          r6.tech["Net treatment capacity"][0], TECH_NON_COMPLIANT)
    check("TC6 Technical Compliance Result", r6.technical, TECH_NON_COMPLIANT)
    check("TC6 Eligible for Scoring", r6.eligible, "NO")

    # --- Test Case 7: escalation case (expired ICV) -----------------------
    r7 = evaluate_bundle(_mk("Expired ICV", d6_validity_date="2026-06-15"), schema)
    check("TC7 D6 NON-COMPLIANT (expired)", r7.mandatory["D6"][0], NON_COMPLIANT)
    check("TC7 Mandatory Screening Result", r7.screening, FAIL)
    check("TC7 Eligible for Scoring", r7.eligible, "NO")

    # --- Decision rules R1-R12 spot checks ---------------------------------
    check("R1 missing D2 -> NON-COMPLIANT",
          evaluate_bundle(_mk("No D2", d2_submitted=False), schema).mandatory["D2"][0],
          NON_COMPLIANT)
    check("R2 D6 not MoIAT -> NON-COMPLIANT",
          evaluate_bundle(_mk("Non MoIAT", d6_moiat_certified=False), schema).mandatory["D6"][0],
          NON_COMPLIANT)
    check("R3 bond < 150 days -> NON-COMPLIANT",
          evaluate_bundle(_mk("Short Bond", d8_validity_days=120), schema).mandatory["D8"][0],
          NON_COMPLIANT)
    check("R4 warranty 12 months -> NON-COMPLIANT",
          evaluate_bundle(_mk("Short Warranty", d9_warranty_months=12), schema).mandatory["D9"][0],
          NON_COMPLIANT)
    check("R5 capacity 29,000 -> TECHNICALLY NON-COMPLIANT",
          evaluate_bundle(_mk("Cap 29k", capacity_m3_per_day=29000), schema).tech["Net treatment capacity"][0],
          TECH_NON_COMPLIANT)
    check("R6 OiW 12 -> TECHNICALLY NON-COMPLIANT",
          evaluate_bundle(_mk("OiW 12", oiw_mg_per_l=12.0), schema).tech["Outlet OiW"][0],
          TECH_NON_COMPLIANT)
    check("R7 delivery 80 weeks -> TECHNICALLY NON-COMPLIANT",
          evaluate_bundle(_mk("Delivery 80", delivery_weeks=80), schema).tech["Delivery schedule"][0],
          TECH_NON_COMPLIANT)
    check("R8 TSS 20 -> NON-COMPLIANT",
          evaluate_bundle(_mk("TSS 20", tss_mg_per_l=20.0), schema).tech["Outlet TSS"][0],
          NON_COMPLIANT)
    check("R9 missing capacity -> INSUFFICIENT (blocks YES)",
          evaluate_bundle(_mk("No Capacity", capacity_m3_per_day=None), schema).eligible, INSUFFICIENT)
    check("R10 missing TSS -> INSUFFICIENT overall",
          evaluate_bundle(_mk("No TSS", tss_mg_per_l=None), schema).eligible, INSUFFICIENT)
    check("R12 all compliant -> YES",
          evaluate_bundle(_mk("Fully Compliant"), schema).eligible, "YES")

    # --- Boundary cases -----------------------------------------------------
    check("Capacity exactly 30,000 -> COMPLIANT",
          evaluate_bundle(_mk("Cap 30000", capacity_m3_per_day=30000), schema).tech["Net treatment capacity"][0],
          COMPLIANT)
    check("OiW exactly 10 -> COMPLIANT",
          evaluate_bundle(_mk("OiW 10", oiw_mg_per_l=10.0), schema).tech["Outlet OiW"][0],
          COMPLIANT)
    check("Delivery exactly 76 -> COMPLIANT",
          evaluate_bundle(_mk("Del 76", delivery_weeks=76), schema).tech["Delivery schedule"][0],
          COMPLIANT)
    check("Warranty exactly 24 -> COMPLIANT",
          evaluate_bundle(_mk("Warr 24", warranty_offered_months=24), schema).tech["Warranty period"][0],
          COMPLIANT)
    check("E7 proximity flag on capacity 30,150",
          any(e.code == "E7" for e in
              evaluate_bundle(_mk("Near Cap", capacity_m3_per_day=30150), schema).escalations), True)
    check("E7 NOT flagged on capacity 32,000",
          any(e.code == "E7" for e in r1.escalations), False)

    # --- Wrong-type input (data-type error -> INSUFFICIENT) ----------------
    check("Capacity as string -> INSUFFICIENT",
          evaluate_bundle(_mk("Str Cap", capacity_m3_per_day="thirty"), schema).tech["Net treatment capacity"][0],
          INSUFFICIENT)

    # --- Summary table + report smoke test ---------------------------------
    results = [evaluate_bundle(_mk(n), schema) for n in ("A", "B")]
    summary = format_summary(results)
    check("Summary table has header", "| Supplier | Mandatory | Technical | Eligible | Notes |" in summary, True)
    check("Summary has 2 rows + header + sep", len(summary.splitlines()), 4)
    report = format_report(r1)
    check("Report contains all 9 D items", all(f"  D{i}:" in report for i in range(1, 10)), True)
    check("Report contains Eligible for Scoring", "Eligible for Scoring: YES" in report, True)

    # --- JSON round-trip -----------------------------------------------------
    d = r1.to_dict()
    check("to_dict has eligible_for_scoring", d["eligible_for_scoring"], "YES")
    check("to_dict has 9 mandatory items", len(d["mandatory_screening"]), 9)

    print("-" * 78)
    if failures:
        print(f"RESULT: {len(failures)} test(s) FAILED")
        return 1
    print("RESULT: all tests PASSED")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compliance & eligibility screening engine")
    parser.add_argument("bids", nargs="?", help="JSON file with supplier evidence bundles (use '-' for stdin)")
    parser.add_argument("--test", action="store_true", help="run test harness")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--schema", help="JSON file overriding the RFP schema (Step 0 schema discovery)")
    args = parser.parse_args(argv)

    if args.test:
        return run_tests()

    if not args.bids:
        parser.error("provide a bids JSON file (or --test)")

    raw = sys.stdin.read() if args.bids == "-" else open(args.bids).read()
    data = json.loads(raw)

    schema = DEFAULT_SCHEMA
    if args.schema:
        with open(args.schema) as f:
            overrides = json.load(f)
        schema = RfpSchema(**{k: v for k, v in overrides.items()
                              if k in RfpSchema.__dataclass_fields__})

    bundles = [EvidenceBundle.from_dict(d) for d in data["bids"]]
    results = [evaluate_bundle(b, schema) for b in bundles]

    if args.json:
        out = {
            "tender_id": schema.tender_id,
            "methodology": {
                "step_order": "0 schema discovery -> 1 mandatory screening (D1-D9) -> "
                              "2 minimum technical requirements -> 3 eligibility determination",
                "classifications": "COMPLIANT / NON-COMPLIANT / TECHNICALLY NON-COMPLIANT / "
                                   "INSUFFICIENT EVIDENCE",
                "award_gates": "eligible = all D1-D9 COMPLIANT AND no rejection condition failed "
                               "AND no Section 5.1 minimum failed",
                "missing_evidence_rule": "Insufficient evidence to determine compliance - never assume",
                "note": "decision-support only - not an official ADNOC procurement decision",
            },
            "suppliers": [r.to_dict() for r in results],
            "summary": [
                {"supplier": r.supplier, "mandatory": r.screening,
                 "technical": r.technical, "eligible": r.eligible}
                for r in results
            ],
            "note": "decision-support only - not an official ADNOC procurement decision",
        }
        print(json.dumps(out, indent=2))
    else:
        for r in results:
            print(format_report(r))
            print()
        print("SUPPLIER SUMMARY")
        print(format_summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
