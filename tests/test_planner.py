"""Tests for the agent loop with a FAKE model, so there are no API calls.

We replace route(), structured_completion() and chat_with_tools() inside planner.py
with scripted fakes, then check that the loop does the right thing: short-circuits,
runs the tools the "model" asks for, feeds results back, and respects the limit.
"""
import json
from types import SimpleNamespace

import pytest

from homebuyer_agent import planner
from homebuyer_agent.guardrails import FAIR_HOUSING_RESPONSE, OUT_OF_SCOPE_RESPONSE
from homebuyer_agent.router import Intent, RouterDecision


def fake_route(intent: Intent):
    return lambda message, history=None: RouterDecision(reasoning="test", intent=intent, confidence=1.0)


def tool_call(call_id: str, name: str, **arguments):
    """Build an object shaped like an OpenAI tool call."""
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def reply(content=None, tool_calls=None):
    """Build an object shaped like an OpenAI assistant message."""
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class ScriptedModel:
    """Returns pre-written replies in order and remembers what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tools, tool_choice="auto"):
        self.calls.append({"messages": [dict(m) for m in messages], "tool_choice": tool_choice})
        return self.replies.pop(0)


@pytest.fixture
def setup(monkeypatch):
    """Patch the model functions; returns a helper to configure each test."""
    def configure(intent: Intent, replies=(), plan_steps=()):
        monkeypatch.setattr(planner, "route", fake_route(intent))
        plan = planner.Plan(goal="test goal", steps=[planner.PlanStep(tool=t, reason="test") for t in plan_steps])
        monkeypatch.setattr(planner, "structured_completion", lambda *args, **kwargs: plan)
        model = ScriptedModel(replies)
        monkeypatch.setattr(planner, "chat_with_tools", model)
        return model
    return configure


# ---------- short-circuits: no planning, no tools ----------

def test_fair_housing_intent_gets_safe_template(setup):
    model = setup(Intent.FAIR_HOUSING_SENSITIVE)
    result = planner.run_agent("Which suburbs have fewer families with kids?")
    assert result.answer == FAIR_HOUSING_RESPONSE
    assert result.tool_calls == [] and model.calls == []


def test_input_guardrail_catches_steering_even_if_router_misses(setup):
    setup(Intent.LISTING_SEARCH)
    result = planner.run_agent("Show me homes near Austin for people like us")
    assert result.answer == FAIR_HOUSING_RESPONSE
    assert "input check" in result.guardrail


def test_talk_to_agent_never_claims_a_booking(setup):
    setup(Intent.TALK_TO_AGENT)
    result = planner.run_agent("Book me a tour of L009 on Saturday at 10am")
    assert "nothing has been scheduled" in result.answer
    assert "L009" in result.answer
    assert result.listing_ids == ["L009"]


def test_out_of_scope_declines(setup):
    setup(Intent.OUT_OF_SCOPE)
    assert planner.run_agent("best crypto for my down payment?").answer == OUT_OF_SCOPE_RESPONSE


# ---------- the tool loop ----------

def test_loop_runs_requested_tool_and_feeds_result_back(setup):
    model = setup(
        Intent.LISTING_SEARCH,
        replies=[
            reply(tool_calls=[tool_call("c1", "search_listings", metro="Phoenix", incentive_keyword="buydown")]),
            reply(content="L014 and L015 offer a rate buydown [kb_004]. Listings are fictional."),
        ],
        plan_steps=["search_listings"],
    )
    result = planner.run_agent("Any Phoenix listings with a buydown?")

    assert [t.name for t in result.tool_calls] == ["search_listings"]
    assert result.tool_calls[0].result["total_matches"] == 2           # the real tool ran
    tool_message = model.calls[1]["messages"][-1]                       # what the model saw next
    assert tool_message["role"] == "tool" and "L014" in tool_message["content"]
    assert result.listing_ids == ["L014", "L015"]
    assert "kb_004" in result.retrieved_docs


def test_two_step_plan_runs_tools_in_order(setup):
    setup(
        Intent.AFFORDABILITY,
        replies=[
            reply(tool_calls=[tool_call("c1", "max_affordable_price", annual_income=95000,
                                        monthly_debts=400, down_payment_savings=40000, annual_rate=6.5)]),
            reply(tool_calls=[tool_call("c2", "search_listings", metro="Austin", min_beds=3, max_price=305000)]),
            reply(content="You could afford about $305,000 (assuming 6.5%)."),
        ],
    )
    result = planner.run_agent("I earn 95k... what can I afford in Austin?")
    assert [t.name for t in result.tool_calls] == ["max_affordable_price", "search_listings"]
    assert result.tool_calls[0].result["max_price"] == pytest.approx(305_000, abs=1_000)


def test_tool_error_goes_back_to_model_instead_of_crashing(setup):
    model = setup(
        Intent.AFFORDABILITY,
        replies=[
            reply(tool_calls=[tool_call("c1", "monthly_payment", price=400000, down_payment_pct=10, annual_rate=65)]),
            reply(content="Sorry, 65% looks like a typo. Did you mean 6.5%?"),
        ],
    )
    result = planner.run_agent("payment on 400k, 10% down, 65%")
    assert result.tool_calls[0].error is not None
    assert "error" in model.calls[1]["messages"][-1]["content"]
    assert "typo" in result.answer


def test_unknown_tool_is_reported_not_run(setup):
    setup(Intent.LISTING_SEARCH, replies=[
        reply(tool_calls=[tool_call("c1", "book_tour", listing_id="L009")]),
        reply(content="I can't book tours."),
    ])
    result = planner.run_agent("homes in Dallas")
    assert "Unknown tool" in result.tool_calls[0].error


def test_loop_stops_at_iteration_limit_and_forces_an_answer(setup):
    endless = [reply(tool_calls=[tool_call(f"c{i}", "search_listings", metro="Austin")]) for i in range(planner.MAX_ITERATIONS)]
    model = setup(Intent.LISTING_SEARCH, replies=endless + [reply(content="Here is what I found.")])
    result = planner.run_agent("homes in Austin")
    assert len(result.tool_calls) == planner.MAX_ITERATIONS
    assert result.hit_iteration_limit
    assert model.calls[-1]["tool_choice"] == "none"      # the final call forbids more tools
    assert result.answer == "Here is what I found."


# ---------- conversation memory ----------

def test_follow_up_sees_earlier_turns(setup, monkeypatch):
    seen_by_router = {}

    def recording_route(message, history=None):
        seen_by_router["history"] = history
        return RouterDecision(reasoning="test", intent=Intent.AFFORDABILITY, confidence=1.0)

    model = setup(Intent.AFFORDABILITY, replies=[reply(content="L029 would cost about ...")])
    monkeypatch.setattr(planner, "route", recording_route)
    history = [
        {"role": "user", "content": "Show me move-in ready homes in Dallas"},
        {"role": "assistant", "content": "Closest options: L029 ($316,000). Want the monthly cost?"},
    ]
    planner.run_agent("yes", history=history)

    assert seen_by_router["history"] == history                     # router saw the context
    sent = model.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert "L029" in sent[2]["content"] and sent[3]["content"] == "yes"


def test_only_recent_history_is_kept(setup):
    model = setup(Intent.LISTING_SEARCH, replies=[reply(content="ok")])
    long_history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(20)]
    planner.run_agent("homes in Austin", history=long_history)
    sent_history = model.calls[0]["messages"][1:-1]                  # between system and new message
    assert len(sent_history) == planner.MAX_HISTORY_MESSAGES
    assert sent_history[-1]["content"] == "turn 19"


def test_answer_guardrail_replaces_unsafe_answer(setup):
    setup(Intent.LISTING_SEARCH, replies=[reply(content="Prosper is predominantly young families, great for you.")])
    result = planner.run_agent("homes in Dallas")
    assert result.answer == FAIR_HOUSING_RESPONSE
    assert "answer check" in result.guardrail
