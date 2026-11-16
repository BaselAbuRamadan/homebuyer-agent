"""The agent's toolbox: plain Python functions plus the JSON schemas the model reads.

TOOL_FUNCTIONS maps a tool name to the Python function that runs it.
TOOL_SCHEMAS is the "menu" sent to the model in Milestone 5 (OpenAI function calling).
"""
from homebuyer_agent.tools.affordability import (
    MAX_AFFORDABLE_PRICE_SCHEMA,
    MONTHLY_PAYMENT_SCHEMA,
    max_affordable_price,
    monthly_payment,
)
from homebuyer_agent.tools.listings import (
    GET_LISTING_SCHEMA,
    SEARCH_LISTINGS_SCHEMA,
    get_listing,
    search_listings,
)

TOOL_FUNCTIONS = {
    "monthly_payment": monthly_payment,
    "max_affordable_price": max_affordable_price,
    "search_listings": search_listings,
    "get_listing": get_listing,
}

TOOL_SCHEMAS = [
    MONTHLY_PAYMENT_SCHEMA,
    MAX_AFFORDABLE_PRICE_SCHEMA,
    SEARCH_LISTINGS_SCHEMA,
    GET_LISTING_SCHEMA,
]
