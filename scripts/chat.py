"""Chat with the V2 planning agent in the terminal.

Run:
  python scripts/chat.py                 # type questions, 'quit' to exit
  python scripts/chat.py --case A01      # run one scenario from data/eval/v2_agent_cases.csv
  python scripts/chat.py --trace         # also send traces to Phoenix
  python scripts/chat.py --quiet         # hide the "under the hood" details

The chat remembers the last few messages, so you can reply "yes" or "what about L030?".
Type 'new' to start a fresh conversation. Nothing is saved after you quit.
"""
import argparse
import csv
import json

from homebuyer_agent.config import EVAL_DIR
from homebuyer_agent.planner import AgentResult, run_agent
from homebuyer_agent.tracing import setup_tracing


def short(value, limit: int = 160) -> str:
    """One-line preview of a tool's arguments or result."""
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def print_details(result: AgentResult) -> None:
    """Show what happened inside the agent: intent, docs, plan, tool calls."""
    print("  ── under the hood ──")
    print(f"  intent:    {result.intent}  ({result.route_reasoning})")
    if result.model:
        print(f"  model:     {result.model}  ({result.model_reason})")
    if result.guardrail:
        print(f"  guardrail: {result.guardrail}")
    if result.retrieved_docs:
        print(f"  guides:    {', '.join(result.retrieved_docs)}")
    if result.plan:
        print(f"  plan:      {result.plan.goal}")
        for i, step in enumerate(result.plan.steps, 1):
            print(f"             {i}. {step.tool}: {step.reason}")
    for call in result.tool_calls:
        outcome = f"ERROR {call.error}" if call.error else short(call.result)
        print(f"  tool:      {call.name}({short(call.arguments, 120)})")
        if call.note:
            print(f"             note: {call.note}")
        print(f"             → {outcome}")
    if result.hit_iteration_limit:
        print("  note:      hit the tool-call limit, answered with what it had")
    print()


def answer(message: str, quiet: bool, history: list[dict] | None = None) -> AgentResult:
    result = run_agent(message, history=history)
    print()
    if not quiet:
        print_details(result)
    print(f"Assistant: {result.answer}\n")
    return result


def load_case(case_id: str) -> str:
    with open(EVAL_DIR / "v2_agent_cases.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["id"].upper() == case_id.upper():
                return row["request"]
    raise SystemExit(f"No case {case_id} in v2_agent_cases.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the homebuyer agent.")
    parser.add_argument("--case", help="run one scenario by id, e.g. A01")
    parser.add_argument("--trace", action="store_true", help="send traces to Phoenix")
    parser.add_argument("--quiet", action="store_true", help="hide the under-the-hood details")
    args = parser.parse_args()
    if args.trace:
        setup_tracing()

    print("🏡 Homebuyer assistant (sample listings for this demo, educational estimates only)\n")
    if args.case:
        message = load_case(args.case)
        print(f"You ({args.case}): {message}")
        answer(message, args.quiet)
        return

    print("Ask a question, 'new' to start a fresh conversation, or 'quit' to exit.\n")
    history: list[dict] = []   # this conversation's turns; lives only while the chat is open
    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"quit", "exit", "q"}:
            break
        if message.lower() == "new":
            history = []
            print("(Started a new conversation.)\n")
            continue
        if message:
            result = answer(message, args.quiet, history)
            history += [{"role": "user", "content": message}, {"role": "assistant", "content": result.answer}]


if __name__ == "__main__":
    main()
