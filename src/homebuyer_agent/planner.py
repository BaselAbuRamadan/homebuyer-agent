"""V2 planning agent: route -> retrieve -> plan -> choose model -> act (tool loop) -> answer -> check.

Short-term memory: run_agent() can take the last few conversation turns, so a
follow-up like "yes" is understood. Nothing is stored between program runs.

This is "planning autonomy": the model decides which steps to take and adapts
them to what the tools return. Python stays in control of the loop, runs every
tool, picks which model to use, and enforces the safety checks and the iteration limit.

Smarter model WHEN NEEDED (OPENAI_MODEL is cheap, SMART_MODEL is stronger):
- the plan has COMPLEX_PLAN_STEPS or more tool steps -> SMART_MODEL from the start
- otherwise OPENAI_MODEL; if that attempt fails a check (empty answer, hit the tool
  limit, ended on a failed tool call, too-short explanation) -> one retry on SMART_MODEL
- if SMART_MODEL is unavailable (wrong name, no access, rate limit) -> back to OPENAI_MODEL
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from openinference.semconv.trace import SpanAttributes
from pydantic import BaseModel, Field

from homebuyer_agent.config import get_model, get_smart_model
from homebuyer_agent.guardrails import (
    FAIR_HOUSING_RESPONSE,
    OUT_OF_SCOPE_RESPONSE,
    TALK_TO_AGENT_RESPONSE,
    check_answer,
    check_message,
)
from homebuyer_agent.llm import ModelCallError, chat_with_tools, structured_completion
from homebuyer_agent.retrieval import RetrievedChunk, retrieve
from homebuyer_agent.router import Intent, load_prompt, route
from homebuyer_agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from homebuyer_agent.tools.listings import load_listings
from homebuyer_agent.tracing import set_output, traced_step

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6          # most rounds of tool calls before we force an answer
RETRIEVAL_K = 3             # how many knowledge-base chunks to retrieve
MAX_HISTORY_MESSAGES = 6    # last 3 exchanges (user + assistant) kept as conversation memory
PLANNER_PROMPT = "planner_v2"
AGENT_PROMPT = "agent_v4"   # v4 = v3 without a data note per answer (the sidebar says it once)
COMPLEX_PLAN_STEPS = 3      # plans with this many tool steps go to SMART_MODEL
MIN_EXPLANATION_CHARS = 400 # an "explain" answer shorter than this counts as a failed attempt
INTERIM_MIN_CHARS = 200     # text written next to a tool call this long is a real answer, not filler

ToolName = Literal["max_affordable_price", "monthly_payment", "search_listings", "get_listing"]


# ---------- data shapes ----------

class PlanStep(BaseModel):
    tool: ToolName = Field(description="Which tool to call.")
    reason: str = Field(description="One short sentence: why this step is needed.")


class Plan(BaseModel):
    """Structured output of the planning step."""

    goal: str = Field(description="What the user wants, in one sentence.")
    explain_first: str = Field(
        description=(
            "If the user asks to explain, describe or understand how something works (e.g. 'explain how "
            "buydowns work', 'walk me through the steps'), name that topic here, including the main types "
            "or options to cover. Otherwise an empty string."
        )
    )
    steps: list[PlanStep] = Field(description="Tool calls in order. Empty if no tools are needed.")


class ToolCallRecord(BaseModel):
    """One tool call the agent made, kept for evaluation and the UI."""

    name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    note: str | None = None           # anything Python changed, e.g. "max_price set to the budget"


class AgentResult(BaseModel):
    """Everything that happened in one run, so it can be evaluated and displayed."""

    message: str
    intent: str
    route_reasoning: str
    plan: Plan | None = None
    tool_calls: list[ToolCallRecord] = []
    retrieved_docs: list[str] = []
    answer: str
    listing_ids: list[str] = []
    guardrail: str | None = None      # which safety check fired, if any
    hit_iteration_limit: bool = False
    model: str | None = None          # which model wrote the answer (None for fixed safe replies)
    model_reason: str | None = None   # why that model was used


@dataclass
class ActResult:
    """What one run of the tool loop produced."""

    answer: str
    tool_calls: list[ToolCallRecord]
    hit_limit: bool


# ---------- helpers ----------

def _fill(template: str, **values: str) -> str:
    """Replace {name} placeholders. Plain replace, so other braces in a prompt are safe."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def _format_guidance(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant guidance found)"
    return "\n\n".join(f"[{c.doc_id}] {c.text}" for c in chunks)


def _format_plan(plan: Plan) -> str:
    lines = [f"Goal: {plan.goal}"]
    if plan.explain_first:
        lines.append(f"FIRST explain, in plain words from the guidance: {plan.explain_first}. "
                     "Do this before any listings or numbers.")
    if not plan.steps:
        lines.append("(No tools needed: answer from the guidance.)")
    lines += [f"{i}. {s.tool}: {s.reason}" for i, s in enumerate(plan.steps, 1)]
    return "\n".join(lines)


def explain_reminder(topic: str) -> str:
    return (f"Reminder: the user asked for an explanation. Start your answer by explaining {topic} "
            "in plain words from the guidance (with its [kb_00X] citation), and only then give the tool results. "
            "The user sees ONLY your final message, so write the whole explanation there, "
            "even if you already wrote some of it earlier.")


ESTIMATE_NOTE = "_Note: figures are educational estimates, not financial advice._"
MONEY_TOOLS = {"monthly_payment", "max_affordable_price"}


def add_required_notes(answer: str, tool_calls: list[ToolCallRecord]) -> str:
    """Make sure money figures carry the "not financial advice" caveat, added by Python
    if the model forgot (the M6 eval showed prompts alone don't guarantee caveats).

    Where the listings come from is stated once in the website's sidebar, not under
    every answer.
    """
    if MONEY_TOOLS & {t.name for t in tool_calls} and "financial advice" not in answer.lower():
        return f"{answer}\n\n{ESTIMATE_NOTE}"
    return answer


def fix_budget_wording(answer: str, tool_calls: list[ToolCallRecord]) -> str:
    """Stop "slightly above budget" when every suggested home is WELL above it.

    The search tool labels each closest-above-budget home ("slightly" up to $30k over,
    "well" beyond). gpt-4o ignored the label once and called a $72,000 gap "slightly".
    If all labels say "well above budget", any "slightly above/over" becomes "well above".
    """
    labels = [
        home.get("budget_label")
        for call in tool_calls
        if call.name == "search_listings" and call.error is None
        for home in call.result.get("closest_above_budget", [])
    ]
    if labels and all(label == "well above budget" for label in labels):
        return re.sub(r"\bslightly (above|over)\b", "well above", answer, flags=re.IGNORECASE)
    return answer


def apply_budget(arguments_json: str, budget: float) -> tuple[str, str | None]:
    """Add the buyer's affordable price to a home search that has no max_price.

    In the model comparison, gpt-4o computed a $305,000 budget and then searched
    WITHOUT it, so the tool could not label homes "slightly" or "well" above budget
    and the model judged the gap itself ("slightly above" for $72,000 over).
    Returns the (possibly changed) arguments and a note saying what changed.
    """
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return arguments_json, None
    if not isinstance(arguments, dict) or arguments.get("max_price") is not None:
        return arguments_json, None
    arguments["max_price"] = budget
    return json.dumps(arguments), f"max_price set to the buyer's affordable price (${budget:,.0f}) from max_affordable_price"


def combine_answer(interim: list[str], final: str) -> str:
    """Keep an answer the model wrote NEXT TO a tool call, which the user would never see.

    In testing, gpt-4o wrote a full 2,700-character explanation alongside its search
    call, then finished with only "I've explained the steps..." (278 characters).
    If the final message is much shorter than that earlier text, show both.
    Short filler like "Let me look that up." is ignored.
    """
    written_before = "\n\n".join(t.strip() for t in interim if len(t.strip()) >= INTERIM_MIN_CHARS)
    if written_before and len(final.strip()) < len(written_before) / 2:
        return f"{written_before}\n\n{final.strip()}".strip()
    return final


def choose_model(plan: Plan) -> tuple[str, str]:
    """Pick the model for the tool loop, and say why (shown in the UI and traces)."""
    base, smart = get_model(), get_smart_model()
    if smart != base and len(plan.steps) >= COMPLEX_PLAN_STEPS:
        return smart, f"multi-step request ({len(plan.steps)}-step plan)"
    return base, "everyday request"


def retry_reason(act: ActResult, plan: Plan) -> str | None:
    """Plain checks that a cheap attempt went wrong. None means it looks fine."""
    if not act.answer.strip():
        return "the first answer was empty"
    if act.hit_limit:
        return "the first attempt hit the tool-call limit"
    if act.tool_calls and act.tool_calls[-1].error is not None:
        return "the first attempt ended on a failed tool call"
    if plan.explain_first and len(act.answer) < MIN_EXPLANATION_CHARS:
        return "the first explanation was too short"
    return None


def _listing_ids_in(text: str) -> list[str]:
    """Listing ids (L001...) mentioned in text that really exist, in order, without repeats."""
    known = {l["id"] for l in load_listings()}
    found = re.findall(r"\bL\d{3}\b", text.upper())
    return [i for i in dict.fromkeys(found) if i in known]


def run_tool(name: str, arguments_json: str) -> ToolCallRecord:
    """Run one tool the model asked for. Never raises: errors go back to the model as text.

    That way a bad argument (e.g. rate=65) becomes a message the model can fix,
    instead of crashing the whole run.
    """
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return ToolCallRecord(name=name, arguments={}, error=f"Arguments were not valid JSON: {e}")
    if name not in TOOL_FUNCTIONS:
        return ToolCallRecord(name=name, arguments=arguments, error=f"Unknown tool {name!r}")
    if not isinstance(arguments, dict):
        return ToolCallRecord(name=name, arguments={}, error="Arguments must be a JSON object")

    with traced_step(f"tool: {name}", "TOOL", json.dumps(arguments)) as span:
        span.set_attribute(SpanAttributes.TOOL_NAME, name)
        try:
            result = TOOL_FUNCTIONS[name](**arguments)
            record = ToolCallRecord(name=name, arguments=arguments, result=result)
        except (TypeError, ValueError) as e:   # wrong/missing arguments or impossible values
            record = ToolCallRecord(name=name, arguments=arguments, error=str(e))
        except Exception as e:                 # a bug in a tool must not break the whole answer
            logger.exception("Tool %s crashed", name)
            record = ToolCallRecord(name=name, arguments=arguments,
                                    error=f"The {name} tool failed unexpectedly ({type(e).__name__}).")
        set_output(span, json.dumps(record.result if record.error is None else {"error": record.error}, default=str))
    return record


def _act(start: list[dict], plan: Plan, model: str) -> ActResult:
    """The tool loop: let the model call tools until it has enough to answer.

    start: system prompt + history + the user's message. Copied, so a retry can
    begin again from the same point.
    """
    messages = list(start)
    tool_calls: list[ToolCallRecord] = []
    interim: list[str] = []          # text the model wrote next to its tool calls
    budget: float | None = None      # the affordable price, once max_affordable_price has run

    for _ in range(MAX_ITERATIONS):
        reply = chat_with_tools(messages, TOOL_SCHEMAS, model=model)
        if not reply.tool_calls:          # no more tools wanted: this is the answer
            return ActResult(combine_answer(interim, reply.content or ""), tool_calls, hit_limit=False)
        if reply.content:
            interim.append(reply.content)
        # Record the model's request, run each tool, and send the results back.
        messages.append({
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in reply.tool_calls
            ],
        })
        for tc in reply.tool_calls:
            arguments_json, note = tc.function.arguments, None
            if tc.function.name == "search_listings" and budget:
                arguments_json, note = apply_budget(arguments_json, budget)
            record = run_tool(tc.function.name, arguments_json)
            if note and record.error is None:
                record.note = note
                record.result["note"] = f"{record.result.get('note', '')} {note}.".strip()
            if record.name == "max_affordable_price" and record.error is None:
                budget = record.result.get("max_price") or budget
            tool_calls.append(record)
            payload = record.result if record.error is None else {"error": record.error}
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(payload, default=str)})
        if plan.explain_first:
            # The model pays most attention to what it read last. After a long block of
            # listing results it forgot the "explain" part (M6 eval, case A02), so we
            # repeat it here, right before it writes.
            messages.append({"role": "system", "content": explain_reminder(plan.explain_first)})

    # Limit reached: no more tools allowed, the model must answer with what it has.
    final = chat_with_tools(messages, TOOL_SCHEMAS, tool_choice="none", model=model).content or ""
    return ActResult(combine_answer(interim, final), tool_calls, hit_limit=True)


def _act_with_smart_model_when_needed(start: list[dict], plan: Plan) -> tuple[ActResult, str, str]:
    """Run the tool loop on the right model (see the module docstring). Returns result, model, reason."""
    base, smart = get_model(), get_smart_model()
    model, reason = choose_model(plan)
    try:
        act = _act(start, plan, model)
    except ModelCallError as e:
        if model == base:
            raise                               # nothing cheaper to fall back to
        logger.warning("Smart model failed, falling back to %s: %s", base, e)
        return _act(start, plan, base), base, f"fallback: {smart} was unavailable"

    if model == base and smart != base:
        problem = retry_reason(act, plan)
        if problem:
            try:
                return _act(start, plan, smart), smart, f"retry: {problem}"
            except ModelCallError as e:         # keep the first attempt rather than fail
                logger.warning("Smart-model retry failed, keeping the first attempt: %s", e)
    return act, model, reason


# ---------- the agent ----------

def run_agent(message: str, history: list[dict] | None = None, agent_prompt: str = AGENT_PROMPT) -> AgentResult:
    """Answer one homebuyer message. See the module docstring for the steps.

    history (optional): earlier turns as [{"role": "user"/"assistant", "content": "..."}],
    oldest first. It lets the agent understand follow-ups like "yes" or "what about L030?".
    Only the last MAX_HISTORY_MESSAGES are used, to keep prompts short.
    agent_prompt: which prompts/agent_vN.txt to use (the eval compares versions).
    """
    history = (history or [])[-MAX_HISTORY_MESSAGES:]
    with traced_step("run_agent", "AGENT", message) as root:
        root.set_attribute("agent.history_turns", len(history))
        root.set_attribute("agent.prompt_version", agent_prompt)
        result = _run(message, history, agent_prompt)
        root.set_attribute("agent.intent", result.intent)
        root.set_attribute("agent.tools", ",".join(t.name for t in result.tool_calls))
        root.set_attribute("agent.model", result.model or "none (fixed reply)")
        root.set_attribute("agent.model_reason", result.model_reason or "")
        set_output(root, result.answer)
        return result


def _run(message: str, history: list[dict], agent_prompt: str) -> AgentResult:
    # 1. ROUTE, plus a keyword safety net in case the router misses steering.
    decision = route(message, history=history)
    intent = decision.intent
    base = {"message": message, "intent": intent.value, "route_reasoning": decision.reasoning}

    input_check = check_message(message)
    if intent == Intent.FAIR_HOUSING_SENSITIVE or input_check.flagged:
        reason = "router" if intent == Intent.FAIR_HOUSING_SENSITIVE else f"input check: '{input_check.matched}'"
        return AgentResult(**base, answer=FAIR_HOUSING_RESPONSE, retrieved_docs=["kb_007"], guardrail=f"fair_housing ({reason})")
    if intent == Intent.TALK_TO_AGENT:
        ids = _listing_ids_in(message)
        listing_part = f" for {', '.join(ids)}" if ids else ""
        return AgentResult(**base, answer=TALK_TO_AGENT_RESPONSE.format(listing_part=listing_part), listing_ids=ids)
    if intent == Intent.OUT_OF_SCOPE:
        return AgentResult(**base, answer=OUT_OF_SCOPE_RESPONSE)

    # 2. RETRIEVE guidance from the knowledge base. A reply like "yes" matches nothing,
    #    so search with the user's previous message as well.
    previous_user = [m["content"] for m in history if m["role"] == "user"][-1:]
    query = " ".join(previous_user + [message])
    with traced_step("retrieve", "RETRIEVER", query) as span:
        chunks = retrieve(query, k=RETRIEVAL_K)
        for i, c in enumerate(chunks):   # Phoenix shows these as a list of documents
            span.set_attribute(f"retrieval.documents.{i}.document.id", c.doc_id)
            span.set_attribute(f"retrieval.documents.{i}.document.score", c.score)
            span.set_attribute(f"retrieval.documents.{i}.document.content", c.text)
    guidance = _format_guidance(chunks)
    doc_ids = list(dict.fromkeys(c.doc_id for c in chunks))

    # 3. PLAN which tools to use (structured output, like the router). The cheap model
    #    is enough here, and the plan tells us how hard the question is.
    with traced_step("plan", "CHAIN", message) as span:
        planner_prompt = _fill(load_prompt(PLANNER_PROMPT), intent=intent.value, guidance=guidance)
        plan = structured_completion(planner_prompt, message, Plan, history=history)
        set_output(span, plan.model_dump_json())

    # 4. ACT on the right model: the tool loop, with a smarter model when needed.
    system = _fill(load_prompt(agent_prompt), plan=_format_plan(plan), guidance=guidance)
    start: list[dict] = [
        {"role": "system", "content": system},
        *history,                                  # earlier turns, so follow-ups make sense
        {"role": "user", "content": message},
    ]
    with traced_step("act", "CHAIN", _format_plan(plan)) as span:
        act, model, model_reason = _act_with_smart_model_when_needed(start, plan)
        span.set_attribute("agent.model", model)
        span.set_attribute("agent.model_reason", model_reason)

    # 5 + 6. ANSWER, after a fair-housing check on what we're about to show.
    answer = act.answer
    with traced_step("answer", "CHAIN", answer) as span:
        output_check = check_answer(answer)
        guardrail = None
        if output_check.flagged:
            guardrail = f"fair_housing (answer check: '{output_check.matched}')"
            answer = FAIR_HOUSING_RESPONSE
        else:
            answer = fix_budget_wording(answer, act.tool_calls)
            answer = add_required_notes(answer, act.tool_calls)
        span.set_attribute("agent.guardrail", guardrail or "none")
        set_output(span, answer)

    return AgentResult(
        **base,
        plan=plan,
        tool_calls=act.tool_calls,
        retrieved_docs=doc_ids,
        answer=answer,
        listing_ids=_listing_ids_in(answer),
        guardrail=guardrail,
        hit_iteration_limit=act.hit_limit,
        model=model,
        model_reason=model_reason,
    )
