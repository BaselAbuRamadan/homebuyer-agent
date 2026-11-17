# Build plan: Homebuyer Assistant Agent

Eight milestones, from an empty repo to a traced, evaluated planning agent with a README you can send to recruiters. Each one maps to a concept from the LinkedIn Learning course.

**How to use this file.** Do one milestone per sitting. For each one:
1. Read **Concept** so you know what you're about to build and why.
2. In VS Code, open Claude Code in **plan mode** and paste the **Prompt**. Read its plan and push back if something is unclear, then let it write the code.
3. Run the **Check** yourself. Don't skip this, because it's what an engineer actually does.
4. Ask Claude Code to explain any line you couldn't defend in an interview.
5. Fill in your entry in `docs/LEARNING_LOG.md` (3–5 lines), then commit with the suggested message.

> The rule that makes this worth doing: **you make the decisions and Claude Code types.** You choose the intents, write extra test cases, decide which prompt change to try, and judge the results. Interviewers will ask about exactly those decisions.

---

## Milestone 0: Set up your workstation (about 1 hour)

**Concept.** An agentic coding workflow means an AI assistant works inside your editor. It reads your repo, proposes a plan, edits files and runs commands, and you review every step. `CLAUDE.md` is its standing brief.

**Do it yourself (no AI needed):**
1. Install **VS Code**, **Python 3.11+** and **Git**.
2. In VS Code, open Extensions and install **Claude Code** (by Anthropic). Sign in with your Claude account; it's included with Pro/Max plans, so you don't need an API key for it. *(Alternative: Cursor, which has a free tier. If you use it, copy `CLAUDE.md` into `.cursor/rules/`.)*
3. Unzip this starter folder, open it in VS Code, then in the terminal:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # then paste your OpenAI key into .env
   ```
4. On platform.openai.com → Billing: **turn off auto-recharge and set a monthly limit** (e.g. $5). This whole project should cost well under that.
5. Start Phoenix in a second terminal: `phoenix serve` → open http://localhost:6006
6. Run `python scripts/check_setup.py` and get every check to ✅.
7. Create an empty **public** GitHub repo called `homebuyer-agent`, then:
   ```bash
   git init && git add . && git commit -m "chore: starter scaffold, data and eval sets"
   git branch -M main && git remote add origin <your-repo-url> && git push -u origin main
   ```

**Check.** `check_setup.py` is all green, Phoenix opens in the browser, and the repo is on GitHub.

---

## Milestone 1: V1 router agent (action autonomy)

**Concept.** The simplest form of agency is the model choosing **which path** a request takes. You'll use *structured output*: the model returns JSON that matches a Pydantic schema (intent + reasoning + confidence) instead of free text, so your code can rely on it.

**Prompt for Claude Code:**
```
Read CLAUDE.md and docs/BUILD_PLAN.md (Milestone 1). Plan first, don't write code yet.

Build the V1 router:
- src/homebuyer_agent/config.py: load .env, expose OPENAI_MODEL and data paths
- src/homebuyer_agent/llm.py: one function that calls the OpenAI chat API with structured output into a Pydantic model
- src/homebuyer_agent/prompts/router_v1.txt: a short, simple baseline system prompt listing the six intents with a one-line description each. Keep it deliberately basic; we will improve it after evaluation.
- src/homebuyer_agent/router.py: RouterDecision (intent enum, reasoning, confidence 0-1) and route(message) -> RouterDecision
- scripts/demo_router.py: run 6 example messages from data/eval/v1_router_cases.csv and print the decisions

Explain the structured-output approach before you implement it.
```

**Check.** `python scripts/demo_router.py` prints six sensible decisions. Change one message to something odd and watch what happens.

**Commit:** `feat(v1): router agent with structured intent output`

---

## Milestone 2: Evaluate V1 and improve it with error analysis

**Concept.** *"Demo looks good" is not evaluation* (the course's main lesson). Measure against a labelled test set, look at **which** cases fail and **why**, make one targeted change, and measure again. This is the Continuous Calibration loop.

**Before prompting, do this yourself:** open `data/eval/v1_router_cases.csv` and **add 10 of your own cases**, especially tricky ones (typos, mixed intents, sarcasm, UK phrasing like "flat" or "mortgage in principle"). Mark them `difficulty=hard`. This is your contribution to the dataset, so talk about it in interviews.

**Prompt for Claude Code:**
```
Milestone 2. Build evals/run_v1_eval.py:
- run every case in data/eval/v1_router_cases.csv through route()
- report overall accuracy, accuracy by difficulty, per-intent precision/recall, and a confusion matrix
- save a timestamped CSV of every prediction plus a markdown summary to results/, including prompt version and model name
- accept --prompt router_v1 so I can compare versions

Then STOP and show me the failures. Don't fix anything yet. I want to do the error analysis myself.
```

**Your job next (no AI):** group the failures into 2–3 *patterns* (e.g. "mixed-intent messages go to listing_search", "fair-housing questions treated as listing_search"). Write them in the learning log.

**Second prompt:**
```
Here is my error analysis: <paste your patterns>. Create prompts/router_v2.txt that addresses ONLY these patterns. Options: clearer intent definitions, a priority rule for mixed intents, and 1-2 few-shot examples per confusing pair. Run the eval for v1 and v2 and produce a comparison table in results/v1_vs_v2.md.
```

**Check.** You have a before/after table. **Copy the real numbers into the README.** If v2 didn't improve, that's fine: write down why. Honest results impress more than perfect ones.

**Commit:** `feat(v1): eval harness + error-analysis-driven prompt v2`

---

## Milestone 3: Tracing with Phoenix

**Concept.** Agents fail in the middle: a wrong tool call, a bad retrieval, a strange plan. **Tracing** records every LLM call (inputs, outputs, latency, tokens) as spans so you can see what happened inside a run.

**Prompt for Claude Code:**
```
Milestone 3. Add src/homebuyer_agent/tracing.py that registers OpenInference OpenAI instrumentation against my local Phoenix (http://localhost:6006, project name "homebuyer-agent"). Call it from demo_router.py and run_v1_eval.py behind a --trace flag. Also wrap route() in a custom span with attributes for intent and prompt version. Explain what a span vs a trace is.
```

**Check.** Run the eval with `--trace`, open Phoenix, click into a failed case and find the exact prompt the model saw. **Take a screenshot → `assets/phoenix_trace.png`** for the README.
*Troubleshooting:* if Phoenix shows a login screen, set `PHOENIX_ENABLE_AUTH=false` before starting it (the same fix as in the Colab notebook).

**Commit:** `feat: Phoenix tracing for router and evals`

---

## Milestone 4: Tools (the agent can act)

**Concept.** Tools are normal, deterministic functions that the model can *choose* to call through function calling. The model decides **what** to do and Python does the maths. This prevents made-up numbers.

**Prompt for Claude Code:**
```
Milestone 4. Create deterministic tools with JSON-schema definitions for OpenAI function calling:
1. tools/affordability.py
   - monthly_payment(price, down_payment_pct, annual_rate, years=30, property_tax_rate, hoa_monthly, insurance_annual=1800, pmi if <20% down at 0.5%/yr) -> itemised breakdown
   - max_affordable_price(annual_income, monthly_debts, down_payment_savings, annual_rate, target_dti=0.36) -> price + assumptions used
2. tools/listings.py
   - search_listings(metro=None, city=None, max_price=None, min_beds=None, status=None, features=None, limit=5) over data/listings.json
   - get_listing(listing_id)
Write pytest tests in tests/ for each, including edge cases (0% down, no results, unknown id). No API calls in tests.
Explain the amortisation formula in plain English.
```

**Check.** `pytest` is green. Check one mortgage payment by hand or against an online calculator; you should be able to explain the formula.

**Commit:** `feat(tools): affordability calculator and listing search with tests`

---

## Milestone 5: V2 planning agent with retrieval (planning autonomy)

**Concept.** Now the agent **decides the steps itself**: retrieve relevant guidance (RAG with BM25), write a short plan, execute tool calls in a loop until it has enough information, then answer with the retrieved guidance as grounding. V2 = V1 router + retrieval + planning + tools.

**Prompt for Claude Code:**
```
Milestone 5. Build V2:
- retrieval.py: BM25 (rank_bm25) over data/knowledge_base/*.md, chunked by heading; retrieve(query, k=3) returns doc ids + text
- planner.py: run_agent(message) that
  1. routes with V1 (out_of_scope / talk_to_agent / fair_housing_sensitive short-circuit to safe template responses)
  2. retrieves KB chunks
  3. asks the model for a Plan (pydantic: list of steps with tool name + reason)
  4. executes tool calls in a loop with a max of 6 iterations
  5. writes a final answer that cites KB doc ids, states assumptions, and lists listing ids used
  Return an AgentResult with plan, tool_calls, retrieved_docs, answer (for evaluation).
- guardrails.py: fair-housing check on the user message AND the final answer
- scripts/chat.py: a simple CLI loop
Add custom Phoenix spans for retrieve, plan, each tool call and answer.
Walk me through the agent loop before writing it.
```

**Check.** Try `A01`, `A05` and `A08` from `data/eval/v2_agent_cases.csv` in the CLI, and look at the full trace tree in Phoenix (route → retrieve → plan → tools → answer). Screenshot it.

**Commit:** `feat(v2): planning agent with BM25 retrieval, tool loop and guardrails`

---

## Milestone 6: Evaluate V2 with custom metrics and LLM-as-judge

**Concept.** Open-ended answers can't be scored with exact match. You define **custom metrics** (did it call the right tools? did retrieval find the right doc?) plus an **LLM-as-judge** with a strict rubric for qualities like groundedness and safety. You then check the judge against your own judgement on a few cases.

**Prompt for Claude Code:**
```
Milestone 6. Build evals/run_v2_eval.py over data/eval/v2_agent_cases.csv:
- tool_selection: precision/recall of tools called vs expected_tools
- retrieval_hit_rate: was any expected_kb_doc in the retrieved docs
- LLM-as-judge (evals/judge_prompts/answer_judge_v1.txt) scoring 1-5 with a short justification for: groundedness, must_include coverage, safety (must_not_include violated? fair housing?), helpfulness
- save results/ CSV + markdown summary
Then create a small script that shows me 5 random judged cases so I can score them myself and compare with the judge.
```

**Your job (no AI):** score 5 cases yourself. Where you disagree with the judge, tighten the rubric. Note the agreement rate. Then do **one** improvement cycle on the weakest metric and record before/after numbers.

**Commit:** `feat(v2): custom metrics + LLM-as-judge eval`

---

## Milestone 7: Demo UI and the recruiter README

**Concept.** Shipping includes making it understandable. A 60-second demo and a clear README are what a hiring manager actually looks at.

**Prompt for Claude Code:**
```
Milestone 7. Create app.py with Streamlit: chat interface over run_agent(), plus a collapsible "Under the hood" panel per answer showing intent, plan, tool calls and retrieved doc ids. Add a sidebar note that the listings are sample data. Then help me update README.md: fill the architecture mermaid diagram to match the real code and populate the results tables from the latest files in results/. Do not invent numbers.
```

**Do yourself:** record a short GIF of the app (ScreenToGif on Windows, Kap on Mac) → `assets/demo.gif`. Write the **"Product thinking"** and **"What I learned"** sections of the README *in your own words*. This is the part that shows you're aiming at AI product ownership, so it shouldn't sound like Claude wrote it.

**Commit:** `docs: demo app, results, and README`

---

## Stretch ideas (pick one to talk about in interviews)
- Swap the model provider (Claude or Gemini) behind `llm.py` and compare eval scores and cost per run.
- Add a "budget-aware" memory: remember the user's income and preferences across turns.
- GitHub Action that runs the unit tests and the V1 eval on every push.
- Track cost and latency per eval run and add them to the results table.
