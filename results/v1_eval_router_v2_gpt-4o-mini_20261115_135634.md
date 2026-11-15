# V1 router eval: `router_v2`

- **Model:** gpt-4o-mini
- **Prompt version:** router_v2
- **Run at:** 20261115_135634
- **Cases:** 40
- **Overall accuracy:** 100.0%

## Accuracy by difficulty

| difficulty | cases | correct | accuracy |
|---|---|---|---|
| easy | 16 | 16 | 1.00 |
| medium | 11 | 11 | 1.00 |
| hard | 13 | 13 | 1.00 |
| overall | 40 | 40 | 1.00 |

## Per-intent precision and recall

| intent | support | predicted | true_pos | precision | recall |
|---|---|---|---|---|---|
| listing_search | 11 | 11 | 11 | 1.00 | 1.00 |
| affordability | 6 | 6 | 6 | 1.00 | 1.00 |
| process_question | 9 | 9 | 9 | 1.00 | 1.00 |
| talk_to_agent | 5 | 5 | 5 | 1.00 | 1.00 |
| out_of_scope | 5 | 5 | 5 | 1.00 | 1.00 |
| fair_housing_sensitive | 4 | 4 | 4 | 1.00 | 1.00 |

## Confusion matrix (rows = expected, columns = predicted)

| expected_intent | listing_search | affordability | process_question | talk_to_agent | out_of_scope | fair_housing_sensitive |
|---|---|---|---|---|---|---|
| listing_search | 11 | 0 | 0 | 0 | 0 | 0 |
| affordability | 0 | 6 | 0 | 0 | 0 | 0 |
| process_question | 0 | 0 | 9 | 0 | 0 | 0 |
| talk_to_agent | 0 | 0 | 0 | 5 | 0 | 0 |
| out_of_scope | 0 | 0 | 0 | 0 | 5 | 0 |
| fair_housing_sensitive | 0 | 0 | 0 | 0 | 0 | 4 |

## Failures (0)

None.
