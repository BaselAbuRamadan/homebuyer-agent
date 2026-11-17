"""Tests for the V2 eval metrics. Pure Python: no API calls."""
import math

import pytest

from homebuyer_agent.eval_metrics import (
    micro_precision_recall,
    normalise_tools,
    parse_list,
    quote_in_answer,
    retrieval_hit,
    tool_selection,
)


def test_parse_list_splits_on_pipe():
    assert parse_list("kb_001|kb_003| kb_006") == {"kb_001", "kb_003", "kb_006"}


@pytest.mark.parametrize("empty", [None, float("nan"), "", " "])
def test_parse_list_empty_cells(empty):
    assert parse_list(empty) == set()


def test_both_affordability_tools_count_as_the_calculator():
    assert normalise_tools(["max_affordable_price", "search_listings", "monthly_payment"]) == {
        "affordability_calculator", "search_listings"}


def test_repeated_calls_count_once():
    assert normalise_tools(["search_listings"] * 4) == {"search_listings"}


def test_perfect_tool_choice():
    s = tool_selection({"affordability_calculator", "search_listings"}, {"affordability_calculator", "search_listings"})
    assert (s["precision"], s["recall"], s["exact"]) == (1.0, 1.0, True)


def test_extra_tool_lowers_precision_only():
    s = tool_selection({"get_listing"}, {"get_listing", "search_listings"})
    assert s["precision"] == 0.5 and s["recall"] == 1.0 and s["fp"] == 1 and not s["exact"]


def test_missed_tool_lowers_recall_only():
    s = tool_selection({"get_listing", "affordability_calculator"}, {"affordability_calculator"})
    assert s["precision"] == 1.0 and s["recall"] == 0.5 and s["fn"] == 1


def test_no_tools_expected_and_none_called_is_perfect():
    s = tool_selection(set(), set())
    assert (s["precision"], s["recall"], s["exact"]) == (1.0, 1.0, True)


def test_tools_called_when_none_expected():
    s = tool_selection(set(), {"search_listings"})
    assert s["precision"] == 0.0 and math.isnan(s["recall"])


def test_no_tools_called_when_some_expected():
    s = tool_selection({"search_listings"}, set())
    assert math.isnan(s["precision"]) and s["recall"] == 0.0


def test_micro_average_sums_counts():
    rows = [tool_selection({"a", "b"}, {"a"}), tool_selection({"c"}, {"c", "d"})]
    precision, recall = micro_precision_recall(rows)
    assert precision == pytest.approx(2 / 3)   # tp=2, fp=1
    assert recall == pytest.approx(2 / 3)      # tp=2, fn=1


ANSWER = "You can afford a maximum home price of **$305,000**.\nThis estimate assumes a 6.5% interest rate."


def test_real_quote_is_found_despite_markdown_and_spacing():
    assert quote_in_answer("maximum home price of $305,000", ANSWER)


def test_shortened_quote_with_dots_is_checked_piece_by_piece():
    assert quote_in_answer("You can afford ... assumes a 6.5% interest rate", ANSWER)


def test_quote_stitched_across_headings_is_accepted():
    answer = "Cheapest homes:\n### 1. **Austin, TX**\n- **Listing ID:** L005\n### 2. **Dallas, TX**\n- **Listing ID:** L026"
    assert quote_in_answer("Cheapest homes: ### 1. **Austin, TX** - **Listing ID:** L005 ### 2. **Dallas, TX**", answer)


def test_invented_quote_is_caught():
    # What happened in A02: the judge quoted the guide, not the answer.
    assert not quote_in_answer("Common types: temporary and permanent buydowns", ANSWER)


def test_missing_is_not_a_claim():
    assert quote_in_answer("MISSING", ANSWER)


def test_retrieval_hit_needs_any_expected_doc():
    assert retrieval_hit({"kb_001", "kb_003"}, ["kb_003", "kb_005"]) is True
    assert retrieval_hit({"kb_002"}, ["kb_001"]) is False


def test_retrieval_not_applicable_when_nothing_expected():
    assert retrieval_hit(set(), ["kb_001"]) is None
