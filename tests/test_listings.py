"""Tests for the listing tools over the fictional data/listings.json. No API calls."""
import pytest

from homebuyer_agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from homebuyer_agent.tools.listings import get_listing, load_listings, search_listings


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
