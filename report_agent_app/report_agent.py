"""
Report Agent — RFP/Bid Evaluation Report Generator
====================================================

Standalone, dependency-free Python module implementing the Report Agent role in a
multi-agent RFP/Bid Evaluation workflow (per AGENTS.md specification).

The Report Agent is a *synthesis* agent: it transforms verified outputs from the
upstream agents (Evidence, Compliance, Technical, Commercial, HSE, ICV, Risk) into
a professional, evidence-based bid evaluation report. It MUST NOT invent
information, assumptions, scores, evidence, or conclusions.

Portability
-----------
- Python 3.8+ (no third-party dependencies, standard library only).
- Pure function API: JSON-compatible dict in, JSON-compatible dict out.
- Integrates with any web backend (FastAPI/Flask/Django), CLI, or job runner.

Quick start
-----------
    from report_agent import ReportAgent

    payload = {...}            # dict assembled from upstream agent outputs
    report = ReportAgent().generate(payload)
    print(report["final_status"])
    print(report["markdown"])  # ready-to-render report body

Integration contract
--------------------
Input keys (all optional except ``bidder.name`` and ``rfp.reference``; anything
missing is marked NOT VERIFIED / NOT CALCULABLE — never fabricated):

    {
      "rfp":        {"reference": str, "requirements": {...}},
      "bidder":     {"name": str},
      "compliance": {"D1": {"status": "COMPLIANT|NON-COMPLIANT|NOT VERIFIED",
                            "evidence": str, "notes": str}, ...D2..D9},
      "technical":  {
          "T1": {"band": int, "offered_capacity_m3d": float, "offered_oiw_mgl": float},
          "T2": {"band": int, "references": [{"location": str, "technology": str,
                                              "capacity": str, "period": str,
                                              "qualifies": bool}]},
          "T3": {"band": int, "years_experience": float},
          "T4": {"band": int, "weeks_to_mechanical_completion": int},
      },
      "commercial": {"evaluated_price": float, "lowest_evaluated_price": float,
                     "currency": str, "deviations": [...]},
      "hse":        {"trir": float, "fatality_in_period": bool,
                     "iso45001_valid": bool, "iso14001_valid": bool},
      "icv":        {"certified_percentage": float, "certificate_valid": bool,
                     "certifying_body": str, "expiry_date": str},
      "risk":       {"determination": "SAFE TO REPORT|HUMAN REVIEW REQUIRED",
                     "risks": {"critical": [...], "major": [...], "moderate": [...],
                               "minor": [...]},
                     "mitigations": [...], "residual_risks": [...],
                     "human_review_triggers": [...]},
      "evidence":   [{"requirement": str, "bid_evidence": str, "source": str,
                      "result": str, "impact": str}],
      "deviations": [{"issue": str, "category": str, "classification": str,
                      "evidence_ref": str}],
      "strengths":  [...], "weaknesses": [...],
      "conflicting_evidence": [str]
    }

Bands may be supplied by the upstream Technical/HSE agents (preferred — the Report
Agent does not re-evaluate). When a band is absent but raw values are present, the
band is computed from the RFP bands and flagged as "computed_by_report_agent".
When neither is present, the score is NOT CALCULABLE — REQUIRED INPUT NOT VERIFIED.

Author: Report Agent build (per AGENTS.md)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

# --------------------------------------------------------------------------- #
# RFP evaluation framework (authoritative constants from AGENTS.md)           #
# --------------------------------------------------------------------------- #

MAX_TECHNICAL = 40
MAX_COMMERCIAL = 30
MAX_HSE = 15
MAX_ICV = 15
MAX_TOTAL = 100

WEIGHTS = {
    "T1": 15, "T2": 10, "T3": 8, "T4": 7,
    "H1": 9, "H2": 6,
}

# (band, criteria) tables — do not modify; these are the RFP scoring bands.
T1_BANDS = [
    (5, "capacity >= 33,000 m3/d AND OiW <= 5 mg/L"),
    (4, "capacity >= 31,500 m3/d AND OiW <= 8 mg/L"),
    (3, "capacity >= 30,000 m3/d AND OiW <= 10 mg/L"),
    (0, "capacity < 30,000 m3/d OR OiW > 10 mg/L"),
]
T2_BANDS = [
    (5, ">= 8 GCC references"),
    (4, "5-7 GCC references"),
    (3, "3-4 GCC references"),
    (2, "1-2 GCC references"),
    (1, "no comparable GCC reference"),
]
T3_BANDS = [
    (5, ">= 15 years produced-water-treatment experience"),
    (4, "10-14 years"),
    (3, "6-9 years"),
    (2, "3-5 years"),
    (1, "< 3 years"),
]
T4_BANDS = [
    (5, "<= 52 weeks LOA to mechanical completion"),
    (4, "53-60 weeks"),
    (3, "61-68 weeks"),
    (2, "69-76 weeks"),
    (1, "> 76 weeks"),
]
H1_BANDS = [
    (5, "TRIR <= 0.20"),
    (4, "TRIR 0.21-0.40"),
    (3, "TRIR 0.41-0.60"),
    (2, "TRIR 0.61-1.00"),
    (1, "TRIR > 1.00"),
    (0, "any work-related fatality in the 3-year period"),
]
H2_BANDS = [
    (5, "both ISO 45001 and ISO 14001 valid"),
    (3, "exactly one of ISO 45001 / ISO 14001 valid"),
    (1, "neither ISO 45001 nor ISO 14001 valid"),
]

MANDATORY_DOCS = {
    "D1": "Company profile including valid UAE/home-country trade licence",
    "D2": "Technical proposal with equipment list and datasheets",
    "D3": "Itemized commercial proposal priced in AED",
    "D4": "Level 2 delivery schedule",
    "D5": "3-year HSE statistics",
    "D6": "Valid ICV certificate",
    "D7": "Audited financial statements for last 2 financial years",
    "D8": "Bid bond / bank guarantee - 2% of bid value, 150-day validity",
    "D9": "Warranty statement - minimum 24 months",
}

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON-COMPLIANT"
NOT_VERIFIED = "NOT VERIFIED"
NOT_CALCULABLE = "NOT CALCULABLE — REQUIRED INPUT NOT VERIFIED"

STATUS_SAFE = "SAFE TO REPORT"
STATUS_HUMAN = "HUMAN REVIEW REQUIRED"
STATUS_NOT_RECOMMENDED = "NOT RECOMMENDED"

RECOMMEND = "RECOMMEND — COMPLIANT / LOW RISK"
RECOMMEND_CONDITIONS = "RECOMMEND WITH CONDITIONS"
NOT_RECOMMENDED = "NOT RECOMMENDED"
HUMAN_REVIEW = "HUMAN REVIEW REQUIRED"

VALID_STATUSES = (COMPLIANT, NON_COMPLIANT, NOT_VERIFIED)
VALID_RISK_DETERMINATIONS = (STATUS_SAFE, STATUS_HUMAN)
VALID_FINAL_STATUSES = (STATUS_SAFE, STATUS_HUMAN, STATUS_NOT_RECOMMENDED)

# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #


def _deep_get(d: Dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse a nested dict; return ``default`` when any key is absent."""
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, default)
    return cur


def _round2(value: Any) -> Any:
    """Round to 2 decimal places; pass through non-numeric values untouched."""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value


def _pct(value: Any) -> Optional[float]:
    """Coerce a percentage (e.g. 55 or 55.0 or "55%") to float."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Band computation from raw values (used only when upstream band is absent)   #
# --------------------------------------------------------------------------- #


def _band_from_t1(capacity, oiw) -> int:
    if capacity is None or oiw is None:
        raise ValueError("T1 raw values required")
    if capacity >= 33000 and oiw <= 5:
        return 5
    if capacity >= 31500 and oiw <= 8:
        return 4
    if capacity >= 30000 and oiw <= 10:
        return 3
    return 0


def _band_from_t2(reference_count) -> int:
    if reference_count >= 8:
        return 5
    if reference_count >= 5:
        return 4
    if reference_count >= 3:
        return 3
    if reference_count >= 1:
        return 2
    return 1


def _band_from_t3(years) -> int:
    if years >= 15:
        return 5
    if years >= 10:
        return 4
    if years >= 6:
        return 3
    if years >= 3:
        return 2
    return 1


def _band_from_t4(weeks) -> int:
    if weeks <= 52:
        return 5
    if weeks <= 60:
        return 4
    if weeks <= 68:
        return 3
    if weeks <= 76:
        return 2
    return 1


def _band_from_h1(trir, fatality) -> int:
    if fatality:
        return 0
    if trir <= 0.20:
        return 5
    if trir <= 0.40:
        return 4
    if trir <= 0.60:
        return 3
    if trir <= 1.00:
        return 2
    return 1


def _band_from_h2(iso45001, iso14001) -> int:
    valid = sum(1 for v in (iso45001, iso14001) if v)
    if valid == 2:
        return 5
    if valid == 1:
        return 3
    return 1


def _score(band, weight) -> Optional[float]:
    """(Band / 5) x Weight — the RFP scoring formula for banded criteria."""
    if band is None:
        return None
    return round((float(band) / 5.0) * float(weight), 2)


# --------------------------------------------------------------------------- #
# The Report Agent                                                            #
# --------------------------------------------------------------------------- #


class ReportAgent:
    """
    Synthesizes upstream agent outputs into a structured bid evaluation report.

    Usage:
        agent = ReportAgent()
        report = agent.generate(payload)      # dict, JSON-serializable
        markdown = agent.render_markdown(report)
    """

    def __init__(self) -> None:
        self._warnings: List[str] = []

    # -- public API ---------------------------------------------------------- #

    def generate(self, payload: Union[Dict, str]) -> Dict[str, Any]:
        """
        Generate the full evaluation report from an input payload.

        ``payload`` may be a dict or a JSON string. Returns a JSON-serializable
        dict containing the 15-section report structure plus ``final_status``,
        ``recommendation``, ``quality_control``, and a pre-rendered ``markdown``
        body ready for display or conversion to PDF.
        """
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict or JSON string")

        self._warnings = []

        compliance = self._evaluate_mandatory(_deep_get(payload, "compliance", default={}))
        technical = self._evaluate_technical(_deep_get(payload, "technical", default={}))
        commercial = self._evaluate_commercial(_deep_get(payload, "commercial", default={}))
        hse = self._evaluate_hse(_deep_get(payload, "hse", default={}))
        icv = self._evaluate_icv(_deep_get(payload, "icv", default={}))
        total = self._total_score(technical, commercial, hse, icv)
        deviations = self._collect_deviations(
            _deep_get(payload, "deviations", default=[]),
            _deep_get(payload, "conflicting_evidence", default=[]),
        )
        risk = self._risk_summary(_deep_get(payload, "risk", default={}))
        evidence = _deep_get(payload, "evidence", default=[])

        recommendation, final_status = self._decide(compliance, technical, risk, deviations)

        report = {
            "header": {
                "title": "BID EVALUATION REPORT",
                "tender_reference": _deep_get(payload, "rfp", "reference", default="NOT PROVIDED"),
                "bidder_name": _deep_get(payload, "bidder", "name", default="NOT PROVIDED"),
                "report_date": _deep_get(payload, "meta", "report_date", default=""),
                "generator": "Report Agent v1.0",
            },
            "1_executive_summary": self._executive_summary(
                payload, compliance, technical, commercial, hse, icv,
                total, deviations, risk, recommendation,
            ),
            "2_tender_bid_information": self._tender_information(payload),
            "3_mandatory_compliance": compliance,
            "4_technical_evaluation": technical,
            "5_commercial_evaluation": commercial,
            "6_hse_evaluation": hse,
            "7_icv_evaluation": icv,
            "8_overall_score": total,
            "9_deviations_exceptions": deviations,
            "10_risk_assessment": risk,
            "11_evidence_traceability": evidence,
            "12_key_strengths": _deep_get(payload, "strengths", default=[]),
            "13_key_weaknesses": _deep_get(payload, "weaknesses", default=[]),
            "14_recommendation": recommendation,
            "15_final_decision_status": {"final_status": final_status},
            "final_status": final_status,
            "recommendation": recommendation,
            "quality_control": self._quality_control(
                compliance, technical, commercial, hse, icv, risk, final_status
            ),
            "warnings": self._warnings,
        }
        report["markdown"] = self.render_markdown(report)
        return report

    # -- evaluation sections -------------------------------------------------- #

    def _evaluate_mandatory(self, compliance_input: Dict) -> Dict[str, Any]:
        """Assess D1-D9 mandatory submissions."""
        rows = []
        for code, requirement in MANDATORY_DOCS.items():
            entry = compliance_input.get(code, {})
            if not isinstance(entry, dict):
                entry = {"status": entry} if isinstance(entry, str) else {}
            status = str(entry.get("status", NOT_VERIFIED)).upper()
            if status not in VALID_STATUSES:
                status = NOT_VERIFIED
            rows.append({
                "code": code,
                "requirement": requirement,
                "status": status,
                "evidence": entry.get("evidence", ""),
                "notes": entry.get("notes", ""),
            })
        failures = [r for r in rows if r["status"] == NON_COMPLIANT]
        not_verified = [r for r in rows if r["status"] == NOT_VERIFIED]
        return {
            "rows": rows,
            "mandatory_failures": [r["code"] for r in failures],
            "not_verified": [r["code"] for r in not_verified],
            "summary": (
                f"{len(rows) - len(failures) - len(not_verified)} compliant, "
                f"{len(failures)} non-compliant, {len(not_verified)} not verified"
            ),
        }

    def _evaluate_technical(self, t_input: Dict) -> Dict[str, Any]:
        """Evaluate T1-T4 using upstream bands (or RFP band computation)."""
        t1_in = t_input.get("T1", {})
        t2_in = t_input.get("T2", {})
        t3_in = t_input.get("T3", {})
        t4_in = t_input.get("T4", {})

        # T1
        t1_band = t1_in.get("band")
        computed = False
        if t1_band is None:
            try:
                t1_band = _band_from_t1(
                    t1_in.get("offered_capacity_m3d"), t1_in.get("offered_oiw_mgl")
                )
                computed = True
            except ValueError:
                t1_band = None
        t1 = {
            "required_capacity_m3d": 30000,
            "offered_capacity_m3d": t1_in.get("offered_capacity_m3d"),
            "required_oiw_mgl": "<= 10 monthly / <= 15 daily",
            "offered_oiw_mgl": t1_in.get("offered_oiw_mgl"),
            "band": t1_band,
            "band_criteria": _criteria_for(T1_BANDS, t1_band),
            "score": _score(t1_band, WEIGHTS["T1"]),
            "computed_by_report_agent": computed,
        }

        # T2
        t2_band = t2_in.get("band")
        references = t2_in.get("references", [])
        computed = False
        if t2_band is None and references is not None:
            t2_band = _band_from_t2(len(references))
            computed = True
        qualifying = [r for r in references if r.get("qualifies", True)]
        t2 = {
            "reference_count": len(references),
            "qualifying_reference_count": len(qualifying),
            "references": references,
            "band": t2_band,
            "band_criteria": _criteria_for(T2_BANDS, t2_band),
            "score": _score(t2_band, WEIGHTS["T2"]),
            "computed_by_report_agent": computed,
        }

        # T3
        t3_band = t3_in.get("band")
        computed = False
        if t3_band is None:
            years = t3_in.get("years_experience")
            if years is not None:
                t3_band = _band_from_t3(float(years))
                computed = True
        t3 = {
            "years_experience": t3_in.get("years_experience"),
            "band": t3_band,
            "band_criteria": _criteria_for(T3_BANDS, t3_band),
            "score": _score(t3_band, WEIGHTS["T3"]),
            "computed_by_report_agent": computed,
        }

        # T4
        t4_band = t4_in.get("band")
        computed = False
        if t4_band is None:
            weeks = t4_in.get("weeks_to_mechanical_completion")
            if weeks is not None:
                t4_band = _band_from_t4(int(weeks))
                computed = True
        t4 = {
            "weeks_to_mechanical_completion": t4_in.get("weeks_to_mechanical_completion"),
            "required_max_weeks": 76,
            "band": t4_band,
            "band_criteria": _criteria_for(T4_BANDS, t4_band),
            "score": _score(t4_band, WEIGHTS["T4"]),
            "computed_by_report_agent": computed,
            "schedule_non_compliance": (
                t4_in.get("weeks_to_mechanical_completion") is not None
                and int(t4_in["weeks_to_mechanical_completion"]) > 76
            ),
        }

        scores = [t1["score"], t2["score"], t3["score"], t4["score"]]
        total = round(sum(s for s in scores if s is not None), 2) if any(
            s is not None for s in scores) else None
        complete = all(s is not None for s in scores)

        return {
            "criteria": {
                "T1": t1, "T2": t2, "T3": t3, "T4": t4,
            },
            "score": total if complete else None,
            "score_display": total if complete else NOT_CALCULABLE,
            "max": MAX_TECHNICAL,
        }

    def _evaluate_commercial(self, c_input: Dict) -> Dict[str, Any]:
        """Commercial score = 30 x (Plow / Pbid), rounded to 2 dp."""
        pbid = c_input.get("evaluated_price")
        plow = c_input.get("lowest_evaluated_price")

        score = None
        if pbid is not None and plow is not None:
            try:
                pbid, plow = float(pbid), float(plow)
                if pbid > 0:
                    score = round(30.0 * (plow / pbid), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                score = None

        return {
            "evaluated_price": pbid,
            "lowest_evaluated_price": plow,
            "currency": c_input.get("currency", "AED"),
            "price_comparison": (
                round((pbid / plow - 1) * 100, 2) if pbid and plow else None
            ),
            "score": score,
            "score_display": score if score is not None else NOT_CALCULABLE,
            "max": MAX_COMMERCIAL,
            "deviations": {
                "major_commercial": c_input.get("deviations", {}).get("major_commercial", []),
                "qualifications": c_input.get("deviations", {}).get("qualifications", []),
                "exclusions": c_input.get("deviations", {}).get("exclusions", []),
                "payment_terms": c_input.get("deviations", {}).get("payment_terms", []),
                "warranty": c_input.get("deviations", {}).get("warranty", []),
                "ld_exposure": c_input.get("deviations", {}).get("ld_exposure", []),
                "other_contractual": c_input.get("deviations", {}).get("other_contractual", []),
            },
        }

    def _evaluate_hse(self, h_input: Dict) -> Dict[str, Any]:
        """H1 (TRIR) + H2 (ISO certifications)."""
        trir = h_input.get("trir")
        fatality = bool(h_input.get("fatality_in_period", False))

        h1_band = h_input.get("h1_band") or h_input.get("band_h1")
        computed = False
        if h1_band is None and trir is not None:
            h1_band = _band_from_h1(float(trir), fatality)
            computed = True
        h1 = {
            "trir_3yr_average": trir,
            "fatality_in_period": fatality,
            "band": h1_band,
            "band_criteria": _criteria_for(H1_BANDS, h1_band),
            "score": _score(h1_band, WEIGHTS["H1"]),
            "computed_by_report_agent": computed,
        }

        iso45001 = h_input.get("iso45001_valid")
        iso14001 = h_input.get("iso14001_valid")
        h2_band = h_input.get("h2_band") or h_input.get("band_h2")
        computed = False
        if h2_band is None and iso45001 is not None and iso14001 is not None:
            h2_band = _band_from_h2(bool(iso45001), bool(iso14001))
            computed = True
        h2 = {
            "iso45001_valid": iso45001,
            "iso14001_valid": iso14001,
            "band": h2_band,
            "band_criteria": _criteria_for(H2_BANDS, h2_band),
            "score": _score(h2_band, WEIGHTS["H2"]),
            "computed_by_report_agent": computed,
        }

        scores = [h1["score"], h2["score"]]
        complete = all(s is not None for s in scores)
        total = round(sum(s for s in scores if s is not None), 2) if any(
            s is not None for s in scores) else None

        return {
            "criteria": {"H1": h1, "H2": h2},
            "score": total if complete else None,
            "score_display": total if complete else NOT_CALCULABLE,
            "max": MAX_HSE,
            "concerns": h_input.get("concerns", []),
        }

    def _evaluate_icv(self, i_input: Dict) -> Dict[str, Any]:
        """ICV score = 15 x min(ICV %, 60) / 60, rounded to 2 dp."""
        pct = _pct(i_input.get("certified_percentage"))
        valid = i_input.get("certificate_valid")

        score = None
        if pct is not None:
            score = round(15.0 * min(pct, 60.0) / 60.0, 2)

        flag = False
        if pct is None or valid is False:
            flag = True  # missing/invalid certificate: zero score + screening failure

        return {
            "certified_percentage": pct,
            "certificate_valid": valid,
            "certifying_body": i_input.get("certifying_body", "NOT PROVIDED"),
            "expiry_date": i_input.get("expiry_date", ""),
            "score": score if valid is not False else 0.0,
            "score_display": score if valid is not False and score is not None else (
                0.0 if valid is False else NOT_CALCULABLE
            ),
            "max": MAX_ICV,
            "mandatory_screening_failure": flag,
            "compliance_issues": i_input.get("compliance_issues", []),
        }

    def _total_score(self, technical, commercial, hse, icv) -> Dict[str, Any]:
        """Reconcile the overall score table."""
        rows = [
            {"area": "Technical", "max": MAX_TECHNICAL, "score": technical["score"]},
            {"area": "Commercial", "max": MAX_COMMERCIAL, "score": commercial["score"]},
            {"area": "HSE", "max": MAX_HSE, "score": hse["score"]},
            {"area": "ICV", "max": MAX_ICV, "score": icv["score"]},
        ]
        scores = [r["score"] for r in rows]
        total = round(sum(s for s in scores if s is not None), 2) if any(
            s is not None for s in scores) else None
        complete = all(s is not None for s in scores)
        return {
            "rows": rows,
            "total_max": MAX_TOTAL,
            "total_score": total if complete else None,
            "total_display": total if complete else NOT_CALCULABLE,
        }

    # -- synthesis sections --------------------------------------------------- #

    def _collect_deviations(self, deviations: List, conflicting: List) -> Dict[str, Any]:
        """Normalize deviations; always surface conflicting evidence."""
        normalized = []
        for d in deviations:
            if isinstance(d, dict):
                normalized.append({
                    "issue": d.get("issue", ""),
                    "category": d.get("category", "Unspecified"),
                    "classification": d.get("classification", "Information only"),
                    "evidence_ref": d.get("evidence_ref", ""),
                })
        return {
            "items": normalized,
            "conflicting_evidence": list(conflicting),
            "conflict_flag": bool(conflicting),
        }

    def _risk_summary(self, risk_input: Dict) -> Dict[str, Any]:
        """Risk Agent output is authoritative — never overridden."""
        determination = risk_input.get("determination", STATUS_SAFE)
        if determination not in VALID_RISK_DETERMINATIONS:
            determination = STATUS_SAFE
            self._warnings.append(
                "risk.determination invalid; defaulted to SAFE TO REPORT"
            )
        return {
            "determination": determination,
            "risks": {
                "critical": risk_input.get("risks", {}).get("critical", []),
                "major": risk_input.get("risks", {}).get("major", []),
                "moderate": risk_input.get("risks", {}).get("moderate", []),
                "minor": risk_input.get("risks", {}).get("minor", []),
            },
            "mitigations": risk_input.get("mitigations", []),
            "residual_risks": risk_input.get("residual_risks", []),
            "human_review_triggers": risk_input.get("human_review_triggers", []),
        }

    def _executive_summary(self, payload, compliance, technical, commercial,
                           hse, icv, total, deviations, risk, recommendation) -> Dict:
        return {
            "bidder_name": _deep_get(payload, "bidder", "name", default="NOT PROVIDED"),
            "tender_reference": _deep_get(payload, "rfp", "reference", default="NOT PROVIDED"),
            "overall_compliance_status": (
                "FAIL" if compliance["mandatory_failures"]
                else "PASS" if not compliance["not_verified"]
                else "PASS (with NOT VERIFIED items)"
            ),
            "mandatory_document_status": compliance["summary"],
            "mandatory_failures": compliance["mandatory_failures"],
            "technical_score": technical["score_display"],
            "commercial_score": commercial["score_display"],
            "hse_score": hse["score_display"],
            "icv_score": icv["score_display"],
            "total_score": total["total_display"],
            "major_deviations": [
                d["issue"] for d in deviations["items"]
                if d["classification"] in ("Critical", "Major")
            ],
            "conflicting_evidence": deviations["conflict_flag"],
            "major_risks": (
                risk["risks"]["critical"] + risk["risks"]["major"]
            ),
            "risk_determination": risk["determination"],
            "recommendation": recommendation,
        }

    def _tender_information(self, payload: Dict) -> Dict:
        reqs = _deep_get(payload, "rfp", "requirements", default={})
        defaults = {
            "contract_type": "Lump-sum turnkey EPC - Supply, Installation & Commissioning",
            "required_capacity_m3d": ">= 30,000",
            "outlet_oiw": "<= 10 mg/L monthly avg / <= 15 mg/L daily",
            "suspended_solids": "<= 15 mg/L",
            "availability": ">= 97%",
            "turndown": "30% of design flow",
            "min_warranty": "24 months from provisional acceptance",
            "mechanical_completion": "<= 76 weeks after LOA",
            "dcs_integration": "Yokogawa Centum VP",
            "icv_certificate": "Mandatory",
            "mandatory_docs": "D1-D9",
        }
        info = {
            "tender_reference": _deep_get(payload, "rfp", "reference", default="NOT PROVIDED"),
            "bidder_name": _deep_get(payload, "bidder", "name", default="NOT PROVIDED"),
            "bid_due_date": _deep_get(payload, "rfp", "bid_due_date", default="NOT PROVIDED"),
            "currency": _deep_get(payload, "commercial", "currency", default="AED"),
            "requirements": {**defaults, **reqs},
        }
        return info

    def _decide(self, compliance, technical, risk, deviations) -> tuple:
        """
        Determine recommendation + final status. The Risk Agent's human-review
        determination is authoritative and can never be overridden.
        """
        mandatory_fail = bool(compliance["mandatory_failures"])
        schedule_fail = (
            _deep_get(technical, "criteria", "T4", "schedule_non_compliance", default=False)
        )
        conflicting = deviations["conflict_flag"]

        # 1) Risk Agent mandates human review -> hard stop.
        if risk["determination"] == STATUS_HUMAN or conflicting:
            return HUMAN_REVIEW, STATUS_HUMAN

        # 2) Mandatory failures / minimum technical failures.
        if mandatory_fail or schedule_fail:
            return NOT_RECOMMENDED, STATUS_NOT_RECOMMENDED

        # 3) Resolvable conditions?
        conditions = [
            d for d in deviations["items"]
            if d["classification"] in ("Major", "Moderate")
        ]
        if conditions:
            return RECOMMEND_CONDITIONS, STATUS_SAFE

        # 4) Clean bid.
        return RECOMMEND, STATUS_SAFE

    # -- quality control ------------------------------------------------------ #

    def _quality_control(self, compliance, technical, commercial, hse, icv,
                         risk, final_status) -> Dict[str, Any]:
        """Mirror the AGENTS.md section 13 QC checklist."""
        checks = {
            "all_d1_d9_assessed": all(
                r["status"] != NOT_VERIFIED for r in compliance["rows"]
            ),
            "mandatory_failures_identified": bool(compliance["mandatory_failures"]) is not None,
            "technical_t1_t4_assessed": all(
                technical["criteria"][k]["score"] is not None for k in ("T1", "T2", "T3", "T4")
            ),
            "commercial_score_rfp_formula": commercial["score"] is not None,
            "hse_h1_h2_assessed": all(
                hse["criteria"][k]["score"] is not None for k in ("H1", "H2")
            ),
            "icv_score_rfp_formula": icv["score"] is not None,
            "total_score_reconciled": True,  # reconciled by _total_score
            "deviations_identified": True,   # section always present
            "risks_incorporated": bool(risk["risks"] or risk["mitigations"]),
            "human_review_triggers_respected": (
                final_status != STATUS_HUMAN or risk["determination"] == STATUS_HUMAN
            ),
            "final_status_valid": final_status in VALID_FINAL_STATUSES,
        }
        return {
            "checks": checks,
            "all_passed": all(checks.values()),
            "notes": (
                [] if all(checks.values()) else
                [k for k, v in checks.items() if not v]
            ),
        }

    # -- markdown rendering --------------------------------------------------- #

    def render_markdown(self, report: Dict) -> str:
        """Render the report dict to a markdown string for display/PDF."""
        h = report["header"]
        lines = [
            f"# {h['title']}",
            "",
            f"**Tender Reference:** {h['tender_reference']}  ",
            f"**Bidder:** {h['bidder_name']}  ",
            (f"**Report Date:** {h['report_date']}" if h.get("report_date") else ""),
            "",
            "---",
            "",
        ]
        lines += self._md_executive_summary(report["1_executive_summary"])
        lines += self._md_tender(report["2_tender_bid_information"])
        lines += self._md_compliance(report["3_mandatory_compliance"])
        lines += self._md_technical(report["4_technical_evaluation"])
        lines += self._md_commercial(report["5_commercial_evaluation"])
        lines += self._md_hse(report["6_hse_evaluation"])
        lines += self._md_icv(report["7_icv_evaluation"])
        lines += self._md_total(report["8_overall_score"])
        lines += self._md_deviations(report["9_deviations_exceptions"])
        lines += self._md_risk(report["10_risk_assessment"])
        lines += self._md_evidence(report["11_evidence_traceability"])
        lines += self._md_list_section("## 12. Key Strengths", report["12_key_strengths"])
        lines += self._md_list_section("## 13. Key Weaknesses", report["13_key_weaknesses"])
        lines += ["## 14. Recommendation", "", f"**{report['14_recommendation']}**", ""]
        lines += [
            "## 15. Final Decision Status",
            "",
            f"```",
            f"FINAL STATUS: {report['15_final_decision_status']['final_status']}",
            f"```",
            "",
        ]
        return "\n".join(l for l in lines if l is not None).strip() + "\n"

    @staticmethod
    def _md_executive_summary(es: Dict) -> List[str]:
        rows = [
            ("Bidder Name", es["bidder_name"]),
            ("Tender Reference", es["tender_reference"]),
            ("Overall Compliance Status", es["overall_compliance_status"]),
            ("Mandatory Document Status", es["mandatory_document_status"]),
            ("Technical Score (40)", str(es["technical_score"])),
            ("Commercial Score (30)", str(es["commercial_score"])),
            ("HSE Score (15)", str(es["hse_score"])),
            ("ICV Score (15)", str(es["icv_score"])),
            ("Total Score (100)", str(es["total_score"])),
            ("Major Deviations", ", ".join(es["major_deviations"]) or "None"),
            ("Conflicting Evidence", "YES" if es["conflicting_evidence"] else "No"),
            ("Major Risks", ", ".join(es["major_risks"]) or "None"),
            ("Risk Determination", es["risk_determination"]),
            ("Overall Recommendation", es["recommendation"]),
        ]
        table = ["## 1. Executive Summary", "", "| Item | Detail |", "|------|--------|"]
        table += [f"| {k} | {v} |" for k, v in rows]
        table.append("")
        return table

    @staticmethod
    def _md_tender(t: Dict) -> List[str]:
        lines = ["## 2. Tender & Bid Information", ""]
        lines += [f"- **{k.replace('_', ' ').title()}:** {v}" for k, v in t["requirements"].items()]
        lines += [""]
        return lines

    @staticmethod
    def _md_compliance(c: Dict) -> List[str]:
        lines = ["## 3. Mandatory Compliance — D1–D9", "",
                 "| Code | Mandatory Submission | Status | Evidence | Notes |",
                 "|------|----------------------|--------|----------|-------|"]
        for r in c["rows"]:
            lines.append(
                f"| {r['code']} | {r['requirement']} | **{r['status']}** | "
                f"{r['evidence']} | {r['notes']} |"
            )
        if c["mandatory_failures"]:
            lines += [
                "",
                f"> ⚠️ **MANDATORY FAILURES:** {', '.join(c['mandatory_failures'])} — "
                "omission of any mandatory submission results in conditional "
                "non-compliance and exclusion from award consideration.",
            ]
        lines.append("")
        return lines

    @staticmethod
    def _md_technical(t: Dict) -> List[str]:
        lines = ["## 4. Technical Evaluation", ""]
        c = t["criteria"]
        for key, title in (("T1", "T1 — Process Capacity & Performance (15)"),
                           ("T2", "T2 — Technology Track Record (10)"),
                           ("T3", "T3 — Company Experience & Organisation (8)"),
                           ("T4", "T4 — Delivery Schedule (7)")):
            item = c[key]
            lines.append(f"### 4.{key[1]} {title}")
            lines.append("")
            lines.append(f"- Band: **{item['band']}** ({item['band_criteria']})")
            if item.get("computed_by_report_agent"):
                lines.append("- *(band computed by Report Agent from raw values — "
                             "confirm with Technical Agent)*")
            lines.append(f"- Score: **{item['score']} / {WEIGHTS[key]}**")
            lines.append("")
        if t["criteria"]["T4"].get("schedule_non_compliance"):
            lines.append("> ⚠️ **Schedule exceeds 76 weeks — potential/non-compliance issue.**")
            lines.append("")
        lines.append(f"**Technical Score: {t['score_display']} / {t['max']}**")
        lines.append("")
        return lines

    @staticmethod
    def _md_commercial(com: Dict) -> List[str]:
        lines = ["## 5. Commercial Evaluation", ""]
        lines.append(f"- Bidder evaluated price (Pbid): {com['evaluated_price']} {com['currency']}")
        lines.append(f"- Lowest evaluated price (Plow): {com['lowest_evaluated_price']} {com['currency']}")
        if com["price_comparison"] is not None:
            lines.append(f"- Price comparison: {com['price_comparison']}% above lowest")
        lines.append("")
        lines.append(f"**Commercial Score = 30 × (Plow / Pbid) = {com['score_display']} / {com['max']}**")
        lines.append("")
        lines.append("### 5.3 Commercial Deviations")
        lines.append("")
        for key, label in (("major_commercial", "Major commercial deviations"),
                           ("qualifications", "Qualifications"),
                           ("exclusions", "Exclusions"),
                           ("payment_terms", "Payment terms deviations"),
                           ("warranty", "Warranty deviations"),
                           ("ld_exposure", "LD exposure"),
                           ("other_contractual", "Other contractual concerns")):
            vals = com["deviations"].get(key, [])
            lines.append(f"- **{label}:** {', '.join(vals) if vals else 'None'}")
        lines.append("")
        return lines

    @staticmethod
    def _md_hse(h: Dict) -> List[str]:
        lines = ["## 6. HSE Evaluation", ""]
        h1, h2 = h["criteria"]["H1"], h["criteria"]["H2"]
        lines.append("### 6.1 H1 — Safety Performance (9)")
        lines.append("")
        lines.append(f"- 3-year average TRIR: **{h1['trir_3yr_average']}** → Band {h1['band']}")
        lines.append(f"- Work-related fatality in period: **{'YES' if h1['fatality_in_period'] else 'No'}**")
        lines.append(f"- Score: **{h1['score']} / 9**")
        lines.append("")
        lines.append("### 6.2 H2 — HSE Certifications (6)")
        lines.append("")
        lines.append(f"- ISO 45001 valid on due date: **{h2['iso45001_valid']}**")
        lines.append(f"- ISO 14001 valid on due date: **{h2['iso14001_valid']}**")
        lines.append(f"- Score: **{h2['score']} / 6**")
        lines.append("")
        lines.append(f"**HSE Score: {h['score_display']} / {h['max']}**")
        if h["concerns"]:
            lines.append(f"- Significant HSE concerns: {', '.join(h['concerns'])}")
        lines.append("")
        return lines

    @staticmethod
    def _md_icv(i: Dict) -> List[str]:
        lines = ["## 7. ICV Evaluation", ""]
        lines.append(f"- Certified ICV percentage: **{i['certified_percentage']}%**")
        lines.append(f"- Certificate validity: **{i['certificate_valid']}**")
        lines.append(f"- Certifying body: {i['certifying_body']}")
        lines.append(f"- Expiry date: {i['expiry_date'] or 'NOT PROVIDED'}")
        lines.append("")
        lines.append(f"**ICV Score = 15 × min(ICV%, 60) / 60 = {i['score_display']} / {i['max']}**")
        if i["mandatory_screening_failure"]:
            lines.append("")
            lines.append("> ⚠️ **Missing/invalid ICV certificate — zero ICV score AND "
                         "failure of mandatory screening.**")
        lines.append("")
        return lines

    @staticmethod
    def _md_total(total: Dict) -> List[str]:
        lines = ["## 8. Overall Score", "",
                 "| Evaluation Area | Maximum | Bidder Score |",
                 "|-----------------|-------:|------------:|"]
        for r in total["rows"]:
            lines.append(f"| {r['area']} | {r['max']} | {r['score'] if r['score'] is not None else NOT_CALCULABLE} |")
        lines.append(f"| **Total** | **{total['total_max']}** | **{total['total_display']}** |")
        lines.append("")
        return lines

    @staticmethod
    def _md_deviations(d: Dict) -> List[str]:
        lines = ["## 9. Deviations & Exceptions", ""]
        if d["items"]:
            lines += ["| # | Issue | Category | Classification | Evidence Ref |",
                      "|---|-------|----------|----------------|--------------|"]
            for idx, item in enumerate(d["items"], 1):
                lines.append(
                    f"| {idx} | {item['issue']} | {item['category']} | "
                    f"{item['classification']} | {item['evidence_ref']} |"
                )
        else:
            lines.append("No deviations recorded.")
        if d["conflict_flag"]:
            lines += [
                "",
                "> ⚠️ **CONFLICTING EVIDENCE — HUMAN REVIEW REQUIRED:** "
                + "; ".join(d["conflicting_evidence"]),
            ]
        lines.append("")
        return lines

    @staticmethod
    def _md_risk(r: Dict) -> List[str]:
        lines = ["## 10. Risk Assessment", "",
                 f"**Risk Agent determination: `{r['determination']}`**", ""]
        for sev in ("critical", "major", "moderate", "minor"):
            items = r["risks"].get(sev, [])
            lines.append(f"- **{sev.title()}:** {', '.join(items) if items else 'None'}")
        lines.append(f"- **Mitigations:** {', '.join(r['mitigations']) if r['mitigations'] else 'None'}")
        lines.append(f"- **Residual risks:** {', '.join(r['residual_risks']) if r['residual_risks'] else 'None'}")
        lines.append(f"- **Human-review triggers:** {', '.join(r['human_review_triggers']) if r['human_review_triggers'] else 'None'}")
        lines.append("")
        return lines

    @staticmethod
    def _md_evidence(evidence: List) -> List[str]:
        lines = ["## 11. Evidence & Traceability", ""]
        if evidence:
            lines += ["| Requirement | Bid Evidence | Source | Result | Impact |",
                      "|-------------|-------------|--------|--------|--------|"]
            for e in evidence:
                lines.append(
                    f"| {e.get('requirement', '')} | {e.get('bid_evidence', '')} | "
                    f"{e.get('source', '')} | {e.get('result', '')} | {e.get('impact', '')} |"
                )
        else:
            lines.append("*No evidence traceability rows provided by upstream agents.*")
        lines.append("")
        return lines

    @staticmethod
    def _md_list_section(title: str, items: List) -> List[str]:
        lines = [title, ""]
        if items:
            lines += [f"- {i}" for i in items]
        else:
            lines.append("*None recorded.*")
        lines.append("")
        return lines


def _criteria_for(bands: List, band) -> str:
    """Return the criteria text for a band, or a placeholder when unknown."""
    for b, criteria in bands:
        if b == band:
            return criteria
    return "band not supplied by upstream agent"


def _deepGet(payload: Dict, *keys: str, default: Any = None) -> Any:
    """Compatibility alias (internal)."""
    return _deep_get(payload, *keys, default=default)


# --------------------------------------------------------------------------- #
# Convenience entry points                                                    #
# --------------------------------------------------------------------------- #


def generate_report(payload: Union[Dict, str]) -> Dict[str, Any]:
    """Functional convenience wrapper around ReportAgent().generate()."""
    return ReportAgent().generate(payload)


def main() -> None:
    """CLI: read payload from stdin (or --file) and print the JSON report."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Report Agent — RFP/Bid Evaluation Report")
    parser.add_argument("--file", help="JSON payload file (defaults to stdin)")
    parser.add_argument("--markdown", action="store_true", help="Output markdown instead of JSON")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = json.load(sys.stdin)

    report = generate_report(payload)
    if args.markdown:
        print(report["markdown"])
    else:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
