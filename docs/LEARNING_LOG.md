# Learning log

One short entry per milestone, written by me, not by the AI. Three to five lines is enough.

Prompts for each entry: *What did I build? What concept clicked? What broke, and how did I find out? What decision did I make myself?*

## M0: Setup
-

## M1: V1 router
- **Built:** a router that classifies a homebuyer message into one of six intents. It uses structured output: a Pydantic `RouterDecision` (reasoning, intent, confidence) becomes a JSON Schema, so the model can only return a valid intent and I get a typed object back with no string parsing. `reasoning` comes before `intent`, so the model explains before it labels.
- **Demo result:** 5/6 correct. **R10** ("Is a 2-1 buydown actually worth it compared to a lower price?") was labelled `process_question` but predicted `affordability`. The model latched onto the money words ("worth it", "price") and treated it as a budget question, but it's really asking how a builder incentive works. The v1 prompt doesn't say where "comparing financing options" belongs, so the boundary between affordability and process_question is vague.
- **Confidence lesson:** every case scored exactly 0.90, *including the wrong one*. Self-reported confidence isn't calibrated, so I can't use it on its own to catch mistakes or trigger a fallback. The eval in M2 is what tells me whether the router is right.
- **Next:** watch for affordability vs process_question confusion in the M2 eval. A clearer definition ("calculations with the user's numbers" vs "explaining how something works") might fix it.

## M2: Evaluation and error analysis
- **Built:** an eval script that runs all test messages through the router and reports accuracy, accuracy by difficulty, precision/recall per intent and a confusion matrix. Each run is saved in `results/`. I grew the test set from 30 to 50 (20 tricky cases of my own) and added a 15-message held-out set.
- **Failure patterns I found:** (1) v1 labelled by *topic* instead of *what the user wants next*: "is a buydown worth it?" went to affordability, and "ready to make an offer" went to process question. (2) Prompt injection worked on v1 and v2. (3) Coded fair-housing language slipped through.
- **What I changed:** v2 added rules for offers and "worth it / compared" questions. It fixed its two targets but broke two other cases, so the score didn't move (94%). v3 said numbers mean affordability, added coded steering phrases and blocked injection: 98%, but it over-flagged a tax question. v4 says the *reason* for avoiding an area decides the label: 100% on the 50 cases, and 15/15 on the held-out set (v1 got 10/15).
- **What clicked:** a prompt fix can break cases you weren't looking at. You have to rerun everything every time, and test on cases you didn't tune on. v2 scored 100% on the first 40 cases and 94% once 10 new ones were added.
- **Decisions I made:** label by "what should the system do next"; offers always go to a human; when unsure, over-flag fair housing rather than miss it; keep temperature at 0 because a classifier needs consistency, not creativity.

## M3: Tracing
- **Built:** `tracing.py` connects to Phoenix and records every OpenAI call. `route()` and each eval case have their own labelled spans, so one test message becomes a trace: `eval_case R44 → route → ChatCompletion`. It's off unless I pass `--trace`.
- **What clicked:** a *span* is one step, and a *trace* is all the steps for one request. The CSV tells me *that* R44 failed. The trace showed me *why*: the model received "ignore your previous instructions…", obeyed, then invented the reason "the user wants to speak to a person".
- **Gotcha:** the green "OK" in Phoenix only means the API call worked, not that the answer was right. I added an `eval.correct` label so I can filter with `eval.correct == False`.
- **Also noticed:** R45 (Arabic) failed on v1 this run but passed on an earlier v1 run, more evidence that v1 is unstable on borderline cases.

## M4: Tools
- **Built:** four plain-Python tools: `monthly_payment` (itemised cost: loan + interest, tax, insurance, HOA, PMI), `max_affordable_price` (28% housing / 36% total-debt rules), `search_listings` and `get_listing`. Each has a JSON schema, the "menu" the model will read in M5. 40 pytest tests, no API calls.
- **What clicked:** the model should *decide* what to calculate, but Python should *do* the maths. Then the same question always gives the same number, and it can be tested. The amortisation formula finds the one fixed monthly payment that clears the loan in exactly 360 payments. Early payments are mostly interest.
- **Checked by hand:** $360k at 6.5% for 30 years = $2,275.44/month, the same as an online calculator. I also tried my own numbers in the terminal.
- **Decisions I made:** two separate affordability tools rather than one combined tool, because simpler inputs mean fewer wrong calls from the model. The V2 eval will count both as "affordability_calculator". Rates are in percent (6.5, not 0.065), and typos like 65% give an error instead of a silly answer.

## M5: V2 planning agent
- **Built:** `run_agent()`: route → retrieve (BM25 over the 7 guides) → plan (structured output) → tool loop (max 6 rounds) → answer → fair-housing check. Fair housing, tour booking and off-topic questions stop early with fixed safe replies. There's also a CLI (`scripts/chat.py`) with an "under the hood" view, and 76 tests, with the loop tested against a fake model.
- **What clicked:** the "agent" is just a loop. The model asks for a tool, Python runs it and sends back the result, and this repeats until the model has enough to answer. Python keeps control of the limit, the tools and the safety checks. Phoenix shows the whole tree, so I could see A01 pass the $305k result from one tool straight into the next.
- **What broke:** tests caught two bugs. "How *much* are closing costs" found the wrong guide, because BM25 thought the rare word "much" was important. And "predominantly *young* families" slipped past the answer check. A01 retrieval misses kb_002 because the user says "earn/afford" and the guide says "income/debt-to-income".
- **Decision I made:** when nothing fits the budget, suggest the closest homes above it instead of just saying "nothing found". This is done in the search tool (Python works out "over budget by $X"), not by trusting the model to remember.
- **Memory:** replying "yes" to "want the monthly cost?" was classed as out_of_scope, because each message was handled alone. I added short-term memory (the last 6 messages go to the router, planner and tool loop), so follow-ups work. It lives only while the chat is open.
- **Bug found by testing it myself:** after "yes", the agent used a $37,604 down payment although I'd said $25k saved. The tool only took a *percent*, so the model converted dollars to percent itself and got it wrong. Fix: the tool also accepts `down_payment_usd`, and the rule sits in the tool's own description, where the model reads it at call time (moving it there took it from inconsistent to 3/3 correct). Lesson: any time a tool's inputs don't match how users talk, the model fills the gap with arithmetic.

## M6: V2 evaluation and LLM-as-judge
- Judge vs me agreement:

## M7: Demo and README
-
