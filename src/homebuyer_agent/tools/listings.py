"""Deterministic listing tools over data/listings.json. No AI.

All listings are FICTIONAL sample data and must never be presented as real.
"""
import json
from functools import lru_cache

from homebuyer_agent.config import LISTINGS_PATH

VALID_STATUSES = {"move_in_ready", "under_construction", "to_be_built"}
CLOSEST_ALTERNATIVES = 2   # how many over-budget homes to suggest when nothing fits the budget
SLIGHTLY_OVER_BUDGET_USD = 30_000   # up to this gap a home is "slightly" above budget; more is "well above"


def budget_label(over_budget_by_usd: float) -> str:
    """Words for how far over budget a home is, decided in Python so the model can't
    call a $72,000 gap "slightly above" (it did, in the M6 eval)."""
    return "slightly above budget" if over_budget_by_usd <= SLIGHTLY_OVER_BUDGET_USD else "well above budget"


@lru_cache(maxsize=1)
def load_listings() -> tuple[dict, ...]:
    """Read the listings file once and keep it in memory (a tuple so it can't be changed by accident)."""
    data = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    return tuple(data["listings"])


def _for_output(listing: dict) -> dict:
    """Copy a listing and add the tax rate in percent (0.021 -> 2.1).

    monthly_payment() takes percent, so the model can pass this value straight
    through instead of converting it itself (no arithmetic by the model).
    """
    return {**listing, "est_property_tax_rate_pct": round(listing["est_property_tax_rate"] * 100, 3)}


def _contains(text: str | None, query: str) -> bool:
    """Case-insensitive 'is query inside text', so 'austin' matches 'Austin, TX'."""
    return bool(text) and query.strip().lower() in text.lower()


def search_listings(
    metro: str | None = None,
    city: str | None = None,
    max_price: float | None = None,
    min_beds: int | None = None,
    status: str | None = None,
    features: list[str] | None = None,
    incentive_keyword: str | None = None,
    limit: int = 5,
) -> dict:
    """Find listings matching ALL the filters given, cheapest first.

    Args:
        metro: metro area, partial match (e.g. "Austin" matches "Austin, TX").
        city: city, partial match (e.g. "Frisco").
        max_price: highest price in USD.
        min_beds: minimum number of bedrooms.
        status: one of move_in_ready, under_construction, to_be_built.
        features: every feature must appear (partial match, e.g. "pool" matches "community pool").
        incentive_keyword: text to find in the builder incentive (e.g. "buydown").
        limit: maximum number of results (1-20).

    Returns {"total_matches", "returned", "listings": [...], "note"}. No matches is not an
    error: it returns an empty list so the agent can say so honestly. Two fallbacks help
    the agent still be useful:
    - nothing fits max_price -> "closest_above_budget": the cheapest homes matching all the
      OTHER filters, each with "over_budget_by_usd" and a "budget_label".
    - nothing has the requested features -> "matches_without_requested_features": homes
      matching every other filter (price included), so the agent can suggest them and
      tell the user to check the feature with the builder.
    """
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}")
    if not 1 <= limit <= 20:
        raise ValueError(f"limit must be between 1 and 20, got {limit}")

    def find(with_features: list[str] | None) -> list[dict]:
        """Every listing matching all filters EXCEPT the price, cheapest first.

        Price is kept separate so that, if nothing fits the budget, we can still
        suggest the closest homes that match the rest.
        """
        found = []
        for listing in load_listings():
            if metro and not _contains(listing["metro"], metro):
                continue
            if city and not _contains(listing["city"], city):
                continue
            if min_beds is not None and listing["beds"] < min_beds:
                continue
            if status and listing["status"] != status:
                continue
            if with_features and not all(any(_contains(f, w) for f in listing["features"]) for w in with_features):
                continue
            if incentive_keyword and not _contains(listing["builder_incentive"], incentive_keyword):
                continue
            found.append(listing)
        return sorted(found, key=lambda l: l["price_usd"])

    def within_budget(listings: list[dict]) -> list[dict]:
        return [l for l in listings if max_price is None or l["price_usd"] <= max_price]

    candidates = find(features)
    matches = within_budget(candidates)

    result = {
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "listings": [_for_output(l) for l in matches[:limit]],
        "note": "Fictional sample listings for a demo, not real homes.",
    }
    if not matches and max_price is not None and candidates:
        # Nothing within budget: offer the cheapest homes that match everything else,
        # with the gap worked out here so the model never does that arithmetic.
        result["closest_above_budget"] = [
            {**_for_output(l),
             "over_budget_by_usd": round(l["price_usd"] - max_price, 2),
             "budget_label": budget_label(l["price_usd"] - max_price)}
            for l in candidates[:CLOSEST_ALTERNATIVES]
        ]
        result["note"] += " No home matched the max price; closest_above_budget lists the cheapest homes matching the other filters."
    elif not matches and features:
        # The features were the problem (the data simply doesn't record them for any
        # home that fits). Offer homes matching everything else so the user isn't left
        # with nothing, and tell them to confirm the feature with the builder.
        without = within_budget(find(None))
        if without:
            result["matches_without_requested_features"] = [_for_output(l) for l in without[:limit]]
            result["note"] += (
                f" No listing records the requested feature(s) {features}. "
                "matches_without_requested_features lists homes matching all the other filters; "
                "the buyer should ask the builder whether these homes have the feature(s)."
            )
    return result


def get_listing(listing_id: str) -> dict:
    """Return one listing by id (e.g. "L001"). Raises ValueError if the id doesn't exist."""
    wanted = listing_id.strip().upper()
    for listing in load_listings():
        if listing["id"] == wanted:
            return {**_for_output(listing), "note": "Fictional sample listing for a demo, not a real home."}
    raise ValueError(f"No listing with id {listing_id!r}")


SEARCH_LISTINGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_listings",
        "description": (
            "Search the (fictional) new-construction listings. All filters are optional and combined. "
            "Results are sorted cheapest first. Metros: Austin TX, Dallas TX, Phoenix AZ, Raleigh NC."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metro": {"type": "string", "description": "Metro area, e.g. 'Austin'."},
                "city": {"type": "string", "description": "City, e.g. 'Frisco'."},
                "max_price": {"type": "number", "description": "Highest price in USD."},
                "min_beds": {"type": "integer", "description": "Minimum bedrooms."},
                "status": {"type": "string", "enum": sorted(VALID_STATUSES), "description": "Build status."},
                "features": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Features that must all be present, e.g. ['pool', 'home office'].",
                },
                "incentive_keyword": {"type": "string", "description": "Text to find in the builder incentive, e.g. 'buydown'."},
                "limit": {"type": "integer", "description": "Max results, 1-20. Default 5."},
            },
            "required": [],
        },
    },
}

GET_LISTING_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_listing",
        "description": "Get full details of one listing by its id, e.g. 'L001' (price, tax rate, HOA, features, incentive).",
        "parameters": {
            "type": "object",
            "properties": {"listing_id": {"type": "string", "description": "Listing id like 'L001'."}},
            "required": ["listing_id"],
        },
    },
}
