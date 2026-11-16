"""Tests for BM25 retrieval over the knowledge base. No API calls."""
from homebuyer_agent.retrieval import chunk_markdown, retrieve, tokenize


def test_tokenize_lowercases_drops_stopwords_keeps_hyphenated_terms():
    assert tokenize("What is a 2-1 Buydown?") == ["2-1", "buydown"]


def test_chunk_by_heading():
    md = "# Title\nIntro text.\n## Part A\nAlpha.\n## Part B\nBeta."
    chunks = chunk_markdown("kb_999", md)
    assert [c.heading for c in chunks] == ["Title", "Part A", "Part B"]
    assert all(c.doc_id == "kb_999" for c in chunks)
    assert "Alpha." in chunks[1].text


def test_buydown_question_finds_incentives_guide():
    assert retrieve("how do builder rate buydowns work")[0].doc_id == "kb_004"


def test_closing_costs_question_finds_closing_costs_guide():
    assert retrieve("how much are closing costs")[0].doc_id == "kb_003"


def test_inspection_question_finds_inspection_guide():
    assert retrieve("do I need an inspection on a new build")[0].doc_id == "kb_005"


def test_steering_question_finds_fair_housing_guide():
    assert retrieve("neighbourhoods with fewer families with kids")[0].doc_id == "kb_007"


def test_returns_at_most_k_best_first():
    results = retrieve("mortgage pre-approval and closing costs", k=2)
    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_unrelated_query_returns_nothing():
    assert retrieve("banana bread recipe") == []
