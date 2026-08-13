"""
orchestrator.py — MIZAN Agent Pipeline Orchestrator

Runs the full 8-agent evaluation pipeline:
  1. Evidence & Retrieval Agent
  2. Compliance & Screening Agent
  3-6. Technical / Commercial / HSE / ICV Agents (parallel)
  7. Risk & Human Escalation Agent
  8. Recommendation & Report Agent

Every agent logs its activity with timestamps, inputs, tools used, and outputs.
"""

import sys, os, json, time, datetime, copy, re, math
from typing import Optional

# ── Path setup: make ProcurX modules importable ──
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Import existing agents ──
from evidence_agent import evidence as ev
from evidence_agent import package as pkg
from evidence_agent import search

# ── Agent activity log ──
_activity_log = []


def log_agent(agent_name: str, status: str, inputs: dict, tool: str, outputs: dict):
    """Record an agent activity entry."""
    _activity_log.append({
        'timestamp': datetime.datetime.now().isoformat(),
        'agent': agent_name,
        'status': status,
        'inputs': inputs,
        'tool': tool,
        'outputs': outputs,
    })


def get_activity_log():
    """Return full activity log."""
    return list(_activity_log)


def clear_activity_log():
    _activity_log.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  TOOLS (deterministic calculation functions per AGENTS.md)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_commercial_score(lowest_price: float, supplier_price: float) -> float:
    """Commercial Score = 30 × (lowest qualifying evaluated price / supplier evaluated price)"""
    if not supplier_price or supplier_price <= 0:
        return 0.0
    score = 30.0 * (lowest_price / supplier_price)
    return round(score, 2)


def calculate_icv_score(icv_percentage: Optional[float]) -> float:
    """ICV Score = 15 × min(icv%, 60) / 60"""
    if icv_percentage is None:
        return 0.0
    capped = min(float(icv_percentage), 60.0)
    score = 15.0 * (capped / 60.0)
    return round(score, 2)


def calculate_total_score(technical: float, commercial: float, hse: float, icv: float) -> float:
    """Total = Technical + Commercial + HSE + ICV (max 100)"""
    return round(technical + commercial + hse + icv, 2)


def escalate_to_human(case_details: dict) -> dict:
    """Trigger human escalation. Returns escalation record."""
    escalation = {
        'escalated': True,
        'timestamp': datetime.datetime.now().isoformat(),
        'case': case_details,
        'status': 'HUMAN REVIEW REQUIRED',
    }
    return escalation


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER: import agent modules lazily
# ═══════════════════════════════════════════════════════════════════════════════

def _import_technical_scorer():
    """Import the technical scorer module."""
    try:
        sys.path.insert(0, os.path.join(ROOT, 'technical score agent'))
        import technical_scorer
        return technical_scorer
    except Exception as e:
        return None


def _import_compliance_agent():
    """Import compliance agent as a callable module."""
    try:
        import compliance_eligibility_agent as cea
        return cea
    except Exception:
        return None


def _import_risk_agent():
    try:
        import risk_escalation_agent as rea
        return rea
    except Exception:
        return None


def _import_report_agent():
    try:
        sys.path.insert(0, os.path.join(ROOT, 'report_agent_app'))
        from report_agent import ReportAgent
        return ReportAgent
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Lazy evaluation field labels — map query field → display label
# ═══════════════════════════════════════════════════════════════════════════════

FIELD_LABELS = {
    'price': 'Total Bid Price', 'capacity': 'Treatment Capacity',
    'oiw': 'Outlet Oil-in-Water Guarantee', 'tss': 'Total Suspended Solids',
    'mc_weeks': 'Mechanical Completion Schedule', 'warranty': 'Warranty Period',
    'trir': '3-Year Average TRIR', 'icv': 'In-Country Value Score',
    'experience': 'Company Experience', 'references': 'GCC References',
    'employees': 'Employees', 'scheme': 'Treatment Scheme',
    'certifications': 'Certifications', 'checklist': 'Submission Checklist',
    'arithmetic': 'Arithmetic Verification', 'alternate': 'Technical Alternate',
    'bid_bond': 'Bid Bond', 'payment': 'Payment Terms',
    'performance': 'Performance Guarantees',
}


def _get_supplier_list():
    """Return list of supplier dicts from evidence_agent data."""
    suppliers = []
    for bid_ref, facts in sorted(search._bid_facts.items()):
        suppliers.append({
            'bid_ref': bid_ref,
            'company': facts.get('company', 'Unknown'),
            'source_file': facts.get('source_file', ''),
            **facts,
        })
    return suppliers


def _get_rfp_info():
    """Return RFP info dict."""
    return search.get_rfp_facts()


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 1 — Evidence & Retrieval
# ═══════════════════════════════════════════════════════════════════════════════

def run_evidence_agent() -> dict:
    """Run Evidence & Retrieval Agent — gather all bid and RFP evidence."""
    t0 = time.time()
    inputs = {'action': 'retrieve_all_evidence', 'query': 'List all bids with their prices and capacities'}

    try:
        # Grab all suppliers
        supplier_list = _get_supplier_list()
        rfp_info = _get_rfp_info()

        # Build evidence package
        evidence_items = ev.build_evidence('List all bids with their prices and capacities')
        evidence_pkg = pkg.build_evidence_package('List all bids with their prices and capacities')

        outputs = {
            'suppliers': supplier_list,
            'rfp_info': rfp_info,
            'evidence_items': evidence_items,
            'evidence_package': evidence_pkg,
            'supplier_count': len(supplier_list),
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('🔎 Evidence & Retrieval', status, inputs, 'search_knowledge_base()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 2 — Compliance & Screening
# ═══════════════════════════════════════════════════════════════════════════════

def run_compliance_agent(evidence_output: dict) -> dict:
    """Run Compliance & Screening Agent — check D1-D9 and tech minimums."""
    t0 = time.time()
    inputs = {'source': 'evidence_agent_output', 'suppliers_count': len(evidence_output.get('suppliers', []))}

    try:
        suppliers = evidence_output.get('suppliers', [])
        rfp = evidence_output.get('rfp_info', {})
        mandatory_codes = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']

        results = []
        for s in suppliers:
            checklist = s.get('submission_checklist', {})
            missing = [d for d in mandatory_codes if checklist.get(d) != 'Enclosed']
            cap = s.get('capacity_m3_per_day')
            oiw = s.get('outlet_oiw_mg_per_l')

            # Technical minimum
            tech_issues = []
            if cap is not None and cap < 30000:
                tech_issues.append(f"Capacity {cap} m³/d < 30,000 minimum")
            if oiw is not None and oiw > 10:
                tech_issues.append(f"OiW {oiw} mg/L > 10 mg/L maximum")
            mc = s.get('mc_weeks_from_loa')
            if mc is not None and mc > 76:
                tech_issues.append(f"MC {mc} weeks > 76 week maximum")

            if missing:
                mandatory_status = 'FAIL' if len(missing) > 2 else 'CONDITIONAL'
            else:
                mandatory_status = 'PASS'

            tech_min_status = 'FAIL' if tech_issues else 'PASS'

            results.append({
                'bid_ref': s.get('bid_ref'),
                'company': s.get('company'),
                'mandatory_status': mandatory_status,
                'missing_requirements': missing,
                'technical_minimum': tech_min_status,
                'technical_issues': tech_issues,
                'evidence': {
                    'checklist': checklist,
                    'capacity': cap,
                    'oiw': oiw,
                    'mc_weeks': mc,
                },
                'reason': 'All mandatory docs present' if not missing else f"Missing: {', '.join(missing)}",
            })

        outputs = {
            'compliance_results': results,
            'passed_count': sum(1 for r in results if r['mandatory_status'] == 'PASS' and r['technical_minimum'] == 'PASS'),
            'conditional_count': sum(1 for r in results if r['mandatory_status'] == 'CONDITIONAL'),
            'failed_count': sum(1 for r in results if r['mandatory_status'] == 'FAIL' or r['technical_minimum'] == 'FAIL'),
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('✓ Compliance & Screening', status, inputs, 'mandatory_check() + technical_minimum_check()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 3 — Technical Evaluation
# ═══════════════════════════════════════════════════════════════════════════════

def run_technical_agent(compliance_output: dict) -> dict:
    """Run Technical Evaluation Agent — score T1-T4 (max 40)."""
    t0 = time.time()
    inputs = {'source': 'compliance_agent_output'}

    try:
        ts = _import_technical_scorer()
        results = []

        for cr in compliance_output.get('compliance_results', []):
            facts = search._bid_facts.get(cr['bid_ref'], {})

            t1_cap = facts.get('capacity_m3_per_day')
            t1_oiw = facts.get('outlet_oiw_mg_per_l')
            t2_refs = facts.get('gcc_references_count')
            t3_exp = facts.get('experience_years')
            t4_mc = facts.get('mc_weeks_from_loa')

            # Use technical scorer if available
            if ts:
                evidence_input = {
                    'supplier': cr['company'],
                    'eligibility_status': 'Eligible' if cr['mandatory_status'] == 'PASS' else 'Not eligible',
                    't1': {
                        'capacity_m3d': t1_cap,
                        'capacity_evidence_present': t1_cap is not None,
                        'oiw_mgL': t1_oiw,
                        'oiw_evidence_present': t1_oiw is not None,
                    },
                    't2': {
                        'gcc_references': t2_refs,
                        'evidence_present': t2_refs is not None,
                    },
                    't3': {
                        'years_experience': t3_exp,
                        'evidence_present': t3_exp is not None,
                    },
                    't4': {
                        'weeks_to_completion': t4_mc,
                        'evidence_present': t4_mc is not None,
                    },
                }
                try:
                    score_result = ts.score_technical(evidence_input)
                except Exception:
                    score_result = None
            else:
                score_result = None

            if score_result and score_result.get('scored'):
                t_score = score_result['technical_score']
                t1_detail = score_result.get('t1', {})
                t2_detail = score_result.get('t2', {})
                t3_detail = score_result.get('t3', {})
                t4_detail = score_result.get('t4', {})
            else:
                # Manual scoring fallback
                def _t1_band(cap, oiw):
                    if cap is None or oiw is None:
                        return None, "Insufficient evidence"
                    if cap >= 33000 and oiw <= 5:
                        return 5, "Capacity ≥ 33,000 m³/d AND OiW ≤ 5 mg/L"
                    if cap >= 31500 and oiw <= 8:
                        return 4, "Capacity ≥ 31,500 m³/d AND OiW ≤ 8 mg/L"
                    if cap >= 30000 and oiw <= 10:
                        return 3, "Capacity ≥ 30,000 m³/d AND OiW ≤ 10 mg/L"
                    return 0, "Capacity < 30,000 m³/d OR OiW > 10 mg/L — technically non-compliant"

                def _t2_band(refs):
                    if refs is None:
                        return None, "Insufficient evidence"
                    if refs >= 8:
                        return 5, "≥ 8 GCC references ≥ 20,000 m³/d"
                    if refs >= 5:
                        return 4, "5-7 GCC references"
                    if refs >= 3:
                        return 3, "3-4 GCC references"
                    if refs >= 1:
                        return 2, "1-2 GCC references"
                    return 1, "No comparable GCC reference"

                def _t3_band(exp):
                    if exp is None:
                        return None, "Insufficient evidence"
                    if exp >= 15:
                        return 5, "≥ 15 years experience"
                    if exp >= 10:
                        return 4, "10-14 years"
                    if exp >= 5:
                        return 3, "5-9 years"
                    if exp >= 3:
                        return 2, "3-4 years"
                    return 1, "< 3 years"

                def _t4_band(mc):
                    if mc is None:
                        return None, "Insufficient evidence"
                    if mc <= 52:
                        return 5, "≤ 52 weeks (target)"
                    if mc <= 60:
                        return 4, "53-60 weeks"
                    if mc <= 68:
                        return 3, "61-68 weeks"
                    if mc <= 76:
                        return 2, "69-76 weeks (contractual max)"
                    return 1, "> 76 weeks — subject to rejection"

                t1_b, t1_txt = _t1_band(t1_cap, t1_oiw)
                t2_b, t2_txt = _t2_band(t2_refs)
                t3_b, t3_txt = _t3_band(t3_exp)
                t4_b, t4_txt = _t4_band(t4_mc)

                def _pts(band, weight):
                    if band is None:
                        return 0.0
                    return round((band / 5.0) * weight, 2)

                t_score = _pts(t1_b, 15) + _pts(t2_b, 10) + _pts(t3_b, 8) + _pts(t4_b, 7)

                t1_detail = {'band': t1_b, 'text': t1_txt, 'points': _pts(t1_b, 15)}
                t2_detail = {'band': t2_b, 'text': t2_txt, 'points': _pts(t2_b, 10)}
                t3_detail = {'band': t3_b, 'text': t3_txt, 'points': _pts(t3_b, 8)}
                t4_detail = {'band': t4_b, 'text': t4_txt, 'points': _pts(t4_b, 7)}

            # Strengths & weaknesses
            strengths = []
            weaknesses = []
            if t1_detail.get('band') and t1_detail['band'] >= 4:
                strengths.append(f"T1: {t1_detail.get('text', 'Strong capacity & OiW')}")
            elif t1_detail.get('band') is None:
                weaknesses.append("T1: Insufficient evidence to calculate")
            elif t1_detail['band'] == 0:
                weaknesses.append(f"T1: {t1_detail.get('text', 'Non-compliant')}")
            else:
                weaknesses.append(f"T1: Meets spec but not top band")

            if t2_detail.get('band') and t2_detail['band'] >= 4:
                strengths.append(f"T2: {t2_detail.get('text', 'Strong GCC track record')}")
            elif t2_detail.get('band') is not None and t2_detail['band'] <= 2:
                weaknesses.append(f"T2: Limited GCC references")

            if t3_detail.get('band') and t3_detail['band'] >= 4:
                strengths.append(f"T3: {t3_detail.get('text', 'Experienced organisation')}")
            elif t3_detail.get('band') is not None and t3_detail['band'] <= 2:
                weaknesses.append(f"T3: Limited company experience")

            if t4_detail.get('band') and t4_detail['band'] >= 4:
                strengths.append(f"T4: {t4_detail.get('text', 'Fast delivery schedule')}")
            elif t4_detail.get('band') and t4_detail['band'] <= 2:
                weaknesses.append(f"T4: Extended delivery schedule")

            results.append({
                'bid_ref': cr['bid_ref'],
                'company': cr['company'],
                'technical_compliance': 'PASS' if t1_detail.get('band', 0) != 0 else 'FAIL',
                't1': t1_detail,
                't2': t2_detail,
                't3': t3_detail,
                't4': t4_detail,
                'technical_total': round(t_score, 2),
                'technical_max': 40,
                'strengths': strengths,
                'weaknesses': weaknesses,
                'missing_evidence': [k for k, v in [('T1 capacity', t1_cap), ('T1 OiW', t1_oiw), ('T2 references', t2_refs), ('T3 experience', t3_exp), ('T4 schedule', t4_mc)] if v is None],
            })

        outputs = {
            'technical_results': results,
            'avg_score': round(sum(r['technical_total'] for r in results) / len(results), 2) if results else 0,
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('🔧 Technical Evaluation', status, inputs, 'score_technical() + band_tables', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 4 — Commercial Evaluation
# ═══════════════════════════════════════════════════════════════════════════════

def run_commercial_agent(compliance_output: dict) -> dict:
    """Run Commercial Evaluation Agent — score pricing (max 30)."""
    t0 = time.time()
    inputs = {'source': 'compliance_agent_output', 'formula': 'C = 30 × (Plow / Pbid)'}

    try:
        results = []

        # Collect all prices for lowest qualifying price
        all_prices = []
        for cr in compliance_output.get('compliance_results', []):
            facts = search._bid_facts.get(cr['bid_ref'], {})
            price = facts.get('price_total')
            currency = facts.get('price_currency', 'AED')
            if price is not None:
                # Convert to AED if needed
                aed_price = price if currency == 'AED' else round(price * 3.6725, 2)
                all_prices.append({
                    'bid_ref': cr['bid_ref'],
                    'company': cr['company'],
                    'price': price,
                    'currency': currency,
                    'aed_equivalent': aed_price,
                })

        if not all_prices:
            outputs = {'commercial_results': [], 'error': 'No prices found'}
            log_agent('💰 Commercial Evaluation', 'error', inputs, 'calculate_commercial_score()', outputs)
            return outputs

        # Lowest qualifying price (only AED or converted)
        all_prices.sort(key=lambda x: x['aed_equivalent'])
        lowest_price = all_prices[0]['aed_equivalent']

        for p in all_prices:
            score = calculate_commercial_score(lowest_price, p['aed_equivalent'])
            results.append({
                'bid_ref': p['bid_ref'],
                'company': p['company'],
                'evaluated_price': p['price'],
                'currency': p['currency'],
                'aed_equivalent': p['aed_equivalent'],
                'lowest_qualifying_price': lowest_price,
                'commercial_score': score,
                'commercial_max': 30,
                'notes': 'Lowest qualifying price' if p['aed_equivalent'] == lowest_price else f"Score = 30 × ({lowest_price:,} / {p['aed_equivalent']:,}) = {score}",
            })

        outputs = {
            'commercial_results': results,
            'lowest_price': lowest_price,
            'lowest_bidder': all_prices[0]['company'],
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('💰 Commercial Evaluation', status, inputs, 'calculate_commercial_score()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 5 — HSE Evaluation
# ═══════════════════════════════════════════════════════════════════════════════

def run_hse_agent(compliance_output: dict) -> dict:
    """Run HSE Evaluation Agent — score H1-H2 (max 15)."""
    t0 = time.time()
    inputs = {'source': 'compliance_agent_output', 'criteria': 'H1 Safety (9pts), H2 Certification (6pts)'}

    try:
        results = []

        for cr in compliance_output.get('compliance_results', []):
            facts = search._bid_facts.get(cr['bid_ref'], {})
            trir = facts.get('trir_3yr_avg')
            has_iso14001 = facts.get('has_iso_14001', False)
            has_iso45001 = facts.get('has_iso_45001', False)

            # H1: TRIR bands (weight 9)
            def _h1_band(trir_val):
                if trir_val is None:
                    return None, "Insufficient evidence"
                if trir_val <= 0.30:
                    return 5, f"TRIR {trir_val} ≤ 0.30 — excellent"
                if trir_val <= 0.50:
                    return 4, f"TRIR {trir_val} ≤ 0.50 — good"
                if trir_val <= 0.70:
                    return 3, f"TRIR {trir_val} ≤ 0.70 — satisfactory"
                if trir_val <= 1.00:
                    return 2, f"TRIR {trir_val} ≤ 1.00 — below average"
                return 1, f"TRIR {trir_val} > 1.00 — poor"

            # H2: Certification bands (weight 6)
            def _h2_band(iso14, iso45):
                if iso14 and iso45:
                    return 5, "Both ISO 14001 & ISO 45001 certified"
                if iso14 or iso45:
                    return 3, f"One certification: {'ISO 14001' if iso14 else 'ISO 45001'}"
                return 1, "No HSE management certification found"

            h1_b, h1_txt = _h1_band(trir)
            h2_b, h2_txt = _h2_band(has_iso14001, has_iso45001)

            h1_points = round((h1_b / 5.0) * 9, 2) if h1_b is not None else 0
            h2_points = round((h2_b / 5.0) * 6, 2) if h2_b is not None else 0

            risks = []
            if trir is not None and trir > 0.5:
                risks.append(f"TRIR {trir} exceeds 0.50 threshold")
            if not has_iso14001 or not has_iso45001:
                risks.append("Missing HSE certification(s)")

            results.append({
                'bid_ref': cr['bid_ref'],
                'company': cr['company'],
                'trir': trir,
                'h1': {'band': h1_b, 'text': h1_txt, 'points': h1_points},
                'h2': {'band': h2_b, 'text': h2_txt, 'points': h2_points},
                'has_iso_14001': has_iso14001,
                'has_iso_45001': has_iso45001,
                'hse_total': round(h1_points + h2_points, 2),
                'hse_max': 15,
                'hse_risks': risks,
            })

        outputs = {
            'hse_results': results,
            'avg_score': round(sum(r['hse_total'] for r in results) / len(results), 2) if results else 0,
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('🦺 HSE Evaluation', status, inputs, 'band_tables(H1, H2)', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 6 — ICV Evaluation
# ═══════════════════════════════════════════════════════════════════════════════

def run_icv_agent(compliance_output: dict) -> dict:
    """Run ICV Evaluation Agent — score In-Country Value (max 15)."""
    t0 = time.time()
    inputs = {'source': 'compliance_agent_output', 'formula': 'ICV = 15 × min(icv%, 60) / 60'}

    try:
        results = []

        for cr in compliance_output.get('compliance_results', []):
            facts = search._bid_facts.get(cr['bid_ref'], {})
            icv_pct = facts.get('icv_score_pct')
            icv_cert = facts.get('icv_cert_no')

            score = calculate_icv_score(icv_pct)

            if icv_pct is None:
                status_text = "Not available in provided dataset"
                icv_note = "ICV certificate (D6) not found in submission"
            else:
                capped = min(float(icv_pct), 60.0)
                status_text = f"Certified ICV: {icv_pct}% (capped at 60%: {capped}%)"
                icv_note = f"Score = 15 × {capped} / 60 = {score}"

            results.append({
                'bid_ref': cr['bid_ref'],
                'company': cr['company'],
                'icv_score': score,
                'icv_max': 15,
                'certified_icv_pct': icv_pct,
                'icv_cert_no': icv_cert,
                'status_text': status_text,
                'formula_note': icv_note,
                'icv_status': 'Verified' if icv_pct is not None else 'Not Found',
                'evidence': facts.get('source_file', ''),
            })

        outputs = {
            'icv_results': results,
            'avg_score': round(sum(r['icv_score'] for r in results) / len(results), 2) if results else 0,
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('🇦🇪 ICV Evaluation', status, inputs, 'calculate_icv_score()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 7 — Risk & Human Escalation
# ═══════════════════════════════════════════════════════════════════════════════

def run_risk_agent(technical: dict, commercial: dict, hse: dict, icv: dict) -> dict:
    """Run Risk & Escalation Agent — identify risks and decide on escalation."""
    t0 = time.time()
    inputs = {
        'sources': ['technical', 'commercial', 'hse', 'icv'],
        'decision': 'escalate if serious risks found',
    }

    try:
        findings = []
        risk_level = 'LOW'
        human_review = False
        escalated_suppliers = []

        # Consolidate all results
        all_suppliers = {}
        for result_set in [technical.get('technical_results', []),
                           commercial.get('commercial_results', []),
                           hse.get('hse_results', []),
                           icv.get('icv_results', [])]:
            for r in result_set:
                bref = r.get('bid_ref')
                if bref:
                    if bref not in all_suppliers:
                        all_suppliers[bref] = {'bid_ref': bref, 'company': r.get('company', '')}
                    all_suppliers[bref].update(r)

        for bref, sup in all_suppliers.items():
            supplier_risks = []

            # Check for missing mandatory info
            if sup.get('technical_total') is None or sup.get('technical_total') == 0:
                if sup.get('missing_evidence'):
                    supplier_risks.append({
                        'category': 'Technical',
                        'issue': f"Missing evidence: {', '.join(sup.get('missing_evidence', []))}",
                        'severity': 'HIGH',
                    })

            # T1 non-compliance
            t1_info = sup.get('t1', {})
            if t1_info.get('band') == 0:
                supplier_risks.append({
                    'category': 'Technical',
                    'issue': f"T1 rejection: {t1_info.get('text', 'Non-compliant')}",
                    'severity': 'HIGH',
                })

            # Commercial risks
            if sup.get('currency') and sup['currency'] != 'AED':
                supplier_risks.append({
                    'category': 'Commercial',
                    'issue': f"Priced in {sup['currency']} (commercial deviation)",
                    'severity': 'MEDIUM',
                })

            # Arithmetic issues from facts
            facts = search._bid_facts.get(bref, {})
            if facts.get('arithmetic_issue'):
                ai = facts['arithmetic_issue']
                supplier_risks.append({
                    'category': 'Commercial',
                    'issue': f"Arithmetic discrepancy: line items sum to {ai['line_item_sum']:,} vs stated {ai['stated_total']:,}",
                    'severity': 'HIGH',
                })

            # Missing ICV
            if sup.get('certified_icv_pct') is None:
                supplier_risks.append({
                    'category': 'ICV',
                    'issue': 'ICV certificate (D6) not found — scores zero for ICV',
                    'severity': 'MEDIUM',
                })

            # HSE risks
            hse_risks = sup.get('hse_risks', [])
            for hr in hse_risks:
                supplier_risks.append({
                    'category': 'HSE',
                    'issue': hr,
                    'severity': 'MEDIUM',
                })

            # Missing ISO certs
            if not sup.get('has_iso_14001') or not sup.get('has_iso_45001'):
                supplier_risks.append({
                    'category': 'HSE',
                    'issue': 'Missing HSE management certification(s)',
                    'severity': 'LOW',
                })

            if supplier_risks:
                high_count = sum(1 for r in supplier_risks if r['severity'] == 'HIGH')
                if high_count > 0:
                    risk_level = 'HIGH'
                    human_review = True
                    escalated_suppliers.append(bref)
                elif len(supplier_risks) >= 3:
                    risk_level = max(risk_level, 'MEDIUM')

            findings.append({
                'bid_ref': bref,
                'company': sup.get('company', ''),
                'risks': supplier_risks,
                'risk_count': len(supplier_risks),
                'high_risk_count': sum(1 for r in supplier_risks if r['severity'] == 'HIGH'),
                'medium_risk_count': sum(1 for r in supplier_risks if r['severity'] == 'MEDIUM'),
            })

        escalation_result = None
        if human_review:
            escalation_result = escalate_to_human({
                'trigger': 'Serious procurement risks identified',
                'affected_suppliers': escalated_suppliers,
                'risk_level': risk_level,
                'findings': [f for f in findings if f['bid_ref'] in escalated_suppliers],
                'recommended_action': 'Manual review of identified risks before proceeding',
            })

        outputs = {
            'findings': findings,
            'risk_level': risk_level,
            'human_review_required': human_review,
            'escalation': escalation_result,
            'total_risks_found': sum(f['risk_count'] for f in findings),
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('⚠ Risk & Escalation', status, inputs, 'escalate_to_human()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENT 8 — Recommendation & Report
# ═══════════════════════════════════════════════════════════════════════════════

def run_recommendation_agent(technical: dict, commercial: dict, hse: dict, icv: dict, risk: dict) -> dict:
    """Run Recommendation & Report Agent — combine scores, rank, report."""
    t0 = time.time()
    inputs = {'sources': ['technical', 'commercial', 'hse', 'icv', 'risk']}

    try:
        # Build combined supplier scores
        combined = {}

        for r in technical.get('technical_results', []):
            bref = r['bid_ref']
            combined[bref] = {
                'bid_ref': bref,
                'company': r['company'],
                'technical': r['technical_total'],
                'technical_max': 40,
                't1': r.get('t1', {}),
                't2': r.get('t2', {}),
                't3': r.get('t3', {}),
                't4': r.get('t4', {}),
                'tech_strengths': r.get('strengths', []),
                'tech_weaknesses': r.get('weaknesses', []),
            }

        for r in commercial.get('commercial_results', []):
            bref = r['bid_ref']
            if bref in combined:
                combined[bref]['commercial'] = r['commercial_score']
                combined[bref]['commercial_max'] = 30
                combined[bref]['price'] = r['evaluated_price']
                combined[bref]['currency'] = r['currency']
                combined[bref]['commercial_notes'] = r.get('notes', '')

        for r in hse.get('hse_results', []):
            bref = r['bid_ref']
            if bref in combined:
                combined[bref]['hse'] = r['hse_total']
                combined[bref]['hse_max'] = 15
                combined[bref]['hse_risks'] = r.get('hse_risks', [])

        for r in icv.get('icv_results', []):
            bref = r['bid_ref']
            if bref in combined:
                combined[bref]['icv'] = r['icv_score']
                combined[bref]['icv_max'] = 15
                combined[bref]['icv_pct'] = r.get('certified_icv_pct')
                combined[bref]['icv_status'] = r.get('icv_status', '')

        # Calculate totals
        for bref, s in combined.items():
            s['total'] = calculate_total_score(
                s.get('technical', 0),
                s.get('commercial', 0),
                s.get('hse', 0),
                s.get('icv', 0),
            )
            s['total_max'] = 100

        # Rank
        ranked = sorted(combined.values(), key=lambda x: x['total'], reverse=True)

        # Check risk findings
        risk_findings = {f['bid_ref']: f for f in risk.get('findings', [])}
        for s in combined.values():
            if s['bid_ref'] in risk_findings:
                rf = risk_findings[s['bid_ref']]
                s['risk_count'] = rf['risk_count']
                s['high_risk_count'] = rf['high_risk_count']
                s['risks'] = rf['risks']
            else:
                s['risk_count'] = 0
                s['high_risk_count'] = 0
                s['risks'] = []

        # Determine recommendation
        human_review = risk.get('human_review_required', False)
        if human_review:
            recommendation = {
                'status': 'HUMAN REVIEW REQUIRED',
                'recommended_supplier': None,
                'message': 'AI evaluation paused — human review required due to identified risks.',
            }
        elif ranked:
            top = ranked[0]
            recommendation = {
                'status': 'AI RECOMMENDATION',
                'recommended_supplier': top['company'],
                'recommended_bid_ref': top['bid_ref'],
                'score': top['total'],
                'message': f"Highest-ranked supplier based on the provided evaluation methodology.",
            }
        else:
            recommendation = {
                'status': 'INSUFFICIENT DATA',
                'recommended_supplier': None,
                'message': 'Cannot make a recommendation — insufficient evaluation data.',
            }

        # Trade-off analysis
        trade_off = []
        if len(ranked) >= 2:
            top = ranked[0]
            second = ranked[1]
            if second.get('commercial', 0) > top.get('commercial', 0):
                trade_off.append(
                    f"{second['company']} has the lower evaluated price and therefore receives the "
                    f"strongest commercial score ({second['commercial']}/30). However, "
                    f"{top['company']} achieves stronger overall evaluation "
                    f"({top['technical']}/40 Technical, {top['hse']}/15 HSE, {top['icv']}/15 ICV), "
                    f"resulting in the higher overall score ({top['total']} vs {second['total']})."
                )

        outputs = {
            'supplier_ranking': ranked,
            'recommendation': recommendation,
            'trade_off_analysis': trade_off,
            'total_suppliers_evaluated': len(ranked),
            'human_review_required': human_review,
        }
        status = 'complete'
    except Exception as e:
        outputs = {'error': str(e)}
        status = 'error'

    log_agent('📝 Recommendation & Report', status, inputs, 'calculate_total_score()', outputs)
    outputs['_elapsed'] = round(time.time() - t0, 2)
    outputs['_status'] = status
    return outputs


# ═══════════════════════════════════════════════════════════════════════════════
#  FULL PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run_full_pipeline() -> dict:
    """Run the complete 8-agent pipeline and return all results."""
    clear_activity_log()

    results = {}

    # Agent 1: Evidence
    results['evidence'] = run_evidence_agent()
    if results['evidence'].get('_status') == 'error':
        return results

    # Agent 2: Compliance
    results['compliance'] = run_compliance_agent(results['evidence'])

    # Agents 3-6: Run in parallel (simulated sequential due to Python GIL)
    results['technical'] = run_technical_agent(results['compliance'])
    results['commercial'] = run_commercial_agent(results['compliance'])
    results['hse'] = run_hse_agent(results['compliance'])
    results['icv'] = run_icv_agent(results['compliance'])

    # Agent 7: Risk
    results['risk'] = run_risk_agent(
        results['technical'], results['commercial'],
        results['hse'], results['icv'],
    )

    # Agent 8: Recommendation
    results['recommendation'] = run_recommendation_agent(
        results['technical'], results['commercial'],
        results['hse'], results['icv'], results['risk'],
    )

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  SUPPLIER INFORMATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_suppliers() -> list:
    """Get all suppliers with their basic info."""
    return _get_supplier_list()


def search_supplier_by_name(name: str) -> Optional[dict]:
    """Find a supplier by company name or bid ref."""
    name_lower = name.lower()
    for s in _get_supplier_list():
        if name_lower in s.get('company', '').lower() or name_lower in s.get('bid_ref', '').lower():
            return s
    return None


def get_supplier_detail(bid_ref: str) -> Optional[dict]:
    """Get detailed info for a specific supplier."""
    facts = search._bid_facts.get(bid_ref)
    if not facts:
        return None
    tracker = search.get_tracker_entry(bid_ref)
    elig = search.get_eligibility(bid_ref)
    return {
        'facts': facts,
        'tracker': tracker,
        'eligibility': elig,
    }