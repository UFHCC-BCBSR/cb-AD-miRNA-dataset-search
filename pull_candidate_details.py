#!/usr/bin/env python3
"""
pull_candidate_details.py

Pulls detailed, sample-level metadata for the top candidate studies and
attempts to auto-detect diagnosis/group, age, and sex columns -- these
column names vary per study (learned earlier: SRA auto-flattens sample
attributes into study-specific columns when detailed=True, e.g. one study
had 'cognitive test' and 'strain', another might have 'diagnosis' and
'age_death').

Usage:
    python pull_candidate_details.py
"""

import pandas as pd
from pysradb import SRAweb

# Update this list based on which studies you want to dig into.
TARGET_STUDIES = [
    "SRP415133",  # transcriptomic progression of AD, BA46 -- cDNA prep
    "SRP500433",  # AD resilience signatures, layer 4 neurons -- cDNA prep
    "SRP355130",  # psychosis in AD, DLPFC -- prep unclear ("other")
]

# Keywords to guess at which columns hold diagnosis/age/sex, since exact
# column names aren't standardized across studies.
DIAGNOSIS_KEYWORDS = ["diagnos", "disease", "condition", "group", "phenotype",
                       "status", "case", "control", "braak", "cerad"]
AGE_KEYWORDS = ["age"]
SEX_KEYWORDS = ["sex", "gender"]


def guess_columns(columns, keywords):
    return [c for c in columns if any(k in c.lower() for k in keywords)]


def main():
    db = SRAweb()

    for acc in TARGET_STUDIES:
        print(f"\n{'='*70}\n{acc}\n{'='*70}")
        try:
            detailed = db.sra_metadata(acc, detailed=True)
        except Exception as e:
            print(f"  Failed to fetch: {e}")
            continue

        detailed.to_csv(f"{acc}_detailed.csv", index=False)
        print(f"  {len(detailed)} rows, {detailed['sample_accession'].nunique()} unique samples")
        print(f"  Saved full detail to {acc}_detailed.csv")

        diag_cols = guess_columns(detailed.columns, DIAGNOSIS_KEYWORDS)
        age_cols = guess_columns(detailed.columns, AGE_KEYWORDS)
        sex_cols = guess_columns(detailed.columns, SEX_KEYWORDS)

        print(f"\n  Likely diagnosis/group column(s): {diag_cols or 'NONE FOUND -- check full column list manually'}")
        for c in diag_cols:
            print(f"    {c}: {detailed[c].value_counts().to_dict()}")

        print(f"\n  Likely age column(s): {age_cols or 'NONE FOUND'}")
        for c in age_cols:
            print(f"    {c}: {detailed[c].dropna().unique()[:10]} ...")

        print(f"\n  Likely sex column(s): {sex_cols or 'NONE FOUND'}")
        for c in sex_cols:
            print(f"    {c}: {detailed[c].value_counts().to_dict()}")

        if not diag_cols:
            print(f"\n  Full column list for manual review:")
            print(f"    {detailed.columns.tolist()}")


if __name__ == "__main__":
    main()
