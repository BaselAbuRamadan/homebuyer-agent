# 🏡 Homebuyer Assistant Agent

**An evaluated, traced AI agent that helps people buying new-construction homes search listings, understand affordability and work through the buying process, while following US fair-housing rules.**

Built by **Basel Aburamadan** (MSc Computing Science, University of Glasgow) to learn agentic AI development end to end, building on the LinkedIn Learning course *Agentic AI: Build Your First Agentic AI System*.

<!-- TODO (M7): replace with your demo GIF -->
![Demo](assets/demo.gif)

---

## Why I built this

<!-- TODO: write this in your own words, 3-5 sentences. Suggested angle:
- you want to work as an AI product owner, so you wanted to understand agents from the inside rather than only on slides
- why homebuying: a high-stakes, confusing purchase where people now expect a conversation rather than filters
- what you wanted to prove to yourself: that you could ship something measurable, not just a demo -->

## What it does

| Ask it… | What happens under the hood |
|---|---|
| "Show me 4-bed homes in Frisco under $500k" | Routed to `listing_search` → deterministic search tool |
| "I earn $95k with $400/month debts. What can I afford, and what's available in Austin?" | Plans two steps → affordability calculator → listing search → grounded answer with stated assumptions |
| "How do builder rate buydowns work?" | BM25 retrieval over a buying-guide knowledge base → answer that cites its sources |
| "Which suburbs have fewer families with kids?" | Fair-housing guardrail → polite explanation + objective alternatives |
| "Book me a tour on Saturday" | Hands off to a human, and never claims to have booked anything |

## Architecture

<!-- TODO (M7): update to match the final code -->
```mermaid
flowchart LR
    U[User message] --> R{V1 Router<br/>intent classification}
    R -- out_of_scope / talk_to_agent --> T[Safe template / human handoff]
    R -- fair_housing_sensitive --> G[Guardrail response]
    R -- listing / affordability / process --> P[V2 Planner]
    P --> K[(BM25 retrieval<br/>buying guides)]
    P --> TL[Tools: affordability calculator,<br/>listing search, get listing]
    TL --> P
    K --> A[Grounded answer<br/>+ assumptions + sources]
    P --> A
    A --> GC[Fair-housing output check]
    subgraph Observability
      PX[Arize Phoenix traces]
    end
    R -.-> PX
    P -.-> PX
```

**Two levels of autonomy (following the course):**
- **V1, action autonomy.** The model picks one of six intents through structured output (Pydantic).
- **V2, planning autonomy.** The model retrieves guidance, writes a plan, calls tools in a bounded loop (max 6 steps) and writes an answer grounded in what it retrieved. The tools do all the arithmetic, so the model never calculates a mortgage payment itself.

## Evaluation (the part I care most about)

I didn't want a demo that only *looks* good, so every change was measured against labelled test sets.

### V1 router: 40 labelled messages (30 starter + 10 hard cases I wrote)
<!-- TODO (M2): paste real numbers from results/v1_vs_v2.md -->
| Prompt | Overall accuracy | Hard cases | Fair-housing recall |
|---|---|---|---|
| `router_v1` (baseline) | __% | __% | __% |
| `router_v2` (after error analysis) | __% | __% | __% |

**What error analysis showed:** <!-- TODO: your 2-3 failure patterns and what you changed -->

### V2 planning agent: 10 multi-step scenarios
<!-- TODO (M6): paste real numbers -->
| Metric | Score |
|---|---|
| Tool selection (precision / recall) | __ / __ |
| Retrieval hit rate | __% |
| LLM-as-judge: groundedness (1–5) | __ |
| LLM-as-judge: safety (1–5) | __ |
| Judge agreement with my own scoring | __ / 5 cases |

## Tracing

Every run is traced in **Arize Phoenix**: route → retrieve → plan → tool calls → answer, with latency and token counts per step. This is how I debugged failures rather than guessing.

<!-- TODO (M3/M5): screenshot -->
![Phoenix trace](assets/phoenix_trace.png)

## Product thinking

<!-- TODO: your own words. This section is what makes the project yours. Ideas to cover:
- Who is the user? (first-time buyers comparing new-build communities)
- What would success look like in production? (e.g. qualified leads handed to sales teams, fewer drop-offs, accuracy of affordability answers)
- Risks you designed for: fair housing / steering, made-up numbers, overpromising (pretending to book tours), giving financial advice
- What you'd measure next and what you'd build next -->

## How I built it: an agentic coding workflow

I built this in VS Code with **Claude Code** as a pair programmer. A `CLAUDE.md` file gives the assistant a standing brief: no agent frameworks, explain before writing, deterministic tools, versioned prompts, fair-housing rules. I worked in eight milestones ([docs/BUILD_PLAN.md](docs/BUILD_PLAN.md)). The assistant wrote most of the code, and I made the decisions: the intent taxonomy, the extra test cases, the error analysis, which prompt changes to try, and the judge rubric. I kept a short learning log after each milestone ([docs/LEARNING_LOG.md](docs/LEARNING_LOG.md)).

## Run it yourself

```bash
git clone <this repo> && cd homebuyer-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your OpenAI key
phoenix serve                 # in a second terminal → http://localhost:6006
python scripts/check_setup.py
python evals/run_v1_eval.py --prompt router_v2 --trace
streamlit run app.py
```

## Tech
Python · OpenAI API (structured outputs, function calling) · Pydantic · BM25 (`rank_bm25`) · Arize Phoenix / OpenInference · pandas · pytest · Streamlit

## Limitations
- Listing data is **fictional** (32 invented homes across Austin, Phoenix, Raleigh and Dallas).
- Affordability figures are **educational estimates, not financial advice**. Rates, taxes and insurance are stated assumptions.
- The evaluation sets are small and hand-written, so the numbers show direction rather than statistical certainty.

## What I learned
<!-- TODO: 3-5 honest sentences in your own voice. -->
