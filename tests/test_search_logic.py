"""Unit tests for pure-logic functions across the search pipeline.

Tests only local functions that do NOT make network calls.
Network-dependent functions (NCBI queries, pysradb) are excluded.
"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from literature_first_search import (
    condition_variants,
    condition_to_pubmed_query,
    condition_to_case_patterns,
    matches_any,
    find_sample_size_snippets,
    CONTROL_PATTERNS,
    SINGLE_CELL_PATTERNS,
    STAGING_ONLY_PATTERNS,
    NON_HUMAN_PATTERNS,
)
from ad_pfc_dataset_search import (
    condition_variants as sra_condition_variants,
    condition_to_sra_queries,
    condition_to_case_patterns as sra_condition_to_case_patterns,
    matches_any as sra_matches_any,
    SINGLE_CELL_SYNONYMS,
    SPECIALIZED_ASSAY_SYNONYMS,
    DISEASE_EXCLUDE_SYNONYMS,
)
from tissue_ontology import (
    normalize_for_match,
    matches_tissue,
)


# -------------------------------------------------------------------
# condition_variants
# -------------------------------------------------------------------
class TestConditionVariants:
    def test_apostrophe_removal(self):
        v = condition_variants("Alzheimer's disease")
        assert "Alzheimer's disease" in v
        assert "Alzheimers disease" in v

    def test_single_word(self):
        v = condition_variants("asthma")
        assert v == ["asthma"]

    def test_multi_word_adds_first_word(self):
        v = condition_variants("breast cancer")
        assert v[0] == "breast cancer"
        assert "breast" in v

    def test_deduplication(self):
        v = condition_variants("diabetes")
        assert len(v) == 1
        assert v[0] == "diabetes"

    def test_type2diabetes_no_apostrophe(self):
        v = condition_variants("type 2 diabetes")
        assert "type 2 diabetes" in v
        assert "type" in v

    def test_consistent_between_modules(self):
        c = "Alzheimer's disease"
        lit = condition_variants(c)
        sra = sra_condition_variants(c)
        assert lit == sra


# -------------------------------------------------------------------
# condition_to_pubmed_query
# -------------------------------------------------------------------
class TestConditionToPubmedQuery:
    def test_basic_structure(self):
        q = condition_to_pubmed_query("cancer", ["brain"])
        assert "(cancer[Title/Abstract])" in q
        assert "(brain[Title/Abstract])" in q
        assert "RNA-seq[Title/Abstract]" in q
        assert q.count("AND") == 2

    def test_multi_word_disease_quoted(self):
        q = condition_to_pubmed_query("breast cancer", ["liver"])
        assert '"breast cancer"[Title/Abstract]' in q
        assert "liver[Title/Abstract]" in q

    def test_alzheimer_generates_variants(self):
        q = condition_to_pubmed_query(
            "Alzheimer's disease", ["prefrontal cortex", "DLPFC"]
        )
        assert "Alzheimer's disease" in q
        assert "Alzheimers disease" in q
        assert "Alzheimer" in q

    def test_tissue_list(self):
        q = condition_to_pubmed_query("X", ["tissueA", "tissueB"])
        assert "tissueA" in q
        assert "tissueB" in q


# -------------------------------------------------------------------
# condition_to_case_patterns
# -------------------------------------------------------------------
class TestConditionToCasePatterns:
    def test_single_word_gets_word_boundary(self):
        p = condition_to_case_patterns("Alzheimer")
        assert any("\\b" in pat for pat in p)

    def test_multi_word_no_word_boundary(self):
        p = condition_to_case_patterns("breast cancer")
        assert "breast\\ cancer" in p

    def test_alzheimer_apostrophe(self):
        p = condition_to_case_patterns("Alzheimer's disease")
        patterns_str = " ".join(p)
        assert "Alzheimer" in patterns_str

    def test_matches_in_text(self):
        p = condition_to_case_patterns("breast cancer")
        assert matches_any("patients with breast cancer", p)
        assert not matches_any("lung cancer study", p)

    def test_alzheimer_matches_in_abstract(self):
        p = condition_to_case_patterns("Alzheimer's disease")
        assert matches_any(
            "This study examined Alzheimer's disease progression", p
        )
        assert matches_any(
            "Alzheimers disease affects millions", p
        )

    def test_consistent_between_modules(self):
        c = "Alzheimer's disease"
        lit = condition_to_case_patterns(c)
        sra = sra_condition_to_case_patterns(c)
        assert lit == sra

    def test_curly_apostrophe_matches(self):
        p = condition_to_case_patterns("Alzheimer's disease")
        assert matches_any("Alzheimer\u2019s disease study", p)
        assert matches_any("Alzheimer's disease study", p)

    def test_curly_apostrophe_in_matches_any(self):
        assert matches_any("Alzheimer\u2019s disease", ["Alzheimer's disease"])
        assert matches_any("Alzheimer's disease", ["Alzheimer\u2019s disease"])


# -------------------------------------------------------------------
# condition_to_sra_queries
# -------------------------------------------------------------------
class TestConditionToSraQueries:
    def test_alzheimer(self):
        q = condition_to_sra_queries("Alzheimer's disease")
        assert "Alzheimer's disease" in q
        assert "Alzheimers disease" in q
        assert "Alzheimer's" in q

    def test_breast_cancer(self):
        q = condition_to_sra_queries("breast cancer")
        assert "breast cancer" in q
        assert "breast" in q

    def test_single_word(self):
        q = condition_to_sra_queries("asthma")
        assert q == ["asthma"]


# -------------------------------------------------------------------
# matches_any
# -------------------------------------------------------------------
class TestMatchesAny:
    def test_basic_match(self):
        assert matches_any("case control study", [r"\bcase\b"])

    def test_no_match(self):
        assert not matches_any("healthy volunteers only", [r"\bdisease\b"])

    def test_empty_text(self):
        assert not matches_any("", [r"\bcase\b"])

    def test_none_text(self):
        assert not matches_any(None, [r"\bcase\b"])

    def test_multiple_patterns(self):
        assert matches_any(
            "healthy subject", [r"\bcase\b", r"\bhealthy\b"]
        )

    def test_case_insensitive(self):
        assert matches_any("CASE study", [r"\bcase\b"])

    def test_sra_module_consistent(self):
        assert sra_matches_any("case control", [r"\bcase\b"])
        assert not sra_matches_any("case control", [r"\bdisease\b"])


# -------------------------------------------------------------------
# Built-in pattern lists exist and are non-empty
# -------------------------------------------------------------------
class TestPatternLists:
    def test_control_patterns(self):
        assert len(CONTROL_PATTERNS) > 0
        assert matches_any("healthy control", CONTROL_PATTERNS)

    def test_single_cell_patterns(self):
        assert len(SINGLE_CELL_PATTERNS) > 0
        assert matches_any("single-cell RNA-seq", SINGLE_CELL_PATTERNS)

    def test_staging_patterns(self):
        assert len(STAGING_ONLY_PATTERNS) > 0
        assert matches_any("Braak stage III", STAGING_ONLY_PATTERNS)

    def test_non_human_patterns(self):
        assert len(NON_HUMAN_PATTERNS) > 0
        assert matches_any("mouse model", NON_HUMAN_PATTERNS)

    def test_sra_single_cell(self):
        assert len(SINGLE_CELL_SYNONYMS) > 0
        assert matches_any("single-nucleus RNA-seq", SINGLE_CELL_SYNONYMS)

    def test_sra_specialized_assay(self):
        assert len(SPECIALIZED_ASSAY_SYNONYMS) > 0
        assert matches_any("MeRIP-seq", SPECIALIZED_ASSAY_SYNONYMS)

    def test_sra_disease_exclude(self):
        assert len(DISEASE_EXCLUDE_SYNONYMS) > 0
        assert matches_any("frontotemporal dementia", DISEASE_EXCLUDE_SYNONYMS)


# -------------------------------------------------------------------
# find_sample_size_snippets
# -------------------------------------------------------------------
class TestSampleSizeSnippets:
    def test_n_equals(self):
        snippets = find_sample_size_snippets("We enrolled n=50 participants.")
        assert len(snippets) >= 1
        assert "50" in snippets[0]

    def test_no_match(self):
        snippets = find_sample_size_snippets("No sample size mentioned.")
        assert snippets == []

    def test_empty(self):
        assert find_sample_size_snippets("") == []

    def test_none(self):
        assert find_sample_size_snippets(None) == []


# -------------------------------------------------------------------
# tissue_ontology: normalize_for_match
# -------------------------------------------------------------------
class TestNormalizeForMatch:
    def test_lowercases(self):
        assert normalize_for_match("Prefrontal Cortex") == "prefrontal cortex"

    def test_strips_curly_quotes(self):
        assert "\u2018" not in normalize_for_match("Alzheimer\u2019s disease")
        assert "\u2019" not in normalize_for_match("Alzheimer\u2019s disease")

    def test_strips_punctuation(self):
        result = normalize_for_match("prefrontal cortex (BA9)")
        assert "(" not in result
        assert ")" not in result
        assert "ba9" in result

    def test_collapses_whitespace(self):
        result = normalize_for_match("prefrontal   cortex")
        assert "  " not in result

    def test_normalizes_dashes(self):
        result = normalize_for_match("frontal\u2012cortex")
        assert "\u2012" not in result
        assert "frontal" in result
        assert "cortex" in result

    def test_non_string_returns_empty(self):
        assert normalize_for_match(None) == ""
        assert normalize_for_match(123) == ""

    def test_empty_string(self):
        assert normalize_for_match("") == ""


# -------------------------------------------------------------------
# tissue_ontology: matches_tissue
# -------------------------------------------------------------------
class TestMatchesTissue:
    def test_long_term_substring(self):
        matched, unmatched = matches_tissue(
            "dorsolateral prefrontal cortex", ["prefrontal cortex", "BA9"]
        )
        assert "prefrontal cortex" in matched
        assert "BA9" in unmatched

    def test_short_term_word_boundary(self):
        matched, unmatched = matches_tissue(
            "BA9 region", ["BA9", "BA10"]
        )
        assert "BA9" in matched
        assert "BA10" in unmatched

    def test_short_term_no_spurious(self):
        matched, unmatched = matches_tissue(
            "BA9 region", ["PFC"]
        )
        assert "PFC" in unmatched

    def test_case_insensitive(self):
        matched, unmatched = matches_tissue(
            "PREFRONTAL CORTEX", ["prefrontal cortex"]
        )
        assert "prefrontal cortex" in matched

    def test_non_string_input(self):
        matched, unmatched = matches_tissue(None, ["prefrontal cortex"])
        assert matched == []
        assert "prefrontal cortex" in unmatched

    def test_empty_text(self):
        matched, unmatched = matches_tissue("", ["prefrontal cortex"])
        assert matched == []
        assert "prefrontal cortex" in unmatched

    def test_empty_terms(self):
        matched, unmatched = matches_tissue("prefrontal cortex", [])
        assert matched == []
        assert unmatched == []

    def test_all_terms_empty_text(self):
        matched, unmatched = matches_tissue(None, ["prefrontal cortex", "BA9"])
        assert matched == []
        assert set(unmatched) == {"prefrontal cortex", "BA9"}
