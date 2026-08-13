"""
Test suite for the Report Agent module.

Run with:  python3 test_report_agent.py   (stdlib unittest, no dependencies)
Or with:   pytest test_report_agent.py
"""

import json
import os
import unittest

from report_agent import (
    NOT_CALCULABLE,
    NOT_VERIFIED,
    RECOMMEND,
    RECOMMEND_CONDITIONS,
    STATUS_HUMAN,
    STATUS_NOT_RECOMMENDED,
    STATUS_SAFE,
    ReportAgent,
    _band_from_h1,
    _band_from_h2,
    _band_from_t1,
    _band_from_t2,
    _band_from_t3,
    _band_from_t4,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def load_example():
    with open(os.path.join(HERE, "example_input.json")) as fh:
        return json.load(fh)


class TestBands(unittest.TestCase):
    """RFP band tables must be applied exactly."""

    def test_t1_bands(self):
        self.assertEqual(_band_from_t1(33000, 5), 5)
        self.assertEqual(_band_from_t1(34000, 4.5), 5)
        self.assertEqual(_band_from_t1(32000, 7), 4)
        self.assertEqual(_band_from_t1(31500, 8), 4)
        self.assertEqual(_band_from_t1(30500, 9), 3)
        self.assertEqual(_band_from_t1(30000, 10), 3)
        self.assertEqual(_band_from_t1(29999, 10), 0)   # below capacity
        self.assertEqual(_band_from_t1(34000, 11), 0)   # OiW too high

    def test_t2_bands(self):
        self.assertEqual(_band_from_t2(8), 5)
        self.assertEqual(_band_from_t2(9), 5)
        self.assertEqual(_band_from_t2(5), 4)
        self.assertEqual(_band_from_t2(3), 3)
        self.assertEqual(_band_from_t2(1), 2)
        self.assertEqual(_band_from_t2(0), 1)

    def test_t3_bands(self):
        self.assertEqual(_band_from_t3(15), 5)
        self.assertEqual(_band_from_t3(10), 4)
        self.assertEqual(_band_from_t3(6), 3)
        self.assertEqual(_band_from_t3(3), 2)
        self.assertEqual(_band_from_t3(2), 1)

    def test_t4_bands(self):
        self.assertEqual(_band_from_t4(52), 5)
        self.assertEqual(_band_from_t4(53), 4)
        self.assertEqual(_band_from_t4(61), 3)
        self.assertEqual(_band_from_t4(69), 2)
        self.assertEqual(_band_from_t4(76), 2)
        self.assertEqual(_band_from_t4(77), 1)

    def test_h1_bands(self):
        self.assertEqual(_band_from_h1(0.20, False), 5)
        self.assertEqual(_band_from_h1(0.35, False), 4)
        self.assertEqual(_band_from_h1(0.55, False), 3)
        self.assertEqual(_band_from_h1(0.80, False), 2)
        self.assertEqual(_band_from_h1(1.50, False), 1)
        self.assertEqual(_band_from_h1(0.10, True), 0)   # fatality overrides TRIR

    def test_h2_bands(self):
        self.assertEqual(_band_from_h2(True, True), 5)
        self.assertEqual(_band_from_h2(True, False), 3)
        self.assertEqual(_band_from_h2(False, True), 3)
        self.assertEqual(_band_from_h2(False, False), 1)


class TestScoring(unittest.TestCase):
    """Score formulas must match the RFP exactly."""

    def test_example_scores(self):
        report = ReportAgent().generate(load_example())

        tech = report["4_technical_evaluation"]
        # T1: band 5 -> (5/5)*15 = 15; T2: band 4 -> (4/5)*10 = 8
        # T3: band 5 -> (5/5)*8 = 8; T4: band 4 -> (4/5)*7 = 5.6
        self.assertEqual(tech["score"], 36.6)

        com = report["5_commercial_evaluation"]
        # 30 * (180000000 / 187500000) = 28.8
        self.assertEqual(com["score"], 28.8)

        hse = report["6_hse_evaluation"]
        # H1: band 5 -> 9; H2: band 5 -> 6
        self.assertEqual(hse["score"], 15.0)

        icv = report["7_icv_evaluation"]
        # 15 * min(48, 60) / 60 = 12.0
        self.assertEqual(icv["score"], 12.0)

        total = report["8_overall_score"]
        self.assertEqual(total["total_score"], 92.4)

    def test_commercial_rounding(self):
        # 30 * (100/103) = 29.1262... -> 29.13
        r = ReportAgent().generate({
            "commercial": {"evaluated_price": 103, "lowest_evaluated_price": 100},
        })
        self.assertEqual(r["5_commercial_evaluation"]["score"], 29.13)

    def test_icv_cap_at_60(self):
        # ICV 80% caps at 60 -> 15 * 60/60 = 15.0
        r = ReportAgent().generate({
            "icv": {"certified_percentage": 80, "certificate_valid": True},
        })
        self.assertEqual(r["7_icv_evaluation"]["score"], 15.0)

    def test_icv_invalid_certificate_zero(self):
        r = ReportAgent().generate({
            "icv": {"certified_percentage": 48, "certificate_valid": False},
        })
        icv = r["7_icv_evaluation"]
        self.assertEqual(icv["score"], 0.0)
        self.assertTrue(icv["mandatory_screening_failure"])

    def test_missing_inputs_not_calculable(self):
        r = ReportAgent().generate({"bidder": {"name": "X"}})
        self.assertEqual(r["4_technical_evaluation"]["score_display"], NOT_CALCULABLE)
        self.assertEqual(r["5_commercial_evaluation"]["score_display"], NOT_CALCULABLE)
        self.assertEqual(r["6_hse_evaluation"]["score_display"], NOT_CALCULABLE)
        self.assertEqual(r["7_icv_evaluation"]["score_display"], NOT_CALCULABLE)
        self.assertEqual(r["8_overall_score"]["total_display"], NOT_CALCULABLE)
        for row in r["3_mandatory_compliance"]["rows"]:
            self.assertEqual(row["status"], NOT_VERIFIED)


class TestDecisions(unittest.TestCase):
    """Recommendation + final status logic."""

    def test_clean_bid_recommended(self):
        r = ReportAgent().generate({
            "compliance": {"D%d" % i: {"status": "COMPLIANT"} for i in range(1, 10)},
            "risk": {"determination": STATUS_SAFE},
        })
        self.assertEqual(r["final_status"], STATUS_SAFE)
        self.assertEqual(r["recommendation"], RECOMMEND)

    def test_conditions_recommend_with_conditions(self):
        r = ReportAgent().generate({
            "compliance": {"D%d" % i: {"status": "COMPLIANT"} for i in range(1, 10)},
            "risk": {"determination": STATUS_SAFE},
            "deviations": [
                {"issue": "Payment terms", "classification": "Major"},
                {"issue": "LD cap", "classification": "Moderate"},
            ],
        })
        self.assertEqual(r["final_status"], STATUS_SAFE)
        self.assertEqual(r["recommendation"], RECOMMEND_CONDITIONS)

    def test_mandatory_failure_not_recommended(self):
        r = ReportAgent().generate({
            "compliance": {"D6": {"status": "NON-COMPLIANT"}},
            "risk": {"determination": STATUS_SAFE},
        })
        self.assertEqual(r["final_status"], STATUS_NOT_RECOMMENDED)
        self.assertEqual(r["recommendation"], "NOT RECOMMENDED")

    def test_risk_human_review_overrides_everything(self):
        r = ReportAgent().generate({
            "compliance": {"D%d" % i: {"status": "COMPLIANT"} for i in range(1, 10)},
            "risk": {"determination": STATUS_HUMAN},
        })
        self.assertEqual(r["final_status"], STATUS_HUMAN)
        self.assertEqual(r["recommendation"], "HUMAN REVIEW REQUIRED")

    def test_conflicting_evidence_forces_human_review(self):
        r = ReportAgent().generate({
            "risk": {"determination": STATUS_SAFE},
            "conflicting_evidence": ["T1 capacity disputed between agents"],
        })
        self.assertEqual(r["final_status"], STATUS_HUMAN)

    def test_schedule_over_76_weeks_not_recommended(self):
        r = ReportAgent().generate({
            "compliance": {"D%d" % i: {"status": "COMPLIANT"} for i in range(1, 10)},
            "technical": {"T4": {"band": 1, "weeks_to_mechanical_completion": 80}},
            "risk": {"determination": STATUS_SAFE},
        })
        self.assertEqual(r["final_status"], STATUS_NOT_RECOMMENDED)


class TestBandComputation(unittest.TestCase):
    """Raw values -> band fallback, flagged for audit."""

    def test_computed_bands_flagged(self):
        r = ReportAgent().generate({
            "technical": {
                "T1": {"offered_capacity_m3d": 32000, "offered_oiw_mgl": 7},
                "T2": {"references": [{"qualifies": True}, {"qualifies": True}]},
                "T3": {"years_experience": 12},
                "T4": {"weeks_to_mechanical_completion": 56},
            },
            "hse": {"trir": 0.35, "fatality_in_period": False,
                    "iso45001_valid": True, "iso14001_valid": False},
        })
        tech = r["4_technical_evaluation"]
        self.assertTrue(tech["criteria"]["T1"]["computed_by_report_agent"])
        self.assertEqual(tech["criteria"]["T1"]["band"], 4)
        self.assertEqual(tech["criteria"]["T2"]["band"], 2)
        self.assertEqual(tech["criteria"]["T3"]["band"], 4)
        self.assertEqual(tech["criteria"]["T4"]["band"], 4)
        hse = r["6_hse_evaluation"]
        self.assertEqual(hse["criteria"]["H1"]["band"], 4)
        self.assertEqual(hse["criteria"]["H2"]["band"], 3)


class TestOutput(unittest.TestCase):
    """Output structure guarantees."""

    def test_full_structure(self):
        r = ReportAgent().generate(load_example())
        for key in ("1_executive_summary", "2_tender_bid_information",
                    "3_mandatory_compliance", "4_technical_evaluation",
                    "5_commercial_evaluation", "6_hse_evaluation",
                    "7_icv_evaluation", "8_overall_score",
                    "9_deviations_exceptions", "10_risk_assessment",
                    "11_evidence_traceability", "12_key_strengths",
                    "13_key_weaknesses", "14_recommendation",
                    "15_final_decision_status"):
            self.assertIn(key, r)
        self.assertIn(r["final_status"], (STATUS_SAFE, STATUS_HUMAN, STATUS_NOT_RECOMMENDED))
        self.assertIn("markdown", r)
        self.assertIn("quality_control", r)

    def test_markdown_contains_sections(self):
        r = ReportAgent().generate(load_example())
        md = r["markdown"]
        for section in ("## 1. Executive Summary", "## 15. Final Decision Status",
                        "FINAL STATUS: SAFE TO REPORT"):
            self.assertIn(section, md)

    def test_qc_passes_for_complete_input(self):
        r = ReportAgent().generate(load_example())
        self.assertTrue(r["quality_control"]["all_passed"])

    def test_json_string_input(self):
        payload = json.dumps({"bidder": {"name": "JSON String Co"}})
        r = ReportAgent().generate(payload)
        self.assertEqual(r["header"]["bidder_name"], "JSON String Co")

    def test_serializable(self):
        r = ReportAgent().generate(load_example())
        json.dumps(r)  # must not raise

    def test_invalid_risk_determination_defaults_safely(self):
        r = ReportAgent().generate({"risk": {"determination": "SOMETHING_ELSE"}})
        self.assertEqual(r["10_risk_assessment"]["determination"], STATUS_SAFE)
        self.assertTrue(any("risk.determination" in w for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
