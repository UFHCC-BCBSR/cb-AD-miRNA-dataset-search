#!/usr/bin/env python3
"""
literature_first_search.py

Literature-first candidate dataset search: search PubMed, read what each
paper's own abstract says about design/tissue/method, and only resolve to
a GEO/SRA accession for papers that plausibly fit -- rather than starting
from deposited SRA metadata, which has repeatedly turned out to be
incomplete or misleading (e.g. a "cDNA, RNA-Seq, Alzheimer, BA46" study
that was actually single-nucleus with no control arm at all -- none of
that was visible in SRA's structured fields, but was stated plainly in
the paper's own abstract).

Usage:
    python literature_first_search.py

Output:
    candidate_papers.csv  -- one row per paper, with design/tissue/method
                             flags and (if resolved) a GEO accession
"""

import re
import time
import pandas as pd
import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 20

# ---------------------------------------------------------------------
# 1. Search terms -- broad on purpose. We're filtering on abstract text
#    afterward, not trying to encode the full brief into the query.
# ---------------------------------------------------------------------
PUBMED_QUERY = (
    '(Alzheimer[Title/Abstract] OR "Alzheimer\'s disease"[Title/Abstract]) AND '
    '(prefrontal[Title/Abstract] OR DLPFC[Title/Abstract] '
    'OR "frontal cortex"[Title/Abstract] OR BA9[Title/Abstract] '
    'OR BA10[Title/Abstract] OR BA46[Title/Abstract] '
    'OR "frontal gyrus"[Title/Abstract]) AND '
    '(RNA-seq[Title/Abstract] OR "RNA sequencing"[Title/Abstract] '
    'OR transcriptom*[Title/Abstract])'
)
RETMAX = 5000

# ---------------------------------------------------------------------
# 2. Abstract-text signals -- these are what actually distinguish a
#    usable case-control bulk study from a staging/single-cell one,
#    based on what SRA metadata has repeatedly failed to surface.
# ---------------------------------------------------------------------
LIBRARY_SELECTION_PATTERNS = [
    r"total\s*RNA",
    r"small\s*RNA",
    r"mirna",
    r"size\s*selected",
]

CASE_CONTROL_PATTERNS = [
    r"\bcase\b",
    r"\bcontrol\b",
    r"\bAD\b",
    r"\bhealthy\b",
    r"\bcognitively\s*normal\b",
]

SINGLE_CELL_PATTERNS = [
    r"single.cell", r"single.nuclei", r"single.nucleus", r"snrna",
    r"scrna", r"10x genomics", r"10x chromium", r"dropseq", r"drop-seq",
]
CONTROL_PATTERNS = [
    r"\bcontrol", r"\bhealthy\b", r"non-?demented", r"cognitively normal",
    r"unaffected",
]
STAGING_ONLY_PATTERNS = [
    # signals a disease-severity/progression design rather than a
    # discrete case-vs-control comparison (like SRP415133 turned out to be)
    r"braak stage", r"pathological continuum", r"disease progression",
    r"spatiotemporal progression",
]
SAMPLE_SIZE_PATTERN = re.compile(
    r"[^.]{0,60}\bn\s*=\s*\d+[^.]{0,60}|"
    r"[^.]{0,40}\b\d{1,4}\s+(?:AD|Alzheimer|control|patient|subject|donor|case)s?\b[^.]{0,40}",
    re.IGNORECASE,
)


def chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def esearch_pubmed(query, retmax):
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "pubmed", "term": query, "retmax": retmax, "retmode": "json",
    }, timeout=TIMEOUT)
    return r.json().get("esearchresult", {}).get("idlist", [])


def efetch_abstracts(pmids):
    """Returns {pmid: abstract_text} for a batch of PMIDs.

    Uses XML (not plain text): PubMed's plaintext abstract format has no
    reliable per-record delimiter, and splitting on the numbered-list
    pattern ("1. ", "2. ", ...) silently misaligns every subsequent
    record in a batch whenever one paper lacks an abstract (or its own
    text happens to contain a similar pattern) -- confirmed this
    happened in practice: one row's "abstract" was actually a
    completely different paper's text. XML explicitly tags each
    <PubmedArticle> with its own <PMID>, so there's no order-dependent
    guessing involved.
    """
    import xml.etree.ElementTree as ET

    out = {}
    for batch in chunked(pmids, 100):
        data = post_with_retry_xml(f"{EUTILS}/efetch.fcgi", {
            "db": "pubmed", "id": batch, "rettype": "abstract", "retmode": "xml",
        })
        if data is None:
            continue
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//PMID")
            if pmid_el is None or not pmid_el.text:
                continue
            abstract_parts = [el.text or "" for el in article.findall(".//AbstractText")]
            out[pmid_el.text] = " ".join(abstract_parts)
        time.sleep(0.4)
    return out


def post_with_retry_xml(url, data, retries=3):
    """Like post_with_retry, but returns raw bytes for XML parsing
    instead of assuming a JSON response."""
    for attempt in range(retries):
        try:
            r = requests.post(url, data=data, timeout=TIMEOUT)
            return r.content
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"    Failed after {retries} attempts: {e}")
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def esummary_pubmed(pmids):
    """Returns {pmid: {"title":..., "year":..., "journal":...}}"""
    out = {}
    for batch in chunked(pmids, 200):
        r = requests.get(f"{EUTILS}/esummary.fcgi", params={
            "db": "pubmed", "id": ",".join(batch), "retmode": "json",
        }, timeout=TIMEOUT)
        result = r.json().get("result", {})
        for pmid in result.get("uids", []):
            rec = result.get(pmid, {})
            out[pmid] = {
                "title": rec.get("title", ""),
                "year": rec.get("pubdate", "")[:4],
                "journal": rec.get("fulljournalname", ""),
            }
        time.sleep(0.4)
    return out


def post_with_retry(url, data, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(url, data=data, timeout=TIMEOUT)
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            if attempt == retries - 1:
                print(f"    Failed after {retries} attempts: {e}")
                return {}
            time.sleep(1.5 * (attempt + 1))
    return {}


def resolve_to_geo(pmids):
    """Batched PMID -> linked GEO accession lookup (elink + esummary).

    Uses POST rather than GET: with many repeated id= params, the GET
    URL gets long enough that NCBI's server (or a proxy in between) can
    cut the response short mid-stream (ChunkedEncodingError /
    "Response ended prematurely"). POST avoids the URL-length issue
    entirely -- this is NCBI's own recommendation for larger ID batches.
    """
    gds_uids = []
    pmid_to_uid = {}
    for batch in chunked(pmids, 100):
        elink = post_with_retry(f"{EUTILS}/elink.fcgi", {
            "dbfrom": "pubmed", "db": "gds", "id": batch, "retmode": "json",
        })
        for linkset in elink.get("linksets", []):
            src_pmid = linkset.get("ids", [None])[0]
            for db_block in linkset.get("linksetdbs", []):
                for uid in db_block.get("links", []):
                    gds_uids.append(uid)
                    pmid_to_uid.setdefault(str(src_pmid), []).append(uid)
        time.sleep(0.4)

    uid_to_acc = {}
    for batch in chunked(list(set(gds_uids)), 100):
        esum = post_with_retry(f"{EUTILS}/esummary.fcgi", {
            "db": "gds", "id": batch, "retmode": "json",
        })
        result = esum.get("result", {})
        for uid in result.get("uids", []):
            uid_to_acc[uid] = result.get(uid, {}).get("accession", "")
        time.sleep(0.4)

    pmid_to_geo = {}
    for pmid, uids in pmid_to_uid.items():
        accs = sorted(set(uid_to_acc.get(u, "") for u in uids if uid_to_acc.get(u)))
        pmid_to_geo[pmid] = accs

    unresolved = [p for p in pmids if p not in pmid_to_geo]
    print(f"  Resolved {len(pmid_to_geo)}/{len(pmids)} papers via elink cross-reference "
          f"({len(unresolved)} unresolved)")
    return pmid_to_geo


def fallback_title_search_geo(pmid, title):
    """For papers with no elink cross-reference, try a direct GEO title
    search -- catches cases where the PubMed<->GEO link just wasn't
    indexed, without assuming every unresolved paper has no public data."""
    if not title:
        return []
    # Strip trailing period and quote the title for a closer match
    query = title.rstrip(".").replace('"', "")
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "gds", "term": f'"{query}"[Title]', "retmax": 5, "retmode": "json",
    }, timeout=TIMEOUT).json()
    uids = r.get("esearchresult", {}).get("idlist", [])
    if not uids:
        return []
    esum = requests.get(f"{EUTILS}/esummary.fcgi", params={
        "db": "gds", "id": uids, "retmode": "json",
    }, timeout=TIMEOUT).json()
    result = esum.get("result", {})
    return sorted(set(result.get(u, {}).get("accession", "") for u in result.get("uids", [])))


def matches_any(text, patterns):
    if not isinstance(text, str):
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def find_sample_size_snippets(text):
    if not isinstance(text, str):
        return []
    return [m.group(0).strip() for m in SAMPLE_SIZE_PATTERN.finditer(text)][:3]


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Literature‑first AD vs control search')
    parser.add_argument('--tissue-synonyms', default=','.join(TISSUE_SYNONYMS),
                        help='Comma‑separated list of tissue synonyms')
    parser.add_argument('--case-control-regex', default='|'.join(CASE_CONTROL_PATTERNS),
                        help='Regex pattern for case/control detection')
    parser.add_argument('--library-filter-mode', choices=['strict','allow-no-info','no-polyA'],
                        default='no-polyA', help='How to treat missing library selection')
    args = parser.parse_args()
    # Override globals if args provided
    global TISSUE_SYNONYMS, CASE_CONTROL_PATTERNS
    TISSUE_SYNONYMS = [s.strip() for s in args.tissue_synonyms.split(',') if s.strip()]
    CASE_CONTROL_PATTERNS = [args.case_control_regex]
    # library_filter_mode currently unused in this script (handled later)
    # -----------------------------------------------------
    print("Searching PubMed...")
    pmids = esearch_pubmed(PUBMED_QUERY, RETMAX)
    print(f"  {len(pmids)} papers found")

    print("Fetching abstracts...")
    abstracts = efetch_abstracts(pmids)

    print("Fetching titles/years/journals...")
    summaries = esummary_pubmed(pmids)

    rows = []
    for pmid in pmids:
        abstract = abstracts.get(pmid, "")
        meta = summaries.get(pmid, {})
        rows.append({
            "pmid": pmid,
            "title": meta.get("title", ""),
            "year": meta.get("year", ""),
            "journal": meta.get("journal", ""),
                "likely_single_cell": matches_any(abstract, SINGLE_CELL_PATTERNS),
                "mentions_control": matches_any(abstract, CONTROL_PATTERNS),
                "staging_design_signal": matches_any(abstract, STAGING_ONLY_PATTERNS),
                "library_selection_match": matches_any(abstract, LIBRARY_SELECTION_PATTERNS),
                "case_control_match": matches_any(abstract, CASE_CONTROL_PATTERNS),
            "sample_size_snippets": find_sample_size_snippets(abstract),
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "abstract": abstract.strip()[:1000],
        })

    df = pd.DataFrame(rows)

    # Promising = mentions a control group, not flagged single-cell,
    # no staging-only signal. Everything else still gets kept in the
    # output, just sorted below, for a human to double check the filter
    # itself isn't too aggressive.
    df["promising"] = (
        df["mentions_control"]
        & df["case_control_match"]
        & ~df["likely_single_cell"]
        & ~df["staging_design_signal"]
    )
    df = df.sort_values("promising", ascending=False)

    print("Resolving promising papers to GEO accessions...")
    promising_pmids = df.loc[df["promising"], "pmid"].tolist()
    pmid_to_geo = resolve_to_geo(promising_pmids) if promising_pmids else {}

    still_unresolved = [p for p in promising_pmids if not pmid_to_geo.get(p)]
    if still_unresolved:
        print(f"  Trying title-search fallback for {len(still_unresolved)} unresolved papers...")
        pmid_title = dict(zip(df["pmid"], df["title"]))
        for pmid in still_unresolved:
            accs = fallback_title_search_geo(pmid, pmid_title.get(pmid, ""))
            if accs:
                pmid_to_geo[pmid] = accs
            time.sleep(0.4)
        resolved_by_fallback = sum(1 for p in still_unresolved if pmid_to_geo.get(p))
        print(f"  Fallback resolved {resolved_by_fallback}/{len(still_unresolved)} additional papers")

    df["geo_accessions"] = df["pmid"].map(lambda p: pmid_to_geo.get(p, []))

    df.to_csv("candidate_papers.csv", index=False)

    print(f"\nDone. {len(df)} papers total, {df['promising'].sum()} flagged promising.")
    print("Saved to candidate_papers.csv")
    print()
    cols = ["pmid", "title", "year", "mentions_control", "likely_single_cell",
            "staging_design_signal", "geo_accessions"]
    print(df.loc[df["promising"], cols].to_string(index=False))


if __name__ == "__main__":
    main()
