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
from homebuyer_agent.llm import ModelCallError
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

    def __call__(self, messages, tools, tool_choice="auto", model=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tool_choice": tool_choice, "model": model})
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def cheap_model_only(monkeypatch):
    """Every test starts with only the cheap model, whatever the real .env says."""
    monkeypatch.setenv("OPENAI_MODEL", "cheap-model")
    monkeypatch.delenv("SMART_MODEL", raising=False)


@pytest.fixture
def smart_model(monkeypatch):
    """Turn on the 'smarter model when needed' option for one test."""
    monkeypatch.setenv("SMART_MODEL", "smart-model")


@pytest.fixture
def setup(monkeypatch):
    """Patch the model functions; returns a helper to configure each test."""
    def configure(intent: Intent, replies=(), plan_steps=(), explain_first=""):
        monkeypatch.setattr(planner, "route", fake_route(intent))
        plan = planner.Plan(goal="test goal", explain_first=explain_first, steps=[planner.PlanStep(tool=t, reason="test") for t in plan_steps])
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
            reply(content="L014 and L015 offer a rate buydown [kb_004]."),
        ],
        plan_steps=["search_listings"],
    )
    result = planner.run_agent("Any Phoenix listings with a buydown?")

    assert [t.name for t in result.tool_calls] == ["search_listings"]
    assert result.tool_calls[0].result["total_matches"] >= 2           # the real tool ran
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


# ---------- caveats added by Python ----------

def test_no_data_note_is_added_under_listing_answers(setup):
    # Where the listings come from is stated once in the website's sidebar, not per answer.
    setup(Intent.LISTING_SEARCH, replies=[
        reply(tool_calls=[tool_call("c1", "search_listings", metro="Phoenix", incentive_keyword="buydown")]),
        reply(content="Try L014, it has a buydown."),
    ])
    assert planner.run_agent("buydown homes?").answer == "Try L014, it has a buydown."


def record(name, result):
    return planner.ToolCallRecord(name=name, arguments={}, result=result)


def test_estimate_note_added_after_money_tools():
    answer = planner.add_required_notes("About $2,275 a month.", [record("monthly_payment", {})])
    assert answer.endswith(planner.ESTIMATE_NOTE)


def test_no_duplicate_estimate_note_when_model_already_said_it():
    text = "About $2,275 a month. This is an educational estimate, not financial advice."
    assert planner.add_required_notes(text, [record("monthly_payment", {})]) == text


def test_slightly_is_corrected_when_every_home_is_well_above_budget():
    search = record("search_listings", {"listings": [], "closest_above_budget": [
        {"id": "L001", "budget_label": "well above budget"}, {"id": "L008", "budget_label": "well above budget"}]})
    fixed = planner.fix_budget_wording("Here are options slightly above your budget:", [search])
    assert fixed == "Here are options well above your budget:"


def test_slightly_is_kept_when_a_home_really_is_slightly_above():
    search = record("search_listings", {"listings": [], "closest_above_budget": [
        {"id": "L001", "budget_label": "slightly above budget"}]})
    text = "L001 is slightly above your budget."
    assert planner.fix_budget_wording(text, [search]) == text


def test_no_notes_for_a_plain_explanation():
    text = "A buydown lowers your rate for a while [kb_004]."
    assert planner.add_required_notes(text, []) == text


def test_explain_first_goes_into_the_agent_instructions():
    plan = planner.Plan(goal="g", explain_first="how buydowns work (temporary vs permanent)", steps=[])
    assert "FIRST explain" in planner._format_plan(plan) and "temporary vs permanent" in planner._format_plan(plan)


def test_explain_reminder_is_the_last_thing_the_model_reads_after_tools(setup):
    model = setup(
        Intent.PROCESS_QUESTION,
        replies=[
            reply(tool_calls=[tool_call("c1", "search_listings", metro="Phoenix", incentive_keyword="buydown")]),
            reply(content="A buydown lowers your rate [kb_004]. L014 and L015 offer one."),
        ],
        explain_first="how buydowns work",
    )
    planner.run_agent("Explain buydowns and any Phoenix listings with one")
    last = model.calls[1]["messages"][-1]
    assert last["role"] == "system" and "how buydowns work" in last["content"]


def test_no_reminder_when_nothing_to_explain(setup):
    model = setup(Intent.LISTING_SEARCH, replies=[
        reply(tool_calls=[tool_call("c1", "search_listings", metro="Austin")]),
        reply(content="L001 ..."),
    ])
    planner.run_agent("homes in Austin")
    assert model.calls[1]["messages"][-1]["role"] == "tool"


# ---------- smarter model when needed ----------

COMPLEX_PLAN = ["get_listing", "get_listing", "monthly_payment"]
LONG_TEXT = "A buydown lowers your interest rate. " * 20          # ~740 characters


def test_everyday_request_uses_the_cheap_model(setup, smart_model):
    model = setup(Intent.LISTING_SEARCH, replies=[reply(content="L001 is in Austin.")], plan_steps=["search_listings"])
    result = planner.run_agent("homes in Austin")
    assert [c["model"] for c in model.calls] == ["cheap-model"]
    assert result.model == "cheap-model" and result.model_reason == "everyday request"


def test_multi_step_request_uses_the_smart_model(setup, smart_model):
    model = setup(Intent.AFFORDABILITY, replies=[reply(content="L001 costs more than L017.")], plan_steps=COMPLEX_PLAN)
    result = planner.run_agent("compare L001 and L017 monthly")
    assert [c["model"] for c in model.calls] == ["smart-model"]
    assert result.model == "smart-model" and "3-step plan" in result.model_reason


def test_without_smart_model_everything_uses_the_cheap_model(setup):
    model = setup(Intent.AFFORDABILITY, replies=[reply(content="ok")], plan_steps=COMPLEX_PLAN)
    assert planner.run_agent("compare L001 and L017").model == "cheap-model"
    assert model.calls[0]["model"] == "cheap-model"


def test_empty_cheap_answer_is_retried_on_the_smart_model(setup, smart_model):
    model = setup(Intent.LISTING_SEARCH, replies=[reply(content=""), reply(content="Here are the homes.")])
    result = planner.run_agent("homes in Austin")
    assert [c["model"] for c in model.calls] == ["cheap-model", "smart-model"]
    assert result.answer.startswith("Here are the homes.")
    assert result.model_reason == "retry: the first answer was empty"


def test_too_short_explanation_is_retried_on_the_smart_model(setup, smart_model):
    model = setup(Intent.PROCESS_QUESTION, replies=[reply(content="It lowers your rate."), reply(content=LONG_TEXT)],
                  explain_first="how buydowns work")
    result = planner.run_agent("explain buydowns")
    assert [c["model"] for c in model.calls] == ["cheap-model", "smart-model"]
    assert result.answer == LONG_TEXT and "too short" in result.model_reason


def test_good_cheap_answer_is_not_retried(setup, smart_model):
    model = setup(Intent.PROCESS_QUESTION, replies=[reply(content=LONG_TEXT)], explain_first="how buydowns work")
    planner.run_agent("explain buydowns")
    assert len(model.calls) == 1


def test_unavailable_smart_model_falls_back_to_the_cheap_model(setup, smart_model, monkeypatch):
    calls = []

    def flaky(messages, tools, tool_choice="auto", model=None):
        calls.append(model)
        if model == "smart-model":
            raise ModelCallError("NotFoundError: model does not exist")
        return reply(content="Answer from the cheap model.")

    setup(Intent.AFFORDABILITY, plan_steps=COMPLEX_PLAN)
    monkeypatch.setattr(planner, "chat_with_tools", flaky)
    result = planner.run_agent("compare L001 and L017")
    assert calls == ["smart-model", "cheap-model"]
    assert result.answer.startswith("Answer from the cheap model.")
    assert result.model == "cheap-model" and result.model_reason.startswith("fallback")


def test_cheap_model_failure_is_not_hidden(setup, monkeypatch):
    def broken(messages, tools, tool_choice="auto", model=None):
        raise ModelCallError("AuthenticationError")

    setup(Intent.LISTING_SEARCH)
    monkeypatch.setattr(planner, "chat_with_tools", broken)
    with pytest.raises(ModelCallError):          # the app turns this into a friendly message
        planner.run_agent("homes in Austin")


def test_failed_retry_keeps_the_first_answer(setup, smart_model, monkeypatch):
    def cheap_short_smart_down(messages, tools, tool_choice="auto", model=None):
        if model == "smart-model":
            raise ModelCallError("RateLimitError")
        return reply(content="Short.")

    setup(Intent.PROCESS_QUESTION, explain_first="how buydowns work")
    monkeypatch.setattr(planner, "chat_with_tools", cheap_short_smart_down)
    result = planner.run_agent("explain buydowns")
    assert result.answer == "Short." and result.model == "cheap-model"


# ---------- answers written next to tool calls ----------

def test_answer_written_next_to_a_tool_call_is_kept(setup):
    # gpt-4o wrote the whole explanation alongside its search, then only "I've explained...".
    setup(Intent.PROCESS_QUESTION, replies=[
        reply(content=LONG_TEXT, tool_calls=[tool_call("c1", "search_listings", city="Glasgow")]),
        reply(content="I've explained the steps above."),
    ])
    answer = planner.run_agent("walk me through buying").answer
    assert answer.startswith(LONG_TEXT.strip()) and "I've explained the steps above." in answer


def test_short_filler_next_to_a_tool_call_is_dropped(setup):
    setup(Intent.LISTING_SEARCH, replies=[
        reply(content="Let me check.", tool_calls=[tool_call("c1", "search_listings", city="Glasgow")]),
        reply(content="No homes matched in Glasgow."),
    ])
    assert planner.run_agent("homes in Glasgow").answer == "No homes matched in Glasgow."


def test_full_final_answer_is_not_doubled():
    final = LONG_TEXT + " Here is a recap."
    assert planner.combine_answer([LONG_TEXT], final) == final


# ---------- the buyer's budget is applied to searches ----------

def test_budget_from_affordability_is_added_to_a_search_without_one(setup):
    model = setup(Intent.AFFORDABILITY, replies=[
        reply(tool_calls=[tool_call("c1", "max_affordable_price", annual_income=95000, monthly_debts=400,
                                    down_payment_savings=40000, annual_rate=6.5)]),
        reply(tool_calls=[tool_call("c2", "search_listings", metro="Austin", min_beds=3)]),   # no max_price!
        reply(content="Here are the Austin homes within your budget."),
    ])
    result = planner.run_agent("I earn 95k... what can I afford in Austin?")
    search = result.tool_calls[1]
    assert search.arguments["max_price"] == pytest.approx(305_000, abs=1_000)
    assert "max_price set" in search.note
    assert all(home["price_usd"] <= search.arguments["max_price"] for home in search.result["listings"])
    assert "max_price set" in model.calls[2]["messages"][-1]["content"]      # the model was told


def test_explicit_max_price_is_never_overwritten():
    arguments, note = planner.apply_budget('{"metro": "Austin", "max_price": 500000}', 305_000)
    assert '"max_price": 500000' in arguments and note is None


# ---------- tools that misbehave ----------

def test_crashing_tool_becomes_an_error_message(monkeypatch):
    def broken_tool(**kwargs):
        raise KeyError("oops")

    monkeypatch.setitem(planner.TOOL_FUNCTIONS, "get_listing", broken_tool)
    record = planner.run_tool("get_listing", '{"listing_id": "L001"}')
    assert "failed unexpectedly" in record.error


def test_non_object_arguments_are_rejected():
    assert "JSON object" in planner.run_tool("search_listings", "[1, 2]").error


def test_answer_guardrail_replaces_unsafe_answer(setup):
    setup(Intent.LISTING_SEARCH, replies=[reply(content="Prosper is predominantly young families, great for you.")])
    result = planner.run_agent("homes in Dallas")
    assert result.answer == FAIR_HOUSING_RESPONSE
    assert "answer check" in result.guardrail
