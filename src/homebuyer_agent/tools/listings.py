"""Deterministic listing tools over data/listings.json. No AI.

All listings are FICTIONAL sample data and must never be presented as real.
"""
import json
from functools import lru_cache

from homebuyer_agent.config import LISTINGS_PATH

VALID_STATUSES = {"move_in_ready", "under_construction", "to_be_built"}


@lru_cache(maxsize=1)
def load_listings() -> tuple[dict, ...]:
    """Read the listings file once and keep it in memory (a tuple so it can't be changed by accident)."""
    data = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    return tuple(data["listings"])


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
    error: it returns an empty list so the agent can say so honestly.
    """
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}")
    if not 1 <= limit <= 20:
        raise ValueError(f"limit must be between 1 and 20, got {limit}")

    matches = []
    for listing in load_listings():
        if metro and not _contains(listing["metro"], metro):
            continue
        if city and not _contains(listing["city"], city):
            continue
        if max_price is not None and listing["price_usd"] > max_price:
            continue
        if min_beds is not None and listing["beds"] < min_beds:
            continue
        if status and listing["status"] != status:
            continue
        if features and not all(any(_contains(f, wanted) for f in listing["features"]) for wanted in features):
            continue
        if incentive_keyword and not _contains(listing["builder_incentive"], incentive_keyword):
            continue
        matches.append(listing)

    matches.sort(key=lambda l: l["price_usd"])
    return {
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "listings": [dict(l) for l in matches[:limit]],
        "note": "Fictional sample listings for a demo, not real homes.",
    }


def get_listing(listing_id: str) -> dict:
    """Return one listing by id (e.g. "L001"). Raises ValueError if the id doesn't exist."""
    wanted = listing_id.strip().upper()
    for listing in load_listings():
        if listing["id"] == wanted:
            return {**listing, "note": "Fictional sample listing for a demo, not a real home."}
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
