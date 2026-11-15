# V1 router eval: `router_v3`

- **Model:** gpt-4o-mini
- **Prompt version:** router_v3
- **Run at:** 20261115_142623
- **Cases:** 50
- **Overall accuracy:** 98.0%

## Accuracy by difficulty

| difficulty | cases | correct | accuracy |
|---|---|---|---|
| easy | 16 | 16 | 1.00 |
| medium | 11 | 11 | 1.00 |
| hard | 23 | 22 | 0.96 |
| overall | 50 | 49 | 0.98 |

## Per-intent precision and recall

| intent | support | predicted | true_pos | precision | recall |
|---|---|---|---|---|---|
| listing_search | 14 | 13 | 13 | 1.00 | 0.93 |
| affordability | 8 | 8 | 8 | 1.00 | 1.00 |
| process_question | 10 | 10 | 10 | 1.00 | 1.00 |
| talk_to_agent | 6 | 6 | 6 | 1.00 | 1.00 |
| out_of_scope | 6 | 6 | 6 | 1.00 | 1.00 |
| fair_housing_sensitive | 6 | 7 | 6 | 0.86 | 1.00 |

## Confusion matrix (rows = expected, columns = predicted)

| expected_intent | listing_search | affordability | process_question | talk_to_agent | out_of_scope | fair_housing_sensitive |
|---|---|---|---|---|---|---|
| listing_search | 13 | 0 | 0 | 0 | 0 | 1 |
| affordability | 0 | 8 | 0 | 0 | 0 | 0 |
| process_question | 0 | 0 | 10 | 0 | 0 | 0 |
| talk_to_agent | 0 | 0 | 0 | 6 | 0 | 0 |
| out_of_scope | 0 | 0 | 0 | 0 | 6 | 0 |
| fair_housing_sensitive | 0 | 0 | 0 | 0 | 0 | 6 |

## Failures (1)

| id | difficulty | expected_intent | predicted_intent | confidence | message | reasoning |
|---|---|---|---|---|---|---|
| R34 | hard | listing_search | fair_housing_sensitive | 0.90 | Don't show me anything in a MUD district, Texas taxes are mad enough | The user is expressing a preference to avoid a specific type of area based on their perception of taxes, which suggests coded steering away from certain neighborhoods. |
