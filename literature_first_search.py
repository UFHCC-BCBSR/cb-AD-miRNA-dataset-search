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
PUBMED_TISSUE_TERMS = [
    "prefrontal", "DLPFC", "frontal cortex", "BA9", "BA10", "BA46",
    "frontal gyrus",
]
HUMAN_FILTER = 'NOT (mouse[Title/Abstract] OR mice[Title/Abstract] OR rat[Title/Abstract] OR rats[Title/Abstract] OR macaque[Title/Abstract] OR murine[Title/Abstract] OR muridae[Title/Abstract] OR rodent[Title/Abstract] OR porcine[Title/Abstract] OR canine[Title/Abstract] OR marmoset[Title/Abstract])'
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

NON_HUMAN_PATTERNS = [
    r"\bmouse\b", r"\bmice\b", r"\brat\b", r"\brats\b",
    r"\brhesus\b", r"\bmacaque\b", r"\bcanine\b", r"\bmouse model\b",
    r"\bmurine\b", r"\brodents?\b", r"\btransgenic\b",
    r"\bmarmoset\b", r"\bporcine\b", r"\bpig\b",
]


def chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def esearch_pubmed(query, retmax):
    all_ids = []
    retstart = 0
    while True:
        result = ncbi_get(f"{EUTILS}/esearch.fcgi", {
            "db": "pubmed", "term": query, "retmax": retmax,
            "retstart": retstart, "retmode": "json",
        })
        esr = result.get("esearchresult", {})
        count = int(esr.get("count", 0))
        batch_ids = esr.get("idlist", [])
        all_ids.extend(batch_ids)
        if retstart == 0:
            print(f"  esearch count={count}, fetching up to {retmax}")
        if len(all_ids) >= count or not batch_ids:
            break
        retstart += len(batch_ids)
    print(f"  esearch fetched={len(all_ids)}/{count}")
    return all_ids


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


def _extract_pmid_from_linkset(linkset):
    """Extract source PMID string from an elink linkset response.

    NCBI elink returns ids as either:
      - flat strings: ["15703411"]
      - dicts: [{"idtype": "pubmed", "value": "15703411"}]
    """
    ids = linkset.get("ids", [])
    if not ids:
        return None
    first = ids[0]
    if isinstance(first, dict):
        return str(first.get("value", ""))
    return str(first)


def resolve_to_geo(pmids):
    """Per-PMID elink -> GEO accession lookup.

    Uses individual elink calls (not batched) because NCBI's batch elink
    response merges ALL GDS UIDs into a single linkset with no per-source
    mapping, making batch results assign every UID to the first PMID.
    """
    pmid_to_uid = {}
    elink_ok = 0
    elink_fail = 0
    for pmid in pmids:
        try:
            elink = ncbi_post(f"{EUTILS}/elink.fcgi", {
                "dbfrom": "pubmed", "db": "gds", "id": pmid,
                "retmode": "json",
            })
        except RuntimeError as e:
            print(f"    [WARN] elink failed for PMID {pmid}: {e}")
            elink_fail += 1
            continue
        for linkset in elink.get("linksets", []):
            src = _extract_pmid_from_linkset(linkset)
            if src != pmid:
                continue
            for db_block in linkset.get("linksetdbs", []):
                for uid in db_block.get("links", []):
                    pmid_to_uid.setdefault(pmid, []).append(uid)
        if pmid in pmid_to_uid:
            elink_ok += 1
        time.sleep(0.35)

    all_uids = list(set(u for uids in pmid_to_uid.values() for u in uids))

    uid_to_acc = {}
    for batch in chunked(all_uids, 100):
        try:
            esum = ncbi_post(f"{EUTILS}/esummary.fcgi", {
                "db": "gds", "id": ",".join(batch), "retmode": "json",
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

    for pmid, accs in pmid_to_geo.items():
        if len(accs) > 5:
            print(f"    [WARN] PMID {pmid} has {len(accs)} accessions "
                  f"(>5 — possible contamination): {accs}")

    unresolved = [p for p in pmids if p not in pmid_to_geo]
    print(f"  elink: {elink_ok}/{len(pmids)} resolved, "
          f"{elink_fail} failed, {len(unresolved)} no GEO links")
    return pmid_to_geo, elink_ok


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
            "db": "gds", "id": ",".join(uids), "retmode": "json",
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
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    return any(re.search(p.replace('\u2018', "'").replace('\u2019', "'"),
                         text, re.IGNORECASE) for p in patterns)


def find_sample_size_snippets(text):
    if not isinstance(text, str):
        return []
    return [m.group(0).strip()
            for m in SAMPLE_SIZE_PATTERN.finditer(text)][:3]


def condition_variants(condition):
    """Generate liberal disease-name variants from a condition string.

    Examples:
        "Alzheimer's disease" -> ["Alzheimer's disease", "Alzheimers disease", "Alzheimer"]
        "breast cancer"       -> ["breast cancer", "breast"]
    """
    variants = [condition]
    if "'" in condition:
        variants.append(condition.replace("'", ""))
    words = condition.split()
    if len(words) > 1:
        variants.append(words[0])
    return list(dict.fromkeys(variants))


def condition_to_pubmed_query(condition, tissue_terms):
    """Build a PubMed query from condition + tissue + RNA-seq method."""
    disease = condition_variants(condition)
    disease_part = " OR ".join(
        f'"{v}"[Title/Abstract]' if " " in v else f'{v}[Title/Abstract]'
        for v in disease
    )
    tissue_part = " OR ".join(
        f'"{t}"[Title/Abstract]' if " " in t else f'{t}[Title/Abstract]'
        for t in tissue_terms
    )
    method_part = (
        'RNA-seq[Title/Abstract] OR "RNA sequencing"[Title/Abstract] '
        'OR transcriptom*[Title/Abstract]'
    )
    return f"({disease_part}) AND ({tissue_part}) AND ({method_part})"


def condition_to_case_patterns(condition):
    """Generate case-control detection patterns from a condition.

    Returns a list of regex patterns that match the condition in text,
    used to flag papers/studies that mention the disease of interest.
    """
    variants = condition_variants(condition)
    patterns = []
    for v in variants:
        if " " in v:
            patterns.append(re.escape(v))
        else:
            patterns.append(r"\b" + re.escape(v) + r"\b")
    return patterns


def main():
    global TISSUE_SYNONYMS
    import argparse
    parser = argparse.ArgumentParser(
        description='Literature-first case-control RNA-seq search')
    parser.add_argument('--condition', required=True,
                        help='Disease/condition of interest (e.g., "Alzheimer\'s disease")')
    parser.add_argument('--tissue-synonyms',
                        default=','.join(PUBMED_TISSUE_TERMS),
                        help='Comma-separated list of tissue synonyms')
    parser.add_argument('--library-filter-mode',
                        choices=['strict', 'allow-no-info', 'no-polyA'],
                        default='no-polyA',
                        help='How to treat missing library selection')
    parser.add_argument('--human-only', action='store_true', default=True,
                        help='Filter to human studies only (default: on)')
    parser.add_argument('--no-human-filter', dest='human_only',
                        action='store_false',
                        help='Disable human-only filter')
    args = parser.parse_args()
    TISSUE_SYNONYMS = [s.strip() for s in
                       args.tissue_synonyms.split(',') if s.strip()]

    case_patterns = condition_to_case_patterns(args.condition)
    print(f"Condition: {args.condition}")
    print(f"  Disease variants: {condition_variants(args.condition)}")
    print(f"  Case/control patterns: {case_patterns}")

    # -----------------------------------------------------
    print("Searching PubMed...")
    query = condition_to_pubmed_query(args.condition, TISSUE_SYNONYMS)
    print(f"  Query: {query[:200]}...")
    if args.human_only:
        query = f"({query}) {HUMAN_FILTER}"
        print("  Human-only filter: ON (exclude mouse/rat/macaque/etc.)")
    else:
        print("  Human-only filter: OFF")
    pmids = esearch_pubmed(query, RETMAX)

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
                abstract, case_patterns),
            "sample_size_snippets": find_sample_size_snippets(abstract),
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "abstract": abstract.strip()[:1000],
        })

    df = pd.DataFrame(rows)

    if args.human_only and len(df):
        df["non_human_species"] = df["title"].apply(
            lambda t: matches_any(t, NON_HUMAN_PATTERNS))
        n_non_human = df["non_human_species"].sum()
        if n_non_human:
            print(f"  Excluded {n_non_human} papers with non-human species "
                  f"in title (mouse/rat/macaque/etc.)")
            df = df[~df["non_human_species"]]
        df = df.drop(columns=["non_human_species"])

    df["promising"] = (
        df["mentions_control"]
        & df["case_control_match"]
        & ~df["likely_single_cell"]
        & ~df["staging_design_signal"]
    )
    df = df.sort_values("promising", ascending=False)

    print("Resolving promising papers to GEO accessions...")
    promising_pmids = df.loc[df["promising"], "pmid"].tolist()
    if promising_pmids:
        pmid_to_geo, elink_ok = resolve_to_geo(promising_pmids)
    else:
        pmid_to_geo, elink_ok = {}, 0

    fallback_ok = 0
    fallback_fail = 0
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

    def resolution_reason(row):
        if row["geo_accessions"]:
            return "resolved"
        if not row["promising"]:
            return "not_promising"
        return "no_geo_link_found"

    df["geo_resolution_reason"] = df.apply(resolution_reason, axis=1)

    df.to_csv("candidate_papers.csv", index=False)

    n_total = len(df)
    n_promising = df["promising"].sum()
    n_resolved = (df["geo_resolution_reason"] == "resolved").sum()
    n_unresolved = (df["geo_resolution_reason"] == "no_geo_link_found").sum()
    n_not_promising = (df["geo_resolution_reason"] == "not_promising").sum()

    print(f"\nDone. {n_total} papers total, "
          f"{n_promising} flagged promising.")
    print(f"GEO resolution: {n_resolved}/{n_promising} promising papers "
          f"resolved ({n_resolved/n_promising*100:.0f}%)" if n_promising
          else "GEO resolution: no promising papers")
    if n_unresolved:
        print(f"  Unresolved: {n_unresolved} papers "
              f"(no GEO link found via elink or title search)")
    if n_not_promising:
        print(f"  Not promising: {n_not_promising} papers "
              f"(filtered out before GEO resolution)")
    print("Saved to candidate_papers.csv")
    print()
    cols = ["pmid", "title", "year", "mentions_control",
            "likely_single_cell", "staging_design_signal",
            "geo_accessions", "geo_resolution_reason"]
    print(df.loc[df["promising"], cols].to_string(index=False))

    print()
    print("=== REGRESSION METRICS ===")
    if n_promising:
        print(f"PubMed: papers_found={n_total} | promising={n_promising} "
              f"| elink_resolved={elink_ok} "
              f"| fallback_resolved={fallback_ok} "
              f"| total_resolved={n_resolved}/{n_promising} "
              f"({n_resolved/n_promising*100:.0f}%)")
    else:
        print("PubMed: no promising papers")
    print("==========================")


if __name__ == "__main__":
    main()
