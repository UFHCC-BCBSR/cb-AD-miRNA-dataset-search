"""UBERON ontology resolution for tissue terms.

Resolves a user's plain-language tissue name to an exhaustive set of
anatomical terms via the EBI OLS4 API, expanding down the UBERON hierarchy
to capture sub-regions, layers, and synonyms.

No API key required.
"""

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

import urllib.request
import urllib.parse

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
CACHE_DIR = "/tmp/ad_search_uberon_cache"
CACHE_TTL_DAYS = 30
CACHE_STALE_DAYS = 90


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_for_match(text):
    """Normalize text for case-insensitive substring matching.

    - NFKD unicode normalization
    - curly quotes / dashes to ASCII
    - strip punctuation (non-alphanumeric -> space)
    - collapse whitespace, lowercase
    """
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


# ---------------------------------------------------------------------------
# Tissue matching
# ---------------------------------------------------------------------------

def matches_tissue(text, terms):
    """Match tissue terms against text with normalization.

    Short terms (<=4 chars) use word-boundary matching.
    Longer terms use substring matching.
    Returns (matched_terms, unmatched_terms).
    """
    text_norm = normalize_for_match(text)
    if not text_norm:
        return [], list(terms)
    matched = []
    unmatched = []
    for term in terms:
        term_norm = normalize_for_match(term)
        if not term_norm:
            unmatched.append(term)
            continue
        if len(term_norm) <= 4:
            if re.search(r"\b" + re.escape(term_norm) + r"\b", text_norm):
                matched.append(term)
            else:
                unmatched.append(term)
        else:
            if term_norm in text_norm:
                matched.append(term)
            else:
                unmatched.append(term)
    return matched, unmatched


def matched_terms_tissue(text, terms):
    """Return list of terms that matched text (wrapper for compatibility)."""
    matched, _ = matches_tissue(text, terms)
    return matched


# ---------------------------------------------------------------------------
# OLS4 API
# ---------------------------------------------------------------------------

def _ols_get(url, retries=2, timeout=15):
    """GET with retries, User-Agent, and content-type check."""
    headers = {"User-Agent": "ad-search/1.0 (tissue-ontology)"}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "json" not in ct:
                    raise ValueError(f"Non-JSON response: {ct}")
                return json.loads(resp.read().decode())
        except Exception:
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
                continue
            raise


def resolve_tissue(query):
    """Resolve free text to UBERON term set via OLS4.

    Steps:
    1. Search for top hit
    2. Expand to hierarchical descendants
    3. Collect labels + all synonyms

    Returns dict with keys: query, resolved_label, obo_id, terms, term_count,
    descendant_count. Returns None on API failure.
    """
    if not query or not query.strip():
        return None

    # Step 1: search
    search_url = (
        f"{OLS_BASE}/search"
        f"?q={urllib.parse.quote(query.strip())}"
        f"&ontology=uberon&rows=10&exact=false"
    )
    try:
        search_data = _ols_get(search_url)
    except Exception as e:
        print(f"  [WARN] OLS search failed for {query!r}: {e}")
        return None

    docs = search_data.get("response", {}).get("docs", [])
    if not docs:
        print(f"  [WARN] OLS search returned no results for {query!r}")
        return None

    top = docs[0]
    iri = top.get("iri", "")
    label = top.get("label", query.strip())
    obo_id = top.get("obo_id", "")

    # Collect synonyms from search result
    all_synonyms = []
    for key in ("exact_synonyms", "related_synonyms", "broad_synonyms"):
        all_synonyms.extend(top.get(key, []))

    # Step 2: hierarchical descendants (double-encoded IRI)
    descendants = []
    if iri:
        encoded_iri = urllib.parse.quote(iri, safe="")
        double_encoded = urllib.parse.quote(encoded_iri, safe="")
        page = 0
        while True:
            desc_url = (
                f"{OLS_BASE}/ontologies/uberon/terms"
                f"/{double_encoded}/hierarchicalDescendants"
                f"?page={page}&size=500"
            )
            try:
                desc_data = _ols_get(desc_url)
            except Exception as e:
                print(f"  [WARN] OLS descendants failed for {obo_id}: {e}")
                break
            page_info = desc_data.get("page", {})
            terms_embedded = desc_data.get("_embedded", {}).get("terms", [])
            descendants.extend(terms_embedded)
            total_pages = page_info.get("totalPages", 1)
            page += 1
            if page >= total_pages:
                break

    # Step 3: assemble term set
    terms = set()
    terms.add(query.strip().lower())
    terms.add(label.lower())
    for syn in all_synonyms:
        s = syn.strip().lower()
        if s:
            terms.add(s)
    for desc in descendants:
        dl = desc.get("label", "").strip().lower()
        if dl:
            terms.add(dl)
        for syn in desc.get("synonyms", []):
            s = syn.strip().lower()
            if s:
                terms.add(s)
        for obo_syn in desc.get("obo_synonym") or []:
            n = obo_syn.get("name", "").strip().lower()
            if n:
                terms.add(n)

    terms = sorted(terms)
    return {
        "query": query.strip(),
        "resolved_label": label,
        "obo_id": obo_id,
        "terms": terms,
        "term_count": len(terms),
        "descendant_count": len(descendants),
    }


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _cache_key(query):
    normalized = query.strip().lower()
    return hashlib.md5(normalized.encode()).hexdigest()


def _cache_path(query):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, _cache_key(query) + ".json")


def _read_cache(query):
    path = _cache_path(query)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
        age_days = (datetime.now() - ts).days
        return data, age_days
    except Exception:
        return None


def _write_cache(query, result):
    result["timestamp"] = datetime.now().isoformat()
    path = _cache_path(query)
    try:
        with open(path, "w") as f:
            json.dump(result, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def get_tissue_terms(query):
    """Resolve tissue query to term list with caching and fallback.

    Returns list of lowercase term strings. Never returns empty list.
    """
    if not query or not query.strip():
        return []

    # Check cache
    cached = _read_cache(query)
    if cached is not None:
        data, age_days = cached
        if age_days <= CACHE_TTL_DAYS:
            print(f"  [INFO] Using cached tissue set for {query!r} ({data['term_count']} terms, {age_days}d old)")
            return data["terms"]
        # Cache exists but stale — try API, fall back to cache on failure

    # Try API
    result = resolve_tissue(query)
    if result is not None:
        _write_cache(query, result)
        print(f"  [INFO] Resolved {query!r} -> {result['obo_id']}: "
              f"{result['term_count']} terms ({result['descendant_count']} descendants)")
        return result["terms"]

    # API failed — try stale cache
    if cached is not None:
        data, age_days = cached
        print(f"  [WARN] Using stale cached tissue set for {query!r} "
              f"({data['term_count']} terms, {age_days}d old, OLS unreachable)")
        return data["terms"]

    # Complete fallback
    fallback = [query.strip().lower()]
    print(f"  [WARN] OLS unreachable and no cache for {query!r}, using raw input as fallback")
    return fallback
