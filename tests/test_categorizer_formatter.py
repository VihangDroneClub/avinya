from __future__ import annotations

from pathlib import Path

from processors.categorizer import categorize_document, load_category_rules
from processors.formatter import format_markdown_document


def test_categorizer_prefers_filename_and_content_rules(tmp_path: Path):
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        """
categories:
  reports:
    priority: 1
    keywords:
      filename: ["report"]
      content: ["quarterly"]
  accounts:
    priority: 2
    keywords:
      filename: ["budget"]
      content: ["cost"]
default_category: technical
""".strip(),
        encoding="utf-8",
    )

    match = categorize_document(
        source_name="budget_report.pdf",
        content="This quarterly report covers cost tracking.",
        rules_path=rules_path,
    )

    assert load_category_rules(rules_path)["default_category"] == "technical"
    assert match.category == "reports"
    assert match.score > 0
    assert "report" in match.matched_terms


def test_categorizer_falls_back_to_default(tmp_path: Path):
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        """
categories:
  reports:
    priority: 1
    keywords:
      filename: ["report"]
      content: ["quarterly"]
default_category: technical
""".strip(),
        encoding="utf-8",
    )

    match = categorize_document(
        source_name="random_notes.txt",
        content="Nothing useful here.",
        rules_path=rules_path,
    )

    assert match.category == "technical"
    assert match.score == 0.0


def test_formatter_emits_standard_frontmatter():
    markdown = format_markdown_document(
        body="---\nold: frontmatter\n---\n\nHello world",
        source_name="budget-2025.pdf",
        title="Budget 2025",
        category="accounts",
        metadata={"conversion_method": "pypdf"},
    )

    assert markdown.startswith("---\n")
    assert "title: Budget 2025" in markdown
    assert "source: budget-2025.pdf" in markdown
    assert "category: accounts" in markdown
    assert "created_at:" in markdown
    assert "conversion_method: pypdf" in markdown
    assert markdown.count("---") == 2
    assert "Hello world" in markdown

