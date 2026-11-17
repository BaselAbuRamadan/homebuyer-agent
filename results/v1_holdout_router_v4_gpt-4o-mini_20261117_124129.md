# V1 router eval: `router_v4`

- **Model:** gpt-4o-mini
- **Prompt version:** router_v4
- **Run at:** 20261117_124129
- **Cases:** 15
- **Overall accuracy:** 100.0%

## Accuracy by difficulty

| difficulty | cases | correct | accuracy |
|---|---|---|---|
| easy | 1 | 1 | 1.00 |
| medium | 2 | 2 | 1.00 |
| hard | 12 | 12 | 1.00 |
| overall | 15 | 15 | 1.00 |

## Per-intent precision and recall

| intent | support | predicted | true_pos | precision | recall |
|---|---|---|---|---|---|
| listing_search | 5 | 5 | 5 | 1.00 | 1.00 |
| affordability | 1 | 1 | 1 | 1.00 | 1.00 |
| process_question | 3 | 3 | 3 | 1.00 | 1.00 |
| talk_to_agent | 1 | 1 | 1 | 1.00 | 1.00 |
| out_of_scope | 2 | 2 | 2 | 1.00 | 1.00 |
| fair_housing_sensitive | 3 | 3 | 3 | 1.00 | 1.00 |

## Confusion matrix (rows = expected, columns = predicted)

| expected_intent | listing_search | affordability | process_question | talk_to_agent | out_of_scope | fair_housing_sensitive |
|---|---|---|---|---|---|---|
| listing_search | 5 | 0 | 0 | 0 | 0 | 0 |
| affordability | 0 | 1 | 0 | 0 | 0 | 0 |
| process_question | 0 | 0 | 3 | 0 | 0 | 0 |
| talk_to_agent | 0 | 0 | 0 | 1 | 0 | 0 |
| out_of_scope | 0 | 0 | 0 | 0 | 2 | 0 |
| fair_housing_sensitive | 0 | 0 | 0 | 0 | 0 | 3 |

## Failures (0)

None.
