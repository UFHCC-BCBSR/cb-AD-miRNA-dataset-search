# AD PFC Dataset Search

Finding public RNA-seq datasets suitable for comparing expression of a
custom noncoding region between Alzheimer's disease (AD) patients and
healthy controls.

## Target criteria

| Criterion | Target |
|---|---|
| Tissue | Prefrontal cortex (PFC) / DLPFC |
| Groups | AD vs. control, age-matched |
| Sample size | 30-50 samples per group |
| Library prep | Random-primed preferred; long-read if available |
| Covariates | Sex (optional) |

The target region isn't in standard reference annotations (GENCODE/RefSeq),
so any dataset used will need custom quantification regardless of source.

## What's in this repo

- **`ad_pfc_dataset_search.py`** -- standalone script that searches SRA for
  candidate studies. Uses broad, disease-only queries plus independent
  synonym-based matching for tissue terms (BA9/BA10/BA46, DLPFC, frontal
  gyrus, etc.) across all available metadata fields, rather than requiring
  an exact phrase match. Also flags likely single-cell/single-nucleus
  studies and specialized assays (e.g. methylation, RNA modification) that
  report as "RNA-seq" but aren't standard expression profiling.
- **`AD_PFC_dataset_search.qmd`** -- exploratory Quarto notebook documenting
  the SRA search process step by step, plus a scaffold for querying the
  AMP-AD/Synapse consortium data (ROSMAP, MSBB, Mayo) once access is
  approved.
- **`requirements.txt`** -- Python dependencies.
- **`install.R`** -- R/Bioconductor dependency bootstrap (recount3,
  synapser, and related packages needed for the Synapse/AMP-AD workflow).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Rscript install.R
```

## Usage

```bash
source .venv/bin/activate
python ad_pfc_dataset_search.py
```

Produces `candidate_datasets.csv` (one row per candidate study) and
`candidate_datasets_full_runs.csv` (one row per matching SRA run).

## Status

- Literature search completed: 300 papers scanned, 64 flagged promising.
- Verification pipeline produced `verified_candidates.csv` with high/low confidence entries.
- Still no public bulk RNA‑seq dataset meets the 30‑50 samples per group target; further controlled‑access sources (ROSMAP, MSBB, Mayo) remain pending.


- Public SRA search: complete first pass, 12 candidate studies identified,
  5 look promising on initial title/metadata review. Per-study AD-vs-control
  group sizes not yet confirmed.
- AMP-AD/Synapse (ROSMAP, MSBB, Mayo): likely the best source for reaching
  the 30-50/group target, but requires a controlled-access data use request
  -- in progress.
- Library prep (random-primed vs. poly-A) not yet confirmed for any
  candidate.
- No public long-read PFC dataset exists at a usable sample size; would
  only serve as a secondary validation check, not a primary cohort.
