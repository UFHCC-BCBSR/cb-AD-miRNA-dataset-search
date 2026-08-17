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

import os
import re
import time
import pandas as pd
import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 20
USER_AGENT = "ad-rna-seq-search/1.0 (contact: jobrant@ufl.edu)"
MAX_RETRIES = 4
MIN_REQUEST_INTERVAL = 0.34  # ~3 req/sec without API key

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
if NCBI_API_KEY:
    MIN_REQUEST_INTERVAL = 0.11  # ~9 req/sec with API key

_last_request_time = 0.0


def _throttle():
    """Shared rate limiter across all NCBI requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def ncbi_get(url, params, retries=MAX_RETRIES):
    """NCBI GET with rate limiting, retries on 429/5xx, JSON validation.

    Returns parsed JSON dict on success.
    Raises RuntimeError with diagnostic info on failure.
    """
    params = dict(params)
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(
                url, params=params, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise RuntimeError(
                    f"NCBI request failed after {retries} attempts: {e}"
                ) from e
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
            print(f"    NCBI {r.status_code} on attempt {attempt+1}, "
                  f"retrying in {retry_after}s...")
            if attempt < retries - 1:
                time.sleep(retry_after)
                continue
            raise RuntimeError(
                f"NCBI returned {r.status_code} after {retries} attempts"
            )

        if r.status_code != 200:
            raise RuntimeError(
                f"NCBI returned HTTP {r.status_code}: "
                f"{r.text[:300]}"
            )

        content_type = r.headers.get("Content-Type", "")
        if "json" not in content_type and "text" not in content_type:
            raise RuntimeError(
                f"NCBI returned unexpected Content-Type '{content_type}' "
                f"(HTTP {r.status_code}). Body preview: {r.text[:300]}"
            )

        try:
            return r.json()
        except ValueError:
            raise RuntimeError(
                f"NCBI returned non-JSON response (HTTP {r.status_code}, "
                f"Content-Type: {content_type}). "
                f"Body preview: {r.text[:300]}"
            )

    raise RuntimeError(f"NCBI request failed after {retries} attempts")


def ncbi_post(url, data, retries=MAX_RETRIES):
    """NCBI POST with rate limiting, retries on 429/5xx, JSON validation.

    Returns parsed JSON dict on success.
    Raises RuntimeError with diagnostic info on failure.
    """
    post_data = dict(data)
    if NCBI_API_KEY:
        post_data["api_key"] = NCBI_API_KEY
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.post(
                url, data=post_data, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise RuntimeError(
                    f"NCBI POST failed after {retries} attempts: {e}"
                ) from e
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
            print(f"    NCBI {r.status_code} on attempt {attempt+1}, "
                  f"retrying in {retry_after}s...")
            if attempt < retries - 1:
                time.sleep(retry_after)
                continue
            raise RuntimeError(
                f"NCBI POST returned {r.status_code} after {retries} attempts"
            )

        if r.status_code != 200:
            raise RuntimeError(
                f"NCBI POST returned HTTP {r.status_code}: "
                f"{r.text[:300]}"
            )

        content_type = r.headers.get("Content-Type", "")
        if "json" not in content_type and "text" not in content_type:
            raise RuntimeError(
                f"NCBI POST returned unexpected Content-Type "
                f"'{content_type}' (HTTP {r.status_code}). "
                f"Body preview: {r.text[:300]}"
            )

        try:
            return r.json()
        except ValueError:
            raise RuntimeError(
                f"NCBI POST returned non-JSON (HTTP {r.status_code}, "
                f"Content-Type: {content_type}). "
                f"Body preview: {r.text[:300]}"
            )

    raise RuntimeError(f"NCBI POST failed after {retries} attempts")


def ncbi_post_xml(url, data, retries=MAX_RETRIES):
    """NCBI POST returning raw bytes for XML parsing."""
    post_data = dict(data)
    if NCBI_API_KEY:
        post_data["api_key"] = NCBI_API_KEY
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.post(
                url, data=post_data, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"    NCBI POST XML failed after {retries} attempts: {e}")
                return None
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
            print(f"    NCBI {r.status_code} on attempt {attempt+1}, "
                  f"retrying in {retry_after}s...")
            if attempt < retries - 1:
                time.sleep(retry_after)
                continue
            print(f"    NCBI POST XML gave up after {retries} attempts")
            return None

        if r.status_code != 200:
            print(f"    NCBI POST XML returned HTTP {r.status_code}")
            return None

        return r.content

    return None


def ncbi_get_xml(url, params, retries=MAX_RETRIES):
    """NCBI GET returning raw bytes for XML parsing."""
    get_params = dict(params)
    if NCBI_API_KEY:
        get_params["api_key"] = NCBI_API_KEY
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(
                url, params=get_params, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"    NCBI GET XML failed after {retries} attempts: {e}")
                return None
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
            print(f"    NCBI {r.status_code} on attempt {attempt+1}, "
                  f"retrying in {retry_after}s...")
            if attempt < retries - 1:
                time.sleep(retry_after)
                continue
            print(f"    NCBI GET XML gave up after {retries} attempts")
            return None

        if r.status_code != 200:
            print(f"    NCBI GET XML returned HTTP {r.status_code}")
            return None

        return r.content

    return None


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

# Tissue synonyms – can be overridden via CLI
TISSUE_SYNONYMS = []

SINGLE_CELL_PATTERNS = [
    r"single.cell", r"single.nuclei", r"single.nucleus", r"snrna",
    r"scrna", r"10x genomics", r"10x chromium", r"dropseq", r"drop-seq",
]
CONTROL_PATTERNS = [
    r"\bcontrol", r"\bhealthy\b", r"non-?demented", r"cognitively normal",
    r"unaffected",
]
STAGING_ONLY_PATTERNS = [
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
    result = ncbi_get(f"{EUTILS}/esearch.fcgi", {
        "db": "pubmed", "term": query, "retmax": retmax, "retmode": "json",
    })
    return result.get("esearchresult", {}).get("idlist", [])


def efetch_abstracts(pmids):
    """Returns {pmid: abstract_text} for a batch of PMIDs.

    Uses XML (not plain text): PubMed's plaintext abstract format has no
    reliable per-record delimiter, and splitting on the numbered-list
    pattern silently misaligns every subsequent record.
    """
    import xml.etree.ElementTree as ET

    out = {}
    for batch in chunked(pmids, 100):
        data = ncbi_post_xml(f"{EUTILS}/efetch.fcgi", {
            "db": "pubmed", "id": batch, "rettype": "abstract",
            "retmode": "xml",
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
            abstract_parts = [
                el.text or ""
                for el in article.findall(".//AbstractText")
            ]
            out[pmid_el.text] = " ".join(abstract_parts)
        time.sleep(0.4)
    return out


def esummary_pubmed(pmids):
    """Returns {pmid: {"title":..., "year":..., "journal":...}}"""
    out = {}
    for batch in chunked(pmids, 200):
        result = ncbi_get(f"{EUTILS}/esummary.fcgi", {
            "db": "pubmed", "id": ",".join(batch), "retmode": "json",
        }).get("result", {})
        for pmid in result.get("uids", []):
            rec = result.get(pmid, {})
            out[pmid] = {
                "title": rec.get("title", ""),
                "year": rec.get("pubdate", "")[:4],
                "journal": rec.get("fulljournalname", ""),
            }
        time.sleep(0.4)
    return out


def resolve_to_geo(pmids):
    """Batched PMID -> linked GEO accession lookup (elink + esummary)."""
    gds_uids = []
    pmid_to_uid = {}
    for batch in chunked(pmids, 100):
        try:
            elink = ncbi_post(f"{EUTILS}/elink.fcgi", {
                "dbfrom": "pubmed", "db": "gds", "id": batch,
                "retmode": "json",
            })
        except RuntimeError as e:
            print(f"    elink failed for batch: {e}")
            time.sleep(0.4)
            continue
        for linkset in elink.get("linksets", []):
            src_pmid = linkset.get("ids", [None])[0]
            for db_block in linkset.get("linksetdbs", []):
                for uid in db_block.get("links", []):
                    gds_uids.append(uid)
                    pmid_to_uid.setdefault(str(src_pmid), []).append(uid)
        time.sleep(0.4)

    uid_to_acc = {}
    for batch in chunked(list(set(gds_uids)), 100):
        try:
            esum = ncbi_post(f"{EUTILS}/esummary.fcgi", {
                "db": "gds", "id": batch, "retmode": "json",
            })
        except RuntimeError as e:
            print(f"    esummary (gds) failed for batch: {e}")
            time.sleep(0.4)
            continue
        result = esum.get("result", {})
        for uid in result.get("uids", []):
            uid_to_acc[uid] = result.get(uid, {}).get("accession", "")
        time.sleep(0.4)

    pmid_to_geo = {}
    for pmid, uids in pmid_to_uid.items():
        accs = sorted(set(
            uid_to_acc.get(u, "") for u in uids if uid_to_acc.get(u)
        ))
        pmid_to_geo[pmid] = accs

    unresolved = [p for p in pmids if p not in pmid_to_geo]
    print(f"  Resolved {len(pmid_to_geo)}/{len(pmids)} papers via elink "
          f"cross-reference ({len(unresolved)} unresolved)")
    return pmid_to_geo


def fallback_title_search_geo(pmid, title):
    """For papers with no elink cross-reference, try a direct GEO title
    search -- catches cases where the PubMed<->GEO link just wasn't
    indexed."""
    if not title:
        return []
    query = title.rstrip(".").replace('"', "")
    try:
        r = ncbi_get(f"{EUTILS}/esearch.fcgi", {
            "db": "gds", "term": f'"{query}"[Title]',
            "retmax": 5, "retmode": "json",
        })
    except RuntimeError as e:
        print(f"    [WARN] esearch failed for PMID {pmid}: {e}")
        return []
    uids = r.get("esearchresult", {}).get("idlist", [])
    if not uids:
        return []
    try:
        esum = ncbi_get(f"{EUTILS}/esummary.fcgi", {
            "db": "gds", "id": uids, "retmode": "json",
        })
    except RuntimeError as e:
        print(f"    [WARN] esummary failed for PMID {pmid}: {e}")
        return []
    result = esum.get("result", {})
    return sorted(set(
        result.get(u, {}).get("accession", "")
        for u in result.get("uids", [])
    ))


def matches_any(text, patterns):
    if not isinstance(text, str):
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def find_sample_size_snippets(text):
    if not isinstance(text, str):
        return []
    return [m.group(0).strip()
            for m in SAMPLE_SIZE_PATTERN.finditer(text)][:3]


def main():
    global TISSUE_SYNONYMS, CASE_CONTROL_PATTERNS
    import argparse
    parser = argparse.ArgumentParser(
        description='Literature-first AD vs control search')
    parser.add_argument('--tissue-synonyms',
                        default=','.join(TISSUE_SYNONYMS),
                        help='Comma-separated list of tissue synonyms')
    parser.add_argument('--case-control-regex',
                        default='|'.join(CASE_CONTROL_PATTERNS),
                        help='Regex pattern for case/control detection')
    parser.add_argument('--library-filter-mode',
                        choices=['strict', 'allow-no-info', 'no-polyA'],
                        default='no-polyA',
                        help='How to treat missing library selection')
    args = parser.parse_args()
    # Override globals if args provided
    TISSUE_SYNONYMS = [s.strip() for s in
                       args.tissue_synonyms.split(',') if s.strip()]
    CASE_CONTROL_PATTERNS = [args.case_control_regex]
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
            "staging_design_signal": matches_any(
                abstract, STAGING_ONLY_PATTERNS),
            "library_selection_match": matches_any(
                abstract, LIBRARY_SELECTION_PATTERNS),
            "case_control_match": matches_any(
                abstract, CASE_CONTROL_PATTERNS),
            "sample_size_snippets": find_sample_size_snippets(abstract),
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "abstract": abstract.strip()[:1000],
        })

    df = pd.DataFrame(rows)

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
        print(f"  Trying title-search fallback for "
              f"{len(still_unresolved)} unresolved papers...")
        pmid_title = dict(zip(df["pmid"], df["title"]))
        fallback_ok = 0
        fallback_fail = 0
        for pmid in still_unresolved:
            try:
                accs = fallback_title_search_geo(
                    pmid, pmid_title.get(pmid, ""))
                if accs:
                    pmid_to_geo[pmid] = accs
                    fallback_ok += 1
                else:
                    fallback_fail += 1
            except Exception as e:
                print(f"    [WARN] fallback failed for PMID {pmid}: {e}")
                fallback_fail += 1
            time.sleep(0.4)
        print(f"  Fallback resolved {fallback_ok}/{len(still_unresolved)} "
              f"additional papers ({fallback_fail} failed)")

    df["geo_accessions"] = df["pmid"].map(
        lambda p: pmid_to_geo.get(p, []))

    df.to_csv("candidate_papers.csv", index=False)

    print(f"\nDone. {len(df)} papers total, "
          f"{df['promising'].sum()} flagged promising.")
    print("Saved to candidate_papers.csv")
    print()
    cols = ["pmid", "title", "year", "mentions_control",
            "likely_single_cell", "staging_design_signal",
            "geo_accessions"]
    print(df.loc[df["promising"], cols].to_string(index=False))


if __name__ == "__main__":
    main()
