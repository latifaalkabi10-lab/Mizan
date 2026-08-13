"""
package.py — Downstream evidence package for the Bid Evaluation Agent.

Produces a structured JSON payload that another agent can consume programmatically.
"""

import json
from . import search, evidence as ev

def build_evidence_package(query):
    """
    Build a structured evidence package consumable by the downstream Bid Evaluation Agent.

    Returns:
      dict with keys:
        tender_ref: str
        query: str
        timestamp: str
        suppliers: list of supplier evidence dicts
        rfp_reference: dict of RFP facts
        tracker_notes: list of tracker entries
        cross_bid_comparisons: list of cross-cutting comparisons
        confidence_summary: dict
        raw_evidence: list of evidence items
    """
    # Get raw evidence
    evidence_items = ev.build_evidence(query)
    bid_ref, company = search.resolve_entity(query)
    fields = search.classify_query(query)
    is_list = search.is_list_query(query)

    rfp = search.get_rfp_facts()
    tracker = search.get_tracker_entries()

    # Build supplier evidence
    suppliers = []
    if bid_ref and bid_ref in search._bid_facts and not is_list:
        facts = search._bid_facts[bid_ref]
        suppliers.append(_build_supplier_entry(bid_ref, facts, search.get_tracker_entry(bid_ref)))

    # Cross-bid comparisons
    comparisons = []
    if is_list or not evidence_items:
        if fields:
            cross = _build_cross_comparisons(search._bid_facts, fields)
            comparisons.extend(cross)

    # Confidence summary
    confidence_counts = {}
    for item in evidence_items:
        c = item.get('CONFIDENCE', 'Unknown')
        confidence_counts[c] = confidence_counts.get(c, 0) + 1

    package = {
        'tender_ref': 'ADNOC-LCIG/RFP/2026-0412',
        'query': query,
        'timestamp': __import__('datetime').datetime.now().isoformat(),
        'suppliers': suppliers,
        'rfp_reference': {
            'tender_ref': rfp.get('tender_ref'),
            'title': rfp.get('title'),
            'bid_deadline': rfp.get('bid_deadline'),
            'evaluation_weights': {
                'technical': {'weight': 40, 'sub_criteria': {
                    'T1': {'label': 'Process capacity & performance guarantee', 'weight': 15},
                    'T2': {'label': 'Technology track record (GCC)', 'weight': 10},
                    'T3': {'label': 'Company experience & organisation', 'weight': 8},
                    'T4': {'label': 'Delivery schedule', 'weight': 7},
                }},
                'commercial': {'weight': 30, 'formula': 'C = 30 × (Plow / Pbid)'},
                'hse': {'weight': 15, 'sub_criteria': {
                    'H1': {'label': 'Safety performance (3-yr TRIR)', 'weight': 9},
                    'H2': {'label': 'HSE management certification', 'weight': 6},
                }},
                'icv': {'weight': 15, 'formula': 'ICV = 15 × min(ICV%, 60) / 60'},
            },
            'mandatory_docs': rfp.get('mandatory_docs', ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']),
            'min_capacity_m3_per_day': rfp.get('min_capacity_m3_per_day'),
            'max_outlet_oiw_mg_per_l': rfp.get('min_outlet_oiw_mg_per_l'),
        },
        'tracker_notes': [
            {
                'bid_ref': e.get('bid_ref'),
                'company': e.get('company'),
                'submission_datetime': e.get('submission_datetime'),
                'currency': e.get('currency'),
                'receipt_remarks': e.get('receipt_remarks'),
            }
            for e in tracker if e.get('receipt_remarks') and e['receipt_remarks'] != 'Complete on visual check'
        ],
        'cross_bid_comparisons': comparisons,
        'confidence_summary': confidence_counts,
        'raw_evidence': evidence_items,
    }

    return package


def _build_supplier_entry(bid_ref, facts, tracker_entry):
    """Build a single supplier entry with all evidence for the downstream agent."""
    entry = {
        'bid_ref': bid_ref,
        'company': facts.get('company'),
        'source_file': facts.get('source_file'),
        'file_vnum': facts.get('file_vnum'),
        'technical': {
            'scheme': facts.get('scheme'),
            'capacity_m3_per_day': facts.get('capacity_m3_per_day'),
            'capacity_source': 'Technical Proposal — Design & Performance Summary',
            'outlet_oiw_mg_per_l': facts.get('outlet_oiw_mg_per_l'),
            'oiw_source': 'Technical Proposal — Design & Performance Summary',
            'oiw_cover_letter': facts.get('outlet_oiw_cover_letter'),
            'gcc_references_count': facts.get('gcc_references_count'),
            'gcc_references_source': 'Project References section',
            'experience_years': facts.get('experience_years'),
            'experience_source': 'Company Profile',
            'mc_weeks_from_loa': facts.get('mc_weeks_from_loa'),
            'mc_source': 'Delivery Schedule',
            'warranty_months': facts.get('warranty_months'),
            'warranty_source': 'Commercial Proposal / Cover Letter',
            'has_technical_alternate': facts.get('has_technical_alternate', False),
            'alternate_details': 'Alternate offers 2 mg/L OiW (base: 3 mg/L) — Aquapure only' if facts.get('has_technical_alternate') else None,
        },
        'commercial': {
            'price_total': facts.get('price_total'),
            'price_currency': facts.get('price_currency'),
            'price_source': 'Commercial Proposal — Itemized Price Schedule',
            'line_items': facts.get('line_items'),
            'line_item_sum': facts.get('line_item_sum'),
            'arithmetic_issue': facts.get('arithmetic_issue'),
            'payment_terms': 'Per RFP Section 7 (10/60/20/10)',
        },
        'hse': {
            'trir_3yr_avg': facts.get('trir_3yr_avg'),
            'trir_source': 'HSE & Quality section',
            'fatalities_3yr': facts.get('fatalities_3yr'),
            'has_iso_14001': facts.get('has_iso_14001'),
            'has_iso_45001': facts.get('has_iso_45001'),
            'hse_cert_source': 'Company Profile — Certifications',
        },
        'icv': {
            'icv_score_pct': facts.get('icv_score_pct'),
            'icv_cert_no': facts.get('icv_cert_no'),
            'icv_source': 'Company Profile — ICV Certificate',
            'icv_cert_status': 'Enclosed' if facts.get('icv_score_pct') is not None else 'Not found in submission',
        },
        'submission_checklist': facts.get('submission_checklist', {}),
        'tracker_info': {
            'submission_datetime': tracker_entry.get('submission_datetime') if tracker_entry else None,
            'currency': tracker_entry.get('currency') if tracker_entry else None,
            'volumes_received': tracker_entry.get('volumes_received') if tracker_entry else None,
            'receipt_remarks': tracker_entry.get('receipt_remarks') if tracker_entry else None,
        },
        'eligibility_issues': search.get_eligibility(bid_ref).get('issues', []) if search.get_eligibility(bid_ref) else [],
    }
    return entry


def _build_cross_comparisons(bid_facts, fields):
    """Build cross-bid comparison tables for the downstream agent."""
    comparisons = []

    # Price comparison
    if 'price' in fields:
        prices = [(bref, f['company'], f['price_total'], f.get('price_currency', 'AED'))
                  for bref, f in bid_facts.items() if f.get('price_total') is not None]
        prices.sort(key=lambda x: x[2])
        comparisons.append({
            'type': 'price_comparison',
            'label': 'Total Bid Price (lowest to highest)',
            'data': [{'bid_ref': bref, 'company': c, 'price': p, 'currency': cur} for bref, c, p, cur in prices],
            'lowest': prices[0][3] if prices else None,
            'highest': prices[-1][3] if prices else None,
        })

    # Capacity comparison
    if 'capacity' in fields:
        caps = [(bref, f['company'], f['capacity_m3_per_day'])
                for bref, f in bid_facts.items() if f.get('capacity_m3_per_day') is not None]
        caps.sort(key=lambda x: -x[2])
        comparisons.append({
            'type': 'capacity_comparison',
            'label': 'Treatment Capacity (highest to lowest)',
            'data': [{'bid_ref': bref, 'company': c, 'capacity_m3_per_day': cap} for bref, c, cap in caps],
        })

    # ICV comparison
    if 'icv' in fields:
        icvs = [(bref, f['company'], f['icv_score_pct'])
                for bref, f in bid_facts.items() if f.get('icv_score_pct') is not None]
        icvs.sort(key=lambda x: -x[2])
        comparisons.append({
            'type': 'icv_comparison',
            'label': 'ICV Score (highest to lowest)',
            'data': [{'bid_ref': bref, 'company': c, 'icv_score_pct': v} for bref, c, v in icvs],
        })

    # TRIR comparison (lower is better)
    if 'trir' in fields:
        trirs = [(bref, f['company'], f['trir_3yr_avg'])
                 for bref, f in bid_facts.items() if f.get('trir_3yr_avg') is not None]
        trirs.sort(key=lambda x: x[2])
        comparisons.append({
            'type': 'trir_comparison',
            'label': 'TRIR (lowest = best)',
            'data': [{'bid_ref': bref, 'company': c, 'trir': v} for bref, c, v in trirs],
        })

    # MC weeks (lower is better)
    if 'mc_weeks' in fields:
        mcs = [(bref, f['company'], f['mc_weeks_from_loa'])
               for bref, f in bid_facts.items() if f.get('mc_weeks_from_loa') is not None]
        mcs.sort(key=lambda x: x[2])
        comparisons.append({
            'type': 'schedule_comparison',
            'label': 'Mechanical Completion (fastest first)',
            'data': [{'bid_ref': bref, 'company': c, 'mc_weeks_from_loa': w} for bref, c, w in mcs],
        })

    return comparisons


def save_package(query, path=None):
    """Build, save, and return the evidence package."""
    package = build_evidence_package(query)
    if path is None:
        path = f"/home/event/Desktop/Evidence Agent/evidence_packages/evidence_package_{__import__('hashlib').md5(query.encode()).hexdigest()[:8]}.json"
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(package, f, indent=2, default=str)
    return path, package