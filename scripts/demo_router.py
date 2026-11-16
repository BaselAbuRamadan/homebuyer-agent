"""Milestone 1 demo: route one example message per intent and print the decisions.

This is a demo, not an evaluation (see evals/run_v1_eval.py for that).
Run: python scripts/demo_router.py [--prompt router_v1] [--trace]
"""
import argparse
import csv

from homebuyer_agent.config import EVAL_DIR
from homebuyer_agent.router import DEFAULT_PROMPT_VERSION, route
from homebuyer_agent.tracing import setup_tracing


def pick_one_case_per_intent(path) -> list[dict]:
    """Return the first case for each expected intent in the CSV, keeping file order."""
    seen: set[str] = set()
    picked: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["expected_intent"] not in seen:
                seen.add(row["expected_intent"])
                picked.append(row)
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description="Route one example message per intent.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT_VERSION, help="prompt version, e.g. router_v1")
    parser.add_argument("--trace", action="store_true", help="send traces to Phoenix (run 'phoenix serve' first)")
    args = parser.parse_args()
    if args.trace:
        setup_tracing()

    cases = pick_one_case_per_intent(EVAL_DIR / "v1_router_cases.csv")
    for case in cases:
        decision = route(case["message"], prompt_version=args.prompt)
        mark = "✅" if decision.intent.value == case["expected_intent"] else "❌"
        print(f"{mark} [{case['id']}] {case['message']}")
        print(f"   expected:  {case['expected_intent']}")
        print(f"   predicted: {decision.intent.value}  (confidence {decision.confidence:.2f})")
        print(f"   reasoning: {decision.reasoning}\n")


if __name__ == "__main__":
    main()
