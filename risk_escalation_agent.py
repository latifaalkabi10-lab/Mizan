#!/usr/bin/env python3
"""
Risk & Escalation Agent
=======================
Python implementation of the Risk & Escalation Agent — the final gatekeeper of
the ADNOC Upstream Procurement Evaluation System (see risk_escalation_agent.md).

Pipeline position:
    Procurement Evidence & Retrieval Agent
    -> Bid Evaluation Agent
    -> RISK & ESCALATION AGENT (this module)
    -> Human Procurement Engineer (via escalation message)

Primary goal (from the spec): prevent the system from making unsupported,
unsafe, or non-compliant procurement recommendations — while never blocking a
sound evaluation on a fabricated or speculative concern.

Four value modes (never duplicated upstream):
    1. VERIFY      — cross-check evidence behind every critical score
    2. INTEGRATE   — look across ALL suppliers (portfolio risks are invisible
                     to per-supplier scores)
    3. JUDGE       — process fidelity: Plow set, eligibility gates, step order,
                     rounding, arithmetic recomputation
    4. DECIDE      — the binary pass-through vs block call

RFP-agnostic: all RFP-specific parameters come from the schema (Step 0),
never assumed. Ships with the ADNOC-LCIG/RFP/2026-0412 default schema.

This module is SELF-CONTAINED — it does not import the Bid Evaluation Agent.
Band tables are embedded (RFP Section 6) so the risk agent can independently
recompute bands and arithmetic without trusting upstream numbers. This is the
"recompute arithmetic yourself" rule from the spec: never trust a total, a
Plow set, or a worked example without independent recalculation.

Evidence discipline (anti-hallucination contract):
    - VERIFIED    = directly observed in a cited source   -> may be a finding
    - INFERRED    = derived from verified observations     -> finding only if
                   HIGH-confidence with reasoning chain written out
    - UNRESOLVED  = needed but unestablishable from dataset -> evidence gap,
                   never a finding; escalate only if material
    - No citation -> no finding. "Not found" != "does not exist".

Usage:
    python3 risk_escalation_agent.py --test                          # test harness
    python3 risk_escalation_agent.py --handoff handoff.json          # review (arithmetic only)
    python3 risk_escalation_agent.py --handoff h.json --bids bids.json  # + band cross-check
    python3 risk_escalation_agent.py --handoff h.json --bids b.json --json   # machine output
    python3 risk_escalation_agent.py --handoff h.json --bids b.json --rfp rfp.json

Stdlib only. No dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Schema (Step 0 — discovered from the RFP, never assumed)
# ---------------------------------------------------------------------------

RISK_CATEGORIES: dict[int, str] = {
    1: "Completeness & document integrity",
    2: "Technical & performance",
    3: "Commercial & financial",
    4: "HSE & safety",
    5: "Local content / ICV & national value",
    6: "Evidence integrity & inter-agent consistency",
    7: "Process & contractual compliance",
    8: "Procurement integrity & anti-corruption",
    9: "Execution & interface risk (brownfield)",
    10: "Portfolio & market-level risk",
}


@dataclass
class RfpSchema:
    """Evaluation schema extracted from the RFP (Step 0)."""

    tender_id: str = "ADNOC-LCIG/RFP/2026-0412"
    # Mandatory document codes (Section 4)
    mandatory_docs: list[str] = field(default_factory=lambda: [f"D{i}" for i in range(1, 10)])
    # Rejection conditions (Section 5.1)
    min_capacity_m3d: float = 30_000.0
    max_oiw_outlet: float = 10.0
    max_delivery_weeks: float = 76.0
    min_warranty_months: float = 24.0
    # Scoring model (Section 6)
    tech_weight: float = 40.0
    commercial_weight: float = 30.0
    hse_weight: float = 15.0
    icv_weight: float = 15.0
    max_band: int = 5
    icv_cap_pct: float = 60.0
    fx_rate_aed_per_usd: float = 3.6725
    trir_band5_max: float = 0.20
    # Key dates & validity
    bid_deadline: str = "16 Jul 2026 14:00"
    bid_deadline_iso: str = "2026-07-16"
    bid_validity_days: int = 120
    bond_pct: float = 2.0
    bond_validity_days: int = 150
    # P1 threshold-proximity margins (fraction of threshold, or absolute)
    proximity_capacity_pct: float = 0.02       # e.g. capacity within 2% of 30,000
    proximity_oiw_abs: float = 1.0             # within 1 mg/L of 10
    proximity_weeks_abs: float = 2.0           # within 2 weeks of 76
    proximity_trir_abs: float = 0.02           # within 0.02 of 0.20
    # Portfolio checks (category 10)
    min_eligible_bidders: int = 3              # fewer -> shallow competition
    price_cv_signal_threshold: float = 0.05    # CV < 5% -> possible signalling (P9)
    price_cv_wide_threshold: float = 0.60      # CV > 60% -> implausibly wide (P3)
    price_outlier_factor: float = 2.0          # price > 2x or < 0.5x median -> outlier
    ranking_sensitivity_gap: float = 2.0       # top-2 gap < 2 points -> fragile (P2)
    # P5 conditional-content markers (substring match on bid conditions)
    conditional_markers: list[str] = field(default_factory=lambda: [
        "subject to", "alternate", "deviation", "conditional", "qualified",
        "pending", "upon", "provided that", "excludes", "excluded",
    ])
    # P9 collusion: identical-total tolerance (AED)
    collusion_total_tolerance: float = 0.01
    # P10: extraction-quality values that mean "poor"
    low_quality_markers: list[str] = field(default_factory=lambda: [
        "low", "poor", "unreadable", "scan", "ocr", "illegible", "blurry",
    ])
    # Scope-specific: brownfield tie-in requirements (Exhibit C)
    brownfield: bool = True
    required_integrity_declarations: list[str] = field(default_factory=lambda: [
        "anti-commission", "conflict-of-interest", "sanctions",
    ])


DEFAULT_SCHEMA = RfpSchema()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class RiskFinding:
    """One row of the risk register."""

    supplier: str
    category: int            # 1-10 (RISK_CATEGORIES)
    finding: str             # observation + why it matters
    evidence: str            # citation (no citation -> no finding)
    claim_class: str         # VERIFIED | INFERRED | UNRESOLVED
    materiality: str         # HIGH | MEDIUM | LOW
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW (escalation level)
    action: str = "watch"    # ESCALATE | watch
    flag: str = ""           # predictive flag code, e.g. P1/P8 (optional)


@dataclass
class EscalationMessage:
    """Structured escalation message for the human procurement engineer."""

    tender_id: str
    supplier: str
    severity: str            # CRITICAL / HIGH / MEDIUM / LOW
    reason: str              # observation + reasoning chain, 1-2 sentences
    criterion: str           # e.g. Mandatory Screening (D6), Technical (T1)
    evidence: str            # citation(s)
    recommended_action: str  # actionable step for the engineer


@dataclass
class ReviewResult:
    """Full review: risk register + verdict."""

    tender_id: str
    schema: RfpSchema
    findings: list[RiskFinding] = field(default_factory=list)
    escalations: list[EscalationMessage] = field(default_factory=list)
    plow_reported: float = 0.0
    plow_recomputed: float = 0.0
    plow_set_ok: bool = True
    eligible_count: int = 0

    # -- verdict -----------------------------------------------------------
    @property
    def has_critical(self) -> bool:
        return any(f.severity == "CRITICAL" for f in self.findings)

    @property
    def has_high(self) -> bool:
        return any(f.severity == "HIGH" for f in self.findings)

    @property
    def has_medium(self) -> bool:
        return any(f.materiality == "MEDIUM" for f in self.findings)

    @property
    def escalation_required(self) -> bool:
        return any(f.action == "ESCALATE" for f in self.findings)

    @property
    def risk_status(self) -> str:
        if self.has_critical:
            return "HUMAN REVIEW REQUIRED"
        if self.has_high:
            return "HIGH"
        if self.has_medium:
            return "MEDIUM"
        return "LOW"

    @property
    def confidence(self) -> str:
        """Calibrate from the risk register, not from optimism."""
        if self.has_critical or self.has_high:
            return "LOW"
        if self.has_medium:
            return "MEDIUM"
        return "HIGH"


# ---------------------------------------------------------------------------
# Raw bid model — used ONLY to independently cross-check upstream numbers.
# The risk agent does not gather evidence; if raw data is not supplied it
# simply skips cross-checks (never invents values).
# ---------------------------------------------------------------------------


@dataclass
class RawBid:
    """Raw bid data as extracted by the upstream Evidence & Retrieval Agent.

    Every field is Optional: None means the upstream agent did not provide
    the evidence. None is NEVER coerced to a default or guessed.
    """

    name: str
    # Mandatory screening (D1-D9): doc code -> submitted?
    docs: dict[str, bool] = field(default_factory=dict)
    icv_cert_valid: Optional[bool] = None          # D6 validity on bid submission date
    icv_cert_valid_until: Optional[str] = None     # ISO date, e.g. "2026-07-01"
    icv_cert_issuer: Optional[str] = None          # e.g. "MoIAT-certified body"
    bond_valid_days: Optional[int] = None          # D8: bond validity in days
    bond_pct: Optional[float] = None               # D8: bond % of bid value
    # Minimum technical requirements (Section 5.1)
    capacity_m3d: Optional[float] = None
    oiw_outlet: Optional[float] = None
    weeks_to_completion: Optional[float] = None
    warranty_months: Optional[float] = None
    # Technical (Section 6.1)
    gcc_refs: Optional[int] = None
    years_exp: Optional[float] = None
    # Commercial (Section 6.2)
    price_aed: Optional[float] = None
    currency: Optional[str] = None
    # HSE (Section 6.3)
    trir: Optional[float] = None
    fatality: Optional[bool] = None
    iso45001: Optional[bool] = None
    iso14001: Optional[bool] = None
    # ICV (Section 6.4)
    icv_pct: Optional[float] = None
    # P5 conditional content (list of strings found in the bid)
    conditions: list[str] = field(default_factory=list)
    # P9 collusion indicators: line-item prices + total
    line_items: list[float] = field(default_factory=list)
    total_price: Optional[float] = None
    # P10 extraction quality: field key -> quality marker
    extraction_quality: dict[str, str] = field(default_factory=dict)
    # P11 performance guarantee
    guarantee_test_method: Optional[str] = None    # e.g. "72-hr run, IP 426/OSPAR"
    # Category 8: integrity declarations submitted.
    # None = upstream did not extract this field (NOT a finding — "not found
    # in the dataset" != "does not exist"). [] = extracted and nothing was
    # submitted (a real finding).
    integrity_declarations: Optional[list[str]] = None
    # Category 9: brownfield execution plan
    execution_plan: Optional[bool] = None          # tie-in/shutdown/interface plan present
    # Evidence bookkeeping: field key -> citation string
    evidence: dict[str, str] = field(default_factory=dict)

    # -- screening ---------------------------------------------------------

    def missing_docs(self, schema: RfpSchema) -> list[str]:
        """Mandatory docs the RFP requires that were NOT submitted.

        An absent key from the upstream agent counts as a missing document,
        never as silent compliance.
        """
        return [code for code in schema.mandatory_docs if not self.docs.get(code, False)]

    def screening_status(self, schema: RfpSchema) -> str:
        """Step 1 equivalent: PASS / CONDITIONALLY NON-COMPLIANT / UNVERIFIABLE."""
        missing = self.missing_docs(schema)
        if missing:
            return f"CONDITIONALLY NON-COMPLIANT - missing: {', '.join(missing)}"
        if self.icv_cert_valid is None:
            return "UNVERIFIABLE - D6 ICV certificate validity not provided by upstream agent"
        if not self.icv_cert_valid:
            return "CONDITIONALLY NON-COMPLIANT - D6 ICV certificate not valid on bid due date"
        return "PASS"

    @property
    def mandatory_pass(self) -> bool:
        return self.screening_status(DEFAULT_SCHEMA) == "PASS"

    def mandatory_pass_for(self, schema: RfpSchema) -> bool:
        return self.screening_status(schema) == "PASS"

    # -- minimum technical requirements ------------------------------------

    def tech_requirement_failures(self, schema: RfpSchema) -> list[str]:
        """Step 2 equivalent: stated rejection conditions breached.
        Missing data is never a pass."""
        fails = []
        if self.capacity_m3d is not None and self.capacity_m3d < schema.min_capacity_m3d:
            fails.append(f"net capacity < {schema.min_capacity_m3d:,.0f} m³/d")
        elif self.capacity_m3d is None:
            fails.append("capacity not provided (Insufficient evidence to calculate this criterion.)")
        if self.oiw_outlet is not None and self.oiw_outlet > schema.max_oiw_outlet:
            fails.append(f"outlet OiW > {schema.max_oiw_outlet} mg/L monthly average")
        elif self.oiw_outlet is None:
            fails.append("outlet OiW not provided (Insufficient evidence to calculate this criterion.)")
        if self.weeks_to_completion is not None and self.weeks_to_completion > schema.max_delivery_weeks:
            fails.append(f"delivery > {schema.max_delivery_weeks:,.0f} weeks contractual maximum")
        elif self.weeks_to_completion is None:
            fails.append("delivery schedule not provided (Insufficient evidence to calculate this criterion.)")
        if self.warranty_months is not None and self.warranty_months < schema.min_warranty_months:
            fails.append(f"warranty < {schema.min_warranty_months:,.0f} months from acceptance")
        elif self.warranty_months is None:
            fails.append("warranty period not provided (Insufficient evidence to calculate this criterion.)")
        return fails

    @property
    def min_tech_pass(self) -> bool:
        return not self.tech_requirement_failures(DEFAULT_SCHEMA)

    def min_tech_pass_for(self, schema: RfpSchema) -> bool:
        return not self.tech_requirement_failures(schema)

    @property
    def eligible_for_award(self) -> bool:
        """Award gate: passes BOTH mandatory screening AND min technical reqs."""
        return self.mandatory_pass and self.min_tech_pass


def raw_bid_from_dict(d: dict[str, Any]) -> RawBid:
    """Load a raw bid from the upstream JSON schema. Absent/None stay None."""
    def opt_float(key: str) -> Optional[float]:
        v = d.get(key)
        return None if v is None else float(v)

    def opt_int(key: str) -> Optional[int]:
        v = d.get(key)
        return None if v is None else int(v)

    def opt_bool(key: str) -> Optional[bool]:
        v = d.get(key)
        return None if v is None else bool(v)

    price_aed = opt_float("price_aed")
    if price_aed is None:
        raw_price = opt_float("price")
        if raw_price is not None:
            price_aed = convert_to_aed(raw_price, d.get("currency"),
                                       DEFAULT_SCHEMA.fx_rate_aed_per_usd)

    return RawBid(
        name=d["name"],
        docs={k: bool(v) for k, v in d.get("docs", {}).items()},
        icv_cert_valid=opt_bool("icv_cert_valid"),
        icv_cert_valid_until=d.get("icv_cert_valid_until"),
        icv_cert_issuer=d.get("icv_cert_issuer"),
        bond_valid_days=opt_int("bond_valid_days"),
        bond_pct=opt_float("bond_pct"),
        capacity_m3d=opt_float("capacity_m3d"),
        oiw_outlet=opt_float("oiw_outlet"),
        weeks_to_completion=opt_float("weeks_to_completion"),
        warranty_months=opt_float("warranty_months"),
        gcc_refs=opt_int("gcc_refs"),
        years_exp=opt_float("years_exp"),
        price_aed=price_aed,
        currency=d.get("currency"),
        trir=opt_float("trir"),
        fatality=opt_bool("fatality"),
        iso45001=opt_bool("iso45001"),
        iso14001=opt_bool("iso14001"),
        icv_pct=opt_float("icv_pct"),
        conditions=list(d.get("conditions", []) or []),
        line_items=[float(x) for x in (d.get("line_items", []) or [])],
        total_price=opt_float("total_price"),
        extraction_quality=dict(d.get("extraction_quality", {}) or {}),
        guarantee_test_method=d.get("guarantee_test_method"),
        integrity_declarations=(
            [str(x).lower() for x in d["integrity_declarations"]]
            if "integrity_declarations" in d else None),
        execution_plan=opt_bool("execution_plan"),
        evidence=dict(d.get("evidence", {}) or {}),
    )


def convert_to_aed(amount: Optional[float], currency: Optional[str],
                   fx_rate_aed_per_usd: float) -> Optional[float]:
    """Convert a price to AED per RFP Section 6.2 / ITB 2.

    AED prices pass through unchanged. USD prices are converted at the RFP's
    reference rate. Other currencies are deviations that the upstream agent is
    expected to resolve before handoff — if they reach here unconverted, the
    price is marked as insufficient evidence (never guessed).
    """
    if amount is None:
        return None
    if currency in (None, "", "AED"):
        return round(amount, 2)
    if currency == "USD":
        return round(amount * fx_rate_aed_per_usd, 2)
    return None  # deliberately None — not a guess


# ---------------------------------------------------------------------------
# Band tables (RFP Section 6) — embedded so the risk agent recomputes bands
# INDEPENDENTLY. Every function returns (band, note); band=None = missing
# evidence (never coerced).
# ---------------------------------------------------------------------------


def band_t1(capacity_m3d: Optional[float], oiw_outlet: Optional[float],
            schema: RfpSchema = DEFAULT_SCHEMA) -> tuple[Optional[int], str]:
    """T1 Process capacity & performance guarantee (weight 15)."""
    if capacity_m3d is None or oiw_outlet is None:
        return None, "Insufficient evidence to calculate this criterion. (T1: capacity or outlet OiW not provided by upstream agent)"
    if capacity_m3d < schema.min_capacity_m3d or oiw_outlet > schema.max_oiw_outlet:
        return 0, "capacity < threshold OR OiW > limit -> technically non-compliant (rejected)"
    if capacity_m3d >= 33_000 and oiw_outlet <= 5.0:
        return 5, "capacity >= 33,000 m³/d AND OiW <= 5 mg/L"
    if capacity_m3d >= 31_500 and oiw_outlet <= 8.0:
        return 4, "capacity >= 31,500 m³/d AND OiW <= 8 mg/L"
    return 3, "capacity >= 30,000 m³/d AND OiW <= 10 mg/L (meets specification)"


def band_t2(gcc_refs: Optional[int]) -> tuple[Optional[int], str]:
    """T2 Technology track record, GCC refs >= 20,000 m³/d, last 10 yrs (10)."""
    if gcc_refs is None:
        return None, "Insufficient evidence to calculate this criterion. (T2: GCC reference count not provided by upstream agent)"
    if gcc_refs >= 8:
        return 5, f"{gcc_refs} references (>= 8)"
    if gcc_refs >= 5:
        return 4, f"{gcc_refs} references (5-7)"
    if gcc_refs >= 3:
        return 3, f"{gcc_refs} references (3-4)"
    if gcc_refs >= 1:
        return 2, f"{gcc_refs} references (1-2)"
    return 1, "no comparable GCC reference"


def band_t3(years_exp: Optional[float]) -> tuple[Optional[int], str]:
    """T3 Company experience & organisation (8)."""
    if years_exp is None:
        return None, "Insufficient evidence to calculate this criterion. (T3: years of experience not provided by upstream agent)"
    if years_exp >= 15:
        return 5, f"{years_exp} years (>= 15)"
    if years_exp >= 10:
        return 4, f"{years_exp} years (10-14)"
    if years_exp >= 6:
        return 3, f"{years_exp} years (6-9)"
    if years_exp >= 3:
        return 2, f"{years_exp} years (3-5)"
    return 1, f"{years_exp} years (< 3)"


def band_t4(weeks: Optional[float],
            schema: RfpSchema = DEFAULT_SCHEMA) -> tuple[Optional[int], str]:
    """T4 Delivery schedule, weeks LOA -> mechanical completion (7)."""
    if weeks is None:
        return None, "Insufficient evidence to calculate this criterion. (T4: delivery schedule not provided by upstream agent)"
    max_w = schema.max_delivery_weeks
    if weeks <= 52:
        return 5, f"{weeks} weeks (<= 52)"
    if weeks <= 60:
        return 4, f"{weeks} weeks (53-60)"
    if weeks <= 68:
        return 3, f"{weeks} weeks (61-68)"
    if weeks <= max_w:
        return 2, f"{weeks} weeks (69-{max_w:,.0f}, contractual maximum)"
    return 1, f"{weeks} weeks (> {max_w:,.0f}) -> subject to rejection as non-compliant"


def band_h1(trir: Optional[float], fatality: Optional[bool]) -> tuple[Optional[int], str]:
    """H1 Safety performance, 3-yr avg TRIR per 200,000 manhours (9)."""
    if trir is None or fatality is None:
        return None, "Insufficient evidence to calculate this criterion. (H1: TRIR or fatality record not provided by upstream agent)"
    if fatality:
        return 0, "work-related fatality in the 3-year period -> band 0 floor"
    if trir <= 0.20:
        return 5, f"TRIR {trir} (<= 0.20)"
    if trir <= 0.40:
        return 4, f"TRIR {trir} (0.21-0.40)"
    if trir <= 0.60:
        return 3, f"TRIR {trir} (0.41-0.60)"
    if trir <= 1.00:
        return 2, f"TRIR {trir} (0.61-1.00)"
    return 1, f"TRIR {trir} (> 1.00)"


def band_h2(iso45001: Optional[bool], iso14001: Optional[bool]) -> tuple[Optional[int], str]:
    """H2 HSE management certification, valid on bid due date (6)."""
    if iso45001 is None or iso14001 is None:
        return None, "Insufficient evidence to calculate this criterion. (H2: ISO certification status not provided by upstream agent)"
    if iso45001 and iso14001:
        return 5, "both ISO 45001 and ISO 14001 valid"
    if iso45001 or iso14001:
        return 3, "exactly one of ISO 45001 / ISO 14001 valid"
    return 1, "neither ISO 45001 nor ISO 14001 valid"


# ---------------------------------------------------------------------------
# Pass A — cheap screening (all suppliers, one pass per check)
# ---------------------------------------------------------------------------


def pass_a_screening(handoff: dict[str, Any], raw_bids: list[RawBid],
                     schema: RfpSchema, findings: list[RiskFinding]) -> None:
    """Cross-check the evaluator's screening output against raw evidence.

    The risk agent does NOT re-flag correctly identified non-compliance — that
    is the evaluator's job. It ONLY flags when the evaluator missed a fatal
    flaw (P7/P8) or when evidence is UNVERIFIABLE.
    """
    by_name = {b.name: b for b in raw_bids}

    for ev in (handoff.get("ranked_evaluations", []) +
               handoff.get("ineligible_evaluations", [])):
        name = ev.get("supplier", "?")
        screening = ev.get("mandatory_screening", "")
        tech = ev.get("technical_compliance", "")
        raw = by_name.get(name)

        # 1. Unverifiable screening (upstream couldn't determine) -> evidence gap
        if "UNVERIFIABLE" in screening:
            findings.append(RiskFinding(
                supplier=name, category=6,
                finding=f"Screening status UNVERIFIABLE: {screening}",
                evidence="no citation - upstream did not provide the evidence",
                claim_class="UNRESOLVED", materiality="MEDIUM", severity="MEDIUM",
                action="watch"))

        # 2. Cross-check: if raw data is available, verify the evaluator's
        #    screening and tech-compliance decisions. A missed rejection
        #    condition is CRITICAL — it corrupts the award gate for the
        #    whole evaluation.
        if raw and "CONDITIONALLY NON-COMPLIANT" not in screening and "FAIL" not in tech:
            if not raw.mandatory_pass_for(schema):
                findings.append(RiskFinding(
                    supplier=name, category=6,
                    finding=f"Evaluator reports screening '{screening}' but raw "
                            f"evidence shows mandatory screening FAIL: {raw.screening_status(schema)}",
                    evidence=f"{name} raw bid -> mandatory_pass = {raw.mandatory_pass_for(schema)}",
                    claim_class="VERIFIED", materiality="HIGH", severity="CRITICAL",
                    action="ESCALATE", flag="P7"))
            if not raw.min_tech_pass_for(schema):
                findings.append(RiskFinding(
                    supplier=name, category=6,
                    finding=f"Evaluator reports technical compliance '{tech}' but "
                            f"raw evidence shows min-tech FAIL: "
                            f"{'; '.join(raw.tech_requirement_failures(schema))}",
                    evidence=f"{name} raw bid -> min_tech_pass = {raw.min_tech_pass_for(schema)}",
                    claim_class="VERIFIED", materiality="HIGH", severity="CRITICAL",
                    action="ESCALATE", flag="P7"))


# ---------------------------------------------------------------------------
# Pass B — materiality screen
# ---------------------------------------------------------------------------


def _criteria_of(ev: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Flatten {scores: {technical: {criteria: {...}}, hse: {criteria: {...}}}}."""
    out = []
    for block in ("technical", "hse"):
        for code, crit in ev.get("scores", {}).get(block, {}).get("criteria", {}).items():
            out.append((code, crit))
    return out


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _extract_pbid(formula: Optional[str]) -> Optional[float]:
    """Extract the bidder price (Pbid) from a formula string like
    '30 * (38,000,000.00 / 41,000,000.00)' -> 41,000,000.00.
    Returns None if not parseable."""
    if not formula or "(" not in formula:
        return None
    try:
        paren = formula[formula.find("(") + 1:formula.find(")")]
        nums = [float(x.replace(",", "")) for x in paren.replace("/", " ").split()
                if _is_number(x.replace(",", ""))]
        return nums[1] if len(nums) >= 2 else None
    except (ValueError, IndexError):
        return None


def pass_b_arithmetic(handoff: dict[str, Any], schema: RfpSchema,
                      findings: list[RiskFinding]) -> None:
    """Independently recompute every reported points value from its band/formula.

    A methodology/arithmetic error is HIGH-severity even when no individual
    score looks wrong — it corrupts every number downstream (P8).
    """
    for ev in handoff.get("ranked_evaluations", []) + handoff.get("ineligible_evaluations", []):
        name = ev.get("supplier", "?")
        scores = ev.get("scores", {})

        # Per-criterion: points = (band / max_band) * weight
        for code, crit in _criteria_of(ev):
            band = crit.get("band")
            points = crit.get("points")
            max_pts = crit.get("max")
            if band is None or points is None or max_pts is None:
                continue
            expected = round((band / schema.max_band) * max_pts, 2)
            if abs(expected - points) > 0.005:
                findings.append(RiskFinding(
                    supplier=name, category=6,
                    finding=f"Arithmetic discrepancy on {code}: evaluator reports "
                            f"{points} pts but band {band} x {max_pts}/{schema.max_band} "
                            f"= {expected} pts",
                    evidence=f"handoff scores.{('technical' if code[0]=='T' else 'hse')}.criteria.{code}",
                    claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                    action="ESCALATE", flag="P8"))

        # Commercial: C = weight * (Plow / Pbid)
        comm = scores.get("commercial", {})
        formula = comm.get("formula")
        if formula and comm.get("points") is not None and ev.get("eligible_for_award"):
            pbid = _extract_pbid(formula)
            plow_in_formula = None
            try:
                paren = formula[formula.find("(") + 1:formula.find(")")]
                nums = [float(x.replace(",", "")) for x in paren.replace("/", " ").split()
                        if _is_number(x.replace(",", ""))]
                if len(nums) >= 2:
                    plow_in_formula = nums[0]
                    pbid = nums[1]
            except (ValueError, IndexError):
                pass
            if pbid and plow_in_formula is not None and pbid > 0:
                expected_c = round(schema.commercial_weight * (plow_in_formula / pbid), 2)
                if abs(expected_c - comm["points"]) > 0.005:
                    findings.append(RiskFinding(
                        supplier=name, category=6,
                        finding=f"Commercial arithmetic discrepancy: reported "
                                f"{comm['points']} but recomputed {expected_c} from formula",
                        evidence="handoff scores.commercial.formula",
                        claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                        action="ESCALATE", flag="P8"))

        # ICV: 15 * min(icv%, cap) / cap
        icv = scores.get("icv", {})
        icv_formula = icv.get("formula")
        if icv_formula and icv.get("points") is not None and "min" in icv_formula:
            try:
                pct = float(icv_formula.split("min(")[1].split("%")[0].replace(",", ""))
                expected_icv = round(schema.icv_weight * min(pct, schema.icv_cap_pct)
                                     / schema.icv_cap_pct, 2)
                if abs(expected_icv - icv["points"]) > 0.005:
                    findings.append(RiskFinding(
                        supplier=name, category=6,
                        finding=f"ICV arithmetic discrepancy: reported {icv['points']} "
                                f"but recomputed {expected_icv} from {icv_formula}",
                        evidence="handoff scores.icv.formula",
                        claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                        action="ESCALATE", flag="P8"))
            except (ValueError, IndexError):
                pass

        # Total = sum of the four categories
        total = scores.get("total", {}).get("points")
        parts = [scores.get(k, {}).get("points")
                 for k in ("technical", "commercial", "hse", "icv")]
        if total is not None and all(p is not None for p in parts):
            expected_total = round(sum(parts), 2)
            if abs(expected_total - total) > 0.005:
                findings.append(RiskFinding(
                    supplier=name, category=6,
                    finding=f"Total score discrepancy: reported {total} but the four "
                            f"categories sum to {expected_total}",
                    evidence="handoff scores.total vs scores.{technical,commercial,hse,icv}",
                    claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                    action="ESCALATE", flag="P8"))


def pass_b_band_crosscheck(handoff: dict[str, Any], raw_bids: list[RawBid],
                           schema: RfpSchema, findings: list[RiskFinding]) -> None:
    """Re-derive each criterion's band from the raw bid values and compare with
    the evaluator's reported band. Band mismatches are evidence risks (P7/P8)."""
    by_name = {b.name: b for b in raw_bids}
    for ev in handoff.get("ranked_evaluations", []) + handoff.get("ineligible_evaluations", []):
        name = ev.get("supplier", "?")
        raw = by_name.get(name)
        if raw is None:
            continue  # no raw data for this supplier -> cross-check skipped

        expected_bands = {
            "T1": band_t1(raw.capacity_m3d, raw.oiw_outlet, schema)[0],
            "T2": band_t2(raw.gcc_refs)[0],
            "T3": band_t3(raw.years_exp)[0],
            "T4": band_t4(raw.weeks_to_completion, schema)[0],
            "H1": band_h1(raw.trir, raw.fatality)[0],
            "H2": band_h2(raw.iso45001, raw.iso14001)[0],
        }
        for code, crit in _criteria_of(ev):
            reported = crit.get("band")
            expected = expected_bands.get(code)
            if expected is None or reported is None:
                continue
            if expected != reported:
                findings.append(RiskFinding(
                    supplier=name, category=6,
                    finding=f"Band cross-check failed on {code}: evaluator reports band "
                            f"{reported} but raw evidence gives band {expected} "
                            f"(recomputed from bid values)",
                    evidence=f"{name} raw bid values -> {code} band function",
                    claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                    action="ESCALATE", flag="P7"))


def pass_b_process_fidelity(handoff: dict[str, Any], raw_bids: list[RawBid],
                            schema: RfpSchema, result: ReviewResult,
                            findings: list[RiskFinding]) -> None:
    """Verify Plow was computed from the correct eligibility set (P8)."""
    if not raw_bids:
        return
    eligible = [b for b in raw_bids if b.mandatory_pass_for(schema) and b.min_tech_pass_for(schema)]
    priced = [b for b in eligible if b.price_aed is not None]
    recomputed = min(b.price_aed for b in priced) if priced else 0.0

    result.plow_recomputed = recomputed
    result.plow_reported = handoff.get("plow", 0.0)
    result.eligible_count = len(eligible)

    if abs(recomputed - result.plow_reported) > 0.01:
        result.plow_set_ok = False
        findings.append(RiskFinding(
            supplier="(tender)", category=6,
            finding=f"Plow mismatch: evaluator used {result.plow_reported:,.2f} but "
                    f"independent recomputation from the eligible set gives "
                    f"{recomputed:,.2f} — Plow set or eligibility gates not applied correctly",
            evidence="handoff.plow vs recomputation over raw bids (eligible = screening "
                     "PASS AND min-tech PASS)",
            claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
            action="ESCALATE", flag="P8"))


def pass_b_portfolio(handoff: dict[str, Any], schema: RfpSchema,
                     result: ReviewResult, findings: list[RiskFinding]) -> None:
    """Cross-supplier / market-level checks (category 10, P2/P3/P9)."""
    eligible = [e for e in handoff.get("ranked_evaluations", [])]

    # Shallow competition
    if len(eligible) < schema.min_eligible_bidders:
        findings.append(RiskFinding(
            supplier="(tender)", category=10,
            finding=f"Shallow competition: only {len(eligible)} eligible bidder(s) "
                    f"after screening (threshold {schema.min_eligible_bidders})",
            evidence="handoff.ranked_evaluations",
            claim_class="VERIFIED", materiality="MEDIUM", severity="MEDIUM",
            action="watch", flag="P2"))

    # Price coherence / outliers (only with >= 3 priced eligible bids)
    prices: list[float] = []
    for e in eligible:
        pbid = _extract_pbid(e.get("scores", {}).get("commercial", {}).get("formula"))
        if pbid is not None:
            prices.append(pbid)
    if len(prices) >= 3:
        mean = sum(prices) / len(prices)
        std = math.sqrt(sum((p - mean) ** 2 for p in prices) / len(prices))
        cv = std / mean if mean else 0.0
        median = sorted(prices)[len(prices) // 2]

        if cv < schema.price_cv_signal_threshold:
            findings.append(RiskFinding(
                supplier="(tender)", category=10,
                finding=f"Price coherence: CV {cv:.1%} across {len(prices)} eligible "
                        f"bids is suspiciously tight — possible signalling (P9)",
                evidence="handoff.ranked_evaluations[].scores.commercial.formula (Pbid)",
                claim_class="INFERRED", materiality="MEDIUM", severity="MEDIUM",
                action="watch", flag="P9"))
        elif cv > schema.price_cv_wide_threshold:
            findings.append(RiskFinding(
                supplier="(tender)", category=10,
                finding=f"Price coherence: CV {cv:.1%} is implausibly wide — possible "
                        f"mispricing (P3)",
                evidence="handoff.ranked_evaluations[].scores.commercial.formula (Pbid)",
                claim_class="INFERRED", materiality="MEDIUM", severity="MEDIUM",
                action="watch", flag="P3"))

        # Outliers vs median
        for e in eligible:
            pbid = _extract_pbid(e.get("scores", {}).get("commercial", {}).get("formula"))
            if pbid is None or median == 0:
                continue
            if pbid > schema.price_outlier_factor * median or \
                    pbid < median / schema.price_outlier_factor:
                findings.append(RiskFinding(
                    supplier=e.get("supplier", "?"), category=3,
                    finding=f"Price outlier: {pbid:,.2f} AED vs field median "
                            f"{median:,.2f} AED (factor {pbid/median:.2f}x) (P3)",
                    evidence="handoff.ranked_evaluations[].scores.commercial.formula",
                    claim_class="INFERRED", materiality="MEDIUM", severity="MEDIUM",
                    action="watch", flag="P3"))

    # Ranking sensitivity (P2): top-2 gap
    totals = [e.get("scores", {}).get("total", {}).get("points")
              for e in eligible if e.get("scores", {}).get("total", {}).get("points") is not None]
    if len(totals) >= 2:
        totals.sort(reverse=True)
        gap = totals[0] - totals[1]
        if gap < schema.ranking_sensitivity_gap:
            findings.append(RiskFinding(
                supplier="(tender)", category=10,
                finding=f"Ranking fragility: top two eligible bids within {gap:.2f} "
                        f"points — recommendation sensitive to any single correction (P2)",
                evidence="handoff.ranked_evaluations[].scores.total.points",
                claim_class="VERIFIED", materiality="MEDIUM", severity="MEDIUM",
                action="watch", flag="P2"))


def pass_b_threshold_proximity(raw_bids: list[RawBid], schema: RfpSchema,
                               findings: list[RiskFinding]) -> None:
    """P1: values within a small margin of a rejection boundary.
    P6: a near-threshold value that also drives multiple criteria."""
    margin_cap = schema.min_capacity_m3d * schema.proximity_capacity_pct
    for raw in raw_bids:
        name = raw.name
        cap = raw.capacity_m3d
        oiw = raw.oiw_outlet
        weeks = raw.weeks_to_completion
        trir = raw.trir

        if cap is not None and schema.min_capacity_m3d <= cap <= schema.min_capacity_m3d + margin_cap:
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Threshold proximity (P1): capacity {cap:,.0f} m³/d is within "
                        f"{margin_cap:,.0f} of the {schema.min_capacity_m3d:,.0f} rejection floor",
                evidence=f"{name} raw bid -> capacity_m3d",
                claim_class="VERIFIED", materiality="LOW", severity="LOW",
                action="watch", flag="P1"))
            # P6: capacity drives T1 AND the min-tech gate
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Single-point dependency (P6): capacity {cap:,.0f} m³/d drives "
                        f"both the T1 band and the minimum-technical gate — one error "
                        f"corrupts two scores",
                evidence=f"{name} raw bid -> capacity_m3d (drives T1 + min-tech)",
                claim_class="INFERRED", materiality="LOW", severity="LOW",
                action="watch", flag="P6"))
        if oiw is not None and schema.max_oiw_outlet - schema.proximity_oiw_abs <= oiw <= schema.max_oiw_outlet:
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Threshold proximity (P1): outlet OiW {oiw} mg/L is within "
                        f"{schema.proximity_oiw_abs} of the {schema.max_oiw_outlet} mg/L rejection limit",
                evidence=f"{name} raw bid -> oiw_outlet",
                claim_class="VERIFIED", materiality="LOW", severity="LOW",
                action="watch", flag="P1"))
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Single-point dependency (P6): outlet OiW {oiw} mg/L drives "
                        f"both the T1 band and the minimum-technical gate",
                evidence=f"{name} raw bid -> oiw_outlet (drives T1 + min-tech)",
                claim_class="INFERRED", materiality="LOW", severity="LOW",
                action="watch", flag="P6"))
        if weeks is not None and schema.max_delivery_weeks - schema.proximity_weeks_abs <= weeks <= schema.max_delivery_weeks:
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Threshold proximity (P1): delivery {weeks} weeks is within "
                        f"{schema.proximity_weeks_abs} of the {schema.max_delivery_weeks:,.0f}-week contractual maximum",
                evidence=f"{name} raw bid -> weeks_to_completion",
                claim_class="VERIFIED", materiality="LOW", severity="LOW",
                action="watch", flag="P1"))
            findings.append(RiskFinding(
                supplier=name, category=2,
                finding=f"Single-point dependency (P6): delivery {weeks} weeks drives "
                        f"both the T4 band and the minimum-technical gate",
                evidence=f"{name} raw bid -> weeks_to_completion (drives T4 + min-tech)",
                claim_class="INFERRED", materiality="LOW", severity="LOW",
                action="watch", flag="P6"))
        if trir is not None and schema.trir_band5_max - schema.proximity_trir_abs <= trir <= schema.trir_band5_max:
            findings.append(RiskFinding(
                supplier=name, category=4,
                finding=f"Threshold proximity (P1): TRIR {trir} is within "
                        f"{schema.proximity_trir_abs} of the {schema.trir_band5_max} band-5 floor",
                evidence=f"{name} raw bid -> trir",
                claim_class="VERIFIED", materiality="LOW", severity="LOW",
                action="watch", flag="P1"))
            findings.append(RiskFinding(
                supplier=name, category=4,
                finding=f"Single-point dependency (P6): TRIR {trir} drives the H1 band "
                        f"and the HSE evidence check",
                evidence=f"{name} raw bid -> trir (drives H1 band)",
                claim_class="INFERRED", materiality="LOW", severity="LOW",
                action="watch", flag="P6"))


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    """Parse an ISO date string; tolerate None and malformed input."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def pass_b_temporal_validity(raw_bids: list[RawBid], schema: RfpSchema,
                             findings: list[RiskFinding]) -> None:
    """P4: certificate/bond/licence validity expires before bid deadline,
    award window, or required validity period. Validity dates are checkable
    facts — escalate."""
    deadline = _parse_iso_date(schema.bid_deadline_iso)
    if deadline is None:
        return  # schema has no date -> nothing to check, not a finding

    for raw in raw_bids:
        name = raw.name

        # ICV certificate validity (D6) — must cover the bid submission date
        if raw.icv_cert_valid_until:
            expiry = _parse_iso_date(raw.icv_cert_valid_until)
            if expiry and expiry < deadline:
                findings.append(RiskFinding(
                    supplier=name, category=5,
                    finding=f"Temporal validity (P4): ICV certificate expires "
                            f"{expiry.isoformat()} — BEFORE the bid submission date "
                            f"{deadline.isoformat()} (D6 requires validity on bid date)",
                    evidence=f"{name} raw bid -> icv_cert_valid_until",
                    claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                    action="ESCALATE", flag="P4"))
            elif expiry and expiry >= deadline and raw.icv_cert_valid is True:
                # valid at deadline, but does it cover the award window?
                award_end = deadline + _days(schema.bid_validity_days)
                if expiry < award_end:
                    findings.append(RiskFinding(
                        supplier=name, category=5,
                        finding=f"Temporal validity (P4): ICV certificate expires "
                                f"{expiry.isoformat()} — within the bid validity window "
                                f"({award_end.isoformat()}); may not cover the award date",
                        evidence=f"{name} raw bid -> icv_cert_valid_until vs schema.bid_validity_days",
                        claim_class="INFERRED", materiality="MEDIUM", severity="MEDIUM",
                        action="watch", flag="P4"))

        # Bid bond validity (D8) — must be >= bond_validity_days
        if raw.bond_valid_days is not None and raw.bond_valid_days < schema.bond_validity_days:
            findings.append(RiskFinding(
                supplier=name, category=1,
                finding=f"Temporal validity (P4): bid bond valid {raw.bond_valid_days} "
                        f"days < required {schema.bond_validity_days} days (D8)",
                evidence=f"{name} raw bid -> bond_valid_days",
                claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                action="ESCALATE", flag="P4"))
        if raw.bond_pct is not None and raw.bond_pct < schema.bond_pct:
            findings.append(RiskFinding(
                supplier=name, category=1,
                finding=f"Bid bond {raw.bond_pct}% < required {schema.bond_pct}% of "
                        f"bid value (D8)",
                evidence=f"{name} raw bid -> bond_pct",
                claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                action="ESCALATE", flag="P4"))


def _days(n: int) -> Any:
    """datetime.timedelta helper."""
    from datetime import timedelta
    return timedelta(days=n)


def pass_b_conditional_content(raw_bids: list[RawBid], schema: RfpSchema,
                               findings: list[RiskFinding]) -> None:
    """P5: 'Subject to…', alternates, deviations, qualifications, conditional
    discounts — terms differ from what the scores assume. Escalate for human
    interpretation of the condition."""
    markers = [m.lower() for m in schema.conditional_markers]
    for raw in raw_bids:
        hits = [c for c in raw.conditions if any(m in c.lower() for m in markers)]
        if hits:
            findings.append(RiskFinding(
                supplier=raw.name, category=7,
                finding=f"Conditional content (P5): bid contains conditional "
                        f"terms that may differ from what the scores assume: "
                        f"{'; '.join(hits[:3])}",
                evidence=f"{raw.name} raw bid -> conditions",
                claim_class="VERIFIED", materiality="MEDIUM", severity="MEDIUM",
                action="ESCALATE", flag="P5"))


def pass_b_collusion(raw_bids: list[RawBid], schema: RfpSchema,
                     findings: list[RiskFinding]) -> None:
    """P9: two or more bids share identical line-item prices, identical
    totals, or identical wording/errors across suppliers. Escalate for human
    review of the procurement file."""
    # Identical totals (from different arithmetic)
    totals_by_value: dict[float, list[str]] = {}
    for raw in raw_bids:
        if raw.total_price is not None:
            totals_by_value.setdefault(round(raw.total_price, 2), []).append(raw.name)
    for val, names in totals_by_value.items():
        if len(names) >= 2:
            findings.append(RiskFinding(
                supplier="(tender)", category=8,
                finding=f"Collusion indicator (P9): identical bid totals {val:,.2f} "
                        f"AED across suppliers: {', '.join(names)}",
                evidence="raw bids -> total_price (identical across suppliers)",
                claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                action="ESCALATE", flag="P9"))

    # Identical line-item prices
    priced_bids_with_items = [r for r in raw_bids if r.line_items]
    if len(priced_bids_with_items) >= 2:
        min_items = min(len(r.line_items) for r in priced_bids_with_items)
        if min_items >= 3:
            for i in range(min_items):
                vals: dict[float, list[str]] = {}
                for raw in raw_bids:
                    if len(raw.line_items) > i:
                        vals.setdefault(round(raw.line_items[i], 2), []).append(raw.name)
                for val, names in vals.items():
                    if len(names) >= 2:
                        findings.append(RiskFinding(
                            supplier="(tender)", category=8,
                            finding=f"Collusion indicator (P9): identical line-item "
                                    f"price {val:,.2f} AED at position {i+1} across "
                                    f"suppliers: {', '.join(names)}",
                            evidence="raw bids -> line_items",
                            claim_class="VERIFIED", materiality="HIGH", severity="HIGH",
                            action="ESCALATE", flag="P9"))


def pass_b_extraction_quality(raw_bids: list[RawBid], schema: RfpSchema,
                              findings: list[RiskFinding]) -> None:
    """P10: evidence for a scored criterion comes only from a low-quality
    scan/OCR or an unreadable document. Escalate if the criterion is material."""
    markers = [m.lower() for m in schema.low_quality_markers]
    for raw in raw_bids:
        for field, quality in raw.extraction_quality.items():
            q = quality.lower()
            if any(m in q for m in markers):
                findings.append(RiskFinding(
                    supplier=raw.name, category=6,
                    finding=f"Extraction uncertainty (P10): evidence for '{field}' "
                            f"comes from low-quality source: '{quality}' — the value "
                            f"may be a misread, not a fact",
                    evidence=f"{raw.name} raw bid -> extraction_quality.{field}",
                    claim_class="UNRESOLVED", materiality="MEDIUM", severity="MEDIUM",
                    action="watch", flag="P10"))


def pass_b_guarantee_verifiability(raw_bids: list[RawBid], schema: RfpSchema,
                                   findings: list[RiskFinding]) -> None:
    """P11: an offered performance guarantee cannot be demonstrated against
    the RFP's stated test method/acceptance criteria. Escalate with the
    specific test-method gap."""
    for raw in raw_bids:
        if raw.guarantee_test_method is None:
            continue  # no guarantee data supplied -> skip, not a finding
        if not raw.guarantee_test_method.strip() or \
                raw.guarantee_test_method.strip().lower() in ("n/a", "not specified", "tbd", "none"):
            findings.append(RiskFinding(
                supplier=raw.name, category=2,
                finding=f"Guarantee unverifiability (P11): offered performance "
                        f"guarantee cannot be demonstrated against the RFP's stated "
                        f"test method — test method not specified ('{raw.guarantee_test_method}')",
                evidence=f"{raw.name} raw bid -> guarantee_test_method",
                claim_class="UNRESOLVED", materiality="HIGH", severity="HIGH",
                action="ESCALATE", flag="P11"))


def pass_b_execution_interface(raw_bids: list[RawBid], schema: RfpSchema,
                               findings: list[RiskFinding]) -> None:
    """Category 9: brownfield/live-plant tie-in and interface risk that scores
    alone do not capture."""
    if not schema.brownfield:
        return
    for raw in raw_bids:
        if raw.execution_plan is False:
            findings.append(RiskFinding(
                supplier=raw.name, category=9,
                finding=f"Execution/interface risk: scope requires tie-in with a "
                        f"live facility but the bid provides no execution/shutdown/"
                        f"interface plan",
                evidence=f"{raw.name} raw bid -> execution_plan",
                claim_class="VERIFIED", materiality="MEDIUM", severity="MEDIUM",
                action="ESCALATE", flag=""))


def pass_b_integrity_declarations(raw_bids: list[RawBid], schema: RfpSchema,
                                  findings: list[RiskFinding]) -> None:
    """Category 8: missing integrity/conflict declarations (anti-commission,
    conflict-of-interest, sanctions certification).

    Only fires when the upstream agent EXTRACTED the declarations field and
    found nothing submitted. If the field was never extracted (None), that is
    an evidence gap, not a finding — "not found in the dataset" != "does not
    exist"."""
    for raw in raw_bids:
        if raw.integrity_declarations is None:
            continue  # not extracted upstream -> no finding (evidence gap)
        submitted = {d.lower() for d in raw.integrity_declarations}
        missing = [req for req in schema.required_integrity_declarations
                   if not any(req in s for s in submitted)]
        if missing:
            findings.append(RiskFinding(
                supplier=raw.name, category=8,
                finding=f"Missing integrity declaration(s): {', '.join(missing)} — "
                        f"required by RFP integrity provisions",
                evidence=f"{raw.name} raw bid -> integrity_declarations",
                claim_class="VERIFIED", materiality="MEDIUM", severity="MEDIUM",
                action="ESCALATE", flag=""))


def pass_b_evidence_gaps(handoff: dict[str, Any], schema: RfpSchema,
                         findings: list[RiskFinding]) -> None:
    """UNRESOLVED gaps and unsupported scores (P7)."""
    for ev in handoff.get("ranked_evaluations", []) + handoff.get("ineligible_evaluations", []):
        name = ev.get("supplier", "?")
        missing = ev.get("missing_information", [])
        if missing:
            findings.append(RiskFinding(
                supplier=name, category=6,
                finding="Evidence gap(s): " + "; ".join(missing[:4])
                        + (" (+more)" if len(missing) > 4 else ""),
                evidence="handoff missing_information (upstream-flagged)",
                claim_class="UNRESOLVED", materiality="MEDIUM", severity="MEDIUM",
                action="watch", flag="P7"))
        # Score assigned without any citation
        ev_sources = ev.get("evidence_sources", {})
        if not ev_sources:
            findings.append(RiskFinding(
                supplier=name, category=6,
                finding="No evidence citations supplied by upstream for any criterion — "
                        "every score is unsupported (P7)",
                evidence="handoff evidence_sources is empty",
                claim_class="UNRESOLVED", materiality="MEDIUM", severity="MEDIUM",
                action="watch", flag="P7"))


# ---------------------------------------------------------------------------
# Pass C — verdict: compile register, build escalations, emit
# ---------------------------------------------------------------------------


def _build_escalations(result: ReviewResult, schema: RfpSchema) -> list[EscalationMessage]:
    msgs = []
    for f in result.findings:
        if f.action != "ESCALATE":
            continue
        criterion = RISK_CATEGORIES.get(f.category, "General")
        msgs.append(EscalationMessage(
            tender_id=schema.tender_id,
            supplier=f.supplier,
            severity=f.severity,
            reason=f.finding,
            criterion=criterion,
            evidence=f.evidence,
            recommended_action=_recommended_action(f)))
    return msgs


def _recommended_action(f: RiskFinding) -> str:
    """Deterministic recommended human action per finding type."""
    if f.category == 1:
        return "Obtain the missing mandatory document or rule on completeness per ITB 5"
    if f.category == 2 and f.flag == "P1":
        return "Verify the near-threshold figure against the original document"
    if f.category == 2 and f.flag == "P11":
        return "Rule on the performance guarantee against the RFP's stated test method (Exhibit D)"
    if f.category == 2:
        return "Rule on technical compliance against RFP Section 5.1 rejection conditions"
    if f.category == 4:
        return "Verify HSE statistics and certificate validity against source documents"
    if f.category == 5:
        return "Verify ICV certificate validity with MoIAT"
    if f.category == 6 and f.flag == "P8":
        return "Recompute the affected scores independently and correct the handoff"
    if f.category == 6 and f.flag == "P7":
        return "Obtain evidence citations for the unsupported score"
    if f.category == 6 and f.flag == "P10":
        return "Re-verify the affected value against the original source document"
    if f.category == 6:
        return "Reconcile the upstream disagreement; record both positions"
    if f.category == 3:
        return "Verify the outlier price against the itemized commercial proposal"
    if f.category == 7:
        return "Rule on the conditional terms before accepting the scored position"
    if f.category == 8:
        return "Human review of the procurement file; obtain missing declarations"
    if f.category == 9:
        return "Assess the execution/shutdown/interface plan against the site constraints"
    if f.category == 10:
        return "Assess competition depth and ranking stability before proceeding"
    return "Human review required per risk register"


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def risk_register_table(findings: list[RiskFinding]) -> str:
    if not findings:
        return "Risk Register:\n| # | Supplier | Category | Finding | Evidence | Class | Materiality | Action |\n| No findings |"
    lines = [
        "Risk Register:",
        "| # | Supplier | Category | Finding | Evidence (source) | Class | Materiality | Action |",
        "|---|----------|----------|---------|-------------------|-------|-------------|--------|",
    ]
    for i, f in enumerate(findings, start=1):
        cat = RISK_CATEGORIES.get(f.category, str(f.category))
        lines.append(
            f"| {i} | {f.supplier} | {cat} | {f.finding} | {f.evidence} | "
            f"{f.claim_class} | {f.materiality} | {f.action} |")
    return "\n".join(lines)


def verdict_text(result: ReviewResult) -> str:
    """Emit the spec's verdict templates (no-escalation / escalation)."""
    lines = [f"Risk Status: {result.risk_status}", ""]
    lines.append(f"Recommendation Confidence: {result.confidence}")

    if not result.escalation_required:
        lines += [
            "  - Every material score cross-checked against cited evidence.",
            "  - Arithmetic independently recomputed; methodology verified against the RFP.",
            "",
        ]
        watch = [f for f in result.findings if f.action == "watch"]
        if watch:
            lines.append("Risk Findings (watch items — informational, no escalation):")
            for f in watch:
                lines.append(
                    f"  - {f.supplier}: {f.finding} [{f.claim_class}, {f.evidence}]")
        else:
            lines += [
                "Risk Findings: None",
                "  - Mandatory documents complete and verified.",
                "  - All suppliers pass minimum technical requirements.",
                "  - Prices conform to RFP currency/arithmetic rules; no material deviations.",
                "  - HSE evidence complete; no fatal safety flags.",
                "  - Certificates valid on the operative dates.",
                "  - All evidence verifiable within the dataset.",
            ]
        lines += [
            "",
            f"Evidence: {result.tender_id} evaluation report and cited bid documents",
            "",
            "Escalation Required: NO",
            "",
            "Reason: No human escalation required based on the available evidence.",
            "",
            "Handoff: The automated recommendation (highest-scoring eligible supplier) may "
            "proceed to the",
            "procurement engineer as decision-support. The engineer retains final award authority.",
        ]
    else:
        lines += [
            "  - Basis: evidence completeness, verified scores, unresolved uncertainty.",
            "",
            "Risk Findings:",
        ]
        for f in result.findings:
            if f.materiality in ("HIGH", "CRITICAL") or f.action == "ESCALATE":
                lines.append(f"  - {f.supplier}: {f.finding} [{f.claim_class}, {f.evidence}]")
        lines += [
            "",
            f"Evidence: {result.tender_id} evaluation report, bid documents, upstream agent notes",
            "",
            "Escalation Required: YES",
            "",
            "Escalation Actions:",
        ]
        for m in result.escalations:
            lines.append(
                f"  - Tender {m.tender_id} | {m.supplier} | {m.severity} | {m.reason} "
                f"| criterion: {m.criterion} | evidence: {m.evidence} "
                f"| action: {m.recommended_action}")
        lines += [
            "",
            f"Reason: {_reason(result)}",
            "",
            "Handoff: The automated recommendation is BLOCKED pending human review of the "
            "escalated",
            "issue(s). No award-support output is generated until the human engineer "
            "resolves them.",
        ]
    lines.append("")
    lines.append("Decision-support output only — not an official ADNOC procurement decision.")
    return "\n".join(lines)


def _reason(result: ReviewResult) -> str:
    if result.has_critical:
        return ("Critical finding(s) make the evaluation unsafe or unsupportable; the "
                "system cannot proceed without human review.")
    if result.has_high:
        return ("Significant uncertainty exists that could flip the ranking; the "
                "automated recommendation is blocked pending human resolution.")
    return ("Material uncertainty is present; escalation required before an "
            "automated recommendation can be supported.")


def full_report(result: ReviewResult, handoff: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        "RISK & ESCALATION REVIEW",
        f"Tender: {result.tender_id}",
        f"Plow reported: {result.plow_reported:,.2f} AED | recomputed: "
        f"{result.plow_recomputed:,.2f} AED | set OK: {result.plow_set_ok}",
        f"Eligible bidders: {result.eligible_count}",
        "=" * 78,
        "",
    ]
    lines.append(risk_register_table(result.findings))
    lines.append("")
    lines.append("-" * 78)
    lines.append(verdict_text(result))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def review(handoff: dict[str, Any], raw_bids: Optional[list[Any]] = None,
           schema: RfpSchema = DEFAULT_SCHEMA) -> ReviewResult:
    """Run Pass A -> Pass B -> Pass C over the evaluator's handoff.

    raw_bids may be a list of dicts (upstream JSON) or a list of RawBid.
    If omitted, cross-checks that need raw data are skipped — the review
    still verifies arithmetic, portfolio, and evidence gaps from the handoff.
    """
    result = ReviewResult(tender_id=handoff.get("tender_id", schema.tender_id), schema=schema)
    raw_bids = raw_bids or []

    # Normalize raw bids: dict -> RawBid
    parsed: list[RawBid] = []
    for b in raw_bids:
        if isinstance(b, RawBid):
            parsed.append(b)
        elif isinstance(b, dict):
            try:
                parsed.append(raw_bid_from_dict(b))
            except (KeyError, TypeError, ValueError):
                continue  # unparseable raw bid -> skip, not a finding
        # else: ignore unknown types

    # Pass A — cheap screening (cross-check evaluator's screening/tech decisions)
    pass_a_screening(handoff, parsed, schema, result.findings)

    # Pass B — materiality (only what can change the outcome)
    pass_b_arithmetic(handoff, schema, result.findings)
    pass_b_band_crosscheck(handoff, parsed, schema, result.findings)
    pass_b_process_fidelity(handoff, parsed, schema, result, result.findings)
    pass_b_portfolio(handoff, schema, result, result.findings)
    pass_b_threshold_proximity(parsed, schema, result.findings)
    pass_b_temporal_validity(parsed, schema, result.findings)
    pass_b_conditional_content(parsed, schema, result.findings)
    pass_b_collusion(parsed, schema, result.findings)
    pass_b_extraction_quality(parsed, schema, result.findings)
    pass_b_guarantee_verifiability(parsed, schema, result.findings)
    pass_b_execution_interface(parsed, schema, result.findings)
    pass_b_integrity_declarations(parsed, schema, result.findings)
    pass_b_evidence_gaps(handoff, schema, result.findings)

    # Pass C — verdict
    result.escalations = _build_escalations(result, schema)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_handoff(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else open(path).read()
    return json.loads(raw)


def load_bids(path: str) -> list[dict[str, Any]]:
    data = json.load(open(path))
    if isinstance(data, list):
        return data
    return data.get("bids", [])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Risk & Escalation review engine")
    parser.add_argument("--test", action="store_true", help="run test harness")
    parser.add_argument("--handoff", help="bid evaluation handoff JSON (or '-' for stdin)")
    parser.add_argument("--bids", help="raw bids JSON (enables band cross-check + Plow fidelity)")
    parser.add_argument("--rfp", help="RFP schema JSON (optional; defaults to ADNOC 2026-0412)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.test:
        return run_tests()

    if not args.handoff:
        parser.error("provide --handoff (or --test)")

    schema = DEFAULT_SCHEMA
    if args.rfp:
        schema = RfpSchema(**json.load(open(args.rfp)))

    handoff = load_handoff(args.handoff)
    raw_bids = load_bids(args.bids) if args.bids else None

    result = review(handoff, raw_bids, schema)

    if args.json:
        print(json.dumps({
            "tender_id": result.tender_id,
            "risk_status": result.risk_status,
            "confidence": result.confidence,
            "escalation_required": result.escalation_required,
            "plow_reported": result.plow_reported,
            "plow_recomputed": result.plow_recomputed,
            "plow_set_ok": result.plow_set_ok,
            "eligible_count": result.eligible_count,
            "findings": [f.__dict__ for f in result.findings],
            "escalations": [m.__dict__ for m in result.escalations],
        }, indent=2))
    else:
        print(full_report(result, handoff))
    return 0


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

SAMPLE_HANDOFF = {
    "tender_id": "ADNOC-LCIG/RFP/2026-0412",
    "plow": 38_000_000.0,
    "plow_set": "Gulfstream Engineering and Contracting WLL",
    "ranked_evaluations": [
        {
            "supplier": "Al Manara Process Solutions LLC",
            "mandatory_screening": "PASS",
            "technical_compliance": "PASS",
            "eligible_for_award": True,
            "scores": {
                "technical": {"points": 38.6, "max": 40, "criteria": {
                    "T1": {"band": 5, "points": 15.0, "max": 15},
                    "T2": {"band": 5, "points": 10.0, "max": 10},
                    "T3": {"band": 5, "points": 8.0, "max": 8},
                    "T4": {"band": 4, "points": 5.6, "max": 7}}},
                "commercial": {"points": 27.8, "max": 30,
                               "formula": "30 * (38,000,000.00 / 41,000,000.00)"},
                "hse": {"points": 15.0, "max": 15, "criteria": {
                    "H1": {"band": 5, "points": 9.0, "max": 9},
                    "H2": {"band": 5, "points": 6.0, "max": 6}}},
                "icv": {"points": 13.0, "max": 15, "formula": "15 * min(52.0%, 60.0%) / 60.0"},
                "total": {"points": 94.4, "max": 100},
            },
            "missing_information": [],
            "evidence_sources": {"D1": "Bid_V01, D1, p.1", "capacity": "Bid_V01, D2, p.12"},
        },
        {
            "supplier": "Gulfstream Engineering and Contracting WLL",
            "mandatory_screening": "PASS",
            "technical_compliance": "PASS",
            "eligible_for_award": True,
            "scores": {
                "technical": {"points": 27.0, "max": 40, "criteria": {
                    "T1": {"band": 3, "points": 9.0, "max": 15},
                    "T2": {"band": 3, "points": 6.0, "max": 10},
                    "T3": {"band": 4, "points": 6.4, "max": 8},
                    "T4": {"band": 4, "points": 5.6, "max": 7}}},
                "commercial": {"points": 30.0, "max": 30,
                               "formula": "30 * (38,000,000.00 / 38,000,000.00)"},
                "hse": {"points": 9.0, "max": 15, "criteria": {
                    "H1": {"band": 3, "points": 5.4, "max": 9},
                    "H2": {"band": 3, "points": 3.6, "max": 6}}},
                "icv": {"points": 9.5, "max": 15, "formula": "15 * min(38.0%, 60.0%) / 60.0"},
                "total": {"points": 75.5, "max": 100},
            },
            "missing_information": [],
            "evidence_sources": {"D1": "Bid_V02, D1, p.1", "capacity": "Bid_V02, D2, p.10"},
        },
        {
            "supplier": "Rheinwasser Technik GmbH",
            "mandatory_screening": "PASS",
            "technical_compliance": "PASS",
            "eligible_for_award": True,
            "scores": {
                "technical": {"points": 33.2, "max": 40, "criteria": {
                    "T1": {"band": 4, "points": 12.0, "max": 15},
                    "T2": {"band": 4, "points": 8.0, "max": 10},
                    "T3": {"band": 4, "points": 6.4, "max": 8},
                    "T4": {"band": 4, "points": 5.6, "max": 7}}},
                "commercial": {"points": 24.0, "max": 30,
                               "formula": "30 * (38,000,000.00 / 47,500,000.00)"},
                "hse": {"points": 12.6, "max": 15, "criteria": {
                    "H1": {"band": 4, "points": 7.2, "max": 9},
                    "H2": {"band": 3, "points": 3.6, "max": 6}}},
                "icv": {"points": 12.0, "max": 15, "formula": "15 * min(48.0%, 60.0%) / 60.0"},
                "total": {"points": 81.8, "max": 100},
            },
            "missing_information": [],
            "evidence_sources": {"D1": "Bid_V03, D1, p.1", "capacity": "Bid_V03, D2, p.9"},
        },
    ],
    "ineligible_evaluations": [
        {
            "supplier": "Petrotech Arabia Ltd",
            "mandatory_screening": "CONDITIONALLY NON-COMPLIANT - missing: D8",
            "technical_compliance": "FAIL - net capacity < 30,000 m³/d",
            "eligible_for_award": False,
            "scores": {
                "technical": {"points": 18.8, "max": 40, "criteria": {
                    "T1": {"band": 0, "points": 0.0, "max": 15},
                    "T2": {"band": 4, "points": 8.0, "max": 10},
                    "T3": {"band": 5, "points": 8.0, "max": 8},
                    "T4": {"band": 2, "points": 2.8, "max": 7}}},
                "commercial": {"points": None, "max": 30, "formula": None},
                "hse": {"points": 13.2, "max": 15, "criteria": {
                    "H1": {"band": 4, "points": 7.2, "max": 9},
                    "H2": {"band": 5, "points": 6.0, "max": 6}}},
                "icv": {"points": 7.5, "max": 15, "formula": "15 * min(30.0%, 60.0%) / 60.0"},
                "total": {"points": None, "max": 100},
            },
            "missing_information": [],
            "evidence_sources": {"D1": "Bid_V07, D1, p.1", "capacity": "Bid_V07, D2, p.8"},
        },
    ],
    "explanation": ["Al Manara ranked above Gulfstream..."],
    "note": "decision-support only",
}

SAMPLE_RAW_BIDS = [
    {"name": "Al Manara Process Solutions LLC", "docs": {f"D{i}": True for i in range(1, 10)},
     "icv_cert_valid": True, "capacity_m3d": 35000, "oiw_outlet": 4.5,
     "weeks_to_completion": 54, "warranty_months": 36, "gcc_refs": 9, "years_exp": 18,
     "price_aed": 41000000, "trir": 0.18, "fatality": False, "iso45001": True,
     "iso14001": True, "icv_pct": 52.0},
    {"name": "Gulfstream Engineering and Contracting WLL",
     "docs": {f"D{i}": True for i in range(1, 10)},
     "icv_cert_valid": True, "capacity_m3d": 31000, "oiw_outlet": 9.5,
     "weeks_to_completion": 60, "warranty_months": 24, "gcc_refs": 4, "years_exp": 11,
     "price_aed": 38000000, "trir": 0.45, "fatality": False, "iso45001": True,
     "iso14001": False, "icv_pct": 38.0},
    {"name": "Rheinwasser Technik GmbH",
     "docs": {f"D{i}": True for i in range(1, 10)},
     "icv_cert_valid": True, "capacity_m3d": 32500, "oiw_outlet": 6.5,
     "weeks_to_completion": 58, "warranty_months": 30, "gcc_refs": 6, "years_exp": 13,
     "price_aed": 47500000, "trir": 0.32, "fatality": False, "iso45001": True,
     "iso14001": False, "icv_pct": 48.0},
]


def _mk_bid(name: str, **overrides: Any) -> dict[str, Any]:
    """Build a clean raw bid dict from defaults + overrides (test helper)."""
    base = {
        "name": name,
        "docs": {f"D{i}": True for i in range(1, 10)},
        "icv_cert_valid": True, "capacity_m3d": 34000, "oiw_outlet": 6.0,
        "weeks_to_completion": 55, "warranty_months": 30, "gcc_refs": 7, "years_exp": 14,
        "price_aed": 40000000, "trir": 0.25, "fatality": False, "iso45001": True,
        "iso14001": True, "icv_pct": 45.0,
    }
    base.update(overrides)
    return base


def run_tests() -> int:
    print("Running risk & escalation test harness...")
    failures = 0

    def check(label: str, actual: Any, expected: Any) -> None:
        nonlocal failures
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
            print(f"  [{status}] {label}: expected {expected!r}, got {actual!r}")
        else:
            print(f"  [{status}] {label}")

    # Clean handoff (correctly evaluated bids -> no risk findings) ----------
    r = review(SAMPLE_HANDOFF, schema=DEFAULT_SCHEMA)
    check("Clean handoff -> risk status LOW", r.risk_status, "LOW")
    check("Clean handoff -> confidence HIGH", r.confidence, "HIGH")
    check("Clean handoff -> no escalation", r.escalation_required, False)

    # Evaluator MISSED a fatal flaw: says PASS but raw data shows FAIL -----
    missed_handoff = json.loads(json.dumps(SAMPLE_HANDOFF))
    missed_handoff["ineligible_evaluations"][0]["mandatory_screening"] = "PASS"
    missed_handoff["ineligible_evaluations"][0]["technical_compliance"] = "PASS"
    missed_handoff["ineligible_evaluations"][0]["eligible_for_award"] = True
    raw_missed = [
        {"name": "Petrotech Arabia Ltd", "docs": {f"D{i}": True for i in range(1, 10) if i != 8},
         "icv_cert_valid": True, "capacity_m3d": 28500, "oiw_outlet": 8.0,
         "weeks_to_completion": 70, "warranty_months": 24, "gcc_refs": 6, "years_exp": 15,
         "price_aed": 35000000, "trir": 0.25, "fatality": False, "iso45001": True,
         "iso14001": True, "icv_pct": 30.0},
    ]
    r2 = review(missed_handoff, raw_bids=raw_missed, schema=DEFAULT_SCHEMA)
    check("Missed fatal flaw -> HUMAN REVIEW REQUIRED", r2.risk_status, "HUMAN REVIEW REQUIRED")
    check("Missed fatal flaw -> escalation YES", r2.escalation_required, True)
    check("Missed fatal flaw -> confidence LOW", r2.confidence, "LOW")
    check("Missed fatal flaw -> P7 (cross-check finding)",
          any(f.flag == "P7" for f in r2.findings), True)

    # Arithmetic discrepancy (P8) ------------------------------------------
    arith = json.loads(json.dumps(SAMPLE_HANDOFF))
    arith["ranked_evaluations"][0]["scores"]["total"]["points"] = 94.4 - 3.0  # wrong total
    r3 = review(arith, schema=DEFAULT_SCHEMA)
    check("Arithmetic error detected (P8)", any(f.flag == "P8" for f in r3.findings), True)
    check("Arithmetic error -> escalation", r3.escalation_required, True)

    # Band cross-check with raw bids (P7) ----------------------------------
    r4 = review(SAMPLE_HANDOFF, raw_bids=SAMPLE_RAW_BIDS, schema=DEFAULT_SCHEMA)
    check("Band cross-check passes on consistent data", r4.risk_status, "LOW")
    check("Plow recomputation matches", abs(r4.plow_recomputed - 38_000_000) < 1, True)

    # Tamper one band in the handoff -> cross-check must catch it
    tampered = json.loads(json.dumps(SAMPLE_HANDOFF))
    tampered["ranked_evaluations"][0]["scores"]["technical"]["criteria"]["T1"]["band"] = 4
    r5 = review(tampered, raw_bids=SAMPLE_RAW_BIDS, schema=DEFAULT_SCHEMA)
    check("Band cross-check catches tampered T1 (P7)",
          any(f.flag == "P7" for f in r5.findings), True)

    # Plow fidelity (P8): disqualified cheap bid must not set Plow ----------
    raw_with_cheap = SAMPLE_RAW_BIDS + [
        _mk_bid("Cheap Disqualified", icv_cert_valid=False, price_aed=5_000_000)]
    r6 = review(SAMPLE_HANDOFF, raw_bids=raw_with_cheap, schema=DEFAULT_SCHEMA)
    check("Plow set OK despite disqualified cheap bid", r6.plow_set_ok, True)

    # Ranking sensitivity (P2) ---------------------------------------------
    tight = json.loads(json.dumps(SAMPLE_HANDOFF))
    tight["ranked_evaluations"][1]["scores"]["total"]["points"] = 94.3  # gap 0.1
    r7 = review(tight, schema=DEFAULT_SCHEMA)
    check("Ranking fragility flagged (P2)",
          any(f.flag == "P2" and "Ranking fragility" in f.finding for f in r7.findings), True)

    # Evidence gap (P7) -----------------------------------------------------
    gap = json.loads(json.dumps(SAMPLE_HANDOFF))
    gap["ranked_evaluations"][0]["missing_information"] = ["T2: Insufficient evidence to calculate this criterion."]
    r8 = review(gap, schema=DEFAULT_SCHEMA)
    check("Evidence gap recorded (UNRESOLVED)",
          any(f.claim_class == "UNRESOLVED" for f in r8.findings), True)

    # Threshold proximity (P1) ---------------------------------------------
    near_raw = [_mk_bid("Near Threshold Bidder", capacity_m3d=30200, oiw_outlet=9.5,
                        weeks_to_completion=75, trir=0.19)]
    near_handoff = {"tender_id": "ADNOC-LCIG/RFP/2026-0412", "plow": 40000000,
                    "plow_set": "Near Threshold Bidder",
                    "ranked_evaluations": [{
                        "supplier": "Near Threshold Bidder", "mandatory_screening": "PASS",
                        "technical_compliance": "PASS", "eligible_for_award": True,
                        "scores": {"technical": {"points": 30.0, "max": 40, "criteria": {}},
                                   "commercial": {"points": 30.0, "max": 30,
                                                  "formula": "30 * (40000000 / 40000000)"},
                                   "hse": {"points": 15.0, "max": 15, "criteria": {}},
                                   "icv": {"points": 10.0, "max": 15,
                                           "formula": "15 * min(40.0%, 60.0%) / 60.0"},
                                   "total": {"points": 85.0, "max": 100}},
                        "missing_information": [], "evidence_sources": {}}],
                    "ineligible_evaluations": [], "explanation": [], "note": ""}
    r9 = review(near_handoff, raw_bids=near_raw, schema=DEFAULT_SCHEMA)
    p1_findings = [f for f in r9.findings if f.flag == "P1"]
    check("P1 threshold proximity flags generated", len(p1_findings) >= 3, True)
    check("P1 flags are LOW (watch, not escalate)",
          all(f.materiality == "LOW" for f in p1_findings), True)
    check("P6 single-point dependency flagged",
          any(f.flag == "P6" for f in r9.findings), True)

    # P4 temporal validity --------------------------------------------------
    p4_raw = [_mk_bid("Expired ICV", icv_cert_valid=True, icv_cert_valid_until="2026-06-01"),
              _mk_bid("Short Bond", bond_valid_days=90, bond_pct=2.0)]
    r10 = review(SAMPLE_HANDOFF, raw_bids=p4_raw, schema=DEFAULT_SCHEMA)
    check("P4 expired ICV escalated", any(f.flag == "P4" and f.supplier == "Expired ICV"
                                          for f in r10.findings), True)
    check("P4 short bond escalated", any(f.flag == "P4" and f.supplier == "Short Bond"
                                         for f in r10.findings), True)

    # P5 conditional content ------------------------------------------------
    p5_raw = [_mk_bid("Conditional Bidder", conditions=["Price subject to final board approval"])]
    r11 = review(SAMPLE_HANDOFF, raw_bids=p5_raw, schema=DEFAULT_SCHEMA)
    check("P5 conditional content escalated",
          any(f.flag == "P5" for f in r11.findings), True)

    # P9 collusion (identical totals) ---------------------------------------
    p9_raw = [_mk_bid("Bidder A", total_price=41_000_000.0),
              _mk_bid("Bidder B", total_price=41_000_000.0)]
    r12 = review(SAMPLE_HANDOFF, raw_bids=p9_raw, schema=DEFAULT_SCHEMA)
    check("P9 collusion indicator (identical totals) escalated",
          any(f.flag == "P9" for f in r12.findings), True)

    # P10 extraction uncertainty --------------------------------------------
    p10_raw = [_mk_bid("Scan Bidder", extraction_quality={"capacity_m3d": "low-quality scan"})]
    r13 = review(SAMPLE_HANDOFF, raw_bids=p10_raw, schema=DEFAULT_SCHEMA)
    check("P10 extraction uncertainty recorded",
          any(f.flag == "P10" for f in r13.findings), True)

    # P11 guarantee unverifiability ------------------------------------------
    p11_raw = [_mk_bid("No Test Method", guarantee_test_method="not specified")]
    r14 = review(SAMPLE_HANDOFF, raw_bids=p11_raw, schema=DEFAULT_SCHEMA)
    check("P11 guarantee unverifiability escalated",
          any(f.flag == "P11" for f in r14.findings), True)

    # Category 9 execution/interface + category 8 declarations ---------------
    r15_raw = [_mk_bid("No Interface Plan", execution_plan=False,
                       integrity_declarations=["anti-commission"])]
    r15 = review(SAMPLE_HANDOFF, raw_bids=r15_raw, schema=DEFAULT_SCHEMA)
    check("Cat 9 execution/interface flagged",
          any(f.category == 9 for f in r15.findings), True)
    check("Cat 8 missing integrity declarations flagged",
          any(f.category == 8 for f in r15.findings), True)

    # Confidence calibration: HIGH/MEDIUM/LOW --------------------------------
    check("Confidence LOW when CRITICAL", r2.confidence, "LOW")
    # MEDIUM: evidence gap is a watch item (not escalation) but materiality
    # is MEDIUM -> risk status MEDIUM, confidence MEDIUM, no escalation.
    med = review(gap, schema=DEFAULT_SCHEMA)
    check("Confidence MEDIUM when only watch items", med.confidence, "MEDIUM")
    check("Watch items do NOT force escalation", med.escalation_required, False)
    check("Risk status MEDIUM from watch items", med.risk_status, "MEDIUM")

    print("-" * 78)
    if failures:
        print(f"RESULT: {failures} test(s) FAILED")
        return 1
    print("RESULT: all tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
