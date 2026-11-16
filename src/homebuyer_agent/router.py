"""V1 router agent: classify a homebuyer message into one of six intents.

This is "action autonomy": the model chooses which path a request takes,
and our code relies on that choice because the output is a typed object.
"""
from enum import Enum

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from pydantic import BaseModel, Field

from homebuyer_agent.config import PROMPTS_DIR
from homebuyer_agent.llm import structured_completion
from homebuyer_agent.tracing import get_tracer

# The best prompt so far (see results/v1_vs_v4.md). Older versions stay for comparison.
DEFAULT_PROMPT_VERSION = "router_v4"


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


def route(message: str, prompt_version: str = DEFAULT_PROMPT_VERSION) -> RouterDecision:
    """Classify one user message and return the router's decision.

    The work happens inside a custom "route" span. In Phoenix it shows the message,
    the decision and labels for prompt version, intent and confidence. The OpenAI
    call made inside it appears as a child span.
    """
    with get_tracer().start_as_current_span("route") as span:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.CHAIN.value)
        span.set_attribute(SpanAttributes.INPUT_VALUE, message)
        span.set_attribute("router.prompt_version", prompt_version)

        decision = structured_completion(load_prompt(prompt_version), message, RouterDecision)

        span.set_attribute("router.intent", decision.intent.value)
        span.set_attribute("router.confidence", decision.confidence)
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, decision.model_dump_json())
        return decision
