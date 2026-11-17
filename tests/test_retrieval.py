"""Tests for BM25 retrieval over the knowledge base. No API calls."""
import csv

import pytest

from homebuyer_agent.config import EVAL_DIR
from homebuyer_agent.retrieval import chunk_markdown, expand_query, retrieve, tokenize

with open(EVAL_DIR / "retrieval_cases.csv", newline="", encoding="utf-8") as f:
    RETRIEVAL_CASES = list(csv.DictReader(f))


@pytest.mark.parametrize("case", RETRIEVAL_CASES, ids=[c["id"] for c in RETRIEVAL_CASES])
def test_every_retrieval_case_finds_its_guide_in_the_top_3(case):
    # Regression guard: editing the guides, stopwords or synonyms must not break these.
    assert case["expected_doc"] in [c.doc_id for c in retrieve(case["question"], k=3)]


def test_plurals_match_singulars():
    assert tokenize("debts taxes families costs") == ["debt", "tax", "family", "cost"]


def test_hyphenated_terms_and_short_words_are_kept_whole():
    assert tokenize("a 2-1 buydown on a move-in ready home") == ["2-1", "buydown", "move-in", "ready", "home"]


def test_everyday_words_are_expanded_to_guide_words():
    assert "income" in expand_query(tokenize("I earn 95k"))


def test_apostrophe_leftovers_are_ignored():
    assert "s" not in tokenize("that's my budget")


def test_income_question_finds_preapproval_guide():
    # A01 in the M6 eval: "debts" and "earn" used to score 0 against kb_002.
    query = "I earn 95k a year with 400/month in debts. What can I afford?"
    assert "kb_002" in [c.doc_id for c in retrieve(query)]


def test_costs_beyond_price_question_finds_closing_costs_guide():
    # A03 in the M6 eval: the agent never saw kb_003, so it never gave the 2-5% range.
    query = "Walk me through buying a to-be-built home and what costs to budget beyond the price"
    assert "kb_003" in [c.doc_id for c in retrieve(query)]


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
