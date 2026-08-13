"""
ingest.py — Parse all challenge documents into a structured corpus + fact database.

Sources:
  - RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf  (8 pages)
  - Bid_Submission_Tracker_2026-0412.xlsx                   (Bid Register)
  - Bid_V01_…V12_*.pdf                                       (12 supplier bids)

Output:
  corpus: list of dicts: {doc_id, page, section, text, source_file}
  facts:  dict keyed by bid_ref or 'rfp' or 'tracker', with structured fields
  aliases: dict mapping company_name -> bid_ref
"""

import os, re, json, glob, subprocess, math, unicodedata

RAW_DIR = os.path.join(os.path.dirname(__file__) or '.', '..', 'raw')
DATA_DIR = os.path.join(os.path.dirname(__file__) or '.', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# ── Bid-Ref ↔ Company Name mapping (from Tracker) ──────────────────────────
BID_REF_MAP = {
    "BID-2026-0412-01": "Bin Sultan Heavy Industries LLC",
    "BID-2026-0412-02": "Aquapure Gulf Technologies FZ-LLC",
    "BID-2026-0412-03": "Rheinwasser Technik GmbH",
    "BID-2026-0412-04": "Al Manara Process Solutions LLC",
    "BID-2026-0412-05": "Qasr Al Bahr Marine & Process LLC",
    "BID-2026-0412-06": "Hanseong Water & Energy Co., Ltd.",
    "BID-2026-0412-07": "Gulfstream Engineering & Contracting WLL",
    "BID-2026-0412-08": "Levant Energy Solutions SAL (UAE Branch)",
    "BID-2026-0412-09": "Petrotech Arabia Ltd.",
    "BID-2026-0412-10": "Emirates Flowline Systems FZE",
    "BID-2026-0412-11": "Nakheel Oilfield Supplies & Services LLC",
    "BID-2026-0412-12": "Al Dhafra Industrial Services Co.",
}

# Reverse: short name -> bid_ref
COMPANY_ALIASES = {}
for ref, name in BID_REF_MAP.items():
    # Register full name
    COMPANY_ALIASES[name.lower()] = ref
    # Register the short / common name (before first comma / "LLC" / "Ltd" etc.)
    short = re.split(r'\s+(?:LLC|Ltd|Co\.|Co\b|SAL|FZE|WLL|FZ-LLC)\b', name, maxsplit=1)[0].strip()
    COMPANY_ALIASES[short.lower()] = ref
    # Register the main word (e.g. "Hanseong", "Bin Sultan", "Petrotech")
    for word in short.split():
        if len(word) > 3 and word[0].isupper():
            COMPANY_ALIASES[word.lower()] = ref

# File V-prefix -> company name (from filenames)
FILE_V_MAP = {}
for fp in sorted(glob.glob(os.path.join(RAW_DIR, 'Bid_V*.txt'))):
    basename = os.path.basename(fp)
    m = re.match(r'Bid_V(\d+)_(.+)\.txt', basename)
    if m:
        vnum = int(m.group(1))
        name = m.group(2).replace('_', ' ')
        FILE_V_MAP[vnum] = name

# Map file V-number to bid ref using token-overlap (Jaccard-like) matching.
# Filenames use 'and' where tracker uses '&', and punctuation differs, so we
# normalize both sides and compare token sets.
def _norm_name(s):
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    return set(w for w in s.split() if len(w) > 1)

def _best_bid_ref(name_tokens, candidates):
    """Return bid_ref with highest token overlap, if meaningful."""
    best_ref, best_score = None, 0.0
    for nref, nname in BID_REF_MAP.items():
        nt = _norm_name(nname)
        if not nt:
            continue
        inter = len(name_tokens & nt)
        score = inter / len(nt)  # fraction of the tracker name covered
        if score > best_score:
            best_ref, best_score = nref, score
    return best_ref if best_score >= 0.5 else None

FILE_V_TO_BID_REF = {}
for v, name in FILE_V_MAP.items():
    tokens = _norm_name(name)
    bref = _best_bid_ref(tokens, BID_REF_MAP)
    if bref:
        FILE_V_TO_BID_REF[v] = bref
    else:
        # fall back to V-prefix naming
        FILE_V_TO_BID_REF[v] = f"BID-V{v:02d}"

# Also register V-aliases like "V01", "V1", "Bid V01"
for v, bref in FILE_V_TO_BID_REF.items():
    COMPANY_ALIASES[f"v{v:02d}"] = bref
    COMPANY_ALIASES[f"v{v}"] = bref
    COMPANY_ALIASES[f"bid v{v:02d}"] = bref

def normalize_text(text):
    """Normalize whitespace, unicode, case."""
    text = unicodedata.normalize('NFKD', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_rfp(path):
    """Parse RFP text into chunks with page/section metadata."""
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    pages = []
    current_page = 1
    lines = text.split('\n')
    page_lines = []
    for line in lines:
        if '\f' in line:
            # page break
            before, after = line.split('\f', 1)
            if before.strip():
                page_lines.append(before)
            pages.append((current_page, '\n'.join(page_lines)))
            page_lines = []
            current_page += 1
            if after.strip():
                page_lines.append(after)
        else:
            page_lines.append(line)
    if page_lines:
        pages.append((current_page, '\n'.join(page_lines)))

    # Section detection
    section_pattern = re.compile(r'^(\d+(?:\.\d+)?)\s+(.*)')
    chunks = []
    for pg, content in pages:
        # split into sections
        lines = content.split('\n')
        current_section = "Cover / Header"
        sec_buf = []
        for line in lines:
            line_s = line.strip()
            m = section_pattern.match(line_s)
            if m and len(line_s) < 100:
                # flush previous section
                if sec_buf:
                    chunks.append({
                        'doc_id': 'rfp',
                        'page': pg,
                        'section': current_section,
                        'text': normalize_text('\n'.join(sec_buf)),
                        'source_file': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf'
                    })
                current_section = line_s
                sec_buf = [line_s]
            else:
                sec_buf.append(line_s)
        if sec_buf:
            chunks.append({
                'doc_id': 'rfp',
                'page': pg,
                'section': current_section,
                'text': normalize_text('\n'.join(sec_buf)),
                'source_file': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf'
            })
    return chunks

def extract_tracker(path):
    """Parse Bid Submission Tracker JSON into structured facts."""
    with open(path) as f:
        data = json.load(f)
    register = data.get('Bid Register', [])
    # rows 0-3 are headers, row 4 is column header, rows 5+ are data
    headers = register[4] if len(register) > 4 else []
    rows = register[5:] if len(register) > 5 else []
    facts = {'entries': []}
    for row in rows:
        if not row or not row[0]:
            continue
        entry = {
            'bid_ref': row[0] if len(row) > 0 else None,
            'company': row[1] if len(row) > 1 else None,
            'country': row[2] if len(row) > 2 else None,
            'city': row[3] if len(row) > 3 else None,
            'contact_name': row[4] if len(row) > 4 else None,
            'contact_email': row[5] if len(row) > 5 else None,
            'phone': row[6] if len(row) > 6 else None,
            'submission_datetime': row[7] if len(row) > 7 else None,
            'currency': row[8] if len(row) > 8 else None,
            'volumes_received': row[9] if len(row) > 9 else None,
            'receipt_remarks': row[10] if len(row) > 10 else None,
        }
        facts['entries'].append(entry)
    # Build tracker corpus chunks
    chunks = []
    chunks.append({
        'doc_id': 'tracker',
        'page': 1, 'section': 'README',
        'text': '\n'.join([r[0] for r in data.get('README', []) if r and r[0]]),
        'source_file': 'Bid_Submission_Tracker_2026-0412.xlsx'
    })
    for entry in facts['entries']:
        chunks.append({
            'doc_id': f"tracker-{entry['bid_ref']}" if entry['bid_ref'] else 'tracker',
            'page': 1, 'section': 'Bid Register',
            'text': json.dumps(entry, indent=1),
            'source_file': 'Bid_Submission_Tracker_2026-0412.xlsx'
        })
    return chunks, facts

def parse_itemized_prices(text):
    """Extract itemized price lines from a bid's commercial section."""
    items = []
    # Find the commercial section
    m = re.search(r'Itemized price schedule.*?(?=4\.2|Commercial conditions)', text, re.DOTALL)
    if not m:
        m = re.search(r'Itemized price schedule.*?(?=\n\n\n)', text, re.DOTALL)
    if m:
        seg = m.group(0)
        # Match lines like: "1    Produced water treatment ...   17,474,000"
        for line in seg.split('\n'):
            line_stripped = line.strip()
            # Skip header lines and empty lines
            if not line_stripped or line_stripped.startswith('#') or 'Description' in line_stripped or 'Amount' in line_stripped:
                continue
            m2 = re.match(r'^\s*(\d+)\s+(.*?)\s+([\d,]{5,})\s*$', line)
            if m2:
                items.append({
                    'item': int(m2.group(1)),
                    'description': m2.group(2).strip(),
                    'amount': int(m2.group(3).replace(',', ''))
                })
    return items

def extract_bid(path, vnum, bid_ref, company_name):
    """Parse a single bid document into structured facts + chunks."""
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()

    # Normalize line endings
    text = text.replace('\r\n', '\n')

    # ── Cover letter extraction ──
    scheme = ""
    m = re.search(r'based on\s+([^.]+?)\s*,\s*rated at a net treatment capacity', text)
    if m:
        scheme = m.group(1).strip()

    # ── Capacity ──
    capacity_m3 = None
    capacity_bbl = None
    m = re.search(r'Net treatment capacity\s*\(continuous\)\s*([\d,]+)\s*m³/d', text)
    if m:
        capacity_m3 = int(m.group(1).replace(',', ''))
    m = re.search(r'Net treatment capacity\s*\(continuous\)\s*([\d,]+)\s*bbl/d', text)
    if m:
        capacity_bbl = int(m.group(1).replace(',', ''))
        # convert to m³ for reference
        capacity_m3 = round(capacity_bbl * 0.158987)

    # ── Outlet OiW ──
    oiw = None
    # Pattern A: terse one-line: "Guaranteed outlet oil-in-water (monthly avg)      12 mg/L"
    m = re.search(r'Guaranteed outlet oil-in-water\s*\(monthly\s*avg\)\s*([\d.]+)\s*mg/L', text)
    if m:
        oiw = float(m.group(1))
    # Pattern B: value wrapped to next line: "Guaranteed outlet oil-in-water (monthly\n  avg)\n  5 mg/L"
    if not m:
        m = re.search(r'Guaranteed outlet oil-in-water\s*\(monthly\s*\n\s*avg\)\s*\n\s*([\d.]+)\s*mg/L', text)
        if m:
            oiw = float(m.group(1))
    # Pattern C: value sandwiched: "Guaranteed outlet oil-in-water (monthly\n  5 mg/L\n  avg)"
    if not m:
        m = re.search(r'Guaranteed outlet oil-in-water\s*\(monthly\s*\n\s*([\d.]+)\s*mg/L\s*\n\s*avg\)', text)
        if m:
            oiw = float(m.group(1))
    # Pattern D: "Guaranteed outlet oil-in-water\n  5 mg/L\n  (monthly avg)"
    if not m:
        m = re.search(r'Guaranteed outlet oil-in-water\s*\n\s*([\d.]+)\s*mg/L\s*\n\s*\(monthly\s*avg\)', text)
        if m:
            oiw = float(m.group(1))

    # Also from cover letter
    oiw_cover = None
    m = re.search(r'guaranteed outlet oil-in-water content of\s*([\d.]+)\s*mg/L', text)
    if m:
        oiw_cover = float(m.group(1))

    # ── Price ──
    price_currency = "AED"
    price_total = None
    m = re.search(r'TOTAL LUMP-SUM PRICE\s*\(([A-Z]+)\)\s+([\d,]+)', text)
    if m:
        price_currency = m.group(1)
        price_total = int(m.group(2).replace(',', ''))

    # ── Line items ──
    line_items = parse_itemized_prices(text)
    line_sum = sum(item['amount'] for item in line_items) if line_items else None
    arithmetic_issue = None
    if line_sum and price_total and line_sum != price_total:
        arithmetic_issue = {
            'line_item_sum': line_sum,
            'stated_total': price_total,
            'difference': line_sum - price_total,
            'governing_per_itb': line_sum  # ITB clause 6: corrected sum governs
        }

    # ── Mechanical Completion ──
    mc_weeks = None
    m = re.search(r'Mechanical completion is offered\s*([\d]+)\s*weeks', text)
    if m:
        mc_weeks = int(m.group(1))

    # ── Warranty ──
    warranty_months = None
    m = re.search(r'warranty period of\s*([\d]+)\s*months', text)
    if m:
        warranty_months = int(m.group(1))

    # ── Track Record ──
    gcc_references = None
    m = re.search(r'(\d+)\s+installed reference', text)
    if m:
        gcc_references = int(m.group(1))

    # ── Experience ──
    experience_years = None
    m = re.search(r'(\d+)\s+years of continuous experience', text)
    if m:
        experience_years = int(m.group(1))

    # ── Employees ──
    employees = None
    m = re.search(r'employs\s*([\d,]+)\s*personnel', text)
    if m:
        employees = int(m.group(1).replace(',', ''))

    # ── Year established ──
    year_est = None
    m = re.search(r'established in\s*(\d{4})', text)
    if m:
        year_est = int(m.group(1))

    # ── TRIR ──
    trir = None
    m = re.search(r'Three-year average\s*TRIR:\s*([\d.]+)\s*per', text)
    if m:
        trir = float(m.group(1))

    # ── Fatalities ──
    fatalities = None
    m = re.search(r'No work-related fatalities', text)
    if m:
        fatalities = 0
    else:
        m = re.search(r'(\d+)\s+work-related fatalities?', text)
        if m:
            fatalities = int(m.group(1))

    # ── ICV ──
    icv_score = None
    icv_cert_no = None
    m = re.search(r'Certified score\s*([\d.]+)%\s*.*?certificate no\.\s*([\S]+)', text)
    if m:
        icv_score = float(m.group(1))
        icv_cert_no = m.group(2)

    # ── ISO certs ──
    has_iso_14001 = 'ISO 14001' in text
    has_iso_45001 = 'ISO 45001' in text

    # ── Submission Checklist ──
    d_status = {}
    m = re.search(r'SUBMISSION CHECKLIST.*?(?=\n\n\n|\Z)', text, re.DOTALL)
    if m:
        checklist_text = m.group(0)
        for d_code in ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']:
            m2 = re.search(rf'{d_code}\s+.*?(\w+)$', checklist_text, re.MULTILINE)
            if m2:
                d_status[d_code] = m2.group(1).strip()

    # ── Technical Alternate ──
    has_alternate = 'technical alternate' in text.lower() or 'alternate capacity' in text.lower()

    # ── Build chunks ──
    chunks = []
    # Split text into sections by page breaks
    for i, page_text in enumerate(text.split('\f')):
        if not page_text.strip():
            continue
        # Detect section headers
        for section_match in re.finditer(r'^([A-Z][A-Z\s&]{2,}|[A-Z][a-z]+.*?(?:Proposal|Schedule|Quality|References|Checklist))', page_text, re.MULTILINE):
            sec = section_match.group(1).strip()
            start = section_match.start()
            end = len(page_text)
            chunk_text = page_text[start:end].strip()[:2000]
            if len(chunk_text) > 50:
                chunks.append({
                    'doc_id': bid_ref,
                    'page': i + 1,
                    'section': sec,
                    'text': normalize_text(chunk_text),
                    'source_file': os.path.basename(path)
                })

    # Structured fact record
    facts = {
        'bid_ref': bid_ref,
        'company': company_name,
        'file_vnum': vnum,
        'source_file': os.path.basename(path),
        'scheme': scheme,
        'capacity_m3_per_day': capacity_m3,
        'capacity_bbl_per_day': capacity_bbl,
        'outlet_oiw_mg_per_l': oiw,
        'outlet_oiw_cover_letter': oiw_cover,
        'price_currency': price_currency,
        'price_total': price_total,
        'line_items': line_items,
        'line_item_sum': line_sum,
        'arithmetic_issue': arithmetic_issue,
        'mc_weeks_from_loa': mc_weeks,
        'warranty_months': warranty_months,
        'gcc_references_count': gcc_references,
        'experience_years': experience_years,
        'employees': employees,
        'year_established': year_est,
        'trir_3yr_avg': trir,
        'fatalities_3yr': fatalities,
        'icv_score_pct': icv_score,
        'icv_cert_no': icv_cert_no,
        'has_iso_14001': has_iso_14001,
        'has_iso_45001': has_iso_45001,
        'submission_checklist': d_status,
        'has_technical_alternate': has_alternate,
    }

    return chunks, facts

def extract_rfp_structured(text):
    """Extract key facts from the RFP text."""
    facts = {
        'tender_ref': 'ADNOC-LCIG/RFP/2026-0412',
        'title': 'Supply, Installation & Commissioning of Produced Water Treatment Package',
        'location': 'Bu Hasnah Field — Central Processing Facility (CPF-2) — Abu Dhabi, UAE',
        'issue_date': '14 May 2026',
        'mandatory_docs_detail': {
            'D1': 'Company profile incl. valid UAE/home-country trade licence — PDF, max 20 pages',
            'D2': 'Technical proposal with equipment list and datasheets — PDF',
            'D3': 'Itemized commercial proposal, priced in AED, with bill of quantities — PDF/Excel',
            'D4': 'HSE management plan incl. risk register, emergency response, waste management — PDF',
            'D5': 'Valid ISO 14001 and ISO 45001 certificates — PDF',
            'D6': 'Valid ICV certificate issued by ADNOC-approved ICV certifier — PDF',
            'D7': 'Company organisation chart and CVs of key personnel — PDF',
            'D8': 'Bid bond of 2% of total bid value, valid 150 days from bid deadline — original or bank-guaranteed copy',
            'D9': 'Signed letter of undertaking accepting RFP terms and conditions (Appendix A) — PDF',
        },
        'bid_deadline': '16 July 2026, 14:00 (UAE time)',
        'bid_validity_days': 120,
        'bid_bond_pct': 2,
        'bid_bond_validity_days': 150,
        'contract_type': 'Lump-sum turnkey (EPC) — Supply, Installation & Commissioning',
        'incoterms': 'DDP Bu Hasnah CPF-2 site (Incoterms 2020)',
        'currency_rule': 'All prices in AED, fixed and firm. USD at AED 3.6725 if converted.',
        'min_capacity_m3_per_day': 30000,
        'max_inlet_oiw_mg_per_l': 650,
        'min_outlet_oiw_mg_per_l': 10,
        'max_outlet_tss_mg_per_l': 15,
        'max_temp_c': 78,
        'max_pressure_barg': 3.5,
        'sour_service': 'NACE MR0175',
        'turndown_pct': 30,
        'availability_pct': 97,
        'min_warranty_months': 24,
        'mandatory_docs': ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9'],
        'evaluation_technical_weight': 40,
        'evaluation_commercial_weight': 30,
        'evaluation_hse_weight': 15,
        'evaluation_icv_weight': 15,
        't1_weight': 15,
        't2_weight': 10,
        't3_weight': 8,
        't4_weight': 7,
        'h1_weight': 9,
        'h2_weight': 6,
        'commercial_formula': 'C = 30 × (Plow / Pbid)',
        'icv_formula': 'ICV = 15 × min(ICV_pct, 60) / 60',
        'payment_milestones': '10% on LOA, 60% supply milestones, 20% mechanical completion, 10% provisional acceptance',
        'performance_bond_pct': 10,
        'ld_rate': '0.5% per week delay, capped at 10%',
        'performance_test': '72-hour continuous run at ≥ 95% design flow, OiW by IP 426 / OSPAR GC-FID',
    }
    return facts

def load_rfp_text():
    """Load RFP text from the raw directory."""
    rfp_path = os.path.join(RAW_DIR, 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.txt')
    if os.path.exists(rfp_path):
        with open(rfp_path) as f:
            return f.read()
    return ""

def load_tracker_json():
    """Load tracker JSON from the raw directory."""
    path = os.path.join(RAW_DIR, 'bid_submission_tracker.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def build_index():
    """Run the full ingest pipeline and persist corpus + facts."""
    rfp_text = load_rfp_text()
    rfp_chunks = extract_rfp(os.path.join(RAW_DIR, 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.txt'))
    rfp_facts = extract_rfp_structured(rfp_text)

    # Tracker
    tracker_data = load_tracker_json()
    if tracker_data:
        tracker_chunks, tracker_facts = extract_tracker(os.path.join(RAW_DIR, 'bid_submission_tracker.json'))
    else:
        tracker_chunks, tracker_facts = [], {'entries': []}

    # Bid documents
    all_chunks = rfp_chunks + tracker_chunks
    bid_facts = {}

    for fp in sorted(glob.glob(os.path.join(RAW_DIR, 'Bid_V*.txt'))):
        basename = os.path.basename(fp)
        m = re.match(r'Bid_V(\d+)_(.+)\.txt', basename)
        if not m:
            continue
        vnum = int(m.group(1))
        company_name = m.group(2).replace('_', ' ')
        bid_ref = FILE_V_TO_BID_REF.get(vnum, f"BID-V{vnum:02d}")

        chunks, facts = extract_bid(fp, vnum, bid_ref, company_name)
        all_chunks.extend(chunks)
        bid_facts[bid_ref] = facts

    # Build per-bid "quick facts" text for the corpus
    for bid_ref, facts in bid_facts.items():
        summary = f"""Bid: {facts['bid_ref']} | Company: {facts['company']}
Scheme: {facts['scheme']}
Capacity: {facts['capacity_m3_per_day']} m³/d{f' ({facts["capacity_bbl_per_day"]} bbl/d)' if facts.get('capacity_bbl_per_day') else ''}
Outlet OiW: {facts['outlet_oiw_mg_per_l']} mg/L (cover letter: {facts['outlet_oiw_cover_letter']} mg/L)
Price: {facts['price_currency']} {facts['price_total']:,}
Line items sum: {facts['line_item_sum']:,} | Arithmetic issue: {facts['arithmetic_issue'] is not None}
MC from LOA: {facts['mc_weeks_from_loa']} weeks
Warranty: {facts['warranty_months']} months
GCC references: {facts['gcc_references_count']}
Experience: {facts['experience_years']} years
Employees: {facts['employees']}
Year est: {facts['year_established']}
TRIR: {facts['trir_3yr_avg']}
Fatalities: {facts['fatalities_3yr']}
ICV: {facts['icv_score_pct']}% (cert: {facts['icv_cert_no']})
ISO 14001: {facts['has_iso_14001']} | ISO 45001: {facts['has_iso_45001']}
Checklist: {json.dumps(facts['submission_checklist'])}
Alternate: {facts['has_technical_alternate']}"""
        all_chunks.append({
            'doc_id': bid_ref,
            'page': 0, 'section': 'Summary',
            'text': summary,
            'source_file': f"Bid_V{vnum:02d}_{facts['company'].replace(' ', '_')}.txt"
        })

    # Add RFP facts as a chunk
    all_chunks.append({
        'doc_id': 'rfp',
        'page': 0, 'section': 'Structured Facts',
        'text': json.dumps(rfp_facts, indent=1),
        'source_file': 'RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf'
    })

    # Persist
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, 'corpus.json'), 'w') as f:
        json.dump(all_chunks, f, indent=1, default=str)
    with open(os.path.join(DATA_DIR, 'rfp_facts.json'), 'w') as f:
        json.dump(rfp_facts, f, indent=1, default=str)
    with open(os.path.join(DATA_DIR, 'bid_facts.json'), 'w') as f:
        json.dump(bid_facts, f, indent=1, default=str)
    with open(os.path.join(DATA_DIR, 'tracker_facts.json'), 'w') as f:
        json.dump(tracker_facts, f, indent=1, default=str)
    with open(os.path.join(DATA_DIR, 'aliases.json'), 'w') as f:
        json.dump({
            'bid_ref_map': BID_REF_MAP,
            'file_v_to_bid_ref': {str(k): v for k, v in FILE_V_TO_BID_REF.items()},
            'company_aliases': {k: v for k, v in COMPANY_ALIASES.items()},
            'file_v_map': {str(k): v for k, v in FILE_V_MAP.items()},
        }, f, indent=1)

    print(f"Index built: {len(all_chunks)} chunks, {len(bid_facts)} bids, {len(tracker_facts.get('entries', []))} tracker entries")
    return all_chunks, rfp_facts, bid_facts, tracker_facts


if __name__ == '__main__':
    build_index()