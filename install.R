# Run this once per machine to install R dependencies, THEN:
#   renv::init()
#   renv::snapshot()
# to generate a real renv.lock from the resolved versions.

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

# Sage Bionetworks repo (not CRAN/Bioconductor) for AMP-AD / Synapse access
install.packages("synapser",
  repos = c("http://ran.synapse.org", "https://cloud.r-project.org")
)

# synapser requires the Python synapseclient package as its backend
# (see requirements.txt) -- make sure reticulate points at the same
# Python env where you ran `pip install -r requirements.txt`.
