"""Evaluate BM25 retrieval on data/eval/retrieval_cases.csv. No API calls, runs in a second.

Each question has the one guide it should find. We report:
- top-1: the expected guide is ranked first
- top-3: the expected guide is among the 3 guides the agent actually receives

Saves a timestamped CSV + markdown summary to results/.

Run:  python evals/run_retrieval_eval.py
"""
from datetime import datetime

import pandas as pd

from homebuyer_agent.config import EVAL_DIR, RESULTS_DIR
from homebuyer_agent.planner import RETRIEVAL_K
from homebuyer_agent.retrieval import retrieve


def main() -> None:
    cases = pd.read_csv(EVAL_DIR / "retrieval_cases.csv")
    rows = []
    for case in cases.itertuples():
        got = [c.doc_id for c in retrieve(case.question, k=RETRIEVAL_K)]
        rows.append({
            "id": case.id,
            "question": case.question,
            "expected_doc": case.expected_doc,
            "retrieved": "|".join(got),
            "top1": got[:1] == [case.expected_doc],
            "top3": case.expected_doc in got,
        })
        mark = "✅" if rows[-1]["top3"] else "❌"
        print(f"{mark} [{case.id}] {case.question}\n     expected {case.expected_doc}, got {got}")

    df = pd.DataFrame(rows)
    top1, top3 = int(df["top1"].sum()), int(df["top3"].sum())
    print(f"\ntop-1: {top1}/{len(df)}   top-{RETRIEVAL_K}: {top3}/{len(df)}")

    RESULTS_DIR.mkdir(exist_ok=True)
    stem = f"retrieval_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    df.to_csv(RESULTS_DIR / f"{stem}.csv", index=False)
    misses = df[~df["top3"]]
    (RESULTS_DIR / f"{stem}.md").write_text(
        f"# Retrieval eval\n\n- **Cases:** {len(df)}\n- **Top-1:** {top1}/{len(df)}\n"
        f"- **Top-{RETRIEVAL_K}:** {top3}/{len(df)}\n\n## Misses ({len(misses)})\n\n"
        + ("\n".join(f"- {r.id}: {r.question} (expected {r.expected_doc}, got {r.retrieved})"
                     for r in misses.itertuples()) or "None.") + "\n",
        encoding="utf-8",
    )
    print(f"Saved: results/{stem}.csv (+ .md)")


if __name__ == "__main__":
    main()
