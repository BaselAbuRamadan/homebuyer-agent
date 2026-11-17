"""BM25 retrieval over the knowledge base (data/knowledge_base/*.md). No AI, no embeddings.

BM25 in one line: score each chunk by how many query words it contains, giving
rare words (e.g. "buydown") more weight than common ones (e.g. "home"), and not
over-rewarding long chunks just for being long.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from homebuyer_agent.config import KB_DIR

# Very common words that carry no meaning for search.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "i",
    "my", "me", "we", "you", "your", "what", "how", "do", "does", "can", "be", "with",
    "that", "this", "at", "as", "by", "if", "any", "about", "should", "would", "there",
    # Question filler: rare in the guides, so BM25 would wrongly treat them as important.
    # (Found by a test: "how MUCH are closing costs" ranked the wrong guide first.)
    "much", "many", "usually", "typically", "actually", "really", "tell", "explain",
    "know", "want", "need", "get", "like", "please", "thanks", "hi", "hello",
    # Leftovers from apostrophes: "that's" -> "that" + "s", "don't" -> "don" + "t".
    "s", "t",
}


@dataclass(frozen=True)
class Chunk:
    """One searchable piece of a guide."""

    doc_id: str     # e.g. "kb_004", taken from the file name
    heading: str    # the heading this chunk sits under
    text: str       # heading + body text


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk plus its BM25 score for one query."""

    doc_id: str
    heading: str
    text: str
    score: float


# Everyday words people type -> words the guides use. Applied to the QUERY only.
# Found by evaluation (data/eval/retrieval_cases.csv, evals/run_retrieval_eval.py):
# - "I earn 95k with 400/month in debts" scored 0 against the pre-approval guide,
#   which says "income" and "debt".
# - "costs to budget beyond the price" never reached the closing-costs guide.
# - "steps to buy a new build" shared no words with the process guide
#   ("stages", "buying", "new-construction").
# Keys are stemmed words (see _stem), so "costs" and "cost" both match "cost".
QUERY_SYNONYMS: dict[str, list[str]] = {
    "earn": ["income"],
    "salary": ["income"],
    "make": ["income"],             # "we make 160k combined"
    "afford": ["income", "debt"],
    "affordable": ["income"],
    "cost": ["closing", "fee"],     # the costs of buying include closing costs and fees
    "fee": ["closing"],
    "step": ["process", "stage"],
    "buy": ["buying"],
}


def _stem(word: str) -> str:
    """Very light plural handling so 'debts' matches 'debt' and 'taxes' matches 'tax'.

    Applied the same way to the guides and the query, so a slightly odd stem
    (e.g. 'status' -> 'statu') still matches itself.
    """
    if len(word) <= 3 or "-" in word or word[0].isdigit():
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"                     # families -> family
    if word.endswith(("xes", "ches", "shes", "sses")):
        return word[:-2]                           # taxes -> tax
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]                           # debts -> debt, costs -> cost
    return word


def tokenize(text: str) -> list[str]:
    """Lowercase, split into words (keeping things like '2-1' and 'move-in' whole),
    drop stopwords, and handle plurals ('debts' -> 'debt')."""
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def expand_query(tokens: list[str]) -> list[str]:
    """Add the guide words for everyday words in the question (see QUERY_SYNONYMS)."""
    return tokens + [extra for t in tokens for extra in QUERY_SYNONYMS.get(t, [])]


def chunk_markdown(doc_id: str, markdown: str) -> list[Chunk]:
    """Split a markdown file into chunks, one per heading (#, ##, ...).

    Text before the first heading (if any) becomes its own chunk.
    """
    chunks: list[Chunk] = []
    heading, lines = "", []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if "".join(lines).strip():
                chunks.append(Chunk(doc_id, heading, "\n".join(lines).strip()))
            heading, lines = line.lstrip("#").strip(), [line]
        else:
            lines.append(line)
    if "".join(lines).strip():
        chunks.append(Chunk(doc_id, heading, "\n".join(lines).strip()))
    return chunks


@lru_cache(maxsize=1)
def _index() -> tuple[list[Chunk], BM25Okapi]:
    """Load and chunk every guide once, then build the BM25 index."""
    chunks: list[Chunk] = []
    for path in sorted(KB_DIR.glob("*.md")):
        doc_id = "_".join(path.stem.split("_")[:2])   # kb_004_builder_incentives -> kb_004
        chunks.extend(chunk_markdown(doc_id, path.read_text(encoding="utf-8")))
    return chunks, BM25Okapi([tokenize(c.text) for c in chunks])


def get_doc_text(doc_id: str) -> str:
    """Full text of one guide (all its chunks), e.g. for the eval judge to read."""
    chunks, _ = _index()
    return "\n\n".join(c.text for c in chunks if c.doc_id == doc_id)


def doc_title(doc_id: str) -> str:
    """The first heading of a guide, e.g. 'kb_004' -> 'Builder incentives' (for display)."""
    chunks, _ = _index()
    return next((c.heading for c in chunks if c.doc_id == doc_id and c.heading), doc_id)


def retrieve(query: str, k: int = 3) -> list[RetrievedChunk]:
    """Return the k chunks that best match the query, best first.

    Chunks that share no words with the query (score 0) are left out, so an
    unrelated question can return fewer than k results.
    """
    chunks, bm25 = _index()
    scores = bm25.get_scores(expand_query(tokenize(query)))
    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    return [
        RetrievedChunk(c.doc_id, c.heading, c.text, round(float(s), 3))
        for c, s in ranked[:k]
        if s > 0
    ]
