"""Tests for the Streamlit app with a FAKE agent, so there are no API calls.

Streamlit's AppTest runs app.py like a browser would: we can click buttons, type
messages and read what is on the page.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from homebuyer_agent import planner
from homebuyer_agent.planner import AgentResult, Plan, PlanStep, ToolCallRecord

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def fake_agent(message, history=None, agent_prompt=planner.AGENT_PROMPT):
    return AgentResult(
        message=message, intent="listing_search", route_reasoning="test",
        plan=Plan(goal="find homes", explain_first="", steps=[PlanStep(tool="search_listings", reason="search")]),
        tool_calls=[ToolCallRecord(name="search_listings", arguments={"metro": "Austin"}, result={"total_matches": 1},
                                   note="max_price set to the buyer's affordable price ($305,000)")],
        retrieved_docs=["kb_004"], answer=f"Fake answer to: {message}",
        model="test-model", model_reason="everyday request",
    )


def broken_agent(message, history=None, agent_prompt=planner.AGENT_PROMPT):
    raise RuntimeError("API down: secret details that must not be shown")


@pytest.fixture
def make_app(monkeypatch):
    """Start the app with a fake agent. Extra settings can be passed as environment variables."""
    def start(**env) -> AppTest:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_MODEL", "test-model")
        monkeypatch.setenv("SMART_MODEL", "test-model")          # same as base = "not used"
        monkeypatch.delenv("DAILY_QUESTION_LIMIT", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(planner, "run_agent", fake_agent)
        return AppTest.from_file(APP, default_timeout=30).run()
    return start


@pytest.fixture
def app(make_app):
    return make_app()


def page_text(at: AppTest) -> str:
    elements = list(at.title) + list(at.markdown) + list(at.caption) + list(at.info)
    return " ".join(str(m.value) for m in elements)


def test_start_screen_shows_title_and_four_cards(app):
    assert "Your Housing Chatbot" in page_text(app)
    cards = [b for b in app.button if b.key and b.key.startswith("example_")]
    assert len(cards) == 4
    assert "Demo by Basel Aburamadan" in page_text(app)
    assert len(app.exception) == 0


def test_clicking_a_card_asks_that_question(app):
    app.button(key="example_3").click().run()
    assert "Fake answer to: How do builder rate buydowns work?" in page_text(app)
    assert any(e.label == "Under the hood" for e in app.expander)
    assert app.session_state.questions_asked == 1


def test_under_the_hood_shows_the_model_and_tool_notes(app):
    app.button(key="example_0").click().run()
    text = page_text(app)
    assert "test-model" in text and "everyday request" in text
    assert "max_price set" in text


def test_typed_question_is_answered(app):
    app.chat_input(key="hero_input").set_value("homes in Dallas").run()
    assert "Fake answer to: homes in Dallas" in page_text(app)


def test_question_limit_stops_more_questions(app):
    app.session_state.questions_asked = 15
    app.run()
    assert "used all 15 questions" in page_text(app)
    assert app.chat_input(key="hero_input").disabled


def test_shared_daily_limit_stops_questions_for_everyone(make_app):
    app = make_app(DAILY_QUESTION_LIMIT="0")
    app.button(key="example_0").click().run()
    assert "today's question limit" in page_text(app)
    assert app.session_state.questions_asked == 0        # nothing was sent to the agent


def test_api_error_shows_friendly_message_not_traceback(app, monkeypatch):
    monkeypatch.setattr(planner, "run_agent", broken_agent)
    app.button(key="example_0").click().run()
    text = page_text(app)
    assert "couldn't reach the AI service" in text
    assert "secret details" not in text and len(app.exception) == 0


def test_error_replies_are_kept_out_of_the_agents_memory(app, monkeypatch):
    monkeypatch.setattr(planner, "run_agent", broken_agent)
    app.button(key="example_0").click().run()            # this one fails

    seen = {}

    def recording_agent(message, history=None, agent_prompt=planner.AGENT_PROMPT):
        seen["history"] = history
        return fake_agent(message, history)

    monkeypatch.setattr(planner, "run_agent", recording_agent)
    app.chat_input(key="chat_input").set_value("try again").run()
    contents = [m["content"] for m in seen["history"]]
    assert "Show me 3-bed homes in Austin under $450k" in contents
    assert not any("couldn't reach" in c for c in contents)


def test_settings_from_streamlit_secrets_are_used(make_app, monkeypatch):
    monkeypatch.setenv("SMART_MODEL", "placeholder")          # so the test restores it afterwards
    monkeypatch.setattr(planner, "run_agent", fake_agent)
    at = AppTest.from_file(APP, default_timeout=30)
    at.secrets["OPENAI_API_KEY"] = "test-key"
    at.secrets["OPENAI_MODEL"] = "test-model"
    at.secrets["SMART_MODEL"] = "secret-smart-model"
    at.run()
    assert "secret-smart-model" in page_text(at)              # shown in the sidebar's "How it works"
