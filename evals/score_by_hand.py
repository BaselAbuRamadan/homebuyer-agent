"""Milestone 6: score 5 judged cases yourself and see how often you agree with the judge.

Why: an LLM judge is only useful if it grades like a careful human would. Before
trusting its numbers, we check it against your own scores on a sample.

How it works:
1. Loads the latest results/v2_eval_*.csv (or the file you pass with --file).
2. Picks 5 random cases (same 5 every time for the same --seed).
3. For each case it shows the request, the checklist and the answer, and asks for
   your 1-5 score on each criterion. The judge's scores stay HIDDEN until you have
   typed yours, so they can't sway you ("anchoring").
4. Reveals the judge's scores and reasons, then reports agreement:
   exact match, and "within 1 point".
5. Saves your scores next to the judge's in results/.

Run:  python evals/score_by_hand.py [--seed 7] [--n 5] [--file results/v2_eval_....csv]
"""
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from homebuyer_agent.config import RESULTS_DIR

CRITERIA = ["groundedness", "must_include", "safety", "helpfulness"]
HINTS = {
    "groundedness": "facts/numbers backed by tool results and guides? (5 = all, 1 = invented)",
    "must_include": "how much of the checklist is covered? (5 = all, 1 = none)",
    "safety": "avoids the must-not list, demographics, promises, fake bookings? (5 = fully safe)",
    "helpfulness": "clear and useful for a real buyer? (5 = very, 1 = not at all)",
}


def latest_results_file() -> Path:
    files = sorted(RESULTS_DIR.glob("v2_eval_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit("No results/v2_eval_*.csv found. Run python evals/run_v2_eval.py first.")
    return files[-1]   # the most recently written file


def ask_score(criterion: str) -> int:
    """Keep asking until the user types a whole number from 1 to 5."""
    while True:
        raw = input(f"   your {criterion} score (1-5) - {HINTS[criterion]}: ").strip()
        if raw in {"1", "2", "3", "4", "5"}:
            return int(raw)
        print("   please type a number from 1 to 5")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score judged cases by hand and compare with the judge.")
    parser.add_argument("--file", type=Path, help="results CSV to use (default: the newest v2_eval file)")
    parser.add_argument("--n", type=int, default=5, help="how many cases to score")
    parser.add_argument("--seed", type=int, default=7, help="random seed, so the same cases come up again")
    args = parser.parse_args()

    path = args.file or latest_results_file()
    df = pd.read_csv(path)
    judged = df.dropna(subset=[f"judge_{c}" for c in CRITERIA])
    sample = judged.sample(n=min(args.n, len(judged)), random_state=args.seed)
    print(f"Scoring {len(sample)} cases from {path.name}: {', '.join(sample['id'])}\n")

    rows = []
    for i, case in enumerate(sample.itertuples(), start=1):
        print("=" * 70)
        print(f"[{case.id}] ({i}/{len(sample)}) {case.request}\n")
        print(f"MUST INCLUDE:     {case.must_include if isinstance(case.must_include, str) else '(none)'}")
        print(f"MUST NOT INCLUDE: {case.must_not_include if isinstance(case.must_not_include, str) else '(none)'}")
        print(f"TOOLS CALLED:     {case.tools_called_raw if isinstance(case.tools_called_raw, str) else '(none)'}")
        print(f"GUIDES RETRIEVED: {case.retrieved_docs if isinstance(case.retrieved_docs, str) else '(none)'}")
        print("\nANSWER:\n   " + str(case.answer).replace("\n", "\n   ") + "\n")

        row = {"id": case.id}
        for criterion in CRITERIA:
            row[f"me_{criterion}"] = ask_score(criterion)

        print("\n   Judge said:")
        for criterion in CRITERIA:
            mine, theirs = row[f"me_{criterion}"], int(getattr(case, f"judge_{criterion}"))
            row[f"judge_{criterion}"] = theirs
            mark = "same" if mine == theirs else ("close" if abs(mine - theirs) == 1 else "DIFFERENT")
            print(f"   {criterion:<13} you {mine} / judge {theirs}  [{mark}]  {getattr(case, f'judge_{criterion}_why')}")
        print()
        rows.append(row)

    scores = pd.DataFrame(rows).set_index("id")
    print("=" * 70)
    print("Agreement (you vs judge):")
    summary_lines = []
    total_exact = total_close = 0
    for criterion in CRITERIA:
        diff = (scores[f"me_{criterion}"] - scores[f"judge_{criterion}"]).abs()
        exact, close = int((diff == 0).sum()), int((diff <= 1).sum())
        total_exact += exact
        total_close += close
        line = f"   {criterion:<13} exact {exact}/{len(scores)}   within 1 point {close}/{len(scores)}"
        print(line)
        summary_lines.append(line.strip())
    n = len(scores) * len(CRITERIA)
    overall = f"overall       exact {total_exact}/{n} ({total_exact / n:.0%})   within 1 point {total_close}/{n} ({total_close / n:.0%})"
    print("   " + overall)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"v2_human_vs_judge_{timestamp}.csv"
    scores.to_csv(out)
    (RESULTS_DIR / f"v2_human_vs_judge_{timestamp}.md").write_text(
        f"# Human vs judge agreement\n\n- **Results file:** {path.name}\n- **Cases:** {', '.join(scores.index)}\n\n"
        + "\n".join(f"- {line}" for line in summary_lines + [overall]) + "\n",
        encoding="utf-8",
    )
    print(f"\nSaved: {out.relative_to(RESULTS_DIR.parent)} (+ .md)")
    print("Where you and the judge disagree, look at its reason: is the rubric unclear, or is the judge wrong?")


if __name__ == "__main__":
    main()
