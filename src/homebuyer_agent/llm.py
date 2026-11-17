"""Thin wrapper around the OpenAI SDK. This is the ONLY module that calls the API.

Keeping every API call here means:
- tests can mock one function instead of the whole SDK,
- swapping providers later (a stretch goal) touches one file,
- tracing (Milestone 3) only has to instrument one place.
"""
from functools import lru_cache
from typing import TypeVar

from openai import APIStatusError, OpenAI
from pydantic import BaseModel

from homebuyer_agent.config import get_model

T = TypeVar("T", bound=BaseModel)

API_TIMEOUT_SECONDS = 60   # give up on a stuck call instead of waiting the SDK default of 10 minutes
API_MAX_RETRIES = 2        # the SDK retries connection errors, 429s and 5xx with backoff


class ModelCallError(RuntimeError):
    """The API answered with an HTTP error: unknown model, no access, rate limit, server error.

    Raised instead of the SDK's own exception so other modules (the planner's
    smart-model fallback) can react without importing the OpenAI SDK.
    """


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Create the OpenAI client once and reuse it (it reads OPENAI_API_KEY from the env)."""
    return OpenAI(timeout=API_TIMEOUT_SECONDS, max_retries=API_MAX_RETRIES)


def structured_completion(
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    history: list[dict] | None = None,
    model: str | None = None,
) -> T:
    """Ask the model for a reply that matches `response_model`, and return it as that type.

    How it works: the SDK turns the Pydantic class into a JSON Schema and sends it as
    `response_format`. The API then uses constrained decoding, so the model can only
    produce JSON that fits the schema. The SDK parses that JSON back into a
    `response_model` instance, so we never parse strings ourselves.

    temperature=0 keeps outputs as repeatable as possible, which matters for evals.
    history: earlier turns ({"role": "user"/"assistant", "content": ...}) placed
    before the new message, so the model can understand replies like "yes".
    model: override the model name (the eval judge uses this); default is OPENAI_MODEL.
    """
    completion = _client().chat.completions.parse(
        model=model or get_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            *(history or []),
            {"role": "user", "content": user_message},
        ],
        response_format=response_model,
        temperature=0,
    )
    message = completion.choices[0].message
    if message.refusal:
        raise RuntimeError(f"Model refused to answer: {message.refusal}")
    if message.parsed is None:
        raise RuntimeError("Model returned no parsed output.")
    return message.parsed


def chat_with_tools(messages: list[dict], tools: list[dict], tool_choice: str = "auto", model: str | None = None):
    """One turn of a conversation where the model may ask to call tools.

    The model sees the conversation so far plus the tool "menu" (JSON schemas).
    It replies with EITHER normal text (it's done) OR one or more tool calls
    (name + JSON arguments) that our code must run and send back.

    tool_choice="none" forces a text answer (used when the loop hits its limit).
    model: override the model name (the planner passes SMART_MODEL when needed); default is OPENAI_MODEL.
    Returns the assistant message (has .content and .tool_calls).
    Raises ModelCallError if the API answers with an HTTP error.
    """
    try:
        completion = _client().chat.completions.create(
            model=model or get_model(),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=0,
        )
    except APIStatusError as e:
        raise ModelCallError(f"{type(e).__name__} from model {model or get_model()!r}: {e.message}") from e
    return completion.choices[0].message
