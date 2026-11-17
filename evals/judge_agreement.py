"""Compare your saved hand scores with ANY judge run, without scoring again.

score_by_hand.py saved your 1-5 scores (results/v2_human_vs_judge_*.csv). When the
judge prompt changes, re-judge the same answers (run_v2_eval.py --rejudge ...) and
run this script to see whether the new judge agrees with you more often.

Run:  python evals/judge_agreement.py --judge-file results/v2_rejudge_....csv [--human results/v2_human_vs_judge_....csv]
"""
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from homebuyer_agent.config import RESULTS_DIR

CRITERIA = ["groundedness", "must_include", "safety", "helpfulness"]


def newest(pattern: str) -> Path:
    files = sorted(RESULTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No results/{pattern} found.")
    return files[-1]


def agreement_table(human: pd.DataFrame, judged: pd.DataFrame) -> pd.DataFrame:
    """Per criterion: exact matches and matches within 1 point, over the cases both scored."""
    both = human.merge(judged, on="id")
    rows = []
    for criterion in CRITERIA:
        diff = (both[f"me_{criterion}"] - both[f"judge_{criterion}"]).abs()
        rows.append({"criterion": criterion, "cases": len(both),
                     "exact": int((diff == 0).sum()), "within_1": int((diff <= 1).sum())})
    table = pd.DataFrame(rows).set_index("criterion")
    table.loc["overall"] = table.sum()
    table.loc["overall", "cases"] = len(both) * len(CRITERIA)
    table["exact_pct"] = (table["exact"] / table["cases"]).map("{:.0%}".format)
    table["within_1_pct"] = (table["within_1"] / table["cases"]).map("{:.0%}".format)
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Agreement between your hand scores and a judge run.")
    parser.add_argument("--judge-file", type=Path, help="judge results CSV (default: newest v2_rejudge_*.csv)")
    parser.add_argument("--human", type=Path, help="your scores (default: newest v2_human_vs_judge_*.csv)")
    args = parser.parse_args()

    human_path = args.human or newest("v2_human_vs_judge_*.csv")
    judge_path = args.judge_file or newest("v2_rejudge_*.csv")
    human = pd.read_csv(human_path)[["id"] + [f"me_{c}" for c in CRITERIA]]
    judged = pd.read_csv(judge_path)[["id"] + [f"judge_{c}" for c in CRITERIA]]

    both = human.merge(judged, on="id").set_index("id")
    print(f"You:   {human_path.name}\nJudge: {judge_path.name}\n")
    print("Case by case (you / judge):")
    for case_id, r in both.iterrows():
        cells = [f"{c} {int(r[f'me_{c}'])}/{int(r[f'judge_{c}'])}" for c in CRITERIA]
        print(f"   {case_id}: " + "   ".join(cells))
    table = agreement_table(human, judged)
    print("\n" + table.to_string())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"v2_agreement_{judge_path.stem}_{timestamp}.md"
    out.write_text(
        f"# Judge agreement\n\n- **Your scores:** {human_path.name}\n- **Judge run:** {judge_path.name}\n\n```\n"
        + table.to_string() + "\n```\n",
        encoding="utf-8",
    )
    print(f"\nSaved: {out.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
