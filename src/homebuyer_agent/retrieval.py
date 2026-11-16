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


def tokenize(text: str) -> list[str]:
    """Lowercase, split into words (keeping things like '2-1' and '1-2-10'), drop stopwords."""
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
    return [w for w in words if w not in STOPWORDS]


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


def retrieve(query: str, k: int = 3) -> list[RetrievedChunk]:
    """Return the k chunks that best match the query, best first.

    Chunks that share no words with the query (score 0) are left out, so an
    unrelated question can return fewer than k results.
    """
    chunks, bm25 = _index()
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    return [
        RetrievedChunk(c.doc_id, c.heading, c.text, round(float(s), 3))
        for c, s in ranked[:k]
        if s > 0
    ]
