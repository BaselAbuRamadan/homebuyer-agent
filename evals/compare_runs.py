"""Compare two V1 eval runs (e.g. router_v1 vs router_v4) and write results/v1_vs_v4.md.

By default it picks the most recent results CSV for each prompt version.
Run:  python evals/compare_runs.py --before router_v1 --after router_v2
"""
import argparse
from pathlib import Path

import pandas as pd

from homebuyer_agent.config import RESULTS_DIR


def latest_run(prompt_version: str) -> Path:
    """Return the newest results CSV for a prompt version (timestamps sort as text)."""
    runs = sorted(RESULTS_DIR.glob(f"v1_eval_{prompt_version}_*.csv"))
    if not runs:
        raise FileNotFoundError(f"No results for {prompt_version}. Run: python evals/run_v1_eval.py --prompt {prompt_version}")
    return runs[-1]


def accuracy_row(preds: pd.DataFrame) -> dict[str, str]:
    """Overall and per-difficulty accuracy, formatted like '38/40 (95%)'."""
    def fmt(subset: pd.DataFrame) -> str:
        return f"{int(subset['correct'].sum())}/{len(subset)} ({subset['correct'].mean():.0%})"

    row = {"overall": fmt(preds)}
    for level in ["easy", "medium", "hard"]:
        row[level] = fmt(preds[preds["difficulty"] == level])
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two router eval runs.")
    parser.add_argument("--before", default="router_v1")
    parser.add_argument("--after", default="router_v2")
    args = parser.parse_args()

    before_path, after_path = latest_run(args.before), latest_run(args.after)
    before, after = pd.read_csv(before_path), pd.read_csv(after_path)

    # Join the two runs on case id so we can see per-case changes.
    merged = before.merge(after, on="id", suffixes=("_before", "_after"))
    fixed = merged[~merged["correct_before"] & merged["correct_after"]]
    broken = merged[merged["correct_before"] & ~merged["correct_after"]]
    still_wrong = merged[~merged["correct_before"] & ~merged["correct_after"]]

    b, a = accuracy_row(before), accuracy_row(after)
    lines = [
        f"# Router comparison: `{args.before}` vs `{args.after}`",
        "",
        f"- Before: `{before_path.name}`",
        f"- After: `{after_path.name}`",
        "",
        f"| slice | {args.before} | {args.after} |",
        "|---|---|---|",
        *[f"| {k} | {b[k]} | {a[k]} |" for k in b],
        "",
    ]

    def case_list(title: str, df: pd.DataFrame) -> list[str]:
        out = [f"## {title} ({len(df)})", ""]
        if df.empty:
            return out + ["None.", ""]
        out += ["| id | expected | before | after | message |", "|---|---|---|---|---|"]
        for r in df.itertuples():
            out.append(f"| {r.id} | {r.expected_intent_before} | {r.predicted_intent_before} | "
                       f"{r.predicted_intent_after} | {r.message_before} |")
        return out + [""]

    lines += case_list("Fixed by the new prompt", fixed)
    lines += case_list("Broken by the new prompt (regressions)", broken)
    lines += case_list("Still wrong", still_wrong)

    # e.g. router_v1 vs router_v4 -> results/v1_vs_v4.md
    out_path = RESULTS_DIR / f"{args.before.removeprefix('router_')}_vs_{args.after.removeprefix('router_')}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {out_path.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
