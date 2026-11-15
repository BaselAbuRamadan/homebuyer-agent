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
-

## M4: Tools
-

## M5: V2 planning agent
-

## M6: V2 evaluation and LLM-as-judge
- Judge vs me agreement:

## M7: Demo and README
-
