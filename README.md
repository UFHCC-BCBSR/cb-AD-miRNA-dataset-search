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

- Literature‑first search completed; **367 papers examined, 74 flagged promising** for miRNA‑compatible bulk RNA‑seq.
- SRA concept‑matching search completed; **0 candidate studies** passed tissue, library‑prep, case/control, and sample‑size filters.
- `verified_candidates.csv` now contains **11 low‑confidence entries** (all GEO studies) with library‑selection details unavailable in abstracts.
- No public dataset meets the ≥30 cases / ≥30 controls target; the best available studies lack explicit group counts.
- Controlled‑access cohorts (ROSMAP, MSBB, Mayo) remain the most promising source for achieving the required sample size.


