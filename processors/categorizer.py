from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class CategoryMatch:
    category: str
    score: float
    matched_terms: list[str]


@lru_cache(maxsize=8)
def load_category_rules(rules_path: str | Path) -> dict[str, Any]:
    path = Path(rules_path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid category rules file: {path}")
    return data


def _flatten_keywords(category_rules: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    keywords = category_rules.get("keywords", {}) or {}
    for group in ("filename", "content"):
        items = keywords.get(group, []) or []
        for item in items:
            text = str(item).strip().lower()
            if text and text not in terms:
                terms.append(text)
    return terms


def _match_terms(text: str, terms: list[str]) -> list[str]:
    haystack = (text or "").lower()
    return [term for term in terms if term in haystack]


def categorize_document(
    *,
    source_name: str,
    content: str,
    rules_path: str | Path = "config/category_rules.yaml",
) -> CategoryMatch:
    rules = load_category_rules(rules_path)
    categories = rules.get("categories", {}) or {}
    default_category = str(rules.get("default_category", "technical"))

    source_lower = source_name.lower()
    content_lower = content.lower()

    best = CategoryMatch(category=default_category, score=0.0, matched_terms=[])
    candidates: list[tuple[int, str, CategoryMatch]] = []

    for category, spec in categories.items():
        spec = spec or {}
        priority = int(spec.get("priority", 999))
        terms = _flatten_keywords(spec)
        filename_terms = list((spec.get("keywords", {}) or {}).get("filename", []) or [])
        content_terms = list((spec.get("keywords", {}) or {}).get("content", []) or [])

        matched_filename = _match_terms(source_lower, [str(term).lower() for term in filename_terms])
        matched_content = _match_terms(content_lower, [str(term).lower() for term in content_terms])
        matched_terms = []
        for term in matched_filename + matched_content:
            if term not in matched_terms:
                matched_terms.append(term)

        total_terms = max(1, len(terms))
        score = len(matched_terms) / total_terms
        candidate = CategoryMatch(category=category, score=score, matched_terms=matched_terms)
        candidates.append((priority, category, candidate))

    if not candidates:
        return best

    candidates.sort(key=lambda item: (item[0], -item[2].score, item[1]))
    for _priority, _category, candidate in candidates:
        if candidate.score > best.score:
            best = candidate
        elif candidate.score == best.score and candidate.category == default_category:
            best = candidate

    if best.score <= 0:
        return CategoryMatch(category=default_category, score=0.0, matched_terms=[])
    return best

