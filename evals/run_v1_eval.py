"""Milestone 2: evaluate the V1 router against the labelled test set.

Runs every case in data/eval/v1_router_cases.csv through route() and reports:
- overall accuracy and accuracy by difficulty
- per-intent precision and recall
- a confusion matrix (rows = expected, columns = predicted)

Saves a timestamped CSV of every prediction and a markdown summary to results/.

Run:  python evals/run_v1_eval.py --prompt router_v1
"""
import argparse
from datetime import datetime

import pandas as pd

from homebuyer_agent.config import EVAL_DIR, RESULTS_DIR, get_model
from homebuyer_agent.router import Intent, route

INTENTS: list[str] = [intent.value for intent in Intent]


def run_cases(cases: pd.DataFrame, prompt_version: str) -> pd.DataFrame:
    """Route every message and return one row per case with the prediction.

    An API error on one case is recorded (predicted = "ERROR") instead of
    stopping the whole run, so a single bad call doesn't waste the others.
    """
    rows = []
    for i, case in enumerate(cases.itertuples(), start=1):
        try:
            decision = route(case.message, prompt_version=prompt_version)
            predicted, confidence, reasoning = decision.intent.value, decision.confidence, decision.reasoning
        except Exception as e:  # noqa: BLE001 - we want to log any failure and continue
            predicted, confidence, reasoning = "ERROR", None, f"{type(e).__name__}: {e}"
        correct = predicted == case.expected_intent
        conf_text = f"{confidence:.2f}" if confidence is not None else "n/a"
        print(f"{'✅' if correct else '❌'} [{case.id}] ({i}/{len(cases)}, {case.difficulty}) {case.message}")
        print(f"   expected:  {case.expected_intent}")
        print(f"   predicted: {predicted}  (confidence {conf_text})")
        print(f"   reasoning: {reasoning}\n")
        rows.append({
            "id": case.id,
            "message": case.message,
            "difficulty": case.difficulty,
            "expected_intent": case.expected_intent,
            "predicted_intent": predicted,
            "correct": correct,
            "confidence": confidence,
            "reasoning": reasoning,
            "notes": case.notes if isinstance(case.notes, str) else "",
        })
    return pd.DataFrame(rows)


def accuracy_by_difficulty(preds: pd.DataFrame) -> pd.DataFrame:
    """Accuracy and case count for each difficulty level, plus an overall row."""
    order = ["easy", "medium", "hard"]
    table = (
        preds.groupby("difficulty")["correct"]
        .agg(cases="count", correct="sum", accuracy="mean")
        .reindex([d for d in order if d in set(preds["difficulty"])])
    )
    table.loc["overall"] = [len(preds), preds["correct"].sum(), preds["correct"].mean()]
    return table


def precision_recall(preds: pd.DataFrame) -> pd.DataFrame:
    """Per-intent precision and recall, computed by hand.

    For an intent X:
    - true positives (TP): expected X and predicted X
    - precision = TP / (all predicted X)  -> "when the model says X, is it right?"
    - recall    = TP / (all expected X)   -> "of the real X messages, how many did it catch?"
    If the denominator is 0 the metric is undefined, so we leave it empty (NaN).
    """
    rows = []
    for intent in INTENTS:
        predicted_x = preds["predicted_intent"] == intent
        expected_x = preds["expected_intent"] == intent
        tp = int((predicted_x & expected_x).sum())
        rows.append({
            "intent": intent,
            "support": int(expected_x.sum()),
            "predicted": int(predicted_x.sum()),
            "true_pos": tp,
            "precision": tp / predicted_x.sum() if predicted_x.sum() else float("nan"),
            "recall": tp / expected_x.sum() if expected_x.sum() else float("nan"),
        })
    return pd.DataFrame(rows).set_index("intent")


def confusion_matrix(preds: pd.DataFrame) -> pd.DataFrame:
    """Counts of expected (rows) vs predicted (columns). Off-diagonal cells are mistakes."""
    columns = INTENTS + (["ERROR"] if (preds["predicted_intent"] == "ERROR").any() else [])
    return pd.crosstab(preds["expected_intent"], preds["predicted_intent"]).reindex(
        index=INTENTS, columns=columns, fill_value=0
    )


def to_markdown(df: pd.DataFrame, float_format: str = "{:.2f}") -> str:
    """Render a DataFrame as a markdown table (avoids an extra 'tabulate' dependency)."""
    def fmt(value) -> str:
        if isinstance(value, float):
            return "" if pd.isna(value) else float_format.format(value)
        return str(value).replace("|", "\\|")

    header = [df.index.name or ""] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    # astype(object) stops pandas from turning integer counts into floats (11 -> 11.00).
    for index, row in df.astype(object).iterrows():
        lines.append("| " + " | ".join([fmt(index)] + [fmt(v) for v in row]) + " |")
    return "\n".join(lines)


def build_summary(preds: pd.DataFrame, prompt_version: str, model: str, timestamp: str) -> str:
    """Assemble the markdown report: metadata, metric tables and the list of failures."""
    failures = preds[~preds["correct"]][
        ["id", "difficulty", "expected_intent", "predicted_intent", "confidence", "message", "reasoning"]
    ].set_index("id")
    return "\n\n".join([
        f"# V1 router eval: `{prompt_version}`",
        f"- **Model:** {model}\n- **Prompt version:** {prompt_version}\n"
        f"- **Run at:** {timestamp}\n- **Cases:** {len(preds)}\n"
        f"- **Overall accuracy:** {preds['correct'].mean():.1%}",
        "## Accuracy by difficulty\n\n" + to_markdown(accuracy_by_difficulty(preds)),
        "## Per-intent precision and recall\n\n" + to_markdown(precision_recall(preds)),
        "## Confusion matrix (rows = expected, columns = predicted)\n\n" + to_markdown(confusion_matrix(preds)),
        f"## Failures ({len(failures)})\n\n" + (to_markdown(failures) if len(failures) else "None."),
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the V1 router.")
    parser.add_argument("--prompt", default="router_v1", help="prompt version, e.g. router_v1 or router_v2")
    parser.add_argument(
        "--cases", default="v1_router_cases.csv",
        help="test file in data/eval/, e.g. v1_router_holdout.csv for the held-out set",
    )
    args = parser.parse_args()

    model = get_model()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cases = pd.read_csv(EVAL_DIR / args.cases)

    print(f"Evaluating {len(cases)} cases from {args.cases} with prompt={args.prompt}, model={model}\n")
    preds = run_cases(cases, args.prompt)

    RESULTS_DIR.mkdir(exist_ok=True)
    # Main test set keeps the "v1_eval_" prefix; other sets get their own prefix
    # (e.g. "v1_holdout_") so compare_runs.py never mixes them up.
    set_tag = args.cases.removesuffix(".csv").removeprefix("v1_router_")
    prefix = "v1_eval" if set_tag == "cases" else f"v1_{set_tag}"
    stem = f"{prefix}_{args.prompt}_{model}_{timestamp}"
    csv_path = RESULTS_DIR / f"{stem}.csv"
    md_path = RESULTS_DIR / f"{stem}.md"
    preds.to_csv(csv_path, index=False)
    md_path.write_text(build_summary(preds, args.prompt, model, timestamp), encoding="utf-8")

    print(f"\nOverall accuracy: {preds['correct'].mean():.1%}")
    print(accuracy_by_difficulty(preds).round(2).to_string())
    print(f"\nSaved: {csv_path.relative_to(RESULTS_DIR.parent)}")
    print(f"Saved: {md_path.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
