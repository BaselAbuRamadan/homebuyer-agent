"""Fair-housing and scope guardrails. Deterministic keyword checks, no AI.

These are a SECOND safety layer on top of the router:
- check_message(): catches obvious steering phrases even if the router misses them.
- check_answer():  stops the final answer from describing areas by who lives there.

They look for steering PHRASES, not single words, so "I use a wheelchair" or
"we're expecting a baby" (the user's own needs) are not flagged.
See data/knowledge_base/kb_007_fair_housing.md.
"""
import re
from dataclasses import dataclass

# Optional "young " in front so "young families" matches as well as "families".
_GROUPS = (
    r"(?:young\s+)?(white|black|african[- ]american|hispanic|latino|latina|asian|indian|arab|"
    r"christian|muslim|jewish|hindu|catholic|immigrants?|foreigners?|"
    r"famil(?:y|ies)|kids|children|retirees|seniors|elderly|young (?:people|professionals)|gay|lgbtq?\+?)"
)

# Phrases in a USER message that ask to pick or avoid areas by who lives there.
MESSAGE_PATTERNS = [
    r"\bpeople like (me|us)\b",
    r"\bmy own kind\b",
    # "no kids" / "suit a family" are left out on purpose: they usually describe the
    # user's OWN household ("no kids yet", "a home to suit a family of five").
    r"\b(fewer|less|away from)\s+" + _GROUPS + r"\b",
    r"\b(mostly|predominantly|majority|lots of|full of)\s+" + _GROUPS + r"\b",
    r"\bwhere\s+" + _GROUPS + r"\s+live\b",
    r"\bpopular with\s+" + _GROUPS + r"\b",
    r"\b(people|neighbou?rs) of my (religion|race|faith|culture)\b",
    r"\bshares? (our|my) (culture|religion|faith)\b",
    r"\bnot too diverse\b",
    r"\bgood demographics\b",
    r"\bno section 8\b",
]

# Phrases in the ASSISTANT's answer that would describe areas by residents.
ANSWER_PATTERNS = [
    r"\b(mostly|predominantly|largely|majority)\s+" + _GROUPS + r"\b",
    r"\b(fewer|less|more|lots of|full of)\s+" + _GROUPS + r"\s+(live|living|residents|in the area|nearby)\b",
    r"\b(popular with|favou?red by|attracts?)\s+" + _GROUPS + r"\b",
    r"\bdemographics? (is|are|of the area)\b",
]


@dataclass(frozen=True)
class GuardrailResult:
    flagged: bool
    matched: str | None = None   # the phrase that triggered the flag, for logs and traces


def _first_match(text: str, patterns: list[str]) -> GuardrailResult:
    for pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE)
        if found:
            return GuardrailResult(True, found.group(0))
    return GuardrailResult(False)


def check_message(message: str) -> GuardrailResult:
    """Flag a user message that asks to choose or avoid areas by who lives there."""
    return _first_match(message, MESSAGE_PATTERNS)


def check_answer(answer: str) -> GuardrailResult:
    """Flag an assistant answer that describes areas by their residents."""
    return _first_match(answer, ANSWER_PATTERNS)


# Safe, fixed responses. No model involved, so they can't go wrong.
FAIR_HOUSING_RESPONSE = (
    "I can't recommend or rule out areas based on who lives there (for example families with "
    "children, religion, race or national origin). Under the US Fair Housing Act that would be "
    "steering. [kb_007]\n\n"
    "I'm happy to help with objective things instead:\n"
    "- price, size, bedrooms and build status\n"
    "- amenities such as trails, pools or a quiet cul-de-sac lot\n"
    "- lot size, HOA rules and commute times\n"
    "- official crime-statistics and school-rating sites you can check yourself\n\n"
    "Tell me which of these matter to you and I'll search the listings."
)

TALK_TO_AGENT_RESPONSE = (
    "I can't book tours, make offers or contact anyone myself, so nothing has been scheduled or "
    "confirmed yet. This is where I hand you over to a person: the community's sales team can "
    "arrange it{listing_part}. In the meantime I can answer questions about the home, the costs or "
    "the buying process."
)

OUT_OF_SCOPE_RESPONSE = (
    "That's outside what I can help with. I'm a homebuying assistant for new-construction homes, "
    "so I can't give investment or general advice. I can help you find homes, estimate what you "
    "can afford, or explain how buying a new build works."
)
