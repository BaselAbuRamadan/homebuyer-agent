"""Custom metrics for the V2 agent eval. Pure Python, no API calls, so they are unit-tested.

Two questions we can answer exactly, without an AI judge:
1. Tool selection: did the agent call the tools the test case expects?
2. Retrieval: did the search find at least one of the expected guides?
"""
import math
import re

# The test file was written before the affordability tool was split in two (Milestone 4).
# Both real tools count as the one "affordability_calculator" the test expects.
TOOL_ALIASES: dict[str, str] = {
    "monthly_payment": "affordability_calculator",
    "max_affordable_price": "affordability_calculator",
}


def parse_list(cell) -> set[str]:
    """Turn a CSV cell like 'kb_001|kb_003' into {'kb_001', 'kb_003'}. Empty/NaN -> empty set."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return set()
    return {item.strip() for item in str(cell).split("|") if item.strip()}


def normalise_tools(tool_names: list[str]) -> set[str]:
    """Map real tool names to the names used in the test file, and drop repeats.

    Calling search_listings 4 times (once per metro) still counts as one tool chosen:
    we measure *which* tools were picked, not how often.
    """
    return {TOOL_ALIASES.get(name, name) for name in tool_names}


def tool_selection(expected: set[str], called: set[str]) -> dict:
    """Compare the tools called with the tools expected for one case.

    - true positives (tp): expected and called
    - false positives (fp): called but not expected (an unnecessary tool)
    - false negatives (fn): expected but never called (a missed tool)
    - precision = tp / called   -> "were the tools it used the right ones?"
    - recall    = tp / expected -> "did it use every tool it needed?"
    - exact: the two sets are identical

    When nothing was expected AND nothing was called (e.g. a fair-housing question),
    that is perfect behaviour, so precision and recall are both 1.0.
    If only one side is empty, the undefined metric is NaN.
    """
    tp = len(expected & called)
    fp = len(called - expected)
    fn = len(expected - called)
    if not expected and not called:
        precision = recall = 1.0
    else:
        precision = tp / len(called) if called else math.nan
        recall = tp / len(expected) if expected else math.nan
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "exact": expected == called}


def micro_precision_recall(rows: list[dict]) -> tuple[float, float]:
    """Precision and recall over ALL cases together, from the summed tp/fp/fn counts.

    This "micro" average counts every tool decision equally, so a case with
    three tools weighs more than a case with one.
    """
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    precision = tp / (tp + fp) if (tp + fp) else math.nan
    recall = tp / (tp + fn) if (tp + fn) else math.nan
    return precision, recall


def _normalise_text(text: str) -> str:
    """Lowercase, drop markdown symbols and quote marks, squash spaces, for fair text matching."""
    text = re.sub(r"[*#`_\"“”‘’]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def quote_in_answer(quote: str, answer: str) -> bool:
    """Check that a quote the judge "copied" really appears in the answer.

    The judge may shorten a quote with "..." or stitch lines together across headings
    ("###"), so each piece is checked separately.
    "MISSING" is the judge saying the point isn't covered, so it is not a claim to check
    (returns True: nothing false was claimed). Used to catch a judge inventing evidence,
    e.g. quoting the knowledge-base guide instead of the answer.
    """
    if quote.strip().upper().startswith("MISSING"):
        return True
    answer_norm = _normalise_text(answer)
    pieces = [_normalise_text(p).strip(" .,;:-") for p in re.split(r"\.\.\.|…|;|#+|\n", quote)]
    pieces = [p for p in pieces if len(p) >= 4]   # ignore tiny fragments
    return bool(pieces) and all(p in answer_norm for p in pieces)


def retrieval_hit(expected_docs: set[str], retrieved_docs: list[str]) -> bool | None:
    """True if ANY expected guide was retrieved. None if the case expects no guide.

    "Any" rather than "all": the answer needs at least one relevant source to be grounded.
    """
    if not expected_docs:
        return None
    return bool(expected_docs & set(retrieved_docs))
