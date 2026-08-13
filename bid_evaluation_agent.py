#!/usr/bin/env python3
"""
Bid Evaluation Agent
====================
Python implementation of the Bid Evaluation Agent — the middle stage of the
ADNOC Upstream Procurement Evaluation System (see bid_evaluation_agent.md).

Pipeline position:
    Procurement Evidence & Retrieval Agent  (upstream: supplies structured evidence)
    -> BID EVALUATION AGENT (this module)
    -> Risk & Escalation Agent  (downstream: consumes scores + evidence citations)

Implements the 7-step MANDATORY WORKFLOW:
    STEP 1  Mandatory screening (D1-D9)          -> conditionally non-compliant?
    STEP 2  Minimum technical requirements        -> technically non-compliant?
    STEP 3  Technical score  (T1..T4,   /40)
    STEP 4  Commercial score (C,        /30)      C = 30 * (Plow / Pbid)
    STEP 5  HSE score        (H1..H2,   /15)
    STEP 6  ICV score        (          /15)      ICV = 15 * min(icv%, 60) / 60
    STEP 7  Total score (max 100) + supplier ranking

Evidence discipline (from the agent spec):
    - This agent NEVER gathers evidence. It consumes only the structured
      evidence handed over by the upstream agent. It does not read PDFs.
    - A missing required field is reported as
          "Insufficient evidence to calculate this criterion."
      and is NEVER guessed, inferred, or retrieved.
    - Every material conclusion carries an evidence citation.
    - Output is decision-support only — NOT an official ADNOC procurement
      decision.

Usage:
    python3 bid_evaluation_agent.py --test              # test harness (incl. RFP worked example)
    python3 bid_evaluation_agent.py bids.json           # score bids, human-readable report
    python3 bid_evaluation_agent.py bids.json --json    # machine-readable handoff for downstream agent
    python3 bid_evaluation_agent.py - < bids.json       # read bids from stdin

Stdlib only. No dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration (RFP Section 6 — ADNOC-LCIG/RFP/2026-0412)
# ---------------------------------------------------------------------------


@dataclass
class RFPConfig:
    """Evaluation configuration extracted from the RFP (Section 6)."""

    name: str = "ADNOC-LCIG/RFP/2026-0412"
    # Category weights (must sum to 100)
    tech_weight: float = 40.0
    commercial_weight: float = 30.0
    hse_weight: float = 15.0
    icv_weight: float = 15.0
    # Banding scheme: points = (band / max_band) * weight
    max_band: int = 5
    # Commercial formula parameters
    fx_rate_aed_per_usd: float = 3.6725  # UAE Central Bank reference rate
    # ICV formula parameters: ICV = weight * min(icv_pct, cap) / cap
    icv_cap_pct: float = 60.0
    # Mandatory documents checklist (Section 4)
    mandatory_docs: list[str] = field(
        default_factory=lambda: [
            "D1 Company profile + valid trade licence",
            "D2 Technical proposal with equipment list/datasheets",
            "D3 Itemized commercial proposal priced in AED",
            "D4 Delivery schedule (Level 2) to mechanical completion",
            "D5 HSE statistics (3-yr TRIR, LTI, fatalities)",
            "D6 Valid ICV certificate (MoIAT-certified body)",
            "D7 Audited financial statements (last 2 years)",
            "D8 Bid bond / bank guarantee (2%, 150-day validity)",
            "D9 Warranty statement (min 24 months from acceptance)",
        ]
    )


DEFAULT_CONFIG = RFPConfig()

MISSING_PHRASE = "Insufficient evidence to calculate this criterion."


# ---------------------------------------------------------------------------
# Band tables (RFP Section 6.1 / 6.3) — every function returns (band, note).
# band=None means the evidence is missing; the note carries the standard phrase.
# ---------------------------------------------------------------------------


def band_t1(capacity_m3d: Optional[float], oiw_outlet: Optional[float]) -> tuple[Optional[int], str]:
    """T1 Process capacity & performance guarantee (weight 15)."""
    if capacity_m3d is None or oiw_outlet is None:
        return None, f"{MISSING_PHRASE} (T1: capacity or outlet OiW not provided by upstream agent)"
    if capacity_m3d < 30_000 or oiw_outlet > 10.0:
        return 0, "capacity < 30,000 m³/d OR OiW > 10 mg/L -> technically non-compliant (rejected)"
    if capacity_m3d >= 33_000 and oiw_outlet <= 5.0:
        return 5, "capacity >= 33,000 m³/d AND OiW <= 5 mg/L"
    if capacity_m3d >= 31_500 and oiw_outlet <= 8.0:
        return 4, "capacity >= 31,500 m³/d AND OiW <= 8 mg/L"
    return 3, "capacity >= 30,000 m³/d AND OiW <= 10 mg/L (meets specification)"


def band_t2(gcc_refs: Optional[int]) -> tuple[Optional[int], str]:
    """T2 Technology track record, GCC refs >= 20,000 m³/d, last 10 yrs (10)."""
    if gcc_refs is None:
        return None, f"{MISSING_PHRASE} (T2: GCC reference count not provided by upstream agent)"
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
        return None, f"{MISSING_PHRASE} (T3: years of experience not provided by upstream agent)"
    if years_exp >= 15:
        return 5, f"{years_exp} years (>= 15)"
    if years_exp >= 10:
        return 4, f"{years_exp} years (10-14)"
    if years_exp >= 6:
        return 3, f"{years_exp} years (6-9)"
    if years_exp >= 3:
        return 2, f"{years_exp} years (3-5)"
    return 1, f"{years_exp} years (< 3)"


def band_t4(weeks: Optional[float]) -> tuple[Optional[int], str]:
    """T4 Delivery schedule, weeks LOA -> mechanical completion (7)."""
    if weeks is None:
        return None, f"{MISSING_PHRASE} (T4: delivery schedule not provided by upstream agent)"
    if weeks <= 52:
        return 5, f"{weeks} weeks (<= 52)"
    if weeks <= 60:
        return 4, f"{weeks} weeks (53-60)"
    if weeks <= 68:
        return 3, f"{weeks} weeks (61-68)"
    if weeks <= 76:
        return 2, f"{weeks} weeks (69-76, contractual maximum)"
    return 1, f"{weeks} weeks (> 76) -> subject to rejection as non-compliant"


def band_h1(trir: Optional[float], fatality: Optional[bool]) -> tuple[Optional[int], str]:
    """H1 Safety performance, 3-yr avg TRIR per 200,000 manhours (9)."""
    if trir is None or fatality is None:
        return None, f"{MISSING_PHRASE} (H1: TRIR or fatality record not provided by upstream agent)"
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
        return None, f"{MISSING_PHRASE} (H2: ISO certification status not provided by upstream agent)"
    if iso45001 and iso14001:
        return 5, "both ISO 45001 and ISO 14001 valid"
    if iso45001 or iso14001:
        return 3, "exactly one of ISO 45001 / ISO 14001 valid"
    return 1, "neither ISO 45001 nor ISO 14001 valid"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Bid:
    """Raw bid data as extracted from the supplier submission (upstream input).

    Every field is Optional: a None value means the upstream agent did not
    provide the evidence. None is NEVER coerced to a default — it is reported
    as "Insufficient evidence to calculate this criterion."
    """

    name: str
    # Mandatory screening (D1-D9): doc code -> submitted?  (D6 additionally needs validity)
    docs: dict[str, bool]
    icv_cert_valid: Optional[bool]  # D6 validity on bid submission date; None = unknown
    # Minimum technical requirements (Section 5.1)
    capacity_m3d: Optional[float]
    oiw_outlet: Optional[float]  # mg/L monthly average
    weeks_to_completion: Optional[float]
    warranty_months: Optional[float]
    # Technical (Section 6.1)
    gcc_refs: Optional[int]
    years_exp: Optional[float]
    # Commercial (Section 6.2): price in AED after conversion/arithmetic fix
    price_aed: Optional[float]
    # HSE (Section 6.3)
    trir: Optional[float]
    fatality: Optional[bool]
    iso45001: Optional[bool]
    iso14001: Optional[bool]
    # ICV (Section 6.4)
    icv_pct: Optional[float]  # certified ICV %, None if no certificate
    # Evidence bookkeeping: field key -> citation string (doc, page/section)
    evidence: dict[str, str] = field(default_factory=dict)

    def cite(self, key: str) -> str:
        """Return the citation for a field, or the missing-evidence phrase."""
        return self.evidence.get(key, f"{MISSING_PHRASE} — no citation provided for '{key}'")

    # -- screening ---------------------------------------------------------

    def missing_docs(self) -> list[str]:
        """Mandatory docs the RFP requires that were NOT submitted.

        Checks against the RFP's mandatory document codes (D1-D9), not just
        the keys present in the input dict — an absent key from the upstream
        agent counts as a missing document, never as silent compliance.
        """
        expected_codes = [d.split()[0] for d in DEFAULT_CONFIG.mandatory_docs]
        return [code for code in expected_codes if not self.docs.get(code, False)]

    def screening_status(self) -> str:
        """Step 1: PASS / CONDITIONALLY NON-COMPLIANT / UNVERIFIABLE."""
        missing = self.missing_docs()
        if missing:
            return f"CONDITIONALLY NON-COMPLIANT - missing: {', '.join(missing)}"
        if self.icv_cert_valid is None:
            return f"UNVERIFIABLE - D6 ICV certificate validity not provided by upstream agent"
        if not self.icv_cert_valid:
            return "CONDITIONALLY NON-COMPLIANT - D6 ICV certificate not valid on bid due date"
        return "PASS"

    @property
    def mandatory_pass(self) -> bool:
        """True only when screening is fully confirmed PASS (no unsupported assumption)."""
        return self.screening_status() == "PASS"

    # -- minimum technical requirements ------------------------------------

    def tech_requirement_failures(self) -> list[str]:
        """Step 2: stated rejection conditions breached. Missing data is never a pass."""
        fails = []
        if self.capacity_m3d is not None and self.capacity_m3d < 30_000:
            fails.append("net capacity < 30,000 m³/d")
        elif self.capacity_m3d is None:
            fails.append(f"capacity not provided ({MISSING_PHRASE})")
        if self.oiw_outlet is not None and self.oiw_outlet > 10.0:
            fails.append("outlet OiW > 10 mg/L monthly average")
        elif self.oiw_outlet is None:
            fails.append(f"outlet OiW not provided ({MISSING_PHRASE})")
        if self.weeks_to_completion is not None and self.weeks_to_completion > 76.0:
            fails.append("delivery > 76 weeks contractual maximum")
        elif self.weeks_to_completion is None:
            fails.append(f"delivery schedule not provided ({MISSING_PHRASE})")
        if self.warranty_months is not None and self.warranty_months < 24.0:
            fails.append("warranty < 24 months from acceptance")
        elif self.warranty_months is None:
            fails.append(f"warranty period not provided ({MISSING_PHRASE})")
        return fails

    def tech_compliance_status(self) -> str:
        if self.tech_requirement_failures():
            return "FAIL - " + "; ".join(self.tech_requirement_failures())
        return "PASS"

    @property
    def min_tech_pass(self) -> bool:
        """Step 2: pass only when NO rejection condition is breached AND all
        data was provided. A None field is never treated as compliant."""
        return not self.tech_requirement_failures()

    @property
    def eligible_for_award(self) -> bool:
        """Award gate: passes BOTH mandatory screening AND min technical reqs,
        with no unverifiable gate left open."""
        return self.mandatory_pass and self.min_tech_pass


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def points_for(band: Optional[int], weight: float, max_band: int) -> Optional[float]:
    """points = (band / max_band) * weight, RFP Section 6. None band -> None."""
    if band is None:
        return None
    return round((band / max_band) * weight, 2)


def convert_to_aed(amount: Optional[float], currency: Optional[str],
                   fx_rate_aed_per_usd: float) -> Optional[float]:
    """Convert a price to AED per RFP Section 6.2 / ITB 2.

    AED prices pass through unchanged. USD prices are converted at the RFP's
    reference rate. Other currencies are deviations that the upstream Evidence
    & Retrieval Agent is expected to resolve before handoff — if they reach
    this agent unconverted, the price is marked as insufficient evidence.
    """
    if amount is None:
        return None
    if currency in (None, "", "AED"):
        return round(amount, 2)
    if currency == "USD":
        return round(amount * fx_rate_aed_per_usd, 2)
    # Other currencies are commercial deviations per ITB 2 — upstream agent
    # should have resolved them. If not, we cannot evaluate.
    return None  # deliberately None — not a guess


def commercial_score(price_aed: Optional[float], plow: float, weight: float) -> Optional[float]:
    """C = weight * (Plow / Pbid), rounded to 2 dp (Section 6.2)."""
    if price_aed is None or plow <= 0 or price_aed <= 0:
        return None
    return round(weight * (plow / price_aed), 2)


def icv_score(icv_pct: Optional[float], weight: float, cap_pct: float) -> Optional[float]:
    """ICV = weight * min(icv%, cap) / cap, rounded to 2 dp (Section 6.4)."""
    if icv_pct is None:
        return None  # caller decides: no cert -> 0.0 per RFP; cert but no % -> missing
    return round(weight * min(icv_pct, cap_pct) / cap_pct, 2)


@dataclass
class Criterion:
    """One scored criterion with its evidence rationale."""

    code: str
    max_points: float
    band: Optional[int]
    points: Optional[float]
    note: str

    @property
    def missing(self) -> bool:
        return self.points is None


@dataclass
class Evaluation:
    """Full evaluation result for one supplier (steps 1-7)."""

    bid: Bid
    config: RFPConfig
    plow: float
    plow_source: str
    screening: str
    technical_compliance: str
    t1: Criterion = None  # type: ignore[assignment]
    t2: Criterion = None  # type: ignore[assignment]
    t3: Criterion = None  # type: ignore[assignment]
    t4: Criterion = None  # type: ignore[assignment]
    h1: Criterion = None  # type: ignore[assignment]
    h2: Criterion = None  # type: ignore[assignment]
    commercial: Optional[float] = None
    commercial_note: str = ""
    icv: Optional[float] = None
    icv_note: str = ""

    @property
    def technical(self) -> Optional[float]:
        pts = [c.points for c in (self.t1, self.t2, self.t3, self.t4)]
        if any(p is None for p in pts):
            return None
        return round(sum(p for p in pts), 2)  # type: ignore[arg-type]

    @property
    def hse(self) -> Optional[float]:
        pts = [c.points for c in (self.h1, self.h2)]
        if any(p is None for p in pts):
            return None
        return round(sum(p for p in pts), 2)  # type: ignore[arg-type]

    @property
    def total(self) -> Optional[float]:
        parts = [self.technical, self.commercial, self.hse, self.icv]
        if any(p is None for p in parts):
            return None
        return round(sum(parts), 2)  # type: ignore[arg-type]

    @property
    def missing_info(self) -> list[str]:
        """Every criterion that could not be scored due to missing evidence."""
        items = []
        for c in (self.t1, self.t2, self.t3, self.t4, self.h1, self.h2):
            if c.missing:
                items.append(f"{c.code}: {MISSING_PHRASE} ({c.note})")
        if self.commercial is None and self.bid.price_aed is not None and self.bid.eligible_for_award:
            items.append(f"Commercial: {MISSING_PHRASE}")
        if self.commercial is None and self.bid.price_aed is None:
            items.append(f"Commercial: {MISSING_PHRASE} (evaluated price not provided)")
        if self.icv is None and self.bid.icv_cert_valid is not False:
            items.append(f"ICV: {MISSING_PHRASE}")
        return items

    def to_dict(self) -> dict[str, Any]:
        def crit(c: Criterion) -> dict[str, Any]:
            return {"band": c.band, "points": c.points, "max": c.max_points, "basis": c.note}

        d: dict[str, Any] = {
            "supplier": self.bid.name,
            "mandatory_screening": self.screening,
            "technical_compliance": self.technical_compliance,
            "eligible_for_award": self.bid.eligible_for_award,
            "scores": {
                "technical": {"points": self.technical, "max": self.config.tech_weight,
                              "criteria": {c.code: crit(c) for c in (self.t1, self.t2, self.t3, self.t4)}},
                "commercial": {"points": self.commercial, "max": self.config.commercial_weight,
                               "formula": f"30 * ({self.plow:,.2f} / {self.bid.price_aed:,.2f})"
                                          if self.bid.price_aed is not None else None,
                               "note": self.commercial_note},
                "hse": {"points": self.hse, "max": self.config.hse_weight,
                        "criteria": {c.code: crit(c) for c in (self.h1, self.h2)}},
                "icv": {"points": self.icv, "max": self.config.icv_weight,
                        "formula": f"15 * min({self.bid.icv_pct}, {self.config.icv_cap_pct}) / {self.config.icv_cap_pct}"
                                   if self.bid.icv_pct is not None else None,
                        "note": self.icv_note},
                "total": {"points": self.total, "max": 100.0},
            },
            "missing_information": self.missing_info,
            "evidence_sources": self.bid.evidence,
        }
        return d


def evaluate(bid: Bid, config: RFPConfig, plow: float, plow_source: str) -> Evaluation:
    """Run steps 1-7 for a single bid given the precomputed Plow."""
    # Step 1 - mandatory screening
    screening = bid.screening_status()
    # Step 2 - minimum technical requirements
    technical_compliance = bid.tech_compliance_status()

    ev = Evaluation(
        bid=bid, config=config, plow=plow, plow_source=plow_source,
        screening=screening, technical_compliance=technical_compliance,
    )

    # Step 3 - technical (weights from RFP 6.1)
    for code, max_pts, fn in (
        ("T1", 15.0, lambda: band_t1(bid.capacity_m3d, bid.oiw_outlet)),
        ("T2", 10.0, lambda: band_t2(bid.gcc_refs)),
        ("T3", 8.0, lambda: band_t3(bid.years_exp)),
        ("T4", 7.0, lambda: band_t4(bid.weeks_to_completion)),
    ):
        b, note = fn()
        setattr(ev, code.lower(), Criterion(code, max_pts, b, points_for(b, max_pts, config.max_band), note))

    # Step 4 - commercial (Section 6.2): only eligible bids are scored.
    # Plow comes from the eligible set only; ineligible bids get no commercial
    # score (excluded from award consideration per ITB 5).
    if bid.eligible_for_award:
        ev.commercial = commercial_score(bid.price_aed, plow, config.commercial_weight)
        ev.commercial_note = (
            f"C = 30 * (Plow / Pbid) = 30 * ({plow:,.2f} / {bid.price_aed:,.2f}); "
            f"Plow from {plow_source}"
        )
    else:
        ev.commercial_note = "Excluded from award consideration (ITB 5) - commercial score not calculated."

    # Step 5 - HSE (Section 6.3)
    for code, max_pts, fn in (
        ("H1", 9.0, lambda: band_h1(bid.trir, bid.fatality)),
        ("H2", 6.0, lambda: band_h2(bid.iso45001, bid.iso14001)),
    ):
        b, note = fn()
        setattr(ev, code.lower(), Criterion(code, max_pts, b, points_for(b, max_pts, config.max_band), note))

    # Step 6 - ICV (Section 6.4):
    #   - no valid certificate  -> 0.0 points AND fails screening (D6) [defined by RFP]
    #   - valid cert but no %   -> missing evidence (None), never guessed
    if bid.icv_cert_valid is False:
        ev.icv = 0.0
        ev.icv_note = "No valid ICV certificate -> 0 ICV points and fails mandatory screening (D6)."
    elif bid.icv_cert_valid is None:
        ev.icv_note = f"{MISSING_PHRASE} (ICV certificate validity not provided)."
    else:
        ev.icv = icv_score(bid.icv_pct, config.icv_weight, config.icv_cap_pct)
        if bid.icv_pct is None:
            ev.icv_note = f"{MISSING_PHRASE} (certified ICV % not provided)."
        else:
            ev.icv_note = f"ICV = 15 * min({bid.icv_pct}%, {config.icv_cap_pct}%) / {config.icv_cap_pct}"

    return ev


def compute_plow(bids: list[Bid], config: RFPConfig) -> tuple[float, str]:
    """Plow = lowest evaluated price among bids passing BOTH gates (6.2).

    Returns (plow, source_description). Returns (0.0, "no eligible bids") when
    the eligible set is empty — never substitutes an ineligible price.
    """
    eligible = [b for b in bids if b.eligible_for_award]
    if not eligible:
        return 0.0, "no eligible bids"
    prices = [b.price_aed for b in eligible]
    if any(p is None for p in prices):
        priced = [b for b in eligible if b.price_aed is not None]
        if not priced:
            return 0.0, "no eligible bids with an evaluated price"
        eligible = priced
    plow = min(b.price_aed for b in eligible)  # type: ignore[type-var]
    src = ", ".join(b.name for b in eligible if b.price_aed == plow)
    return plow, src


def evaluate_all(bids: list[Bid], config: RFPConfig = DEFAULT_CONFIG) -> tuple[list[Evaluation], float, str]:
    """Evaluate every bid; return (ranked eligible evaluations, plow, plow_source)."""
    plow, plow_source = compute_plow(bids, config)
    evals = [evaluate(b, config, plow, plow_source) for b in bids]
    eligible = [e for e in evals if e.bid.eligible_for_award]
    eligible.sort(key=lambda e: (e.total if e.total is not None else -1.0), reverse=True)
    return eligible, plow, plow_source


# ---------------------------------------------------------------------------
# Reporting (agent.md output template)
# ---------------------------------------------------------------------------


def format_number(x: Optional[float], digits: int = 2) -> str:
    return "N/A" if x is None else f"{x:.{digits}f}"


def supplier_card(e: Evaluation) -> str:
    """Render the OUTPUT FOR EACH SUPPLIER template from bid_evaluation_agent.md."""
    b = e.bid
    lines = [
        "=" * 78,
        f"Supplier: {b.name}",
        "=" * 78,
        f"Mandatory Screening: {e.screening}",
        f"Technical Compliance: {e.technical_compliance}",
        "",
        f"Technical Score: {format_number(e.technical)} / {e.config.tech_weight:.0f}",
    ]
    for c in (e.t1, e.t2, e.t3, e.t4):
        lines.append(f"  {c.code} ({c.max_points:.0f}): band {c.band} -> {format_number(c.points)} | {c.note}")
    lines.append(f"Commercial Score: {format_number(e.commercial)} / {e.config.commercial_weight:.0f}"
                 f"   [{e.commercial_note}]")
    lines.append(f"HSE Score: {format_number(e.hse)} / {e.config.hse_weight:.0f}")
    for c in (e.h1, e.h2):
        lines.append(f"  {c.code} ({c.max_points:.0f}): band {c.band} -> {format_number(c.points)} | {c.note}")
    lines.append(f"ICV Score: {format_number(e.icv)} / {e.config.icv_weight:.0f}   [{e.icv_note}]")
    lines.append(f"Total Score: {format_number(e.total)} / 100")
    lines.append("")
    lines.append("Key Strengths:")
    for s in strengths(e):
        lines.append(f"  - {s}")
    lines.append("Key Weaknesses:")
    for w in weaknesses(e):
        lines.append(f"  - {w}")
    lines.append("Missing Information:")
    mi = e.missing_info
    lines.append("  - (none)" if not mi else "".join(f"  - {m}" for m in mi))
    lines.append("Risks:")
    for r in risks(e):
        lines.append(f"  - {r}")
    lines.append("Evidence Sources:")
    if b.evidence:
        for k, v in b.evidence.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (no citations provided by upstream agent)")
    lines.append("")
    return "\n".join(lines)


def strengths(e: Evaluation) -> list[str]:
    s = []
    if e.bid.eligible_for_award:
        s.append("Passes mandatory screening (D1-D9) and minimum technical requirements")
    for c in (e.t1, e.t2, e.t3, e.t4, e.h1, e.h2):
        if c.points is not None and c.max_points > 0 and c.points >= 0.8 * c.max_points:
            s.append(f"Strong {c.code} result: {c.points:.2f}/{c.max_points:.0f} (band {c.band}) — {c.note}")
    if e.commercial is not None and e.plow > 0 and e.bid.price_aed is not None:
        ratio = e.bid.price_aed / e.plow
        if ratio <= 1.05:
            s.append(f"Highly competitive pricing (within 5% of Plow {e.plow:,.2f} AED)")
        elif ratio <= 1.15:
            s.append(f"Competitive pricing ({ratio:.2f}x Plow)")
    if e.icv is not None and e.icv >= 0.8 * e.config.icv_weight:
        s.append(f"Strong ICV contribution: {e.icv:.2f}/{e.config.icv_weight:.0f} (national value)")
    return s


def weaknesses(e: Evaluation) -> list[str]:
    w = []
    if not e.bid.eligible_for_award:
        w.append("NOT eligible for award — excluded from consideration and from Plow set")
    for c in (e.t1, e.t2, e.t3, e.t4, e.h1, e.h2):
        if c.points is not None and c.max_points > 0 and c.points <= 0.4 * c.max_points and c.points > 0:
            w.append(f"Weak {c.code} result: {c.points:.2f}/{c.max_points:.0f} (band {c.band}) — {c.note}")
    if e.commercial is not None and e.plow > 0 and e.bid.price_aed is not None:
        ratio = e.bid.price_aed / e.plow
        if ratio >= 1.30:
            w.append(f"Price premium: {ratio:.2f}x the lowest evaluated price ({e.bid.price_aed:,.2f} AED)")
    if e.icv is not None and e.icv <= 0.4 * e.config.icv_weight:
        w.append(f"Low ICV contribution: {e.icv:.2f}/{e.config.icv_weight:.0f}")
    return w


def risks(e: Evaluation) -> list[str]:
    r = []
    if not e.bid.eligible_for_award:
        r.append("Excluded from award consideration (conditionally/technically non-compliant)")
    if e.bid.fatality is True:
        r.append("Work-related fatality in 3-year period — H1 band 0 floor applies")
    if e.bid.weeks_to_completion is not None and e.bid.weeks_to_completion > 76:
        r.append("Delivery exceeds 76-week contractual maximum — subject to rejection")
    if e.bid.warranty_months is not None and e.bid.warranty_months < 24:
        r.append("Warranty shorter than required 24 months from acceptance")
    if e.bid.icv_cert_valid is False:
        r.append("No valid ICV certificate on bid date — D6 failure")
    for m in e.missing_info:
        r.append(m)
    return r


def explanation(evals: list[Evaluation]) -> list[str]:
    """EXPLANATION (agent.md): why each supplier ranked higher than the next.

    Explicitly identifies trade-offs such as:
      - Lower price versus stronger technical performance
      - Higher ICV versus lower commercial price
      - Better HSE versus weaker delivery
      - Lower risk versus higher cost
    Only comparisons grounded in computed scores / provided evidence are made.
    """
    lines = []
    for i in range(len(evals) - 1):
        hi, lo = evals[i], evals[i + 1]
        if hi.total is None or lo.total is None:
            continue  # cannot explain a ranking gap without both totals

        gap = hi.total - lo.total
        lines.append(f"{hi.bid.name} ranked above {lo.bid.name} "
                     f"(Total {hi.total:.2f} vs {lo.total:.2f}, gap {gap:+.2f}).")

        # --- trade-off: lower price vs stronger technical performance ------
        if (hi.bid.price_aed is not None and lo.bid.price_aed is not None
                and hi.technical is not None and lo.technical is not None):
            price_delta = hi.bid.price_aed - lo.bid.price_aed
            tech_delta = hi.technical - lo.technical
            if price_delta > 0 and tech_delta > 0:
                lines.append(
                    f"  - Trade-off (price vs technical): {hi.bid.name} costs "
                    f"{price_delta:,.0f} AED more than {lo.bid.name} "
                    f"(commercial {hi.commercial:.2f} vs {lo.commercial:.2f}) but "
                    f"outperforms on technical by {tech_delta:.2f} points."
                )
            elif price_delta < 0 and tech_delta < 0:
                lines.append(
                    f"  - Trade-off (price vs technical): {hi.bid.name} is cheaper "
                    f"({price_delta:,.0f} AED) and therefore scores higher "
                    f"commercially, but trails {lo.bid.name} technically by "
                    f"{-tech_delta:.2f} points."
                )

        # --- trade-off: higher ICV vs lower commercial price ----------------
        if (hi.icv is not None and lo.icv is not None
                and hi.commercial is not None and lo.commercial is not None
                and hi.icv > lo.icv and hi.commercial < lo.commercial):
            lines.append(
                f"  - Trade-off (ICV vs price): {hi.bid.name} gains "
                f"{hi.icv - lo.icv:.2f} ICV points over {lo.bid.name} while "
                f"conceding {lo.commercial - hi.commercial:.2f} commercial points."
            )

        # --- trade-off: better HSE vs weaker delivery -----------------------
        if (hi.hse is not None and lo.hse is not None
                and hi.t4.points is not None and lo.t4.points is not None
                and hi.hse > lo.hse and hi.t4.points < lo.t4.points):
            lines.append(
                f"  - Trade-off (HSE vs delivery): {hi.bid.name} has the stronger "
                f"HSE profile ({hi.hse:.2f} vs {lo.hse:.2f}) but offers a longer "
                f"delivery schedule (T4 {hi.t4.points:.2f} vs {lo.t4.points:.2f})."
            )

        # --- trade-off: lower risk vs higher cost ----------------------------
        hi_risks, lo_risks = risks(hi), risks(lo)
        if (len(hi_risks) < len(lo_risks)
                and hi.bid.price_aed is not None and lo.bid.price_aed is not None
                and hi.bid.price_aed > lo.bid.price_aed):
            lines.append(
                f"  - Trade-off (risk vs cost): {hi.bid.name} carries fewer "
                f"flagged risks ({len(hi_risks)} vs {len(lo_risks)}) at a price "
                f"premium of {hi.bid.price_aed - lo.bid.price_aed:,.0f} AED."
            )

    return lines


def report(evals: list[Evaluation], all_evals: list[Evaluation], plow: float, plow_source: str) -> str:
    lines = [
        "=" * 78,
        "BID EVALUATION REPORT",
        f"Tender: {DEFAULT_CONFIG.name}",
        f"Plow (lowest evaluated price among ELIGIBLE bids): {plow:,.2f} AED"
        + (f"  [{plow_source}]" if plow_source else ""),
        "=" * 78,
        "",
        "RANKED LIST (eligible suppliers, highest total first):",
        f"{'Rank':<6}{'Supplier':<42}{'Total':<10}{'Tech':<8}{'Com':<8}{'HSE':<8}{'ICV':<8}",
        "-" * 78,
    ]
    for i, e in enumerate(evals, start=1):
        lines.append(
            f"{i:<6}{e.bid.name:<42}{format_number(e.total):<10}{format_number(e.technical):<8}"
            f"{format_number(e.commercial):<8}{format_number(e.hse):<8}{format_number(e.icv):<8}"
        )
    lines.append("")
    lines.append("EXPLANATION (why each supplier ranked higher — trade-offs):")
    expl = explanation(evals)
    if expl:
        lines.extend(f"  {x}" for x in expl)
    else:
        lines.append("  - (single eligible supplier or no comparable totals)")
    lines.append("")
    lines.append("Note: the cheapest supplier is NOT automatically recommended — "
                 "commercial score is only one part (30/100) of the overall evaluation.")
    lines.append("")
    lines.append("NOT ELIGIBLE (excluded from award consideration — benchmark scores only):")
    ineligible = [e for e in all_evals if not e.bid.eligible_for_award]
    if ineligible:
        for e in ineligible:
            lines.append(f"  - {e.bid.name}: {e.screening} | {e.technical_compliance}")
    else:
        lines.append("  (none)")
    lines.append("")
    for e in evals + ineligible:
        lines.append(supplier_card(e))
    lines.append("=" * 78)
    lines.append("Disclaimer: decision-support output only — not an official ADNOC procurement decision.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def bid_from_dict(d: dict[str, Any], config: RFPConfig = DEFAULT_CONFIG) -> Bid:
    """Load a bid from the upstream JSON schema. Absent/None values stay None.

    Commercial price may arrive either pre-converted as ``price_aed`` (the
    normal upstream handoff) or as ``price`` + ``currency``, in which case it
    is converted to AED at the RFP reference rate (ITB 2: AED 3.6725/USD).
    Unconvertible currencies yield None -> "Insufficient evidence ...".
    """
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
            price_aed = convert_to_aed(raw_price, d.get("currency"), config.fx_rate_aed_per_usd)

    return Bid(
        name=d["name"],
        docs={k: bool(v) for k, v in d.get("docs", {}).items()},
        icv_cert_valid=opt_bool("icv_cert_valid"),
        capacity_m3d=opt_float("capacity_m3d"),
        oiw_outlet=opt_float("oiw_outlet"),
        weeks_to_completion=opt_float("weeks_to_completion"),
        warranty_months=opt_float("warranty_months"),
        gcc_refs=opt_int("gcc_refs"),
        years_exp=opt_float("years_exp"),
        price_aed=price_aed,
        trir=opt_float("trir"),
        fatality=opt_bool("fatality"),
        iso45001=opt_bool("iso45001"),
        iso14001=opt_bool("iso14001"),
        icv_pct=opt_float("icv_pct"),
        evidence=dict(d.get("evidence", {})),
    )


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

WORKED_EXAMPLE = {
    "name": "WorkedExampleBid",
    "docs": {f"D{i}": True for i in range(1, 10)},
    "icv_cert_valid": True,
    "capacity_m3d": 32_000,
    "oiw_outlet": 6.0,
    "weeks_to_completion": 58,
    "warranty_months": 24,
    "gcc_refs": 6,
    "years_exp": 12,
    "price_aed": 44_000_000,
    "trir": 0.35,
    "fatality": False,
    "iso45001": True,
    "iso14001": True,
    "icv_pct": 48.0,
}


def run_tests() -> int:
    print("Running test harness...")
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

    # --- Worked example (RFP Section 6.5) ---------------------------------
    # Independent recomputation gives 84.47, NOT the 82.47 printed in the RFP.
    plow = 40_000_000
    bid = bid_from_dict(WORKED_EXAMPLE)
    ev = evaluate(bid, DEFAULT_CONFIG, plow, "WorkedExampleBid")
    check("Worked example T1 band", ev.t1.band, 4)
    check("Worked example T1 points", ev.t1.points, 12.00)
    check("Worked example T2 points", ev.t2.points, 8.00)
    check("Worked example T3 points", ev.t3.points, 6.40)
    check("Worked example T4 points", ev.t4.points, 5.60)
    check("Worked example Commercial", ev.commercial, 27.27)
    check("Worked example H1 points", ev.h1.points, 7.20)
    check("Worked example H2 points", ev.h2.points, 6.00)
    check("Worked example ICV", ev.icv, 12.00)
    check("Worked example TOTAL = 84.47 (RFP prints 82.47 - RFP arithmetic error)",
          ev.total, 84.47)

    # --- Band edge cases --------------------------------------------------
    b, _ = band_t1(33_000, 5.0)
    check("T1 band 5 boundary (33,000 / 5)", b, 5)
    b, _ = band_t1(31_500, 8.0)
    check("T1 band 4 boundary (31,500 / 8)", b, 4)
    b, _ = band_t1(30_000, 10.0)
    check("T1 band 3 boundary (30,000 / 10)", b, 3)
    b, _ = band_t1(29_999, 5.0)
    check("T1 band 0 (capacity 29,999 -> rejection)", b, 0)
    b, _ = band_t1(35_000, 10.5)
    check("T1 band 0 (OiW 10.5 -> rejection)", b, 0)
    b, _ = band_t1(32_000, 9.0)
    check("T1 compound condition (32,000 / OiW 9 -> band 3)", b, 3)

    b, _ = band_t2(8)
    check("T2 band 5 (8 refs)", b, 5)
    b, _ = band_t2(5)
    check("T2 band 4 (5 refs)", b, 4)
    b, _ = band_t2(0)
    check("T2 band 1 (0 refs)", b, 1)

    b, _ = band_t4(76)
    check("T4 band 2 (76 weeks, contractual max)", b, 2)
    b, _ = band_t4(77)
    check("T4 band 1 (77 weeks -> rejection risk)", b, 1)

    b, _ = band_h1(0.20, False)
    check("H1 band 5 (TRIR 0.20)", b, 5)
    b, _ = band_h1(0.21, False)
    check("H1 band 4 (TRIR 0.21)", b, 4)
    b, _ = band_h1(1.50, True)
    check("H1 band 0 floor (fatality, any TRIR)", b, 0)

    b, _ = band_h2(True, False)
    check("H2 band 3 (exactly one cert)", b, 3)

    # --- Commercial / ICV formulas ----------------------------------------
    check("Commercial formula 30*(40/44)", commercial_score(44_000_000, 40_000_000, 30), 27.27)
    check("Commercial lowest bidder gets full 30", commercial_score(40_000_000, 40_000_000, 30), 30.0)
    check("ICV 45% -> 11.25 (RFP example)", icv_score(45.0, 15, 60.0), 11.25)
    check("ICV cap at 60% -> 15.0", icv_score(80.0, 15, 60.0), 15.0)
    check("ICV % missing -> raw formula returns None (no guess); "
          "0.0-for-no-certificate rule applied in evaluate()", icv_score(None, 15, 60.0), None)

    # --- Currency conversion (Section 6.2 / ITB 2) -----------------------
    check("AED passes through unchanged", convert_to_aed(100.0, "AED", 3.6725), 100.0)
    check("None currency treated as AED", convert_to_aed(100.0, None, 3.6725), 100.0)
    check("USD converted at 3.6725", convert_to_aed(100.0, "USD", 3.6725), 367.25)
    check("None amount -> None", convert_to_aed(None, "USD", 3.6725), None)
    check("Unsupported currency -> None (no guess)", convert_to_aed(100.0, "EUR", 3.6725), None)
    usd_bid = bid_from_dict({**WORKED_EXAMPLE, "price_aed": None, "price": 100_000_000, "currency": "USD"})
    check("USD price in input schema converts to AED", usd_bid.price_aed, 367_250_000.0)

    # --- Screening gates --------------------------------------------------
    no_d6 = bid_from_dict({**WORKED_EXAMPLE, "icv_cert_valid": False})
    check("Missing valid D6 -> conditionally non-compliant",
          no_d6.screening_status(), "CONDITIONALLY NON-COMPLIANT - D6 ICV certificate not valid on bid due date")
    check("Missing valid D6 -> not eligible for award", no_d6.eligible_for_award, False)
    check("Missing valid D6 -> ICV 0", evaluate(no_d6, DEFAULT_CONFIG, plow, "x").icv, 0.0)

    missing_d8 = bid_from_dict({**WORKED_EXAMPLE,
                                "docs": {f"D{i}": True for i in range(1, 10) if i != 8}})
    check("Missing D8 -> screening flags missing doc", "D8" in missing_d8.missing_docs(), True)

    low_cap = bid_from_dict({**WORKED_EXAMPLE, "capacity_m3d": 28_000})
    check("Capacity 28,000 -> min-tech FAIL", low_cap.min_tech_pass, False)
    check("Capacity 28,000 -> T1 band 0 rejection", band_t1(28_000, 6.0)[0], 0)

    # --- Missing-evidence discipline (agent.md: never guess) --------------
    no_capacity = bid_from_dict({**WORKED_EXAMPLE, "capacity_m3d": None})
    ev_m = evaluate(no_capacity, DEFAULT_CONFIG, plow, "x")
    check("Missing capacity -> T1 points None (not a guess)", ev_m.t1.points, None)
    check("Missing capacity -> technical total None", ev_m.technical, None)
    check("Missing capacity -> total None", ev_m.total, None)
    check("Missing capacity -> missing_info flagged",
          any("T1" in m for m in ev_m.missing_info), True)
    check("Missing capacity -> min-tech does NOT pass",
          no_capacity.min_tech_pass, False)
    check("Missing capacity -> not eligible (no unsupported assumption)",
          no_capacity.eligible_for_award, False)

    # --- Plow only among eligible -----------------------------------------
    bids = [
        bid_from_dict({**WORKED_EXAMPLE, "name": "EligibleLow", "price_aed": 40_000_000}),
        bid_from_dict({**WORKED_EXAMPLE, "name": "DisqualifiedCheap", "price_aed": 10_000_000,
                       "icv_cert_valid": False}),
        bid_from_dict({**WORKED_EXAMPLE, "name": "EligibleHigh", "price_aed": 50_000_000}),
    ]
    plow_computed, _src = compute_plow(bids, DEFAULT_CONFIG)
    check("Plow ignores disqualified bidder's 10M (uses 40M)", plow_computed, 40_000_000)

    # --- Ranking ----------------------------------------------------------
    eligible, plow_r, _ = evaluate_all(bids)
    check("Ranking: highest total first", eligible[0].bid.name, "EligibleLow")
    check("Ranking: disqualified excluded from ranked list",
          all(e.bid.name != "DisqualifiedCheap" for e in eligible), True)

    # --- Explanation / trade-offs (agent.md EXPLANATION section) ----------
    rpt = report(eligible, eligible, plow_r, "EligibleLow")
    check("Report contains EXPLANATION header", "EXPLANATION" in rpt, True)
    check("Report contains cheapest-supplier note",
          "cheapest supplier is NOT automatically recommended" in rpt, True)
    expl = explanation(eligible)
    check("Explanation generated for 2-supplier ranking", len(expl) > 0, True)
    check("Explanation references both suppliers",
          "EligibleLow" in expl[0] and "EligibleHigh" in expl[0], True)

    print("-" * 78)
    if failures:
        print(f"RESULT: {failures} test(s) FAILED")
        return 1
    print("RESULT: all tests PASSED")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Bid evaluation scoring engine")
    parser.add_argument("bids", nargs="?", help="JSON file with bids (use '-' for stdin)")
    parser.add_argument("--test", action="store_true", help="run test harness")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output (downstream handoff)")
    args = parser.parse_args(argv)

    if args.test:
        return run_tests()

    if not args.bids:
        parser.error("provide a bids JSON file (or --test)")

    raw = sys.stdin.read() if args.bids == "-" else open(args.bids).read()
    data = json.loads(raw)
    bids = [bid_from_dict(d) for d in data["bids"]]

    eligible, plow, plow_source = evaluate_all(bids)
    all_evals = [evaluate(b, DEFAULT_CONFIG, plow, plow_source) for b in bids]

    if args.json:
        handoff = {
            "tender_id": DEFAULT_CONFIG.name,
            "plow": plow,
            "plow_set": plow_source,
            "methodology": {
                "step_order": "1 mandatory screening -> 2 min tech -> 3 technical -> "
                              "4 commercial -> 5 HSE -> 6 ICV -> 7 total/ranking",
                "rounding": "2 decimal places (all scores)",
                "award_gates": "eligible = pass mandatory screening AND minimum technical requirements",
                "plow_rule": "Plow = lowest evaluated price among ELIGIBLE bids only (ITB 5)",
                "commercial_formula": "C = 30 * (Plow / Pbid)",
                "icv_formula": "ICV = 15 * min(icv%, 60) / 60",
                "note": "decision-support only - not an official ADNOC procurement decision",
            },
            "ranked_evaluations": [e.to_dict() for e in eligible],
            "ineligible_evaluations": [e.to_dict() for e in all_evals if not e.bid.eligible_for_award],
            "explanation": explanation(eligible),
            "note": "decision-support only - not an official ADNOC procurement decision",
        }
        print(json.dumps(handoff, indent=2))
    else:
        print(report(eligible, all_evals, plow, plow_source))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
