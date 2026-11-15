"""V1 router agent: classify a homebuyer message into one of six intents.

This is "action autonomy": the model chooses which path a request takes,
and our code relies on that choice because the output is a typed object.
"""
from enum import Enum

from pydantic import BaseModel, Field

from homebuyer_agent.config import PROMPTS_DIR
from homebuyer_agent.llm import structured_completion


class Intent(str, Enum):
    """The six intents the router can choose from. The API enforces this list."""

    LISTING_SEARCH = "listing_search"
    AFFORDABILITY = "affordability"
    PROCESS_QUESTION = "process_question"
    TALK_TO_AGENT = "talk_to_agent"
    OUT_OF_SCOPE = "out_of_scope"
    FAIR_HOUSING_SENSITIVE = "fair_housing_sensitive"


class RouterDecision(BaseModel):
    """Structured output of the router.

    Field order matters: the model generates `reasoning` first, then commits to an
    `intent`, a light form of "think before you answer".
    The descriptions are part of the JSON Schema, so the model sees them too.
    """

    reasoning: str = Field(description="One or two sentences explaining the choice.")
    intent: Intent = Field(description="The single best intent for the message.")
    confidence: float = Field(ge=0, le=1, description="Self-reported confidence from 0 to 1.")


def load_prompt(version: str) -> str:
    """Read a versioned prompt file, e.g. load_prompt('router_v1') -> prompts/router_v1.txt."""
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"No prompt file at {path}")
    return path.read_text(encoding="utf-8")


def route(message: str, prompt_version: str = "router_v1") -> RouterDecision:
    """Classify one user message and return the router's decision."""
    system_prompt = load_prompt(prompt_version)
    return structured_completion(system_prompt, message, RouterDecision)
