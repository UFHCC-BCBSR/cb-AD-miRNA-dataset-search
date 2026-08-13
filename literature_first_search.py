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
RETMAX = 300

# ---------------------------------------------------------------------
# 2. Abstract-text signals -- these are what actually distinguish a
#    usable case-control bulk study from a staging/single-cell one,
#    based on what SRA metadata has repeatedly failed to surface.
# ---------------------------------------------------------------------
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
    """Returns {pmid: abstract_text} for a batch of PMIDs."""
    out = {}
    for batch in chunked(pmids, 100):
        r = requests.get(f"{EUTILS}/efetch.fcgi", params={
            "db": "pubmed", "id": ",".join(batch),
            "rettype": "abstract", "retmode": "text",
        }, timeout=TIMEOUT)
        # PubMed's plain-text abstract format separates records with blank
        # lines and numbers them "1.", "2.", ... -- split on that pattern.
        records = re.split(r"\n\d+\.\s", "\n" + r.text)
        for pmid, rec in zip(batch, records[1:] if len(records) > len(batch) else records):
            out[pmid] = rec
        time.sleep(0.4)
    return out


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


def resolve_to_geo(pmids):
    """Batched PMID -> linked GEO accession lookup (elink + esummary)."""
    gds_uids = []
    pmid_to_uid = {}
    for batch in chunked(pmids, 200):
        elink = requests.get(f"{EUTILS}/elink.fcgi", params={
            "dbfrom": "pubmed", "db": "gds", "id": ",".join(batch), "retmode": "json",
        }, timeout=TIMEOUT).json()
        for linkset in elink.get("linksets", []):
            src_pmid = linkset.get("ids", [None])[0]
            for db_block in linkset.get("linksetdbs", []):
                for uid in db_block.get("links", []):
                    gds_uids.append(uid)
                    pmid_to_uid.setdefault(str(src_pmid), []).append(uid)
        time.sleep(0.4)

    uid_to_acc = {}
    for batch in chunked(list(set(gds_uids)), 200):
        esum = requests.get(f"{EUTILS}/esummary.fcgi", params={
            "db": "gds", "id": ",".join(batch), "retmode": "json",
        }, timeout=TIMEOUT).json()
        result = esum.get("result", {})
        for uid in result.get("uids", []):
            uid_to_acc[uid] = result.get(uid, {}).get("accession", "")
        time.sleep(0.4)

    pmid_to_geo = {}
    for pmid, uids in pmid_to_uid.items():
        accs = sorted(set(uid_to_acc.get(u, "") for u in uids if uid_to_acc.get(u)))
        pmid_to_geo[pmid] = accs
    return pmid_to_geo


def matches_any(text, patterns):
    if not isinstance(text, str):
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def find_sample_size_snippets(text):
    if not isinstance(text, str):
        return []
    return [m.group(0).strip() for m in SAMPLE_SIZE_PATTERN.finditer(text)][:3]


def main():
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
        & ~df["likely_single_cell"]
        & ~df["staging_design_signal"]
    )
    df = df.sort_values("promising", ascending=False)

    print("Resolving promising papers to GEO accessions...")
    promising_pmids = df.loc[df["promising"], "pmid"].tolist()
    pmid_to_geo = resolve_to_geo(promising_pmids) if promising_pmids else {}
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
