"""Milestone 6: evaluate the V2 planning agent on data/eval/v2_agent_cases.csv.

For every scenario it runs the full agent, then scores the run three ways:
1. Tool selection (exact, Python): precision / recall of tools called vs expected.
2. Retrieval hit (exact, Python): was any expected guide retrieved?
3. LLM-as-judge: 1-5 scores with a justification for groundedness, must_include
   coverage, safety and helpfulness, using evals/judge_prompts/<judge>.txt.

Saves a timestamped CSV (one row per case, everything needed for hand-scoring)
and a markdown summary to results/.

Run:
  python evals/run_v2_eval.py [--agent-prompt agent_v2] [--judge answer_judge_v2] [--trace]
  python evals/run_v2_eval.py --rejudge results/v2_eval_....csv --judge answer_judge_v2
      (re-grades the SAVED answers with a different judge; the agent is not run again,
       so any change in scores comes from the judge alone)
"""
import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from pydantic import BaseModel, Field

from homebuyer_agent import planner
from homebuyer_agent.config import EVAL_DIR, RESULTS_DIR, get_judge_model, get_model, get_smart_model
from homebuyer_agent.eval_metrics import (
    micro_precision_recall,
    normalise_tools,
    parse_list,
    quote_in_answer,
    retrieval_hit,
    tool_selection,
)
from homebuyer_agent.llm import structured_completion
from homebuyer_agent.retrieval import get_doc_text
from homebuyer_agent.router import DEFAULT_PROMPT_VERSION
from homebuyer_agent.tracing import get_tracer, setup_tracing
from run_v1_eval import to_markdown   # same folder; reuse the markdown table helper

JUDGE_PROMPTS_DIR = Path(__file__).parent / "judge_prompts"
CRITERIA = ["groundedness", "must_include", "safety", "helpfulness"]
MAX_TOOL_RESULT_CHARS = 4000   # keep the judge prompt a sensible size
SHORT_CIRCUIT_INTENTS = {"fair_housing_sensitive", "talk_to_agent", "out_of_scope"}


# ---------- the judge's structured output ----------

class CriterionScore(BaseModel):
    justification: str = Field(description="One or two sentences explaining the score. Written BEFORE the score.")
    score: int = Field(ge=1, le=5, description="1 (worst) to 5 (best), following the rubric.")


class JudgeVerdict(BaseModel):
    """answer_judge_v1: four scores."""

    groundedness: CriterionScore
    must_include: CriterionScore
    safety: CriterionScore
    helpfulness: CriterionScore


class ChecklistItem(BaseModel):
    point: str = Field(description="One MUST INCLUDE point.")
    quote: str = Field(description="Exact words copied from the ANSWER that cover it, or MISSING.")


class JudgeVerdictV2(BaseModel):
    """answer_judge_v2: the judge must show its evidence BEFORE scoring.

    Field order matters: the model fills them top to bottom, so it has to quote the
    answer for every checklist point and list problems before it is allowed to score.
    That stops it from "ticking off" points the answer never covered.
    """

    checklist: list[ChecklistItem]
    missing_caveats: list[str] = Field(description="Applicable caveats the answer lacks; empty if none.")
    problems: list[str] = Field(description="Factual problems found (quote the answer); empty if none.")
    groundedness: CriterionScore
    must_include: CriterionScore
    safety: CriterionScore
    helpfulness: CriterionScore


JUDGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "answer_judge_v1": JudgeVerdict,
    "answer_judge_v2": JudgeVerdictV2,
    "answer_judge_v3": JudgeVerdictV2,   # same output shape as v2; only the rubric text changed
    "answer_judge_v4": JudgeVerdictV2,   # v3 without the listing-data caveat (the website states it once)
}


# ---------- helpers ----------

def text_or_empty(value) -> str:
    """CSV cells that are blank come back as NaN; turn them into ''."""
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)


def build_evidence(result: planner.AgentResult) -> str:
    """Everything the agent had to work with: tool calls + results and the retrieved guides."""
    parts = []
    if result.plan is None or result.guardrail:   # a short-circuit or a safety replacement
        parts.append(f"(The system answered with a fixed reply. Intent: {result.intent}; guardrail: {result.guardrail or 'none'}.)")
    for i, call in enumerate(result.tool_calls, 1):
        output = call.result if call.error is None else {"error": call.error}
        output_text = json.dumps(output, default=str)
        if len(output_text) > MAX_TOOL_RESULT_CHARS:
            output_text = output_text[:MAX_TOOL_RESULT_CHARS] + " ...(truncated)"
        parts.append(f"Tool call {i}: {call.name}({json.dumps(call.arguments)})\nResult: {output_text}")
    if not result.tool_calls:
        parts.append("No tools were called.")
    for doc_id in result.retrieved_docs:
        parts.append(f"Guide [{doc_id}]:\n{get_doc_text(doc_id)}")
    return "\n\n".join(parts)


def result_from_row(row: dict) -> planner.AgentResult:
    """Rebuild what the judge needs from a saved results row (used by --rejudge)."""
    intent = text_or_empty(row.get("intent"))
    return planner.AgentResult(
        message=row["request"],
        intent=intent,
        route_reasoning="",
        plan=None if intent in SHORT_CIRCUIT_INTENTS else planner.Plan(goal="", explain_first="", steps=[]),
        tool_calls=[planner.ToolCallRecord(**t) for t in json.loads(text_or_empty(row.get("tool_calls_json")) or "[]")],
        retrieved_docs=[d for d in text_or_empty(row.get("retrieved_docs")).split("|") if d],
        answer=text_or_empty(row.get("answer")),
        guardrail=text_or_empty(row.get("guardrail")) or None,
    )


def judge(case, result: planner.AgentResult, judge_name: str, judge_prompt: str, judge_model: str) -> BaseModel:
    """Ask the judge model to grade one answer against the rubric."""
    prompt = judge_prompt
    for key, value in {
        "request": case["request"],
        "must_include": text_or_empty(case["must_include"]) or "(none)",
        "must_not_include": text_or_empty(case["must_not_include"]) or "(none)",
        "evidence": build_evidence(result),
        "answer": result.answer,
    }.items():
        prompt = prompt.replace("{" + key + "}", value)
    return structured_completion(prompt, "Grade the ANSWER now.", JUDGE_SCHEMAS[judge_name], model=judge_model)


def add_judge_scores(row: dict, result: planner.AgentResult, judge_name: str, judge_prompt: str, judge_model: str) -> None:
    """Run the judge and copy its scores (and v2's checklist/problems) into the row."""
    try:
        verdict = judge(row, result, judge_name, judge_prompt, judge_model)
    except Exception as e:  # noqa: BLE001 - record and continue
        row["error"] = f"judge failed: {type(e).__name__}: {e}"
        return
    for criterion in CRITERIA:
        score: CriterionScore = getattr(verdict, criterion)
        row[f"judge_{criterion}"] = score.score
        row[f"judge_{criterion}_why"] = score.justification
    if isinstance(verdict, JudgeVerdictV2):
        row["judge_checklist"] = json.dumps([c.model_dump() for c in verdict.checklist])
        row["judge_missing_caveats"] = "; ".join(verdict.missing_caveats)
        row["judge_problems"] = "; ".join(verdict.problems)
        # Check the judge's evidence in Python: every quote must really be in the answer.
        fake = [c.point for c in verdict.checklist if not quote_in_answer(c.quote, result.answer)]
        row["judge_fake_quotes"] = "; ".join(fake)


# ---------- running the cases ----------

def evaluate_case(case, agent_prompt: str) -> tuple[dict, planner.AgentResult | None]:
    """Run the agent on one case and return a row with the exact metrics and raw details."""
    expected_tools = parse_list(case.expected_tools)
    expected_docs = parse_list(case.expected_kb_docs)
    row = {
        "id": case.id,
        "request": case.request,
        "must_include": text_or_empty(case.must_include),
        "must_not_include": text_or_empty(case.must_not_include),
        "expected_tools": "|".join(sorted(expected_tools)),
        "expected_kb_docs": "|".join(sorted(expected_docs)),
        "agent_prompt": agent_prompt,
    }
    start = time.perf_counter()
    try:
        result = planner.run_agent(case.request, agent_prompt=agent_prompt)
    except Exception as e:  # noqa: BLE001 - log the failure and move on to the next case
        return {**row, "error": f"{type(e).__name__}: {e}"}, None
    row["seconds"] = round(time.perf_counter() - start, 1)   # how long the visitor would wait

    called_raw = [t.name for t in result.tool_calls]
    called = normalise_tools(called_raw)
    tools = tool_selection(expected_tools, called)
    row.update({
        "intent": result.intent,
        "plan": " -> ".join(s.tool for s in result.plan.steps) if result.plan else "",
        "tools_called_raw": ",".join(called_raw),
        "n_tool_calls": len(called_raw),
        "tools_called": "|".join(sorted(called)),
        "tool_tp": tools["tp"], "tool_fp": tools["fp"], "tool_fn": tools["fn"],
        "tool_precision": tools["precision"], "tool_recall": tools["recall"], "tool_exact": tools["exact"],
        "retrieved_docs": "|".join(result.retrieved_docs),
        "retrieval_hit": retrieval_hit(expected_docs, result.retrieved_docs),
        "guardrail": result.guardrail or "",
        "hit_iteration_limit": result.hit_iteration_limit,
        "answer_model": result.model or "",          # which model wrote it ("" for fixed safe replies)
        "model_reason": result.model_reason or "",
        "answer": result.answer,
        "tool_calls_json": json.dumps([t.model_dump() for t in result.tool_calls], default=str),
        "error": "",
    })
    return row, result


def print_case(row: dict, i: int, total: int) -> None:
    """Show one case in the terminal so you can follow the run."""
    print(f"===== [{row['id']}] ({i}/{total}) {row['request']}")
    if row.get("error") and "answer" not in row:
        print(f"   ERROR: {row['error']}\n")
        return
    tick = "✅" if row["tool_exact"] else "❌"
    print(f"   intent: {row['intent']}   plan: {row['plan'] or '(none)'}")
    if row.get("answer_model"):
        print(f"   model: {row['answer_model']} ({row.get('model_reason', '')})   time: {row.get('seconds', '?')} s")
    print(f"   {tick} tools  expected: {row['expected_tools'] or '(none)'}   called: {row['tools_called'] or '(none)'}"
          f"   (raw: {row['tools_called_raw'] or '-'})")
    hit = row["retrieval_hit"]
    hit_text = "n/a" if hit is None or (isinstance(hit, float) and math.isnan(hit)) else ("✅ hit" if hit else "❌ miss")
    print(f"   {hit_text} retrieval  expected: {row['expected_kb_docs'] or '(none)'}   got: {row['retrieved_docs'] or '(none)'}")
    print("   answer:\n      " + str(row["answer"]).replace("\n", "\n      "))
    if row.get("error"):
        print(f"   ERROR: {row['error']}")
    if row.get("judge_checklist"):
        for item in json.loads(row["judge_checklist"]):
            mark = "❌" if item["quote"].strip().upper().startswith("MISSING") else "✅"
            print(f"   {mark} checklist: {item['point']}  <- {item['quote'][:110]}")
    for key, label in [("judge_missing_caveats", "missing caveats"), ("judge_problems", "problems"),
                       ("judge_fake_quotes", "JUDGE QUOTE NOT IN ANSWER for")]:
        if row.get(key) and row[key] != "none":
            print(f"   ⚠ {label}: {row[key]}")
    for criterion in CRITERIA:
        if f"judge_{criterion}" in row:
            print(f"   judge {criterion:<13} {row[f'judge_{criterion}']}/5  {row[f'judge_{criterion}_why']}")
    print()


def traced_case(case_id: str, request: str):
    """One Phoenix trace per case, labelled with its id."""
    span = get_tracer().start_as_current_span(f"eval_case {case_id}")
    return span


def label_span(span, row: dict) -> None:
    span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.CHAIN.value)
    span.set_attribute(SpanAttributes.INPUT_VALUE, row["request"])
    span.set_attribute("eval.case_id", row["id"])
    span.set_attribute(SpanAttributes.OUTPUT_VALUE, str(row.get("answer", row.get("error", ""))))
    if "tool_exact" in row:
        span.set_attribute("eval.tool_exact", bool(row["tool_exact"]))
    for criterion in CRITERIA:
        if f"judge_{criterion}" in row:
            span.set_attribute(f"eval.judge_{criterion}", int(row[f"judge_{criterion}"]))


def run_cases(cases: pd.DataFrame, agent_prompt: str, judge_name: str, judge_prompt: str, judge_model: str) -> pd.DataFrame:
    """Full run: agent + exact metrics + judge, one case at a time."""
    rows = []
    for i, case in enumerate(cases.itertuples(), start=1):
        with traced_case(case.id, case.request) as span:
            row, result = evaluate_case(case, agent_prompt)
            if result is not None:
                add_judge_scores(row, result, judge_name, judge_prompt, judge_model)
            label_span(span, row)
        print_case(row, i, len(cases))
        rows.append(row)
    return pd.DataFrame(rows)


def rejudge(saved: pd.DataFrame, judge_name: str, judge_prompt: str, judge_model: str) -> pd.DataFrame:
    """Re-grade saved answers with another judge. Exact metrics are kept as they were."""
    rows = []
    for i, row in enumerate(saved.to_dict("records"), start=1):
        # Drop the old judge's scores, and turn blank CSV cells (NaN) back into None.
        row = {k: (None if isinstance(v, float) and math.isnan(v) else v)
               for k, v in row.items() if not str(k).startswith("judge_")}
        if text_or_empty(row.get("answer")):
            add_judge_scores(row, result_from_row(row), judge_name, judge_prompt, judge_model)
        print_case(row, i, len(saved))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------- summary ----------

def headline_metrics(df: pd.DataFrame) -> dict:
    """The few numbers that go in the README."""
    errors = df["error"].astype(object).fillna("") if "error" in df else pd.Series("", index=df.index)
    ok = df[errors == ""]
    tool_rows = [
        {"tp": r["tool_tp"], "fp": r["tool_fp"], "fn": r["tool_fn"]}
        for r in df.dropna(subset=["tool_tp"]).to_dict("records")
    ]
    precision, recall = micro_precision_recall(tool_rows)
    hits = df["retrieval_hit"].dropna()
    metrics = {
        "cases": len(df),
        "errors": int((errors != "").sum()),
        "tool_precision": precision,
        "tool_recall": recall,
        "tool_exact": f"{int(df['tool_exact'].astype(object).fillna(False).astype(bool).sum())}/{len(tool_rows)}",
        "retrieval_hit_rate": f"{int(hits.astype(bool).sum())}/{len(hits)}",
    }
    if "seconds" in df:
        metrics["avg_seconds"] = df["seconds"].mean()
        metrics["max_seconds"] = df["seconds"].max()
    if "n_tool_calls" in df:
        metrics["total_tool_calls"] = int(df["n_tool_calls"].fillna(0).sum())
    if "answer_model" in df and "model_reason" in df:
        reasons = df["model_reason"].astype(object).fillna("")
        metrics["smart_model_used"] = int((reasons.str.startswith(("multi-step", "retry"))).sum())
        metrics["smart_model_retries"] = int(reasons.str.startswith("retry").sum())
    if "judge_fake_quotes" in df:
        metrics["judge_fake_quotes"] = int((df["judge_fake_quotes"].astype(object).fillna("") != "").sum())
    for criterion in CRITERIA:
        column = f"judge_{criterion}"
        metrics[f"judge_{criterion}_avg"] = ok[column].mean() if column in ok else math.nan
    return metrics


def build_summary(df: pd.DataFrame, metrics: dict, info: dict) -> str:
    meta = "\n".join(f"- **{k}:** {v}" for k, v in info.items())
    headline = pd.DataFrame(
        [{"metric": k, "value": v} for k, v in metrics.items()]
    ).set_index("metric")
    score_cols = ["intent", "expected_tools", "tools_called", "tool_exact", "expected_kb_docs",
                  "retrieved_docs", "retrieval_hit"] + [f"judge_{c}" for c in CRITERIA]
    per_case = df.set_index("id")[[c for c in score_cols if c in df.columns]]
    details = []
    for row in df.to_dict("records"):
        lines = [f"### {row['id']}: {row['request']}"]
        if text_or_empty(row.get("error")):
            lines.append(f"**Error:** {row['error']}")
        for key, label in [("judge_missing_caveats", "Missing caveats"), ("judge_problems", "Problems")]:
            if text_or_empty(row.get(key)):
                lines.append(f"- **{label}:** {row[key]}")
        for criterion in CRITERIA:
            if isinstance(row.get(f"judge_{criterion}_why"), str):
                lines.append(f"- **{criterion} {int(row[f'judge_{criterion}'])}/5:** {row[f'judge_{criterion}_why']}")
        details.append("\n".join(lines))
    return "\n\n".join([
        "# V2 agent eval",
        meta,
        "## Headline\n\n" + to_markdown(headline),
        "## Per case\n\n" + to_markdown(per_case),
        "## Judge justifications\n\n" + "\n\n".join(details),
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the V2 planning agent.")
    parser.add_argument("--agent-prompt", default=planner.AGENT_PROMPT, help="agent prompt, e.g. agent_v1 or agent_v2")
    parser.add_argument("--judge", default="answer_judge_v4", choices=sorted(JUDGE_SCHEMAS), help="judge prompt")
    parser.add_argument("--rejudge", type=Path, help="re-grade the answers saved in this results CSV (no agent run)")
    parser.add_argument("--trace", action="store_true", help="send traces to Phoenix (run 'phoenix serve' first)")
    args = parser.parse_args()
    if args.trace:
        setup_tracing()

    base_model, smart_model, judge_model = get_model(), get_smart_model(), get_judge_model()
    # One label for file names: "gpt-4o-mini", or "gpt-4o-mini_smart-gpt-4o" when the
    # agent may switch to a smarter model when needed.
    model = base_model if smart_model == base_model else f"{base_model}_smart-{smart_model}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    judge_prompt = (JUDGE_PROMPTS_DIR / f"{args.judge}.txt").read_text(encoding="utf-8")

    if args.rejudge:
        saved = pd.read_csv(args.rejudge)
        agent_prompt = text_or_empty(saved["agent_prompt"].iloc[0]) if "agent_prompt" in saved else "agent_v1"
        source = f"answers re-judged from {args.rejudge.name}"
    else:
        agent_prompt = args.agent_prompt
        source = "fresh agent run"
    info = {
        "Base model (router, planner, everyday answers)": base_model,
        "Smart model (used when needed)": smart_model if smart_model != base_model else "not set",
        "Judge model": judge_model,
        "Prompts": f"{DEFAULT_PROMPT_VERSION}, {planner.PLANNER_PROMPT}, {agent_prompt}",
        "Judge prompt": args.judge,
        "Source": source,
        "Run at": timestamp,
    }
    print("V2 eval. " + ", ".join(f"{k}: {v}" for k, v in info.items()) + "\n")

    if args.rejudge:
        df = rejudge(saved, args.judge, judge_prompt, judge_model)
        df["agent_prompt"] = agent_prompt
    else:
        cases = pd.read_csv(EVAL_DIR / "v2_agent_cases.csv")
        df = run_cases(cases, agent_prompt, args.judge, judge_prompt, judge_model)
    metrics = headline_metrics(df)

    RESULTS_DIR.mkdir(exist_ok=True)
    kind = "v2_rejudge" if args.rejudge else "v2_eval"
    # e.g. v2_eval_agent_v2_gpt-4o-mini_answer_judge_v2_gpt-4o_<time>: agent prompt + model, then judge prompt + model
    stem = f"{kind}_{agent_prompt}_{model}_{args.judge}_{judge_model}_{timestamp}"
    csv_path, md_path = RESULTS_DIR / f"{stem}.csv", RESULTS_DIR / f"{stem}.md"
    df.to_csv(csv_path, index=False)
    md_path.write_text(build_summary(df, metrics, info), encoding="utf-8")

    print("===== Headline")
    for key, value in metrics.items():
        print(f"   {key:<24} {value:.2f}" if isinstance(value, float) else f"   {key:<24} {value}")
    print(f"\nSaved: {csv_path.relative_to(RESULTS_DIR.parent)}")
    print(f"Saved: {md_path.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
