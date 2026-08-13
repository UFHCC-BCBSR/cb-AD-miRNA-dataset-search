# Run this once per machine to install R dependencies, THEN:
#   renv::init()
#   renv::snapshot()
# to generate a real renv.lock from the resolved versions.

# Non-interactive installs need an explicit CRAN mirror, or install.packages()
# errors out instead of prompting.
options(repos = c(CRAN = "https://cloud.r-project.org"))

if (!requireNamespace("BiocManager", quietly = TRUE)) {
  install.packages("BiocManager")
}

# Bioconductor packages
BiocManager::install(c(
  "recount3",
  "GenomicRanges",
  "IRanges",
  "megadepth"
), update = FALSE, ask = FALSE)

# CRAN packages
install.packages(c("dplyr", "tibble"))

# --- Point reticulate at the project's Python venv before installing synapser ---
# Recent reticulate versions default to an ephemeral, uv-managed Python env
# that has NO pip -- synapser's installer needs pip to fetch synapseclient,
# so it fails with "No module named 'pip'" unless we point reticulate at a
# real venv first. Use the same .venv you created for requirements.txt
# (it already has synapseclient installed).
if (!requireNamespace("reticulate", quietly = TRUE)) install.packages("reticulate")
library(reticulate)

venv_python <- file.path(".venv", "bin", "python")  # adjust path if your venv lives elsewhere
if (!file.exists(venv_python)) {
  stop(
    "No .venv found at ./.venv. Create it first:\n",
    "  python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt\n",
    "then re-run this script."
  )
}
use_python(venv_python, required = TRUE)

# Sage Bionetworks repo (not CRAN/Bioconductor) for AMP-AD / Synapse access
install.packages("synapser",
  repos = c("http://ran.synapse.org", "https://cloud.r-project.org")
)
