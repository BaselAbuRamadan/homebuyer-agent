# 🏡 Homebuyer Assistant Agent

**An evaluated, traced AI agent that helps people buying new-construction homes search listings, understand affordability and work through the buying process, while following US fair-housing rules.**

Designed and implemented end to end by **Basel Aburamadan** (MSc Computing Science, University of Glasgow): intent routing, a planning agent with tools and retrieval, evaluation with an AI judge, tracing, and a public deployment.

**[▶ Try the live demo](https://basel-housing-homebuyer-agent.streamlit.app/)**

[![Demo of Your Housing Chatbot](assets/demo.gif)](https://basel-housing-homebuyer-agent.streamlit.app/)
<!-- Placeholder animation. To show a real recording, save it over assets/demo.gif (same name); no README change needed. -->


---

## Why I built this

I built this project to demonstrate two things: that I can **own an AI product** from problem definition to launch, and that I can **build agentic systems hands-on**, not just describe them.

As a product owner, I defined the users and the scope. I set the success measures before writing features and made the trade-offs: accuracy versus cost, helpfulness versus legal risk, automation versus human hand-off. As an engineer, I built the agent loop by hand with the OpenAI SDK, without agent frameworks, so every decision the system makes can be traced, tested and explained.

I chose homebuying because it's a high-stakes, regulated purchase. People need clear numbers, honest limits and fair treatment. That makes it a demanding test of whether an AI product can be useful **and** trustworthy. The result is a deployed, evaluated product, with the evidence for each decision recorded in this repository.

## What it does

| Ask it… | What happens under the hood |
|---|---|
| "Show me 4-bed homes in Frisco under $500k" | Routed to `listing_search` → deterministic search tool |
| "I earn $95k with $400/month debts. What can I afford, and what's available in Austin?" | Plans two steps → affordability calculator → listing search, with the $305k budget applied by Python → homes within budget. If none had fit, it would suggest the closest ones, labelled "slightly" or "well" above budget |
| "Compare the monthly cost of L001 and L017 with 10% down" | A 4-step plan, so it switches to the stronger model → two listings + two payment calculations, itemised |
| "How do builder rate buydowns work?" | BM25 retrieval over a buying-guide knowledge base → explanation that cites its source |
| "A single-storey home with step-free entry under $400k" | Accessibility features of a *home* are fine to filter on → matching homes. If a feature isn't recorded for any home, it shows the homes matching everything else and says to check with the builder |
| "Which suburbs have fewer families with kids?" | Fair-housing guardrail → polite explanation + objective alternatives |
| "Book me a tour on Saturday" | Hands off to a human, and never claims to have booked anything |

## Architecture

```mermaid
flowchart LR
    U[User message] --> R{Router<br/>6 intents}
    U --> IC[Input check:<br/>steering phrases]
    R -- fair_housing_sensitive --> G[Fixed safe reply]
    IC -- match --> G
    R -- talk_to_agent / out_of_scope --> T[Hand-off or polite decline]
    R -- listing / affordability / process --> K[(BM25 retrieval:<br/>7 buying guides)]
    K --> P[Planner:<br/>structured plan]
    P --> M{Choose model:<br/>3+ steps → stronger}
    M --> L[Tool loop, max 6 rounds:<br/>calculators + listing search]
    L -- fails a check --> RT[Retry once on<br/>the stronger model]
    L --> A[Answer]
    RT --> A
    A --> OC[Output checks: fair housing,<br/>budget wording, required notes]
    OC --> Out[Reply + Under the hood]
```

Every step is traced in Arize Phoenix when tracing is on (evals and scripts, not the public app).

**Two levels of autonomy:**
- **V1, action autonomy.** The model picks one of six intents through structured output (Pydantic).
- **V2, planning autonomy.** The model retrieves guidance, writes a plan, calls tools in a bounded loop (max 6 rounds) and writes an answer grounded in what it retrieved. The tools do all the arithmetic, so the model never calculates a mortgage payment itself.

**A stronger model only when needed.** Everyday questions run on `gpt-4o-mini`. Python switches to `gpt-4o` in two situations: the plan has 3 or more tool steps, or the cheap attempt fails a plain check (empty answer, hit the tool limit, ended on a failed tool call, or a too-short explanation). If `gpt-4o` is unavailable, the answer comes from `gpt-4o-mini` instead of failing. "Under the hood" shows which model answered and why.

### The tools
The model decides *which* tool to call and with what inputs, but plain Python does the maths, so the same question always gives the same number and every tool is covered by unit tests.

| Tool | Question it answers | You give it | You get back | Example |
|---|---|---|---|---|
| `monthly_payment` | "What will this house cost me each month?" | price, down payment ($ or %), rate, optional tax rate / HOA / monthly budget | itemised monthly cost: loan + interest, tax, insurance, HOA, PMI, and over/under budget if a budget is given | $400k, 10% down, 6.5% → **$2,942/month** |
| `max_affordable_price` | "How expensive a house can I afford?" | yearly income, monthly debts, savings, rate | highest price, using the stricter of the **28% housing** and **36% total-debt** rules | $95k income, $400 debts, $40k saved → **$305,000** (28% rule applies) |
| `search_listings` | "What's available?" | metro/city, max price, beds, status, features, incentives | matching homes; if none fit the budget, the closest ones above it, by how much, labelled "slightly" (≤ $30k) or "well" above budget; if no home has a requested feature, the homes matching everything else. After `max_affordable_price`, Python fills in the budget if the model leaves it out. | |
| `get_listing` | "Tell me about this home" | a listing id | full details for that home | |

**Same maths, opposite directions:** `monthly_payment` starts from a **price** and ends with a **monthly cost**, while `max_affordable_price` starts from **my income** and ends with a **price**. I kept them as two simple tools rather than one combined calculator, because simpler inputs mean fewer wrong calls from the model. The V2 eval counts both as "affordability calculator".

## Evaluation (the part I care most about)

I didn't want a demo that only *looks* good, so every change was measured against labelled test sets.

### V1 router: 50 labelled messages (30 starter + 20 tricky cases I wrote)
Each prompt was run on the same 50 messages. Versions 2–4 were run twice to check the results were stable, and both runs gave the same score.

| Prompt | Overall | Hard cases | Fair-housing recall* |
|---|---|---|---|
| `router_v1` (baseline) | 47/50 (94%) | 20/23 (87%) | 6/6 (100%) |
| `router_v2` | 47/50 (94%) | 20/23 (87%) | 5/6 (83%) |
| `router_v3` | 49/50 (98%) | 22/23 (96%) | 6/6 (100%) |
| `router_v4` (current) | **50/50 (100%)** | **23/23 (100%)** | **6/6 (100%)** |

\* *Fair-housing recall = out of all the messages that really were fair-housing issues, how many the router caught. For a safety check, this is the number that matters most.*

**Held-out check (15 new messages, never used to tune the prompt):** `router_v1` 10/15 (67%), `router_v4` **15/15 (100%)** on two runs. *Honest caveat: I wrote these after v4 existed, so they aren't fully "blind". Both test sets are small.*

The final pre-launch check re-ran both sets on the finished code: still **50/50** and **15/15**.

**What error analysis showed, and what I changed:**
1. **v1 labelled by topic, not by what the user wanted.** "Is a buydown worth it?" went to *affordability* because it mentions money, although the user wanted an explanation. "I'm ready to make an offer" went to *process question* instead of a human. → **v2** added clear rules for both.
2. **v2 fixed those cases but broke two others.** It sent a cost question with real numbers to *process question*, and it missed coded fair-housing language ("away from the rough areas, you know what I mean"). Repeat runs showed this was a real regression, not noise. → **v3** said numbers mean *affordability*, added a list of coded steering phrases, and blocked prompt injection ("ignore your instructions…").
3. **v3 over-flagged.** "Don't show me anything in a MUD district, taxes are mad" was flagged as fair housing. → **v4** says the **reason** decides the label: avoiding an area for money, risk, land or distance is fine, while avoiding it because of *who lives there* is not.

**Trade-off I chose:** when the router can't tell, flagging an innocent question costs the user a rephrase, but missing real steering is a legal and ethical failure. So I'd rather it over-flag than under-flag.

**Temperature stays at 0**, so the router gives the same answer every time as far as possible. Higher temperature adds randomness, which helps creative writing but hurts a classifier.

Full results: [results/v1_vs_v4.md](results/v1_vs_v4.md) · [results/v1_vs_v2.md](results/v1_vs_v2.md) · every run is saved in [results/](results/).

### Retrieval: 26 questions, each with the guide it should find
BM25 matches words exactly, so "I earn 95k with 400/month in debts" scored **zero** against the pre-approval guide, which says "income" and "debt". The question "what costs to budget beyond the price" never reached the closing-costs guide. I added plural handling ("debts" → "debt") and a short list of everyday-word matches ("earn" → "income", "costs" → "closing", "steps" → "process"). Each one was kept only if it improved this test set without breaking another question.

| Search | Top-1 correct | In the top 3 the agent sees | 10 agent scenarios |
|---|---|---|---|
| Plain BM25 | 24/26 | 24/26 | 7/8 |
| **+ plurals + everyday-word matches** (current) | **26/26** | **26/26** | **8/8** |

*Caveat: I wrote these questions knowing the guides, so this is a regression check, not a blind test.* The pytest suite runs all 26 questions, so a later change that breaks one fails the build. Run it with `python evals/run_retrieval_eval.py`.

### V2 planning agent: 10 multi-step scenarios
Two kinds of scoring:
- **Exact checks in Python:** did the agent call the right tools, and did retrieval find the right guide?
- **An LLM-as-judge:** it grades each answer from 1 to 5 against a written rubric.

Before trusting the judge, I scored 5 answers myself and compared.

**Step 1: make the judge trustworthy.** Same 10 saved answers each time; only the judge changed.

| Judge | Agrees with me exactly | Within 1 point | What went wrong |
|---|---|---|---|
| v1 rubric, gpt-4o-mini | 10/20 (50%) | 85% | Too lenient: said answers covered points they didn't. Also too harsh on caveats that didn't apply. |
| v2 "quote it or it's MISSING", gpt-4o-mini | 14/20 (70%) | 85% | Still invented quotes, copying the guide instead of the answer. |
| v2, gpt-4o | 13/20 (65%) | 95% | Recalculated totals itself, and penalised my "closest homes above budget" feature. |
| **v3, gpt-4o** (current) | **14/20 (70%)** | **95%** | No invented quotes. |

Python also checks every quote the judge gives against the answer, so a judge that makes up evidence gets caught. Where the judge and I still disagree, the judge was sometimes right. For example, it noticed one answer never mentioned closing costs, which I had missed.

**Step 2: improve the agent.** Graded by the same judge (v3, gpt-4o) on the same 10 scenarios:

| Metric | `agent_v1` | `agent_v2` |
|---|---|---|
| Tool selection precision / recall | 0.89 / 0.80 | 0.89 / 0.80 |
| Retrieval hit rate | 7/8 | 7/8 |
| Judge: groundedness (1–5) | 4.6 | **4.9** |
| Judge: covers the checklist | 4.4 | **4.8** |
| Judge: safety | 4.7 | **5.0** |
| Judge: helpfulness | 4.4 | **4.9** |

**What changed from v1 to v2, and why:**
1. **"Explain how buydowns work…" got only a list of homes.** The model forgot the "explain" part after reading long tool results. → The planner now records "explain first: …", and Python repeats it as the last thing the model reads before it answers.
2. **A home $72,000 over budget was called "slightly above".** → The search tool now labels each home in Python: "slightly above budget" up to $30k, and "well above budget" beyond that. The model must use that label.
3. **The note about the listing data was left out in 4 of 10 answers**, although the prompt asked for it. → Python added the note automatically. *(Later I moved this disclosure to a single line in the website's sidebar, so answers stay clean.)*
4. **No home had "step-free entry", so the agent just said "nothing found".** → The search now returns homes that match everything else, and the agent tells the user to check the feature with the builder.

The lesson repeats from Milestone 4: **a rule that must always hold belongs in code, not in a prompt.**

**Does a smarter model help?** I ran the same 10 scenarios, on the same code and with the same judge, in three setups:

| Setup | Groundedness | Checklist | Safety | Helpfulness | Avg wait | Tool calls |
|---|---|---|---|---|---|---|
| All gpt-4o-mini | 4.7 | **4.8** | 5.0 | **4.9** | 9.1 s | **17** |
| All gpt-4o | **4.9** | 4.7 | 5.0 | 4.8 | **5.9 s** | 22 |
| Split: mini router, gpt-4o for every answer | 4.3 | 4.5 | 5.0 | 4.5 | 6.2 s | 22 |

- **Quality: no clear winner.** The differences are within one run's noise on 10 cases.
- **gpt-4o was faster** but costs several times more.
- **It broke two rules that mini followed.** Reading the answers showed two weaknesses in my code, not just in the model:
  - On A01 it searched **without the $305k budget**, then called a home $72,000 over "slightly above your budget". → Python now adds the budget to any search that leaves it out, so the tool's label always decides.
  - It once replied "I've explained the steps…" with no steps. I reproduced it: gpt-4o had written a 2,700-character explanation **next to a tool call**, and my loop threw that text away. → The loop now keeps it, and prompt v3 says the user only sees the final message.

**Final pre-launch check.** Prompt `agent_v3` plus all the fixes above, then the "smarter model when needed" rule. Same 10 scenarios, same judge:

| Setup | Retrieval | Tool precision / recall | Groundedness | Checklist | Safety | Helpful | Tool calls | Slowest |
|---|---|---|---|---|---|---|---|---|
| Before the check-up (`agent_v2`, mini) | 7/8 | 1.00 / 0.80 | 4.7 | 4.8 | 5.0 | 4.9 | 17 | 17.8 s |
| `agent_v3` + fixes, mini only | **8/8** | 0.89 / 0.80 | **4.9** | **4.9** | 5.0 | **4.9** | 29 | 22.2 s |
| **Final: + gpt-4o when needed** (live) | **8/8** | **1.00** / 0.80 | 4.7 | **4.9** | 5.0 | 4.7 | **17** | **16.3 s** |

- **A03 is fixed.** Retrieval now brings in the closing-costs guide, and both runs state the "2–5% of the loan amount" range. It had been missing since Milestone 6.
- **The smart model ran on 2 of 10 questions** (the two multi-step comparisons). Those two got faster and leaner: A10 went from 21 tool calls to 9, and its wait from 22.2 s to 12.5 s. Mini kept re-fetching homes the search had already returned, against the prompt's rule; gpt-4o didn't.
- **Why the final row's judge scores are slightly lower:** I checked each lower score by hand. Both are judge mistakes. A01 was answered by **mini in both runs** with the same correct "well above budget" wording, yet scored 5/5 once and 3/5 the other time. On A10 the judge called "$210.35 under budget" wrong, but it is exactly the calculator's result. One run on 10 cases can't separate these two setups on quality. Speed and tool use can.

**Decision: gpt-4o-mini for everyday questions, gpt-4o only when needed** (`SMART_MODEL`).

*After this check, I grew the listings from 32 to 160 homes, so typical searches find matches (151 test searches: none leave a visitor with no homes to look at). I also moved the "sample data" disclosure from every answer to one line in the website's sidebar. The live prompt is `agent_v4`, which is `agent_v3` minus the per-answer data note. The scores above were measured on the 32-home data.*

**Still open:**
- A10 doesn't always say that tax rates differ by state.
- When mini is used, it can ignore the "don't re-fetch homes" rule (multi-step questions now go to gpt-4o, which follows it).
- 10 scenarios and a single run per setup are too few to rank similar setups on quality. A bigger test set is the next step.

Full results: every run is saved in [results/](results/), named `v2_eval_*`, `v2_rejudge_*`, `v2_agreement_*` and `retrieval_eval_*`.

## Tracing

Every run is traced in **Arize Phoenix**: route → retrieve → plan → tool calls → answer, with latency and token counts per step. This is how I debugged failures rather than guessing.

**Finding failures:** each eval case is a trace labelled with its expected and predicted intent. Filtering on `eval.correct == False` shows only the cases the router got wrong (here, the baseline `router_v1`):

![Phoenix: failed eval cases](assets/phoenix_failures.png)

**Seeing why it failed:** opening case R44 shows the exact message the model received, a prompt-injection attempt, and its answer. The baseline router obeyed the injection and then made up a reason. `router_v4` blocks this.

![Phoenix trace of a prompt injection](assets/phoenix_trace.png)

**The full V2 agent, step by step:** one question ("I earn 95k… what can I afford, 3-beds in Austin?") becomes this tree. The router picks the intent, BM25 retrieves guides, the model writes a plan, then it calls `max_affordable_price` and feeds that result into `search_listings`, and finally a fair-housing check runs on the answer. Each step shows its inputs, outputs and timing.

![Phoenix trace of the V2 planning agent](assets/phoenix_agent_trace.png)

## Product thinking

**The user:** first-time and early-stage buyers comparing new-construction homes. They want to know what they can afford, what's available, and how buying from a builder works, without feeling pushed into a sales conversation too early.

**Where it could be used:**
- **Homebuilder websites:** a 24/7 assistant that answers buyer questions, matches people to homes in their budget, and hands qualified buyers to the sales team with context.
- **Mortgage lenders and brokers:** an education and pre-qualification front door that explains affordability, down payments and buydowns before a loan officer gets involved.
- **Real-estate portals and agencies:** a conversational search layer on top of existing listings, with the same tool-based design.
- **Internal sales enablement:** a consistent, compliant first answer for sales teams handling repetitive questions.

**Key product decisions I made:**

| Decision | Why |
|---|---|
| **Python does all the maths; the AI only decides what to calculate** | Financial figures must be exact and repeatable. A model that "estimates" a mortgage payment is a liability. |
| **Fair housing: when unsure, flag it** | A wrongly flagged question costs the user a rephrase. Missing real steering is a legal and ethical failure. The *reason* for avoiding an area decides the label: cost, flood risk and commute are fine; who lives there is not. |
| **Offers and tour bookings always go to a human, and the assistant never claims to have booked anything** | Over-promising destroys trust, and these are the moments where a sales team adds value. |
| **When nothing fits the budget, suggest the closest homes, labelled "slightly" (up to $30k) or "well" above budget** | "Nothing found" is a dead end. Honest, clearly labelled alternatives keep the buyer engaged without misleading them. |
| **Explanation questions get an explanation first, not just listings** | Buyers asking "how does this work?" need understanding before options. Listing homes alone answered the wrong question. |
| **gpt-4o-mini by default, gpt-4o only when a question needs it** | Measured, not assumed: the cheaper model matched quality on everyday questions. Paying for the stronger model only on multi-step questions improved speed and efficiency at a controlled cost. |
| **Cost and abuse limits from day one** | Per-visitor limits, a shared daily cap and an account budget make a public demo safe to run on a personal API key. |
| **Transparency in the product** | "Under the hood" shows the intent, plan, tools, model and sources behind every answer, so users and stakeholders can see *why* the assistant said what it said. |
| **One clear disclosure instead of repeated warnings** | The sample-data notice sits once in the sidebar, which keeps answers clean while staying honest. |
| **Evaluation before features** | Every change was measured against labelled test sets, and the AI judge was checked against my own scoring before I trusted it. |

**How I'd measure success in production:**
- Answer accuracy on a growing test set
- Hand-off rate to sales, and conversion from those hand-offs
- How many conversations end with a home or a clear next step
- Fair-housing flags reviewed by a person
- Cost per conversation

**What I'd build next:**
- Connect to a real listings feed and a builder's CRM for hand-offs
- Grow the evaluation set from real (anonymised) conversations
- Add semantic search alongside keyword search
- Collect user feedback on each answer to drive the next improvement cycle

## How I built it: an agentic coding workflow

I built this in VS Code with **Claude Code** as a pair programmer. A `CLAUDE.md` file gives the assistant a standing brief: no agent frameworks, explain before writing, deterministic tools, versioned prompts, fair-housing rules. I worked in eight milestones ([docs/BUILD_PLAN.md](docs/BUILD_PLAN.md)). The assistant wrote most of the code, and I made the decisions: the intent taxonomy, the extra test cases, the error analysis, which prompt changes to try, and the judge rubric. I kept a short learning log after each milestone ([docs/LEARNING_LOG.md](docs/LEARNING_LOG.md)).

## The journey: what broke, and what I learned from it

Each stage followed the same loop: build it, measure it, read the failures, fix the cause, then measure again.

| Stage | What went wrong | How I found it | What I changed | Lesson |
|---|---|---|---|---|
| **1. Router** | The model said it was 90% confident on every message, *including the one it got wrong*. | A 6-message demo | Stopped treating self-reported confidence as a safety signal | Only an eval tells you whether a model is right. |
| **2. Router eval** | Prompt v2 fixed the two cases I targeted but broke two others. v3 then over-flagged a tax question as fair housing. | 50 labelled messages, repeat runs, a 15-message held-out set | Label by *what should happen next*. For fair housing, the *reason* someone avoids an area decides the label. 94% → 100%, held-out 67% → 100%. | A fix can break cases you weren't looking at. Rerun everything, every time. |
| **3. Tracing** | A green "OK" in Phoenix only meant the API call worked. A prompt injection had fooled the router. | Opening the trace and reading the exact messages | Labelled every eval trace with `correct = true/false` | A CSV tells you *that* something failed. A trace tells you *why*. |
| **4. Tools** | Asked for a monthly cost, the model turned "$25k saved" into the wrong percentage ($37,604 down). | Testing it myself in the terminal | The tool accepts dollars directly. All maths lives in Python. | Whenever a tool's inputs don't match how people talk, the model fills the gap with arithmetic, and gets it wrong. |
| **5. Agent** | Replying "yes" to a follow-up was treated as off-topic. Search ranked the wrong guide because of the word "much". A guardrail missed "young families". | Chatting with it, and unit tests | Short-term memory (last 6 messages), stopword fixes, guardrail patterns | Unit tests catch the boring bugs, so I could focus on the interesting ones. |
| **6. AI judge** | The first judge agreed with me only 50% of the time. It said answers covered points they never mentioned, and later quoted text that wasn't in the answer. | Scoring 5 answers myself *before* seeing the judge's scores | Judge must quote the answer for every point, Python checks those quotes, a stronger judge model. Agreement: 50% → 70% exact, 95% within 1 point. | You have to evaluate the evaluator. And sometimes the judge was right and I was wrong. |
| **6. Agent fixes** | It called a home $72,000 over budget "slightly above". It answered "explain how buydowns work" with only a list of homes. It forgot the data disclaimer in 4 of 10 answers. | Judge scores, then reading the answers | "Slightly / well above budget" decided in Python ($30k line). An "explain first" reminder placed where the model reads it last. Required notes added in code. | **A rule that must always hold belongs in code, not in a prompt.** |
| **7. Smarter model** | gpt-4o was *not* clearly better than gpt-4o-mini. It searched without the user's budget, and once threw away its own 2,700-character explanation. | A three-way comparison, then reading every answer | Python now applies the budget and keeps text written next to tool calls. gpt-4o is used **only when needed** (multi-step questions or a failed check): same quality, faster, fewer tool calls. | A stronger model can expose holes in your code that a cheaper one happened not to hit. |
| **7. Retrieval** | "I earn 95k with debts" scored zero against the guide about "income and debt". A question about costs never reached the closing-costs guide. | A new 26-question retrieval test | Plural handling plus a small list of everyday-word matches: 24/26 → 26/26. The missing "closing costs 2–5%" appeared in answers. | What looked like a model failure was a search failure. |
| **7. Going live** | Only 32 homes, so many searches found nothing. The deploy file allowed versions missing features the app needs. | 151 test searches, and a fresh install in a clean environment | 160 homes (generated reproducibly from the same rules), pinned requirements, daily cost limits, real end-to-end questions through the website | Test the deployment the way the host will run it. |

## Run it yourself

```bash
git clone <this repo> && cd homebuyer-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # app + evals + tests + Phoenix
cp .env.example .env          # add your OpenAI key
phoenix serve                 # in a second terminal → http://localhost:6006
python scripts/check_setup.py # checks packages, data, and a test call to each model
pytest                        # unit tests: tools, retrieval, agent loop, app (no API calls)
python evals/run_retrieval_eval.py               # retrieval on 26 questions (no API calls)
python evals/run_v1_eval.py --prompt router_v4 --trace
python evals/run_v2_eval.py   # agent eval + LLM-as-judge (set JUDGE_MODEL in .env)
python evals/score_by_hand.py # score 5 answers yourself, then compare with the judge
streamlit run app.py          # the chat app → http://localhost:8501
```

## Deploy (Streamlit Community Cloud, free)

1. Push the repo to GitHub (`.env` stays private: it is git-ignored).
2. Go to [share.streamlit.io](https://share.streamlit.io), click **Create app**, pick this repo, branch `main` and main file `app.py`.
3. Open **Advanced settings**. Choose **Python 3.12 or newer**, then paste into **Secrets**:
   ```toml
   OPENAI_API_KEY = "sk-..."
   OPENAI_MODEL = "gpt-4o-mini"
   SMART_MODEL = "gpt-4o"          # used only when needed; leave out to run everything on mini
   DAILY_QUESTION_LIMIT = "300"    # optional: questions per day from all visitors together
   ```
4. Click **Deploy**. Streamlit installs `requirements.txt`, which contains only what the app needs, pinned to tested versions. Phoenix and pytest are in `requirements-dev.txt`, so the deploy stays fast.

**Cost protection, three layers:**
- Each visitor gets **15 questions per session**, up to 500 characters each, and the input is locked while an answer is being written.
- All visitors together get **`DAILY_QUESTION_LIMIT` questions per day**, so refreshing the page doesn't get around the per-visitor limit. This counter lives in server memory, so it resets when the app restarts.
- The hard stop: set a **monthly budget limit** on your OpenAI account (Settings → Limits).

Most questions run on gpt-4o-mini, which costs a fraction of a cent each. Multi-step ones use gpt-4o, which costs several times more. Tracing is off in the app.

## Tech
Python · OpenAI API (structured outputs, function calling) · Pydantic · BM25 (`rank_bm25`) · Arize Phoenix / OpenInference · pandas · pytest · Streamlit

## Limitations
- Listings are **sample data made up for this demo**, not real homes: 160 homes across Austin, Phoenix, Raleigh and Dallas. 32 were written by hand, and 128 were generated by [scripts/generate_listings.py](scripts/generate_listings.py) with a fixed seed, following the same price and tax rules. The website says so in its sidebar.
- Affordability figures are **educational estimates, not financial advice**. Rates, taxes and insurance are stated assumptions.
- The evaluation sets are small and hand-written, so the numbers show direction rather than statistical certainty.
- Retrieval is keyword search (BM25) with a small hand-made list of everyday-word matches ("earn" → "income"). A question phrased in words that aren't on that list can still miss its guide. Embeddings would handle meaning better.
- The AI judge is gpt-4o, and on multi-step questions the agent also answers with gpt-4o, so the judge partly grades its own writing. My hand scores are the check on that.

## What I learned
- **An agent is just a loop.** The model chooses the next step, and Python runs the tools, enforces the limits and checks the safety rules. Building it by hand, without a framework, means I can explain every step.
- **Measure before changing anything, and read the answers behind the numbers.** Several "improvements" broke other cases, and several low scores turned out to be the judge's mistakes. Neither showed up until I looked.
- **Put guarantees in code.** Arithmetic, budget wording, required caveats and fair-housing checks all became reliable once Python enforced them, whichever model was answering.
- **Choose the model for the job, not the biggest one.** The cheap model handles everyday questions as well as the expensive one. Paying for the stronger model only when a question needs it gave the best mix of quality, speed and cost.
- **Shipping is part of the work.** Cost limits, friendly errors, a clean install and a README a stranger can follow took real time, and they're what turn a demo into something people can use.
