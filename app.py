"""Milestone 7: public Streamlit demo of the homebuyer agent.

Run locally:  streamlit run app.py   (opens http://localhost:8501)

How Streamlit works, in one line: the whole script reruns from top to bottom on every
click or message. Anything that must survive a rerun (the chat, the question count)
lives in st.session_state.

Safety and cost, because this is public and uses a real OpenAI key:
- the key and models come from st.secrets (Streamlit Cloud) or the .env file, never the code
- each visitor gets MAX_QUESTIONS questions per session, MAX_CHARS characters each
- ALL visitors together get DAILY_QUESTION_LIMIT questions per day (a refresh can't reset it)
- the input is disabled while an answer is being written, so it can't be sent twice
- Phoenix tracing is never turned on here
- API failures show a friendly message, never a traceback

Look and feel use native Streamlit elements plus .streamlit/config.toml (no custom CSS),
following Streamlit's own best-practice guide.
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

import streamlit as st

# Make the agent package importable on Streamlit Cloud without installing it.
sys.path.insert(0, str(Path(__file__).parent / "src"))

MAX_QUESTIONS = 15                 # per visitor, per browser session
MAX_CHARS = 500                    # per question
DEFAULT_DAILY_LIMIT = 300          # all visitors together; override with DAILY_QUESTION_LIMIT
REPO_URL = "https://github.com/BaselAbuRamadan/homebuyer-agent"
SETTINGS = ("OPENAI_API_KEY", "OPENAI_MODEL", "SMART_MODEL", "DAILY_QUESTION_LIMIT")
EXAMPLES = [   # (card text, Material Symbols icon)
    ("Show me 3-bed homes in Austin under $450k", ":material/home:"),
    ("I earn $90k with $500/month debts. What can I afford?", ":material/payments:"),
    ("What's the monthly cost of L001 with 10% down?", ":material/calculate:"),
    ("How do builder rate buydowns work?", ":material/school:"),
]
INTENT_LABELS = {
    "listing_search": "Home search",
    "affordability": "Affordability / costs",
    "process_question": "Buying-process question",
    "talk_to_agent": "Hand-off to a person",
    "out_of_scope": "Outside what I can help with",
    "fair_housing_sensitive": "Fair-housing safeguard",
}
ERROR_REPLY = "Sorry, I couldn't reach the AI service just now. Please try again in a moment."
LOGO_SVG = (
    '<svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="32" fill="#0F766E"/>'
    '<text x="32" y="43" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
    'font-size="32" font-weight="700" fill="#FFFFFF">H</text></svg>'
)


# ---------- setup ----------

def load_settings() -> None:
    """Copy the settings from st.secrets into the environment, where the agent code reads them.

    Locally there is usually no secrets file, so we simply fall back to the .env
    file / existing environment variables.
    """
    for key in SETTINGS:
        try:
            value = st.secrets.get(key)
        except Exception:   # no secrets file at all: that's fine locally
            value = None
        if value:
            os.environ[key] = str(value)


def daily_limit_setting() -> int:
    """DAILY_QUESTION_LIMIT from settings, or the default if missing or not a number."""
    try:
        return max(0, int(os.getenv("DAILY_QUESTION_LIMIT", DEFAULT_DAILY_LIMIT)))
    except ValueError:
        return DEFAULT_DAILY_LIMIT


st.set_page_config(page_title="Your Housing Chatbot", page_icon=":material/home:", layout="centered")
load_settings()

from homebuyer_agent import planner  # noqa: E402  (import after the settings are in place)
from homebuyer_agent.config import get_model, get_smart_model  # noqa: E402
from homebuyer_agent.retrieval import doc_title  # noqa: E402
from homebuyer_agent.usage import DailyLimit  # noqa: E402

if not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")):
    # Importing the agent loaded .env, so a missing value means the app isn't set up yet.
    st.warning("OPENAI_API_KEY and OPENAI_MODEL need to be set in Streamlit secrets or the .env file.",
               title="This demo isn't configured yet")
    st.stop()


@st.cache_resource
def shared_daily_limit(limit: int) -> DailyLimit:
    """ONE counter shared by every visitor (cache_resource keeps a single object per server)."""
    return DailyLimit(limit)


# All per-visitor state, initialised in one place.
st.session_state.setdefault("messages", [])         # [{"role", "content", "details", "error"}]
st.session_state.setdefault("questions_asked", 0)
st.session_state.setdefault("pending", None)        # a question waiting to be answered on this run
st.session_state.setdefault("daily_limit_hit", False)


# ---------- helpers ----------

def short_json(value, limit: int = 220) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def details_from(result: planner.AgentResult, seconds: float) -> dict:
    """Keep only what the 'Under the hood' panel shows, as plain data."""
    return {
        "seconds": round(seconds, 1),
        "intent": result.intent,
        "model": result.model,
        "model_reason": result.model_reason,
        "guardrail": result.guardrail,
        "goal": result.plan.goal if result.plan else None,
        "steps": [f"{s.tool}: {s.reason}" for s in result.plan.steps] if result.plan else [],
        "tools": [
            {"name": t.name, "inputs": short_json(t.arguments, 160), "note": t.note,
             "output": f"error: {t.error}" if t.error else short_json(t.result)}
            for t in result.tool_calls
        ],
        "guides": [f"{d} · {doc_title(d)}" for d in result.retrieved_docs],
    }


def show_details(details: dict) -> None:
    """The collapsed panel under each answer."""
    with st.expander("Under the hood", type="compact", icon=":material/manage_search:"):
        st.markdown(f"**Intent:** {INTENT_LABELS.get(details['intent'], details['intent'])} "
                    f"(`{details['intent']}`)")
        if details.get("model"):
            st.markdown(f"**Model:** `{details['model']}` ({details['model_reason']})")
        if details["guardrail"]:
            st.markdown(f"**Safety check:** {details['guardrail']}")
        if details["goal"]:
            st.markdown(f"**Plan:** {details['goal']}")
            for i, step in enumerate(details["steps"], 1):
                st.markdown(f"{i}. `{step}`")
        if details["tools"]:
            st.markdown("**Tool calls** (the maths is done by Python, not the AI):")
            for tool in details["tools"]:
                note = f"  \n  note: {tool['note']}" if tool.get("note") else ""
                st.markdown(f"- `{tool['name']}`  \n  inputs: `{tool['inputs']}`{note}  \n  result: `{tool['output']}`")
        if details["guides"]:
            st.markdown("**Guides used:** " + ", ".join(details["guides"]))
        if not (details["goal"] or details["tools"]):
            st.caption("Answered with a fixed safe reply; no tools were needed.")
        st.caption(f"Answered in {details['seconds']} s")


def queue_question(question: str) -> None:
    """Callback for the chat input and the example cards: accept a question.

    Callbacks run before the script reruns, so the page goes straight to chat view.
    """
    question = (question or "").strip()
    if not question or st.session_state.questions_asked >= MAX_QUESTIONS:
        return
    if len(question) > MAX_CHARS:
        st.toast(f"Please keep questions under {MAX_CHARS} characters.", icon=":material/warning:")
        return
    if not shared_daily_limit(daily_limit_setting()).try_use():
        st.session_state.daily_limit_hit = True
        return
    st.session_state.pending = question


def queue_typed(input_key: str) -> None:
    queue_question(st.session_state.get(input_key))


def history_for_agent() -> list[dict]:
    """Earlier turns for the agent's memory. Error replies are left out: they'd only confuse it."""
    return [{"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages if not m.get("error")]


def answer_pending() -> None:
    """Answer the waiting question, showing a thinking indicator while the agent works."""
    question = st.session_state.pending
    st.session_state.pending = None
    history = history_for_agent()
    st.session_state.messages.append({"role": "user", "content": question, "details": None})
    st.session_state.questions_asked += 1
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.status(":shimmer[Thinking… this can take 10–20 seconds]", type="compact"):
            start = time.perf_counter()
            try:
                result = planner.run_agent(question, history=history)
                message = {"role": "assistant", "content": result.answer,
                           "details": details_from(result, time.perf_counter() - start)}
            except Exception:
                logging.exception("Agent failed")   # full error in the server log only
                message = {"role": "assistant", "content": ERROR_REPLY, "details": None, "error": True}
    st.session_state.messages.append(message)
    st.rerun()   # redraw the conversation with the finished answer and its panel


# ---------- sidebar ----------

with st.sidebar:
    st.subheader("What can I ask?")
    st.markdown(
        "- **Homes:** search new-build listings by city, price, bedrooms or features\n"
        "- **Affordability:** what price fits your income, debts and savings\n"
        "- **Monthly cost:** loan, tax, insurance, HOA and PMI for a home\n"
        "- **Buying process:** buydowns, inspections, closing costs and more"
    )
    base_model, smart_model = get_model(), get_smart_model()
    models = (f"Everyday questions use `{base_model}`; multi-step ones switch to `{smart_model}`."
              if smart_model != base_model else f"Answers use `{base_model}`.")
    st.caption("**How it works:** an AI agent plans the steps, uses calculators and a listing search "
               f"(Python does all the maths), and cites buying guides. {models}")
    st.caption("Listings are sample data for this demo. Figures are educational estimates, not financial advice.")
    st.caption(f"Questions used this session: {st.session_state.questions_asked} / {MAX_QUESTIONS}")
    if st.session_state.messages and st.button("Start a new chat", key="new_chat", icon=":material/add_comment:"):
        st.session_state.messages = []
        st.rerun()


# ---------- main page ----------

limit_message = (f"You've used all {MAX_QUESTIONS} questions for this demo session. "
                 f"Thanks for trying it! You can see how it works on [GitHub]({REPO_URL}).")
daily_message = "The demo has reached today's question limit. Please come back tomorrow."


def show_limit_notices(limit_reached: bool) -> None:
    if limit_reached:
        st.info(limit_message)
    elif st.session_state.daily_limit_hit:
        st.info(daily_message)


if not st.session_state.messages and not st.session_state.pending:
    # Start screen: logo, title, subtitle, centred input and example cards.
    limit_reached = st.session_state.questions_asked >= MAX_QUESTIONS
    st.space("large")
    with st.container(horizontal_alignment="center"):
        st.image(LOGO_SVG, width=64, alt="Your Housing Chatbot logo: the letter H in a teal circle")
    st.title("Your Housing Chatbot", anchor=False, text_alignment="center")
    st.markdown(":gray[Ask about new-build homes, what you can afford, and how buying works.]",
                text_alignment="center")
    with st.container():   # inside a container, chat_input sits in the page instead of the bottom
        st.chat_input("Ask anything…", key="hero_input", max_chars=MAX_CHARS, disabled=limit_reached,
                      submit_mode="disable", on_submit=queue_typed, args=("hero_input",))
    show_limit_notices(limit_reached)
    with st.grid(2):
        for i, (example, icon) in enumerate(EXAMPLES):
            st.button(example, key=f"example_{i}", icon=icon, width="stretch", wrap=True,
                      disabled=limit_reached, on_click=queue_question, args=(example,))
else:
    # Chat view: earlier messages, then the newest answer, input at the bottom.
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["details"]:
                show_details(message["details"])
    if st.session_state.pending:
        answer_pending()
    limit_reached = st.session_state.questions_asked >= MAX_QUESTIONS
    show_limit_notices(limit_reached)
    st.chat_input("Ask anything…", key="chat_input", max_chars=MAX_CHARS, disabled=limit_reached,
                  submit_mode="disable", on_submit=queue_typed, args=("chat_input",))

st.space("medium")
st.caption("Demo by Basel Aburamadan", text_alignment="center")
