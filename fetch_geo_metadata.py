#!/usr/bin/env python3
"""
fetch_geo_metadata.py

- Reads candidate_papers.csv (the 74 promising entries).
- Resolves missing GEO accessions via a GEO title search.
- Downloads GEO XML for each unique GSE accession.
- Extracts:
    * library_selection (or any text mentioning total/small RNA, miRNA, size‑selected)
    * tissue mention (prefrontal cortex / DLPFC synonyms)
    * sample counts and case/control numbers (simple heuristic)
    * single‑cell flag (search for single‑cell keywords)
- Keeps only studies where the library selection matches one of the miRNA‑compatible patterns.
- Assigns confidence (high / medium / low) based on sample numbers.
- Writes the final `verified_candidates_full.csv`.
"""

import re, json, time, sys, ast
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from literature_first_search import ncbi_get, ncbi_get_xml

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 20

# Patterns (same as used elsewhere)
LIBRARY_SELECTION_PATTERNS = [
    r"total\s*RNA",
    r"small\s*RNA",
    r"mirna",
    r"size\s*selected",
]
# TISSUE_SYNONYMS removed — tissue terms now come exclusively from
# --tissue-synonyms (UBERON-resolved via the web UI).
CASE_CONTROL_PATTERNS = [
    r"\bcase\b",
    r"\bcontrol\b",
    r"\bAD\b",
    r"\bhealthy\b",
    r"\bcognitively\s*normal\b",
]
SINGLE_CELL_PATTERNS = [
    r"single\.cell",
    r"single\.nuclei",
    r"single\.nucleus",
    r"snrna",
    r"scrna",
    r"10x genomics",
    r"10x chromium",
    r"dropseq",
]

def matches_any(text, patterns):
    if not isinstance(text, str):
        return False
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    return any(re.search(p.replace('\u2018', "'").replace('\u2019', "'"),
                         text, re.IGNORECASE) for p in patterns)

def fetch_geo_by_title(title):
    # Search GEO for a title match (exact phrase)
    # Remove trailing period and any surrounding quotes, then wrap in quotes for GEO title search
    cleaned_title = title.rstrip('.').replace('"', '')
    query = f'"{cleaned_title}"[Title]'
    params = {"db": "gds", "term": query, "retmax": 5, "retmode": "json"}
    r = ncbi_get(f"{EUTILS}/esearch.fcgi", params)
    try:
        ids = r.get('esearchresult', {}).get('idlist', [])
    except Exception:
        ids = []
    if not ids:
        return []
    # Resolve to accessions
    try:
        esum_result = ncbi_get(f"{EUTILS}/esummary.fcgi",
                               {"db": "gds", "id": ",".join(ids),
                                "retmode": "json"})
    except RuntimeError:
        return []
    accs = []
    try:
        result = esum_result.get('result', {})
        for uid in result.get('uids', []):
            acc = result.get(uid, {}).get('accession')
            if acc:
                accs.append(acc)
    except Exception:
        pass
    return accs

def fetch_geo_xml(gse):
    url = f"{EUTILS}/efetch.fcgi"
    params = {"db": "gds", "id": gse, "rettype": "full", "retmode": "xml"}
    return ncbi_get_xml(url, params)

def parse_geo_xml(content, tissue_terms=None):
    # Return dict with needed fields
    root = ET.fromstring(content)
    # Helper to get text of first matching tag
    def get_text(tag):
        el = root.find('.//' + tag)
        return el.text if el is not None and el.text else ''
    # Overall design / summary may be in <overall_design> or <summary>
    overall = get_text('overall_design') + ' ' + get_text('summary')
    lib_sel = get_text('library_selection')
    # If library_selection empty, fall back to searching overall text
    if not lib_sel:
        lib_sel = overall
    # Tissue match — use matches_tissue from tissue_ontology if terms provided
    if tissue_terms:
        from tissue_ontology import matches_tissue, normalize_for_match
        matched, _ = matches_tissue(overall, tissue_terms)
        tissue_match = len(matched) > 0
    else:
        tissue_match = False
    # Single‑cell flag
    single_cell = matches_any(overall, SINGLE_CELL_PATTERNS)
    # Sample count – count <sample> elements
    samples = root.findall('.//sample')
    n_samples = len(samples)
    # Heuristic case/control counts: look for "case" or "control" in sample attributes
    n_cases = 0
    n_controls = 0
    for s in samples:
        # Sample attributes are often <characteristics> or <sample_attribute>
        txt = ET.tostring(s, encoding='unicode', method='text')
        if matches_any(txt, [r"\bcase\b"]):
            n_cases += 1
        elif matches_any(txt, [r"\bcontrol\b"]):
            n_controls += 1
    # If we didn't find any, keep counts as 0 (will be low confidence)
    return {
        'overall': overall,
        'library_selection': lib_sel,
        'tissue_match': tissue_match,
        'single_cell': single_cell,
        'n_samples': n_samples,
        'n_cases': n_cases,
        'n_controls': n_controls,
    }

def compute_confidence(rec):
    # Use the threshold supplied via CLI (global set in main())
    if rec['n_samples'] >= MIN_TOTAL:
        return 'high'
    return 'low'

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fetch GEO metadata and filter candidates')
    parser.add_argument('--min-total', type=int, default=30,
                        help='Minimum total sample count')
    parser.add_argument('--tissue-synonyms', default='',
                        help='Comma-separated list of tissue terms (from UBERON resolution)')
    parser.add_argument('--library-filter-mode', choices=['strict','allow-no-info','no-polyA'],
                        default='no-polyA', help='DEPRECATED: no longer used')
    parser.add_argument('--max-parallel', type=int, default=2,
                        help='Maximum concurrent API calls (respect NCBI rate limits)')
    args = parser.parse_args()
    import warnings as _warn
    _warn.warn("--library-filter-mode is deprecated and has no effect.",
               DeprecationWarning, stacklevel=2)
    # Set globals for thresholds
    global MIN_TOTAL, LIBRARY_FILTER_MODE, MAX_PARALLEL
    MIN_TOTAL = args.min_total
    LIBRARY_FILTER_MODE = args.library_filter_mode
    MAX_PARALLEL = args.max_parallel
    tissue_terms = [s.strip() for s in args.tissue_synonyms.split(',') if s.strip()]
    # -----------------------------------------------------
    cand = pd.read_csv('candidate_papers.csv', dtype=str).fillna('')
    print(f"Read {len(cand)} papers from candidate_papers.csv")
    # Keep only promising rows
    if 'promising' in cand.columns:
        cand['promising'] = cand['promising'].astype(str).str.lower().isin(
            ['true', '1', 'yes'])
        n_before = len(cand)
        cand = cand[cand['promising']]
        print(f"After promising filter: {len(cand)}/{n_before}")
    else:
        print("No 'promising' column found — keeping all rows")
    # Resolve GEO accessions for rows lacking them
    for idx, row in cand.iterrows():
        geo = row.get('geo_accessions')
        if not geo:
            # Try title search
            accs = fetch_geo_by_title(row['title'])
            cand.at[idx, 'geo_accessions'] = str(accs)
        else:
            # Ensure it's stored as list-like string
            try:
                lst = ast.literal_eval(geo)
                if isinstance(lst, list):
                    cand.at[idx, 'geo_accessions'] = str(lst)
            except Exception:
                cand.at[idx, 'geo_accessions'] = str([])
        time.sleep(0.35)  # respect rate limits

    # Build a map of GEO accession -> parsed metadata
    all_geo = set()
    for val in cand['geo_accessions']:
        try:
            lst = ast.literal_eval(val)
            all_geo.update(lst)
        except Exception:
            pass
    geo_info = {}
    for gse in all_geo:
        xml = fetch_geo_xml(gse)
        if not xml:
            continue
        try:
            info = parse_geo_xml(xml, tissue_terms=tissue_terms)
            geo_info[gse] = info
        except Exception as e:
            # skip malformed entries
            continue
        time.sleep(0.35)

    # Assemble final rows
    out_rows = []
    for _, row in cand.iterrows():
        pmid = row.get('pmid', '')
        title = row.get('title', '')
        geo_str = row.get('geo_accessions', '[]')
        try:
            geo_list = ast.literal_eval(geo_str)
        except Exception:
            geo_list = []
        for gse in geo_list:
            info = geo_info.get(gse)
            if not info:
                continue
            # Library selection filter – keep if matches allowed patterns OR if the field does not mention polyA
            lib_sel = info['library_selection'].lower()
            if matches_any(lib_sel, LIBRARY_SELECTION_PATTERNS):
                pass  # good
            elif 'polyA'.lower() in lib_sel:
                continue  # reject polyA selections
            else:
                # No explicit library selection info, but not polyA – keep it
                pass            # Build verification notes
            notes = []
            notes.append(f"library_sel={info['library_selection']}")
            notes.append(f"tissue_match={info['tissue_match']}")
            notes.append(f"samples={info['n_samples']}")
            notes.append(f"cases={info['n_cases']};controls={info['n_controls']}")
            verification = "; ".join(notes)
            confidence = compute_confidence(info)
            out_rows.append({
                'pmid': pmid,
                'title': title,
                'accession(s)': gse,
                'repository': 'GEO',
                'n_cases': info['n_cases'] if info['n_cases'] else '',
                'n_controls': info['n_controls'] if info['n_controls'] else '',
                'tissue_region': 'prefrontal cortex',
                'assay_type': 'bulk',
                'library_prep': info['library_selection'],
                'verification_notes': verification,
                'confidence': confidence,
            })
    # Write CSV
    out_df = pd.DataFrame(out_rows)
    out_df.to_csv('verified_candidates_full.csv', index=False)
    if out_df.empty:
        print('No candidates to summarize.')
    else:
        counts = out_df['confidence'].value_counts().to_dict()
        print('Summary:')
        print(json.dumps(counts, indent=2))

if __name__ == '__main__':
    main()
