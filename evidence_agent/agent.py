"""
agent.py — Procurement Evidence & Retrieval Agent (main entry point).

Usage (CLI):
    python -m evidence_agent "What is the price of Hanseong?"
    python -m evidence_agent --package "List all bids"        # also save JSON package
    python -m evidence_agent --interactive                     # REPL

Role: retrieve accurate, grounded evidence from the ADNOC challenge dataset
and hand it to the downstream Bid Evaluation Agent. Does NOT recommend winners.
"""

import argparse, json, sys, os
from . import evidence as ev
from . import package as pkg
from . import search

ROLE = """You are the Procurement Evidence & Retrieval Agent for tender ADNOC-LCIG/RFP/2026-0412
(Supply, Installation & Commissioning of Produced Water Treatment Package, Bu Hasnah CPF-2).
You retrieve grounded evidence from the challenge dataset (RFP, Bid Submission Tracker,
12 supplier bid documents) and hand it to the Bid Evaluation Agent. You do NOT make
a supplier recommendation. Every fact is traceable to a source document."""

def run_query(query, verbose=False, save_package_path=None, save_wanted=False):
    """Run a query and print the evidence in the standard output format."""
    evidence = ev.build_evidence(query)

    print('=' * 78)
    print('PROCUREMENT EVIDENCE & RETRIEVAL AGENT — ADNOC-LCIG/RFP/2026-0412')
    print('=' * 78)
    print(f'QUERY: {query}')
    print('-' * 78)

    if not evidence:
        print('FACT: Not found in the provided challenge dataset. I cannot verify this from the available evidence.')
        print('SOURCE: —')
        print('LOCATION: —')
        print('EVIDENCE: —')
        print('CONFIDENCE: Not Found')
    else:
        for i, item in enumerate(evidence, 1):
            print(f'FACT: {item.get("FACT", "")}')
            print(f'SOURCE: {item.get("SOURCE", "—")}')
            print(f'LOCATION: {item.get("LOCATION", "—")}')
            print(f'EVIDENCE: {item.get("EVIDENCE", "")}')
            print(f'CONFIDENCE: {item.get("CONFIDENCE", "Not Found")}')
            if i < len(evidence):
                print('-' * 78)

    # Downstream handoff package
    if save_wanted or verbose:
        path, package = pkg.save_package(query, save_package_path)
        print('-' * 78)
        print(f'DOWNSTREAM HANDOFF: evidence package saved to {path}')
        print(f'  Suppliers covered: {len(package["suppliers"])}')
        print(f'  Cross-bid comparisons: {len(package["cross_bid_comparisons"])}')
        print(f'  Confidence summary: {package["confidence_summary"]}')
        if not save_package_path:
            print(f'  (save with --package to persist)')

    return evidence


def interactive():
    """REPL loop."""
    print(ROLE)
    print('Type a query, or "exit" / "quit" to leave.\n')
    while True:
        try:
            q = input('Evidence&Retrieval> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ('exit', 'quit', 'q'):
            break
        run_query(q)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='evidence_agent',
        description='Procurement Evidence & Retrieval Agent for ADNOC-LCIG/RFP/2026-0412')
    parser.add_argument('query', nargs='?', help='Evidence retrieval query')
    parser.add_argument('--package', metavar='PATH', nargs='?', const='auto',
                        help='Save downstream evidence package (JSON)')
    parser.add_argument('--interactive', '-i', action='store_true', help='Interactive REPL')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show handoff info')
    args = parser.parse_args(argv)

    if args.interactive or not args.query:
        interactive()
        return

    save_path = None
    if args.package:
        if args.package == 'auto':
            save_path = None  # auto path inside save_package
        else:
            save_path = args.package
    run_query(args.query, verbose=args.verbose, save_package_path=save_path, save_wanted=bool(args.package))


if __name__ == '__main__':
    main()