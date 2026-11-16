"""Thin wrapper around the OpenAI SDK. This is the ONLY module that calls the API.

Keeping every API call here means:
- tests can mock one function instead of the whole SDK,
- swapping providers later (a stretch goal) touches one file,
- tracing (Milestone 3) only has to instrument one place.
"""
from functools import lru_cache
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from homebuyer_agent.config import get_model

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Create the OpenAI client once and reuse it (it reads OPENAI_API_KEY from the env)."""
    return OpenAI()


def structured_completion(
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    history: list[dict] | None = None,
) -> T:
    """Ask the model for a reply that matches `response_model`, and return it as that type.

    How it works: the SDK turns the Pydantic class into a JSON Schema and sends it as
    `response_format`. The API then uses constrained decoding, so the model can only
    produce JSON that fits the schema. The SDK parses that JSON back into a
    `response_model` instance, so we never parse strings ourselves.

    temperature=0 keeps outputs as repeatable as possible, which matters for evals.
    history: earlier turns ({"role": "user"/"assistant", "content": ...}) placed
    before the new message, so the model can understand replies like "yes".
    """
    completion = _client().chat.completions.parse(
        model=get_model(),
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


def chat_with_tools(messages: list[dict], tools: list[dict], tool_choice: str = "auto"):
    """One turn of a conversation where the model may ask to call tools.

    The model sees the conversation so far plus the tool "menu" (JSON schemas).
    It replies with EITHER normal text (it's done) OR one or more tool calls
    (name + JSON arguments) that our code must run and send back.

    tool_choice="none" forces a text answer (used when the loop hits its limit).
    Returns the assistant message (has .content and .tool_calls).
    """
    completion = _client().chat.completions.create(
        model=get_model(),
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=0,
    )
    return completion.choices[0].message
