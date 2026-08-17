#!/usr/bin/env python3
"""
ad_pfc_dataset_search.py

Candidate dataset search for AD vs. control bulk RNA-seq in prefrontal
cortex, using MetaSRA-style concept matching instead of exact-phrase
AND search.

Why this is different from the earlier approach:
Exact-phrase search (e.g. '"Alzheimer" AND "prefrontal cortex"') requires
both concepts to appear as literal adjacent-ish phrases in a study's
title/description. That's brittle -- a study using "BA9" instead of
"prefrontal cortex", or one that only names the tissue in its abstract
and not its SRA title, gets silently missed.

MetaSRA's actual fix for this is to normalize free text into ontology
terms so unrelated-looking strings (BA9, DLPFC, "prefrontal cortex") are
recognized as the same underlying concept. We don't have MetaSRA's live
database (it appears to be a frozen ~2017-2018 snapshot, too stale for
recent studies), so this script hand-rolls the same logic against a
live SRA search: cast a wide net with loose, disease-only queries, then
independently check EVERY returned study for tissue/disease/assay
concepts across ALL available text fields using synonym sets, rather
than requiring any of it to be phrased a particular way up front.

Usage:
    python ad_pfc_dataset_search.py

Output:
    candidate_datasets.csv           -- one row per candidate STUDY
    candidate_datasets_full_runs.csv -- one row per matching SRA run
"""

import re
import time
import xml.etree.ElementTree as ET
import pandas as pd
import requests
from pysradb import SRAweb

# ---------------------------------------------------------------------
# 1. Synonym sets (the "ontology" -- expand these anytime a reviewer
#    spots a real study using wording not covered here)
# ---------------------------------------------------------------------

TISSUE_SYNONYMS = [
    r"prefrontal cortex", r"dorsolateral prefrontal", r"\bdlpfc\b",
    r"\bba ?9\b", r"\bba ?10\b", r"\bba ?46\b",
    r"frontal cortex", r"frontal lobe", r"frontal gyrus",
    r"middle frontal gyrus", r"superior frontal gyrus",
    r"brodmann area 9", r"brodmann area 10", r"\bpfc\b",
]

# Conditions that overlap in free text with Alzheimer's but are NOT it --
# flagged rather than silently excluded, so a human makes the final call.
DISEASE_EXCLUDE_SYNONYMS = [
    r"frontotemporal dementia", r"\bftd\b", r"vascular dementia",
    r"lewy body dementia", r"parkinson",
]

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

SINGLE_CELL_SYNONYMS = [
    r"single.cell", r"single.nuclei", r"single.nucleus", r"snrna",
    r"scrna", r"10x genomics", r"sn-rna", r"sc-rna",
]

SPECIALIZED_ASSAY_SYNONYMS = [
    r"m6a", r"merip", r"meripseq", r"rna.ip", r"immunoprecipitation",
    r"ribo-seq", r"ribosome profiling", r"bisulfite",
]


def matches_any(text, patterns):
    if not isinstance(text, str):
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def matched_terms(text, patterns):
    if not isinstance(text, str):
        return []
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def fetch_biosample_tissue(biosample_ids, batch_size=200):
    """Fetch source_name from BioSample for a list of biosample accessions.

    Returns {biosample_accession: source_name_string}.
    """
    import xml.etree.ElementTree as ET
    out = {}
    ids_list = list(set(biosample_ids))
    for i in range(0, len(ids_list), batch_size):
        batch = ids_list[i:i + batch_size]
        try:
            r = requests.post(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                data={"db": "biosample", "id": ",".join(batch),
                      "retmode": "xml"},
                timeout=30,
                headers={"User-Agent": "ad-rna-seq-search/1.0"},
            )
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for sample in root.findall(".//BioSample"):
                acc = sample.get("accession", "")
                for attr in sample.findall(".//Attribute"):
                    name = attr.get("attribute_name",
                                    attr.get("harmonized_name", ""))
                    if name == "source_name" and attr.text:
                        out[acc] = attr.text.strip()
        except Exception as e:
            print(f"  [WARN] BioSample fetch failed for batch: {e}")
        time.sleep(0.4)
    return out


def main():
    global TISSUE_SYNONYMS, CASE_CONTROL_PATTERNS
    import argparse
    parser = argparse.ArgumentParser(description='SRA AD vs control search with tissue & library filters')
    parser.add_argument('--tissue-synonyms', default=','.join(TISSUE_SYNONYMS),
                        help='Comma‑separated list of tissue synonyms')
    parser.add_argument('--case-control-regex', default='|'.join(CASE_CONTROL_PATTERNS),
                        help='Regex pattern for case/control detection')
    parser.add_argument('--library-filter-mode', choices=['strict','allow-no-info','no-polyA'],
                        default='no-polyA', help='How to treat missing library selection')
    args = parser.parse_args()
    TISSUE_SYNONYMS = [s.strip() for s in args.tissue_synonyms.split(',') if s.strip()]
    CASE_CONTROL_PATTERNS = [args.case_control_regex]
    # library_filter_mode not used directly here; will be passed downstream
    db = SRAweb()

    # -------------------------------------------------------------
    # 2. Cast a wide net: DISEASE term alone, no tissue requirement
    #    in the query itself. Tissue is checked afterward, across
    #    every field we can see -- this is the key change from the
    #    AND-phrase approach.
    # -------------------------------------------------------------
    broad_queries = ["Alzheimer", "Alzheimer's disease", "dementia"]

    print("Searching SRA with broad, disease-only queries...")
    raw_hits = []
    for q in broad_queries:
        r = db.search_sra(search_str=f'"{q}"')
        if r is not None and len(r):
            r["query_used"] = q
            raw_hits.append(r)
            print(f"  {q!r:<25} -> {len(r)} rows")

    raw = pd.concat(raw_hits, ignore_index=True) if raw_hits else pd.DataFrame()
    if len(raw) and "run_accession" in raw.columns:
        raw = raw.drop_duplicates(subset=["run_accession"])
    print(f"Total unique runs after dedup: {len(raw)}")

    # -------------------------------------------------------------
    # 3. Hard filters: human, RNA-seq only
    # -------------------------------------------------------------
    if len(raw):
        raw = raw[raw["organism_name"] == "Homo sapiens"]
        raw = raw[raw["library_strategy"].str.contains("RNA-Seq", case=False, na=False)]
        # Keep only runs with library selection that retains small RNAs (total/small RNA, miRNA, size‑selected)
        raw = raw[ raw["library_selection"].isna() | raw["library_selection"].str.contains("total|small|mirna|size", case=False, na=False) ]
    print(f"After human + RNA-seq filter: {len(raw)}")

    # -------------------------------------------------------------
    # 3b. Fetch tissue info from BioSample (source_name attribute)
    # -------------------------------------------------------------
    if len(raw) and "biosample" in raw.columns:
        bs_ids = raw["biosample"].dropna().unique().tolist()
        print(f"  Fetching tissue info from {len(bs_ids)} BioSample records...")
        tissue_map = fetch_biosample_tissue(bs_ids)
        raw["biosource"] = raw["biosample"].map(
            lambda b: tissue_map.get(b, "") if pd.notna(b) else "")
        n_with_tissue = (raw["biosource"] != "").sum()
        print(f"  Got tissue info for {n_with_tissue}/{len(raw)} runs")
        if n_with_tissue:
            print(f"  Sample tissues: {raw['biosource'].value_counts().head(10).to_dict()}")
    else:
        raw["biosource"] = ""

    # -------------------------------------------------------------
    # 4. Concept matching across every available text field
    # -------------------------------------------------------------
    text_cols = [c for c in ["biosource", "study_title", "experiment_title",
                             "experiment_desc", "sample_title"]
                  if c in raw.columns]

    def row_text(row):
        return " | ".join(str(row[c]) for c in text_cols if pd.notna(row[c]))

    if len(raw):
        raw = raw.copy()
        raw["_all_text"] = raw.apply(row_text, axis=1)
        raw["tissue_match"] = raw["_all_text"].apply(lambda t: matches_any(t, TISSUE_SYNONYMS))
        raw["tissue_terms_found"] = raw["_all_text"].apply(lambda t: matched_terms(t, TISSUE_SYNONYMS))
        raw["disease_exclude_flag"] = raw["_all_text"].apply(lambda t: matches_any(t, DISEASE_EXCLUDE_SYNONYMS))
        raw["likely_single_cell"] = raw["_all_text"].apply(lambda t: matches_any(t, SINGLE_CELL_SYNONYMS))
        raw["likely_specialized_assay"] = raw["_all_text"].apply(lambda t: matches_any(t, SPECIALIZED_ASSAY_SYNONYMS))
        raw["case_control_match"] = raw["_all_text"].apply(lambda t: matches_any(t, CASE_CONTROL_PATTERNS))

    candidates = raw[raw["tissue_match"]] if len(raw) else raw
    print(f"After tissue-concept match (any synonym, any field): {len(candidates)}")

    if len(raw) and "tissue_match" in raw.columns:
        print("  Per-synonym match counts:")
        for pat in TISSUE_SYNONYMS:
            count = raw["_all_text"].apply(
                lambda t: bool(re.search(pat, str(t), re.IGNORECASE))
            ).sum()
            if count > 0:
                print(f"    {pat!r:<35} -> {count} runs")
        print("  Sample _all_text for 5 runs (first 150 chars):")
        for _, row in raw.head(5).iterrows():
            txt = str(row.get("_all_text", ""))[:150]
            print(f"    {row.get('run_accession','?')}: {txt}")

    # -------------------------------------------------------------
    # 5. Roll up to STUDY level for a reviewable summary
    # -------------------------------------------------------------
    if len(candidates):
        summary = (
            candidates.groupby("study_accession")
            .agg(
                study_title=("study_title", "first"),
                n_runs=("run_accession", "nunique"),
                n_samples=("sample_accession", "nunique"),
                tissue_terms_found=("tissue_terms_found", lambda x: sorted(set(t for lst in x for t in lst))),
                disease_exclude_flag=("disease_exclude_flag", "any"),
                likely_single_cell=("likely_single_cell", "any"),
                likely_specialized_assay=("likely_specialized_assay", "any"),
                instrument_models=("instrument_model", lambda x: sorted(set(x))),
            )
            .reset_index()
                .sort_values("n_samples", ascending=False)
              )
        # Keep only studies with at least 30 total samples (approximate target)
        summary = summary[summary["n_samples"] >= 30]
    else:
        summary = pd.DataFrame()

    summary.to_csv("candidate_datasets.csv", index=False)
    candidates.to_csv("candidate_datasets_full_runs.csv", index=False)

    print()
    print(f"Done. {len(summary)} candidate studies -> candidate_datasets.csv")
    print(f"({len(candidates)} matching runs -> candidate_datasets_full_runs.csv)")
    if len(summary):
        print()
        cols = ["study_accession", "study_title", "n_samples",
                "disease_exclude_flag", "likely_single_cell", "likely_specialized_assay"]
        print(summary[cols].to_string(index=False))

    print()
    n_deduped = len(raw) if len(raw) else 0
    n_human_rnaseq = n_deduped
    n_tissue = len(candidates)
    n_final = len(summary)
    print("=== REGRESSION METRICS ===")
    print(f"SRA: runs_deduped={n_deduped} | after_human_rnaseq={n_human_rnaseq} "
          f"| after_tissue={n_tissue} | final_datasets={n_final}")
    print("PubMed: (see literature_first_search.py output)")
    print("==========================")


if __name__ == "__main__":
    main()
