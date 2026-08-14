#!/usr/bin/env python3
"""
generate_verified_candidates.py

Merges literature‑first and SRA‑first candidate tables,
adds confidence scores, and writes verified_candidates.csv.
"""

import pandas as pd
import csv

LIT_CSV = "candidate_papers.csv"
SRA_CSV = "candidate_datasets.csv"
OUT_CSV = "verified_candidates.csv"

FIELDS = [
    "pmid",
    "title",
    "accession(s)",
    "repository",
    "n_cases",
    "n_controls",
    "tissue_region",
    "assay_type",
    "library_prep",
    "verification_notes",
    "confidence",
]

def compute_confidence(row):
    # Low if any exclusion flag
    if row.get("disease_exclude_flag") or row.get("likely_single_cell") or row.get("likely_specialized_assay"):
        return "low"
    # Sample‑size tier
    n = int(row.get("n_samples") or 0)
    if n >= 30:
        return "high"
    elif n >= 20:
        return "medium"
    else:
        return "low"

def main():
    lit = pd.read_csv(LIT_CSV, dtype=str).fillna("")
    try:
        sra = pd.read_csv(SRA_CSV, dtype=str).fillna("")
    except Exception:
        sra = pd.DataFrame(columns=[])


    # ---- literature stream ----
    lit["accession(s)"] = lit["geo_accessions"].apply(lambda x: ";".join(eval(x)) if x else "")
    lit["repository"] = lit["geo_accessions"].apply(lambda x: "GEO" if x else "unknown")
    lit["pmid"] = lit["pmid"]
    lit["title"] = lit["title"]
    lit["n_cases"] = ""
    lit["n_controls"] = ""
    lit["tissue_region"] = "prefrontal cortex"
    lit["assay_type"] = "bulk"
    lit["library_prep"] = lit["library_selection_match"].apply(lambda v: "total/small RNA" if v else "")
    lit["verification_notes"] = lit.apply(
        lambda r: f"library_sel={r['library_selection_match']}; case_ctrl={r['case_control_match']}", axis=1
    )
    lit["confidence"] = lit.apply(compute_confidence, axis=1)

    # ---- SRA stream ----
    if "study_accession" in sra.columns:
        sra["accession(s)"] = sra["study_accession"]
    else:
        sra["accession(s)"] = ""
    sra["repository"] = "SRA"
    sra["pmid"] = ""
    sra["title"] = sra["study_title"] if "study_title" in sra.columns else ""
    sra["n_cases"] = ""
    sra["n_controls"] = ""
    sra["tissue_region"] = "prefrontal cortex"
    sra["assay_type"] = "bulk"
    sra["library_prep"] = sra["library_selection"] if "library_selection" in sra.columns else ""
    sra["verification_notes"] = sra.apply(
        lambda r: f"library_sel={r.get('library_selection','')}; case_ctrl={r.get('case_control_match','')}", axis=1
    )
    sra["confidence"] = sra.apply(compute_confidence, axis=1)

    # ---- combine & dedupe ----
    combined = pd.concat([lit[FIELDS], sra[FIELDS]], ignore_index=True)
    combined = combined.drop_duplicates(subset=["accession(s)"])

    # ---- write output ----
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(combined.to_dict(orient="records"))

    print(f"✔️  generated {OUT_CSV} with {len(combined)} rows")

if __name__ == "__main__":
    main()
