# CLAUDE.md — project brief for AI coding assistants

Claude Code reads this file automatically at the start of every session. Cursor users: copy it to `.cursor/rules/project.md`.

## What this project is
A **homebuyer assistant agent** for US new-construction homes, built as a learning and portfolio project by Basel Aburamadan.
It follows the same progression as the LinkedIn Learning course *Agentic AI: Build Your First Agentic AI System*:
- **V1: Action autonomy.** A router agent classifies a homebuyer's message into an intent.
- **V2: Planning autonomy.** A planning agent retrieves guidance (BM25 RAG), plans steps, calls tools and writes an answer.
- At every stage: **evaluation first**, error analysis, then targeted changes. Tracing goes through **Arize Phoenix**.

## The developer is learning — how to work with him
- Work in **small steps**. One milestone (see `docs/BUILD_PLAN.md`) per session, and stop for review between milestones.
- **Explain before you write.** Before editing files, give a short plan: which files, why, and the key concept involved.
- Keep code **readable rather than clever**: plain functions, type hints, docstrings, and no unnecessary abstraction or frameworks.
- **Do not use LangChain, LlamaIndex, CrewAI or similar agent frameworks.** The point is to build the loop by hand so it can be explained in interviews. Use the `openai` SDK directly.
- After each change, tell him how to run it and what output to expect.
- When he asks "why", answer the concept, not just the code.

## Tech stack
- Python 3.11+, local virtualenv (`.venv`)
- `openai` SDK; model names come from env vars, never hard-coded:
  `OPENAI_MODEL` (everyday model), `SMART_MODEL` (optional stronger model the planner uses when needed), `JUDGE_MODEL` (evals only)
- `pydantic` for structured outputs (intents, plans, tool arguments)
- `rank_bm25` for retrieval over `data/knowledge_base/*.md`
- `arize-phoenix` + `openinference-instrumentation-openai` for tracing (local server on http://localhost:6006)
- `pandas` for evaluation results; `pytest` for tests
- `streamlit` for the public demo (`app.py`). `requirements.txt` = app only (Streamlit Cloud); `requirements-dev.txt` = everything

## Layout
```
app.py              # public Streamlit demo (limits, Under the hood panel)
.streamlit/         # theme config (no custom CSS)
src/homebuyer_agent/
  config.py         # env loading, model names, paths
  llm.py            # thin OpenAI client wrapper (single place for API calls)
  router.py         # V1: intent classification
  prompts/          # versioned prompts: router_v1-4, planner_v1-2, agent_v1-4 (latest = live)
  tools/            # deterministic tools: affordability.py, listings.py
  retrieval.py      # BM25 over the knowledge base (+ plurals, query synonyms)
  planner.py        # V2: plan -> choose model -> act -> answer loop
  guardrails.py     # fair-housing and scope checks
  eval_metrics.py   # tool precision/recall, retrieval hit, judge-quote check
  usage.py          # shared daily question limit for the web app
  tracing.py        # Phoenix setup (Phoenix imported only when tracing is turned on)
evals/
  run_v1_eval.py    # accuracy, confusion matrix, per-case errors -> results/
  run_v2_eval.py    # tool selection, retrieval hit rate, LLM-as-judge (--rejudge)
  run_retrieval_eval.py  # retrieval top-1/top-3 on data/eval/retrieval_cases.csv
  score_by_hand.py, judge_agreement.py  # human vs judge agreement
  judge_prompts/
results/            # eval outputs (CSV/markdown), committed so results are visible
tests/              # pytest unit tests: tools, retrieval, agent loop, app (no API calls)
```

## Rules
- **Never commit secrets.** Keys live in `.env` (git-ignored). Read them with `python-dotenv`.
- Tools (affordability, listing search) must be **deterministic Python**. The LLM decides *when* to call them and never does the arithmetic itself.
- Unit tests must not call the API. Mock `llm.py` where needed.
- Prompts are files under `prompts/` with version numbers, so prompt changes show up in git diffs and eval comparisons.
- Every eval run saves a timestamped file in `results/` with the prompt version and model name.
- **Fair housing:** the assistant must never filter, rank or describe areas by the demographics of residents (race, religion, national origin, familial status, sex, disability). See `data/knowledge_base/kb_007_fair_housing.md`. Accessibility features of a *home* are fine.
- The assistant gives **educational information, not financial advice**, and states its assumptions (rate, tax, insurance).
- All listing data is sample data invented for this demo (`data/listings.json`, 160 homes; L033+ come from `scripts/generate_listings.py`). Never present it as real. The website states this once, in the sidebar; answers don't repeat it.

## Domain intents (V1)
`listing_search`, `affordability`, `process_question`, `talk_to_agent`, `out_of_scope`, `fair_housing_sensitive`
