"""V2 planning agent: route -> retrieve -> plan -> act (tool loop) -> answer -> check.

Short-term memory: run_agent() can take the last few conversation turns, so a
follow-up like "yes" is understood. Nothing is stored between program runs.

This is "planning autonomy": the model decides which steps to take and adapts
them to what the tools return. Python stays in control of the loop, runs every
tool, and enforces the safety checks and the iteration limit.
"""
import json
import re
from typing import Any, Literal

from openinference.semconv.trace import SpanAttributes
from pydantic import BaseModel, Field

from homebuyer_agent.guardrails import (
    FAIR_HOUSING_RESPONSE,
    OUT_OF_SCOPE_RESPONSE,
    TALK_TO_AGENT_RESPONSE,
    check_answer,
    check_message,
)
from homebuyer_agent.llm import chat_with_tools, structured_completion
from homebuyer_agent.retrieval import RetrievedChunk, retrieve
from homebuyer_agent.router import Intent, load_prompt, route
from homebuyer_agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from homebuyer_agent.tools.listings import load_listings
from homebuyer_agent.tracing import set_output, traced_step

MAX_ITERATIONS = 6          # most rounds of tool calls before we force an answer
RETRIEVAL_K = 3             # how many knowledge-base chunks to retrieve
MAX_HISTORY_MESSAGES = 6    # last 3 exchanges (user + assistant) kept as conversation memory
PLANNER_PROMPT = "planner_v1"
AGENT_PROMPT = "agent_v1"

ToolName = Literal["max_affordable_price", "monthly_payment", "search_listings", "get_listing"]


# ---------- data shapes ----------

class PlanStep(BaseModel):
    tool: ToolName = Field(description="Which tool to call.")
    reason: str = Field(description="One short sentence: why this step is needed.")


class Plan(BaseModel):
    """Structured output of the planning step."""

    goal: str = Field(description="What the user wants, in one sentence.")
    steps: list[PlanStep] = Field(description="Tool calls in order. Empty if no tools are needed.")


class ToolCallRecord(BaseModel):
    """One tool call the agent made, kept for evaluation and the UI."""

    name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None


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
    if not plan.steps:
        return f"Goal: {plan.goal}\n(No tools needed: answer from the guidance.)"
    lines = [f"Goal: {plan.goal}"] + [f"{i}. {s.tool}: {s.reason}" for i, s in enumerate(plan.steps, 1)]
    return "\n".join(lines)


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

    with traced_step(f"tool: {name}", "TOOL", json.dumps(arguments)) as span:
        span.set_attribute(SpanAttributes.TOOL_NAME, name)
        try:
            result = TOOL_FUNCTIONS[name](**arguments)
            record = ToolCallRecord(name=name, arguments=arguments, result=result)
        except (TypeError, ValueError) as e:   # wrong/missing arguments or impossible values
            record = ToolCallRecord(name=name, arguments=arguments, error=str(e))
        set_output(span, json.dumps(record.result if record.error is None else {"error": record.error}, default=str))
    return record


# ---------- the agent ----------

def run_agent(message: str, history: list[dict] | None = None) -> AgentResult:
    """Answer one homebuyer message. See the module docstring for the steps.

    history (optional): earlier turns as [{"role": "user"/"assistant", "content": "..."}],
    oldest first. It lets the agent understand follow-ups like "yes" or "what about L030?".
    Only the last MAX_HISTORY_MESSAGES are used, to keep prompts short.
    """
    history = (history or [])[-MAX_HISTORY_MESSAGES:]
    with traced_step("run_agent", "AGENT", message) as root:
        root.set_attribute("agent.history_turns", len(history))
        result = _run(message, history)
        root.set_attribute("agent.intent", result.intent)
        root.set_attribute("agent.tools", ",".join(t.name for t in result.tool_calls))
        set_output(root, result.answer)
        return result


def _run(message: str, history: list[dict]) -> AgentResult:
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

    # 3. PLAN which tools to use (structured output, like the router).
    with traced_step("plan", "CHAIN", message) as span:
        planner_prompt = _fill(load_prompt(PLANNER_PROMPT), intent=intent.value, guidance=guidance)
        plan = structured_completion(planner_prompt, message, Plan, history=history)
        set_output(span, plan.model_dump_json())

    # 4. ACT: let the model call tools in a loop until it has enough to answer.
    system = _fill(load_prompt(AGENT_PROMPT), plan=_format_plan(plan), guidance=guidance)
    messages: list[dict] = [
        {"role": "system", "content": system},
        *history,                                  # earlier turns, so follow-ups make sense
        {"role": "user", "content": message},
    ]
    tool_calls: list[ToolCallRecord] = []
    answer, hit_limit = None, False

    with traced_step("act", "CHAIN", _format_plan(plan)):
        for _ in range(MAX_ITERATIONS):
            reply = chat_with_tools(messages, TOOL_SCHEMAS)
            if not reply.tool_calls:          # no more tools wanted: this is the answer
                answer = reply.content or ""
                break
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
                record = run_tool(tc.function.name, tc.function.arguments)
                tool_calls.append(record)
                payload = record.result if record.error is None else {"error": record.error}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(payload, default=str)})
        else:
            # Limit reached: no more tools allowed, the model must answer with what it has.
            hit_limit = True
            answer = chat_with_tools(messages, TOOL_SCHEMAS, tool_choice="none").content or ""

    # 5 + 6. ANSWER, after a fair-housing check on what we're about to show.
    with traced_step("answer", "CHAIN", answer) as span:
        output_check = check_answer(answer)
        guardrail = None
        if output_check.flagged:
            guardrail = f"fair_housing (answer check: '{output_check.matched}')"
            answer = FAIR_HOUSING_RESPONSE
        span.set_attribute("agent.guardrail", guardrail or "none")
        set_output(span, answer)

    return AgentResult(
        **base,
        plan=plan,
        tool_calls=tool_calls,
        retrieved_docs=doc_ids,
        answer=answer,
        listing_ids=_listing_ids_in(answer),
        guardrail=guardrail,
        hit_iteration_limit=hit_limit,
    )
