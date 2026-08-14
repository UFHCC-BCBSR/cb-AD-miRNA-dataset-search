#!/usr/bin/env python3
"""
verify_sra_candidates.py

Create a high‑level verification CSV from the SRA search output
(`candidate_datasets.csv`). It adds the columns required by the project
specification and assigns a confidence level based on simple heuristics.

Columns produced:
    pmid, title, accession(s), repository, n_cases, n_controls,
    tissue_region, assay_type, library_prep, verification_notes, confidence

Because the SRA metadata does not provide case/control breakdown, those
fields are left blank. Confidence is derived from:
* No exclusion flags (disease_exclude_flag, likely_single_cell,
  likely_specialized_assay)
* Sample size (n_samples) – high if ≥30, medium 20‑29, low otherwise.
"""

import pandas as pd
import csv

INPUT = "candidate_datasets.csv"
OUTPUT = "verified_candidates_sra.csv"

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


def confidence_from(row):
    # Determine confidence level based on flags and sample size
    if row.get("disease_exclude_flag") or row.get("likely_single_cell") or row.get("likely_specialized_assay"):
        base = "low"
    else:
        base = "high"
    n = row.get("n_samples", 0)
    if isinstance(n, str):
        try:
            n = int(n)
        except ValueError:
            n = 0
    # Adjust based on sample count
    if n >= 30:
        level = "high"
    elif n >= 20:
        level = "medium"
    else:
        level = "low"
    # Combine: if any exclusion flag present, stay low regardless of count
    if base == "low":
        return "low"
    return level


def main():
    df = pd.read_csv(INPUT, dtype=str).fillna("")
    rows = []
    for _, r in df.iterrows():
        notes = []
        notes.append("Human RNA‑seq SRA study")
        if r.get("disease_exclude_flag"):
            notes.append("Disease exclusion flag present")
        if r.get("likely_single_cell"):
            notes.append("Likely single‑cell assay")
        if r.get("likely_specialized_assay"):
            notes.append("Specialized assay (e.g., MeRIP)")
        notes.append(f"{r.get('n_samples', '')} total samples reported")

        rows.append({
            "pmid": "",
            "title": r.get("study_title", ""),
            "accession(s)": r.get("study_accession", ""),
            "repository": "SRA",
            "n_cases": "",
            "n_controls": "",
            "tissue_region": "prefrontal cortex",
            "assay_type": "bulk" if not r.get("likely_single_cell") else "single‑cell",
            "library_prep": "",
            "verification_notes": "; ".join([n for n in notes if n]),
            "confidence": confidence_from(r),
        })
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {OUTPUT} with {len(rows)} rows")

if __name__ == "__main__":
    main()
