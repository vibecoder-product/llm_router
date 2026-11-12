# Benchmark results

48 held-out prompts x 3 runs per config (432 requests). Cost/latency over all runs; quality weighted per prompt. Router totals include Prism + rule overhead and every fallback attempt.

## Headline

| config          | cost ₹ / 1k req   | cost vs frontier   | p50 ms   | p95 ms   |   quality (0-1) | pass rate   | pass: English   | pass: Indic   | pass: hard slice   | interactive within SLA   |   human handoffs |
|:----------------|:------------------|:-------------------|:---------|:---------|----------------:|:------------|:----------------|:--------------|:-------------------|:-------------------------|-----------------:|
| always_cheapest | ₹7.55             | 10%                | 878      | 1,812    |            0.92 | 91%         | 93%             | 86%           | 91%                | 100%                     |                0 |
| always_frontier | ₹73.56            | 100%               | 1,390    | 3,357    |            0.91 | 89%         | 87%             | 93%           | 79%                | 100%                     |                0 |
| router          | ₹19.50            | 27%                | 1,013    | 2,134    |            0.91 | 91%         | 92%             | 89%           | 87%                | 100%                     |                0 |

## Router internals

- Traffic split by answering model: {'glm-flash': 0.82, 'glm-5.3': 0.17, 'sarvam-105b': 0.01}
- Decided by: {'rules': 93, 'prism': 49, 'fallback_rules': 2}
- Fallback fired: 0.7% of requests ({'wrong_language(expected hinglish)': 1})
- Router overhead: mean 58 ms, p95 164 ms; cost ₹0.0435 of ₹2.8081 total (1.55%)
- SLA traded (no model fit the latency budget): 0

## Pass rate by use case

| uc                  |   always_cheapest |   always_frontier |   router |
|:--------------------|------------------:|------------------:|---------:|
| attr_extract        |              1    |              1    |     1    |
| catalogue_translate |              1    |              0.5  |     1    |
| chat_summary        |              0.86 |              0.71 |     0.86 |
| code                |              1    |              0.94 |     0.94 |
| live_chat_reply     |              0.78 |              1    |     0.89 |
| policy_dispute      |              0.85 |              0.89 |     0.78 |
| ticket_intent       |              1    |              1    |     1    |

## Cost per 1k requests by use case (₹)

| use_case            |   always_cheapest |   always_frontier |   router |
|:--------------------|------------------:|------------------:|---------:|
| attr_extract        |              3.67 |             43.5  |     4.33 |
| catalogue_translate |              5.74 |             56.94 |     6.16 |
| chat_summary        |              7.69 |             68.84 |    30.21 |
| code                |              8.43 |             81.04 |    75.89 |
| live_chat_reply     |              7.97 |             70.79 |     8.37 |
| policy_dispute      |             13.38 |            137.75 |    13.54 |
| ticket_intent       |              2.97 |             28.16 |     3.06 |

## Uncertainty (95% bootstrap CI over the 48 prompts)

| | pass rate [95% CI] |
|---|---|
| always_cheapest | 91% [83%, 98%] |
| always_frontier | 89% [81%, 97%] |
| router | 91% [83%, 98%] |
| router - cheapest | -0% [-8%, 8%] |
| router - frontier | 2% [-8%, 11%] |

A difference whose interval includes 0% is not distinguishable from noise at this sample size.

## Judge sensitivity

| config | pass rate (2-judge average, headline) | pass rate (GLM-5.3 judge only) |
|---|---|---|
| always_cheapest | 91% | 93% |
| always_frontier | 89% | 93% |
| router | 91% | 93% |

Judged outputs: 59. Judges within 2 points: 81%. Flagged for human review (>3 points apart): 9.
