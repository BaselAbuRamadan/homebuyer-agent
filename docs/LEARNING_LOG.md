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
- Failure patterns I found:
- What I changed in router_v2 and why:

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
