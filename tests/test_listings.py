"""Tests for the listing tools over the fictional data/listings.json. No API calls."""
import pytest

from homebuyer_agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from homebuyer_agent.tools.listings import budget_label, get_listing, load_listings, search_listings


# ---------- search_listings ----------

def test_no_filters_returns_cheapest_first():
    result = search_listings(limit=20)
    prices = [l["price_usd"] for l in result["listings"]]
    assert prices == sorted(prices)
    assert result["total_matches"] == len(load_listings())


def test_metro_partial_and_case_insensitive():
    result = search_listings(metro="austin", limit=20)
    assert result["total_matches"] == 8
    assert all(l["metro"] == "Austin, TX" for l in result["listings"])


def test_filters_combine():
    result = search_listings(metro="Austin", min_beds=3, max_price=450_000, limit=20)
    assert result["total_matches"] > 0
    for l in result["listings"]:
        assert l["metro"] == "Austin, TX" and l["beds"] >= 3 and l["price_usd"] <= 450_000


def test_status_filter():
    result = search_listings(status="move_in_ready", limit=20)
    assert result["total_matches"] == 12
    assert all(l["status"] == "move_in_ready" for l in result["listings"])


def test_all_requested_features_must_match():
    result = search_listings(features=["pool", "office"], limit=20)
    assert result["total_matches"] > 0
    for l in result["listings"]:
        text = " ".join(l["features"])
        assert "pool" in text and "office" in text


def test_incentive_keyword_finds_buydowns_in_phoenix():
    result = search_listings(metro="Phoenix", incentive_keyword="buydown")
    assert {l["id"] for l in result["listings"]} == {"L014", "L015"}


def test_limit_caps_results_but_reports_total():
    result = search_listings(limit=2)
    assert result["returned"] == 2
    assert len(result["listings"]) == 2
    assert result["total_matches"] == len(load_listings())


def test_no_results_is_empty_not_an_error():
    result = search_listings(city="Frisco", max_price=100_000)
    assert result["total_matches"] == 0
    assert result["listings"] == []


def test_over_budget_search_suggests_closest_homes():
    # No 3-bed in Austin under 305k, so suggest the cheapest Austin 3-beds instead.
    result = search_listings(metro="Austin", min_beds=3, max_price=305_000)
    assert result["listings"] == []
    closest = result["closest_above_budget"]
    assert 1 <= len(closest) <= 2
    for home in closest:
        assert home["metro"] == "Austin, TX" and home["beds"] >= 3        # other filters still apply
        assert home["over_budget_by_usd"] == home["price_usd"] - 305_000  # gap worked out in Python
    assert closest[0]["price_usd"] <= closest[-1]["price_usd"]           # closest first


def test_budget_label_says_slightly_only_up_to_30k():
    assert budget_label(30_000) == "slightly above budget"
    assert budget_label(30_001) == "well above budget"
    assert budget_label(72_000) == "well above budget"


def test_closest_homes_carry_a_budget_label():
    # A01's case: L001 is $72,000 over a $305k budget, so it must NOT be "slightly" above.
    closest = search_listings(metro="Austin", min_beds=3, max_price=305_000)["closest_above_budget"]
    assert closest[0]["over_budget_by_usd"] == 72_000
    assert closest[0]["budget_label"] == "well above budget"
    near = search_listings(metro="Austin", min_beds=3, max_price=360_000)["closest_above_budget"]
    assert near[0]["budget_label"] == "slightly above budget"          # $17,000 over


def test_missing_feature_still_offers_homes_matching_the_rest():
    # A07's case: no listing records "step-free entry", but homes under 400k exist.
    result = search_listings(max_price=400_000, features=["step-free entry"])
    assert result["listings"] == []
    others = result["matches_without_requested_features"]
    assert others and all(l["price_usd"] <= 400_000 for l in others)   # price filter still applies
    assert "builder" in result["note"]


def test_no_feature_fallback_when_feature_matches():
    assert "matches_without_requested_features" not in search_listings(features=["pool"])


def test_no_suggestions_when_budget_was_not_the_problem():
    result = search_listings(city="Glasgow", max_price=300_000)
    assert result["total_matches"] == 0
    assert "closest_above_budget" not in result


def test_no_suggestions_when_homes_fit_the_budget():
    assert "closest_above_budget" not in search_listings(metro="Austin", max_price=500_000)


def test_unknown_city_gives_no_results():
    assert search_listings(city="Glasgow")["total_matches"] == 0


def test_results_are_marked_fictional():
    assert "Fictional" in search_listings()["note"]


def test_bad_status_raises():
    with pytest.raises(ValueError):
        search_listings(status="sold")


def test_bad_limit_raises():
    with pytest.raises(ValueError):
        search_listings(limit=0)


def test_results_are_copies_not_the_cached_data():
    # Changing a result must not corrupt the data other searches see.
    search_listings(limit=1)["listings"][0]["price_usd"] = 1
    assert search_listings(limit=1)["listings"][0]["price_usd"] != 1


# ---------- get_listing ----------

def test_get_listing_by_id():
    listing = get_listing("L017")
    assert listing["id"] == "L017"
    assert listing["price_usd"] == 488_000


def test_get_listing_ignores_case_and_spaces():
    assert get_listing(" l001 ")["id"] == "L001"


def test_unknown_id_raises():
    with pytest.raises(ValueError, match="No listing"):
        get_listing("L999")


# ---------- the toolbox the model will see ----------

def test_every_schema_has_a_matching_function():
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert schema_names == set(TOOL_FUNCTIONS)


def test_schema_parameters_exist_in_the_function():
    import inspect
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        params = set(inspect.signature(TOOL_FUNCTIONS[name]).parameters)
        assert set(schema["function"]["parameters"]["properties"]) <= params, name
