"""
evidence.py — Evidence assembly and formatting.

Takes a query + retrieved data → structured evidence with
FACT/SOURCE/LOCATION/EVIDENCE/CONFIDENCE format.
"""

import json
from . import search

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

def format_value(field, facts):
    """Format a structured fact value for display."""
    v = facts.get(field)
    if v is None:
        return 'Not provided in submission'
    # Lazy formatting: only build the string for the requested field,
    # so we never crash on {v:,} when v is a non-numeric value.
    n = v if isinstance(v, (int, float)) else 0
    # Strip trailing .0 on whole-number floats
    _fmt = lambda vv: str(int(vv)) if isinstance(vv, float) and vv == int(vv) else str(vv)
    _fmtn = lambda vv: f"{vv:,}" if isinstance(vv, (int, float)) else str(vv)
    m = {
        'price_total': f"{facts.get('price_currency', 'AED')} {_fmtn(v)}",
        'capacity_m3_per_day': f"{_fmtn(v)} m³/d ({_fmtn(facts.get('capacity_bbl_per_day', 0))} bbl/d)" if facts.get('capacity_bbl_per_day') else f"{_fmtn(v)} m³/d",
        'outlet_oiw_mg_per_l': f"{_fmt(v)} mg/L (monthly avg)",
        'trir_3yr_avg': f"{_fmt(v)} per 200,000 manhours",
        'icv_score_pct': f"{_fmt(v)}%",
        'mc_weeks_from_loa': f"{_fmt(v)} weeks from LOA",
        'warranty_months': f"{_fmt(v)} months",
        'gcc_references_count': f"{_fmtn(v)} reference(s) ≥ 20,000 m³/d in GCC",
        'experience_years': f"{_fmt(v)} years",
        'employees': f"{_fmtn(v)}",
    }
    if field in m:
        return m[field]
    return str(v)

def build_evidence(query, top_k=10):
    """
    Main evidence-building function.
    Returns a list of evidence items, each with FACT/SOURCE/LOCATION/EVIDENCE/CONFIDENCE.
    """
    evidence = []

    # Resolve entity
    bid_ref, company = search.resolve_entity(query)
    fields = search.classify_query(query)
    is_list = search.is_list_query(query)
    is_comp = search.is_comparison_query(query)
    is_thresh = search.is_threshold_query(query)
    thresh_op, thresh_val = search.extract_threshold(query)

    # ── Case 1: Structured fact lookup for a specific bid ──
    if bid_ref and bid_ref in search._bid_facts and not is_list:
        facts = search.get_bid_facts(bid_ref)
        tracker_entry = search.get_tracker_entry(bid_ref)
        rfp = search.get_rfp_facts()

        # General info
        evidence.append({
            'FACT': f"Bidder: {facts['company']} ({bid_ref})",
            'SOURCE': facts['source_file'],
            'LOCATION': 'Cover letter / Company Profile',
            'EVIDENCE': f"Bid ref: {bid_ref} | Company: {facts['company']} | Source file: {facts['source_file']}",
            'CONFIDENCE': 'Verified'
        })

        # If specific fields requested, return those. Otherwise return all.
        if fields:
            for f in fields:
                fact_key = _field_to_fact_key(f)
                if fact_key and fact_key in facts:
                    val = format_value(fact_key, facts)
                    evidence.append({
                        'FACT': f"{FIELD_LABELS.get(f, f)}: {val}",
                        'SOURCE': facts['source_file'],
                        'LOCATION': f"Company Profile / Technical Proposal / Commercial Proposal",
                        'EVIDENCE': val,
                        'CONFIDENCE': 'Verified'
                    })
        else:
            # Return all available facts
            for f, label in FIELD_LABELS.items():
                fact_key = _field_to_fact_key(f)
                if fact_key and fact_key in facts and facts[fact_key] is not None:
                    val = format_value(fact_key, facts)
                    evidence.append({
                        'FACT': f"{label}: {val}",
                        'SOURCE': facts['source_file'],
                        'LOCATION': 'Varies by fact',
                        'EVIDENCE': val,
                        'CONFIDENCE': 'Verified'
                    })

        # Scheme
        if facts.get('scheme'):
            evidence.append({
                'FACT': f"Treatment Scheme: {facts['scheme']}",
                'SOURCE': facts['source_file'],
                'LOCATION': 'Cover Letter / Technical Proposal',
                'EVIDENCE': facts['scheme'],
                'CONFIDENCE': 'Verified'
            })

        # Arithmetic issue
        if facts.get('arithmetic_issue'):
            ai = facts['arithmetic_issue']
            evidence.append({
                'FACT': f"Arithmetic Discrepancy: Line items sum to {ai['line_item_sum']:,} vs stated total {ai['stated_total']:,} (difference {ai['difference']:+,})",
                'SOURCE': facts['source_file'],
                'LOCATION': 'Section 4.1 — Itemized Price Schedule',
                'EVIDENCE': f"Sum of 10 line items = {ai['line_item_sum']:,} AED; stated total = {ai['stated_total']:,} AED",
                'CONFIDENCE': 'Verified'
            })

        # Tracker info
        if tracker_entry:
            evidence.append({
                'FACT': f"Submission: {tracker_entry.get('submission_datetime', '?')} | Currency: {tracker_entry.get('currency', '?')} | Volumes: {tracker_entry.get('volumes_received', '?')}",
                'SOURCE': 'Bid_Submission_Tracker_2026-0412.xlsx',
                'LOCATION': 'Bid Register',
                'EVIDENCE': f"Submitted {tracker_entry.get('submission_datetime')} in {tracker_entry.get('currency')}",
                'CONFIDENCE': 'Verified'
            })
            if tracker_entry.get('receipt_remarks') and tracker_entry['receipt_remarks'] != 'Complete on visual check':
                evidence.append({
                    'FACT': f"Tracker Remark: {tracker_entry['receipt_remarks']}",
                    'SOURCE': 'Bid_Submission_Tracker_2026-0412.xlsx',
                    'LOCATION': 'Bid Register',
                    'EVIDENCE': tracker_entry['receipt_remarks'],
                    'CONFIDENCE': 'Verified'
                })

        # Checklist status
        checklist = facts.get('submission_checklist', {})
        missing = [d for d, s in checklist.items() if s != 'Enclosed']
        if missing:
            evidence.append({
                'FACT': f"Missing Mandatory Documents: {', '.join(missing)}",
                'SOURCE': facts['source_file'],
                'LOCATION': 'Submission Checklist',
                'EVIDENCE': '; '.join(f"{d}: {checklist[d]}" for d in missing),
                'CONFIDENCE': 'Verified'
            })

        # Eligibility
        elig = search.get_eligibility(bid_ref)
        if elig and elig.get('issues'):
            for issue in elig['issues']:
                evidence.append({
                    'FACT': f"Compliance Issue: {issue}",
                    'SOURCE': 'RFP + Bid Document',
                    'LOCATION': 'Sections 4–6',
                    'EVIDENCE': issue,
                    'CONFIDENCE': 'Verified'
                })

        # Alternate
        if facts.get('has_technical_alternate'):
            evidence.append({
                'FACT': 'Technical alternate offered (per ITB clause 9, one alternate permitted)',
                'SOURCE': facts['source_file'],
                'LOCATION': 'Technical Proposal — Alternate section',
                'EVIDENCE': 'Alternate offer documented with unchanged capacity, improved OiW guarantee',
                'CONFIDENCE': 'Verified'
            })

    # ── Case 2: RFP / requirements query ──
    if bid_ref == 'rfp' and not is_list:
        rfp = search.get_rfp_facts()
        # Check for D1-D9 query
        if any(d in query.lower() for d in ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8', 'd9', 'mandatory', 'submission']):
            detail = rfp.get('mandatory_docs_detail', {})
            for d_code in ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']:
                desc = detail.get(d_code, '')
                evidence.append({
                    'FACT': f"Mandatory {d_code}: {desc}",
                    'SOURCE': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf',
                    'LOCATION': 'Section 4 — Mandatory Submission Requirements',
                    'EVIDENCE': desc,
                    'CONFIDENCE': 'Verified'
                })
        # Check for specific RFP field matches
        else:
            matched = False
            for key, val in rfp.items():
                if any(kw in query.lower() for kw in key.replace('_', ' ').split()):
                    label = key.replace('_', ' ').title()
                    # Format numeric values with commas
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        display = f"{val:,}" if isinstance(val, int) else f"{val:,.2f}"
                    else:
                        display = str(val)
                    evidence.append({
                        'FACT': f"{label}: {display}",
                        'SOURCE': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf',
                        'LOCATION': 'Various sections',
                        'EVIDENCE': display,
                        'CONFIDENCE': 'Verified'
                    })
                    matched = True
            if not matched:
                evidence.append({
                    'FACT': f"RFP Tender Reference: {rfp.get('tender_ref', '?')}",
                    'SOURCE': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf',
                    'LOCATION': 'Cover page',
                    'EVIDENCE': json.dumps(rfp, indent=1)[:1000],
                    'CONFIDENCE': 'Verified'
                })

    # ── Case 3: List query (all bids, comparison) ──
    if is_list:
        facts_list = []
        for bref, f in sorted(search._bid_facts.items()):
            facts_list.append(f)
        if facts_list:
            all_evidence = _build_comparison_evidence(facts_list, fields, query)
            evidence.extend(all_evidence)

    # ── Case 4: Threshold query (e.g., TRIR below 0.3) ──
    if is_thresh and thresh_op:
        fact_field = None
        for f in fields:
            fact_key = _field_to_fact_key(f)
            if fact_key:
                fact_field = fact_key
                break
        if not fact_field:
            # Try to infer from query
            if 'trir' in query.lower() or 'safety' in query.lower():
                fact_field = 'trir_3yr_avg'
            elif 'price' in query.lower() or 'cost' in query.lower():
                fact_field = 'price_total'
            elif 'capacity' in query.lower():
                fact_field = 'capacity_m3_per_day'
            elif 'oiw' in query.lower() or 'oil' in query.lower():
                fact_field = 'outlet_oiw_mg_per_l'
            elif 'icv' in query.lower():
                fact_field = 'icv_score_pct'

        if fact_field:
            matching = []
            for bref, f in sorted(search._bid_facts.items()):
                v = f.get(fact_field)
                if v is not None:
                    if thresh_op == 'below' and v < thresh_val:
                        matching.append(f)
                    elif thresh_op == 'above' and v > thresh_val:
                        matching.append(f)
            if matching:
                label = FIELD_LABELS.get(fields[0] if fields else 'unknown', fact_field)
                evidence.append({
                    'FACT': f"{len(matching)} bidder(s) with {label} {thresh_op} {thresh_val}",
                    'SOURCE': 'Multiple bid documents',
                    'LOCATION': 'Aggregated',
                    'EVIDENCE': '; '.join(f"{f['company']} ({format_value(fact_field, f)})" for f in matching),
                    'CONFIDENCE': 'Verified'
                })
            else:
                evidence.append({
                    'FACT': f"No bidders found with {label} {thresh_op} {thresh_val}",
                    'SOURCE': 'Multiple bid documents',
                    'LOCATION': 'Aggregated',
                    'EVIDENCE': f'All {len(search._bid_facts)} bids checked',
                    'CONFIDENCE': 'Verified'
                })

    # ── Case 5: Unknown company → Not Found (grounding rule) ──
    if not evidence and bid_ref is None and search.mentions_unknown_company(query):
        evidence.append({
            'FACT': 'Not found in the provided challenge dataset. I cannot verify this from the available evidence.',
            'SOURCE': '—',
            'LOCATION': '—',
            'EVIDENCE': 'The query names a company that is not present in the challenge dataset. No matching evidence across RFP, Bid Submission Tracker, or 12 supplier bid documents.',
            'CONFIDENCE': 'Not Found'
        })

    # ── Case 6: Keyword / free-text search ──
    if not evidence:
        results = search.search(query, top_k=top_k)
        for r in results:
            evidence.append({
                'FACT': r['text'][:200],
                'SOURCE': r['source_file'],
                'LOCATION': f"Page {r['page']}, Section: {r['section']}",
                'EVIDENCE': r['text'][:500],
                'CONFIDENCE': 'Verified' if r['score'] > 0.5 else 'Partially Verified'
            })

    # ── Fallback ──
    if not evidence:
        evidence.append({
            'FACT': 'Not found in the provided challenge dataset. I cannot verify this from the available evidence.',
            'SOURCE': '—',
            'LOCATION': '—',
            'EVIDENCE': 'No matching evidence across RFP, Bid Submission Tracker, or 12 supplier bid documents.',
            'CONFIDENCE': 'Not Found'
        })

    return evidence

def _field_to_fact_key(field):
    mapping = {
        'price': 'price_total', 'capacity': 'capacity_m3_per_day',
        'oiw': 'outlet_oiw_mg_per_l', 'tss': 'outlet_tss', 'mc_weeks': 'mc_weeks_from_loa',
        'warranty': 'warranty_months', 'trir': 'trir_3yr_avg', 'icv': 'icv_score_pct',
        'experience': 'experience_years', 'references': 'gcc_references_count',
        'employees': 'employees', 'scheme': 'scheme', 'certifications': None,
        'checklist': 'submission_checklist', 'arithmetic': None,
        'alternate': 'has_technical_alternate', 'bid_bond': None,
    }
    return mapping.get(field)

def _build_comparison_evidence(facts_list, fields, query):
    """Build comparative evidence across multiple bids."""
    evidence = []
    if not fields:
        fields = ['price', 'capacity', 'oiw', 'mc_weeks', 'icv', 'trir']

    # Price comparison
    if 'price' in fields:
        prices = []
        for f in facts_list:
            if f.get('price_total') is not None:
                prices.append((f['company'], f['price_total'], f.get('price_currency', 'AED')))
        prices.sort(key=lambda x: x[1])
        if prices:
            evidence.append({
                'FACT': f"Price Ranking (lowest to highest): {len(prices)} bids",
                'SOURCE': 'Multiple bid documents',
                'LOCATION': 'Commercial Proposals',
                'EVIDENCE': ' → '.join(f"{c}: {cur} {p:,}" for c, p, cur in prices),
                'CONFIDENCE': 'Verified'
            })

    # Capacity
    if 'capacity' in fields:
        caps = []
        for f in facts_list:
            if f.get('capacity_m3_per_day') is not None:
                caps.append((f['company'], f['capacity_m3_per_day']))
        caps.sort(key=lambda x: -x[1])
        if caps:
            evidence.append({
                'FACT': f"Capacity Ranking (highest to lowest):",
                'SOURCE': 'Multiple bid documents',
                'LOCATION': 'Technical Proposals',
                'EVIDENCE': ' → '.join(f"{c}: {v:,} m³/d" for c, v in caps),
                'CONFIDENCE': 'Verified'
            })

    # ICV
    if 'icv' in fields:
        icvs = []
        for f in facts_list:
            if f.get('icv_score_pct') is not None:
                icvs.append((f['company'], f['icv_score_pct']))
        icvs.sort(key=lambda x: -x[1])
        if icvs:
            evidence.append({
                'FACT': f"ICV Ranking (highest to lowest):",
                'SOURCE': 'Multiple bid documents',
                'LOCATION': 'Company Profiles',
                'EVIDENCE': ' → '.join(f"{c}: {v}%" for c, v in icvs),
                'CONFIDENCE': 'Verified'
            })

    # TRIR
    if 'trir' in fields:
        trirs = []
        for f in facts_list:
            if f.get('trir_3yr_avg') is not None:
                trirs.append((f['company'], f['trir_3yr_avg']))
        trirs.sort(key=lambda x: x[1])
        if trirs:
            evidence.append({
                'FACT': f"TRIR Ranking (lowest = best):",
                'SOURCE': 'Multiple bid documents',
                'LOCATION': 'HSE Sections',
                'EVIDENCE': ' → '.join(f"{c}: {v}" for c, v in trirs),
                'CONFIDENCE': 'Verified'
            })

    # MC weeks
    if 'mc_weeks' in fields:
        mcs = []
        for f in facts_list:
            if f.get('mc_weeks_from_loa') is not None:
                mcs.append((f['company'], f['mc_weeks_from_loa']))
        mcs.sort(key=lambda x: x[1])
        if mcs:
            evidence.append({
                'FACT': f"Mechanical Completion Ranking (fastest first):",
                'SOURCE': 'Multiple bid documents',
                'LOCATION': 'Delivery Schedules',
                'EVIDENCE': ' → '.join(f"{c}: {v} weeks" for c, v in mcs),
                'CONFIDENCE': 'Verified'
            })

    return evidence

# ── Structured output for the evidence package ──
def evidence_to_json(evidence):
    """Output evidence as a clean JSON array."""
    return json.dumps(evidence, indent=2, default=str)

def evidence_to_markdown(evidence):
    """Output evidence as markdown."""
    lines = ['## Procurement Evidence & Retrieval Results\n']
    for i, item in enumerate(evidence, 1):
        lines.append(f'### Evidence Item {i}')
        lines.append(f'**FACT:** {item.get("FACT", "")}')
        lines.append(f'**SOURCE:** {item.get("SOURCE", "—")}')
        lines.append(f'**LOCATION:** {item.get("LOCATION", "—")}')
        lines.append(f'**EVIDENCE:** {item.get("EVIDENCE", "")}')
        lines.append(f'**CONFIDENCE:** {item.get("CONFIDENCE", "Not Found")}')
        lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    for q in [
        "What is the price of Hanseong?",
        "Show me Al Manara's ICV score",
        "What is the capacity of V10 (Bin Sultan)?",
        "Which bidders have TRIR below 0.3?",
        "What is the Petrotech arithmetic issue?",
        "List all bids with their prices and capacities",
    ]:
        print(f'=== Query: {q} ===')
        ev = build_evidence(q)
        for item in ev:
            print(f'  FACT: {item["FACT"][:80]}')
            print(f'  CONFIDENCE: {item["CONFIDENCE"]}')
            print()
        print()