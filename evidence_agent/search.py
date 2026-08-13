"""
search.py — Query parsing, entity resolution, and retrieval.

Decodes natural-language queries into:
1. Entity resolution: which bidder/bid-ref/document is being asked about
2. Keyword search: TF-IDF based retrieval from the chunked corpus
3. Structured fact lookup: direct field queries from the fact database

Supports queries like:
  "What is the bid price of Hanseong?"
  "Show me Al Manara's ICV score"
  "What is the capacity of V10?"
  "Which bidders have TRIR below 0.3?"
  "What is the Petrotech arithmetic issue?"
  "Tell me about the D1 requirement"
  "List all bids with their prices"
"""

import os, re, json, math, collections, unicodedata
from pathlib import Path

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ── Load persisted data ────────────────────────────────────────────────────
def _load_json(filename):
    p = os.path.join(DATA_DIR, filename)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}

_corpus = _load_json('corpus.json')
_bid_facts = _load_json('bid_facts.json')
_rfp_facts = _load_json('rfp_facts.json')
_tracker_facts = _load_json('tracker_facts.json')
_aliases = _load_json('aliases.json')

# Build inverted index lazily
_inverted_index = None
_doc_lengths = None

# ── Tokenizer ───────────────────────────────────────────────────────────────
_STOP_WORDS = frozenset('a an the and or but in on at to for of by with from is are was were be been has have had do does did will would could should may might shall can not no nor this that these those its it s t'.split())

def tokenize(text):
    """Tokenize and stem (simple Porter-style)."""
    text = unicodedata.normalize('NFKD', text).lower()
    # Remove common document artifacts
    text = re.sub(r'[^\w\s]', ' ', text)
    tokens = text.split()
    return [t for t in tokens if len(t) > 2 and t not in _STOP_WORDS]

def simple_stem(t):
    """Very simple stemmer for English."""
    for suffix in ['ing', 'tion', 'ment', 'ness', 'able', 'ible', 'ed', 'ly', 's']:
        if len(t) > 4 and t.endswith(suffix):
            return t[:-len(suffix)]
    return t

# ── Inverted index builder ──────────────────────────────────────────────────
def build_index():
    global _inverted_index, _doc_lengths
    _inverted_index = collections.defaultdict(lambda: collections.defaultdict(int))
    _doc_lengths = {}
    for i, chunk in enumerate(_corpus):
        tokens = [simple_stem(t) for t in tokenize(chunk.get('text', ''))]
        _doc_lengths[i] = len(tokens) or 1
        for t in set(tokens):
            _inverted_index[t][i] += 1
    return _inverted_index

def get_index():
    global _inverted_index
    if _inverted_index is None:
        build_index()
    return _inverted_index

def get_doc_lengths():
    global _doc_lengths
    if _doc_lengths is None:
        build_index()
    return _doc_lengths

# ── Search ──────────────────────────────────────────────────────────────────
def search(query, top_k=10):
    """TF-IDF cosine similarity search over corpus chunks."""
    idx = get_index()
    dl = get_doc_lengths()
    N = len(_corpus)

    q_tokens = [simple_stem(t) for t in tokenize(query)]
    q_tf = collections.Counter(q_tokens)

    # Compute TF-IDF scores per document
    scores = collections.defaultdict(float)
    for q_term, q_tf_val in q_tf.items():
        if q_term not in idx:
            continue
        df = len(idx[q_term])
        idf = math.log((N + 1) / (df + 1)) + 1
        for doc_id, tf in idx[q_term].items():
            tfidf = (1 + math.log(tf)) * idf
            scores[doc_id] += tfidf * q_tf_val

    if not scores:
        return []

    # Normalize by document length
    for doc_id in scores:
        scores[doc_id] /= (dl[doc_id] ** 0.5)

    # Sort
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    results = []
    for doc_id, score in ranked[:top_k]:
        chunk = _corpus[doc_id]
        text = chunk.get('text', '')[:500]
        results.append({
            'doc_id': chunk.get('doc_id', ''),
            'page': chunk.get('page', ''),
            'section': chunk.get('section', ''),
            'source_file': chunk.get('source_file', ''),
            'text': text,
            'score': round(score, 4),
        })
    return results

# ── Entity Resolution ───────────────────────────────────────────────────────
def resolve_entity(query):
    """Extract bid-ref, company name, or document from a query."""
    q = query.lower()

    # Direct bid reference: "BID-2026-0412-04" or "BID-04"
    m = re.search(r'bid[-\s]*(?:\d{4}[-\s]*\d*[-\s]*)?(\d{2})', q)
    if m:
        num = m.group(1)
        for ref in _bid_facts:
            if ref.endswith(f'-{num}'):
                return ref, _bid_facts[ref]['company']
            if ref.endswith(f'-{num}'):
                pass

    # V-number: "V10", "V01", "Bid V05"
    m = re.search(r'(?:bid\s*)?[Vv](\d{1,2})', q)
    if m:
        vnum = int(m.group(1))
        v_key = str(vnum)
        v_map = _aliases.get('file_v_to_bid_ref', {})
        if v_key in v_map:
            bref = v_map[v_key]
            if bref in _bid_facts:
                return bref, _bid_facts[bref]['company']

    # Full bid ref: "BID-2026-0412-12"
    m = re.search(r'(BID-\d{4}-\d{4}-\d{2})', q.upper())
    if m:
        bref = m.group(1)
        if bref in _bid_facts:
            return bref, _bid_facts[bref]['company']

    # Company name (from aliases) — prefer longer matches
    # Blocklist of generic words that shouldn't resolve to a specific bidder
    _GENERIC_ALIAS_BLOCK = frozenset([
        'water', 'energy', 'gulf', 'industrial', 'marine', 'process',
        'solutions', 'technologies', 'engineering', 'supplies', 'services',
        'systems', 'heavy', 'industries', 'arabia', 'technik', 'gmbh',
        'llc', 'fze', 'wll', 'sal', 'ltd', 'co', 'bahr', 'sultan',
    ])
    best_alias = None
    best_len = 0
    for alias, bref in _aliases.get('company_aliases', {}).items():
        if alias in q and alias not in _GENERIC_ALIAS_BLOCK:
            # Prefer longer, more specific aliases over short generic words
            if len(alias) > best_len:
                best_alias = bref
                best_len = len(alias)
                best_company = _bid_facts.get(bref, {}).get('company') if bref in _bid_facts else None
    if best_alias:
        return best_alias, best_company

    # RFP / tracker references
    if any(w in q for w in ['rfp', 'tender', 'requirement', 'mandatory', 'd1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8', 'd9']):
        return 'rfp', 'RFP ADNOC-LCIG/RFP/2026-0412'

    if 'tracker' in q or 'register' in q:
        return 'tracker', 'Bid Submission Tracker'

    return None, None

# ── Structured fact lookup ──────────────────────────────────────────────────
def get_bid_facts(bid_ref):
    """Return structured facts for a bid."""
    return _bid_facts.get(bid_ref)

def get_rfp_facts():
    return _rfp_facts

def get_tracker_entries():
    return _tracker_facts.get('entries', [])

def get_tracker_entry(bid_ref):
    for e in _tracker_facts.get('entries', []):
        if e.get('bid_ref') == bid_ref:
            return e
    return None

# ── Query interpretation: what field is being asked? ────────────────────────
FIELD_KEYWORDS = {
    'price': ['price', 'cost', 'bid value', 'commercial', 'aed', 'total', 'lump sum', 'amount'],
    'capacity': ['capacity', 'throughput', 'm3/d', 'm³/d', 'bbl/d', 'treatment capacity', 'size'],
    'oiw': ['oil-in-water', 'oiw', 'outlet oil', 'oil content', 'mg/l', 'outlet quality'],
    'tss': ['suspended solids', 'tss', 'solids'],
    'mc_weeks': ['mechanical completion', 'delivery', 'schedule', 'mc', 'weeks', 'loa'],
    'warranty': ['warranty', 'warranty period'],
    'trir': ['trir', 'safety', 'incident rate', 'hse performance'],
    'icv': ['icv', 'in-country value', 'in country value', 'local content'],
    'experience': ['experience', 'years', 'track record', 'established'],
    'references': ['reference', 'track record', 'gcc', 'installation'],
    'employees': ['employees', 'personnel', 'staff'],
    'scheme': ['scheme', 'technology', 'treatment', 'process', 'solution', 'hydrocyclone', 'flotation', 'filtration', 'cpi', 'igf'],
    'certifications': ['iso', 'certification', 'certified', 'certificate'],
    'checklist': ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8', 'd9', 'mandatory', 'submission', 'checklist'],
    'arithmetic': ['arithmetic', 'line item', 'sum vs', 'total mismatch', 'itemized'],
    'alternate': ['alternate', 'alternate bid', 'technical alternate'],
    'bid_bond': ['bid bond', 'bank guarantee', 'bond'],
    'payment': ['payment', 'milestone', 'margin'],
    'performance': ['performance test', 'performance guarantee', 'ld', 'liquidated damages'],
}

def classify_query(query):
    """Determine what type of information is being requested."""
    q = query.lower()
    fields = []
    for field, keywords in FIELD_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            fields.append(field)
    return fields

# ── Query interpretation: what field is being asked? ────────────────────────
# Company-name suffixes that indicate a query is naming a specific supplier.
COMPANY_SUFFIXES = ('corp', 'corporation', 'llc', 'ltd', 'limited', 'co', 'gmbh',
                    'fze', 'fz-llc', 'wll', 'sal', 'inc', 'company', 'ag', 'bv',
                    's.p.a', 'holdings')

def mentions_unknown_company(query):
    """
    Heuristic: does this query name a supplier that is NOT in the dataset?

    Grounding rule (AGENTS.md): never return keyword-match noise for a company
    that does not exist. If the query carries company-name structure (e.g.
    "Acme Water Corp", "price of X LLC", possessive "X's bid") but no known
    alias resolves, the agent must answer Not Found instead of fuzzy-searching
    on a generic word that happens to appear in another company's document.
    """
    q = query.lower()

    # Possessive company reference: "X's price", "X's ICV" where X is not known
    m = re.search(r"([a-z][a-z &.\-']+?)'s\b", q)
    if m and len(m.group(1)) > 3:
        candidate = m.group(1).strip()
        # Skip generic possessives ("bidder's", "company's", "supplier's")
        if candidate not in ('bidder', 'company', 'supplier', 'contractor',
                             'vendor', 'bid', 'tender', 'evaluator', 'agency'):
            known = any(a in candidate for a in _aliases.get('company_aliases', {}))
            if not known:
                return True

    # Named company pattern: "... Corp/LLC/Ltd/Co ..." not matching any alias
    words = re.findall(r'[a-z]+', q)
    if any(suf in q for suf in COMPANY_SUFFIXES):
        # Extract the name token before the suffix
        for suf in sorted(COMPANY_SUFFIXES, key=len, reverse=True):
            m = re.search(r'([a-z]+(?:\s+[a-z]+){0,2})\s+' + re.escape(suf) + r'\b', q)
            if m:
                name = m.group(1)
                # Whole name (or its distinctive leading words) unknown?
                alias_map = _aliases.get('company_aliases', {})
                known = any(
                    alias in name or name in alias
                    for alias in alias_map
                )
                if not known:
                    return True

    # "price/capacity/ICV of <unknown capitalized name>" pattern
    m = re.search(r'(?:price|bid|capacity|icv|trir|oiw|score|schedule|commercial|technical)\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})', query)
    if m:
        name = m.group(1).lower()
        alias_map = _aliases.get('company_aliases', {})
        known = any(alias in name or name in alias for alias in alias_map)
        if not known and 'water' in name or 'corp' in name or 'llc' in name or 'ltd' in name or 'co' in name:
            return True
    return False


# ── Comparison / list queries ───────────────────────────────────────────────
def is_list_query(query):
    q = query.lower()
    return any(w in q for w in ['list', 'all', 'every', 'compare', 'each', 'show me all', 'which'])

def is_comparison_query(query):
    q = query.lower()
    return any(w in q for w in ['compare', 'vs', 'versus', 'better', 'best', 'lowest', 'highest', 'cheapest', 'most expensive'])

def is_threshold_query(query):
    q = query.lower()
    return bool(re.search(r'(below|above|under|over|less than|greater than|>=?|<=?|minimum|maximum|at least|at most)', q))

def extract_threshold(query):
    """Extract numeric threshold from query like 'below 0.3' or 'above 30,000'."""
    q = query
    m = re.search(r'(below|under|less than|<=?)\s*([\d,]+(?:\.\d+)?)', q, re.I)
    if m:
        return 'below', float(m.group(2).replace(',', ''))
    m = re.search(r'(above|over|greater than|>=?|at least)\s*([\d,]+(?:\.\d+)?)', q, re.I)
    if m:
        return 'above', float(m.group(2).replace(',', ''))
    return None, None

# ── Convenience alias for V-number → bid-ref ────────────────────────────────
def v_to_bid_ref(vnum):
    vm = _aliases.get('file_v_to_bid_ref', {})
    return vm.get(str(vnum))

# ── Bid eligibility summary (auto-computed) ─────────────────────────────────
def get_eligibility(bid_ref):
    facts = _bid_facts.get(bid_ref)
    if not facts:
        return None
    issues = []

    # T1: capacity ≥ 30,000 and OiW ≤ 10
    cap = facts.get('capacity_m3_per_day')
    oiw = facts.get('outlet_oiw_mg_per_l')
    if cap is not None and cap < 30000:
        issues.append(f"Capacity {cap} m³/d < 30,000 minimum → T1 band 0, technically non-compliant")
    if oiw is not None and oiw > 10:
        issues.append(f"OiW {oiw} mg/L > 10 mg/L maximum → T1 band 0, technically non-compliant")

    # D6 ICV certificate
    checklist = facts.get('submission_checklist', {})
    tracker_entry = get_tracker_entry(bid_ref)
    if checklist.get('D6', '') != 'Enclosed':
        issues.append(f"D6 ICV certificate: {checklist.get('D6', 'Not found')} → conditionally non-compliant")
    if tracker_entry and tracker_entry.get('receipt_remarks') and 'icv certificate not found' in (tracker_entry['receipt_remarks'] or '').lower():
        issues.append(f"Tracker confirms ICV certificate not found in submission")

    # D8 Bid bond
    if checklist.get('D8', '') != 'Enclosed':
        issues.append(f"D8 Bid bond: {checklist.get('D8', 'Not found')} → conditionally non-compliant")
    if tracker_entry and tracker_entry.get('receipt_remarks') and 'bid bond not found' in (tracker_entry['receipt_remarks'] or '').lower():
        issues.append(f"Tracker confirms bid bond not found in submission")

    # Currency deviation
    if facts.get('price_currency') and facts['price_currency'] != 'AED':
        issues.append(f"Priced in {facts['price_currency']} (not AED) → commercial deviation per ITB clause 2")

    # Arithmetic issue
    if facts.get('arithmetic_issue'):
        issues.append(f"Arithmetic discrepancy: line items sum to {facts['arithmetic_issue']['line_item_sum']:,} vs stated total {facts['arithmetic_issue']['stated_total']:,} (diff {facts['arithmetic_issue']['difference']:+,}) → per ITB clause 6, corrected sum governs")

    # T4: MC > 76 weeks
    mc = facts.get('mc_weeks_from_loa')
    if mc is not None and mc > 76:
        issues.append(f"MC at {mc} weeks > 76 week contractual maximum → T4 band 1, subject to rejection")

    # T4: MC 69-76 is band 2
    if mc is not None and mc > 68:
        issues.append(f"MC at {mc} weeks → T4 band 2 (69-76 weeks, contractual maximum)")

    # Alternate
    if facts.get('has_technical_alternate'):
        issues.append(f"Technical alternate offered (per ITB clause 9)")

    return {
        'bid_ref': bid_ref,
        'company': facts.get('company'),
        'issues': issues,
        'passes_mandatory': all(v == 'Enclosed' for v in [checklist.get(d, '') for d in ['D1','D2','D3','D4','D5','D6','D7','D8','D9']]),
        'passes_technical_minimum': not any('T1 band 0' in i for i in issues),
    }

if __name__ == '__main__':
    # quick test
    for q in [
        "What is the bid price of Hanseong?",
        "Show me Al Manara's ICV score",
        "What is the capacity of V10?",
        "Which bidders have TRIR below 0.3?",
        "What is the Petrotech arithmetic issue?",
        "Tell me about the D1 requirement",
        "List all bids with their prices",
    ]:
        bref, company = resolve_entity(q)
        fields = classify_query(q)
        print(f'Q: {q}')
        print(f'  Entity: {bref} ({company})')
        print(f'  Fields: {fields}')
        print()