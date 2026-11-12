# Part 2: monthly cost to serve 50M input + 10M output tokens

| Configuration | Monthly cost | vs always-frontier |
|---|---|---|
| Always-cheapest (glm5.3-flash) | ₹1,125 | 11% |
| Always-frontier (glm5.3) | ₹10,200 | 100% |
| **Router (measured mix)** | **₹2,854** | **28%** |

**Router saves 72.0% vs always-frontier** (₹7,346/month).

Router cost breakdown (shares include tokens spent on attempts that later fell back):

| Model | share of input tokens | share of output tokens | ₹/month |
|---|---|---|---|
| glm-flash | 83.3% | 79.2% | ₹919 |
| sarvam-105b | 0.6% | 0.7% | ₹8 |
| glm-5.3 | 16.7% | 20.7% | ₹1,856 |
| Prism (router overhead) | - | - | ₹70 |

## Status-quo reference (not measured)

If the same customer sends everything to a closed frontier model (Claude Opus 5.5 at list price, $4/$20 per 1M at ₹88/$): **₹35,200/month**. The router configuration would be 91.9% cheaper than that, but we did not measure Opus quality on our test set, so this is a price comparison only.

## Sensitivity

| Scenario | Router ₹/month | Saving vs frontier |
|---|---|---|
| 10% of tokens need the frontier tier | ₹2,103 | 79% |
| 30% of tokens need the frontier tier | ₹3,918 | 62% |
| 50% of tokens need the frontier tier | ₹5,733 | 44% |

- **Tokenizer effect (not measured):** the brief's token counts are assumed identical on every model. In practice Indic text tokenises differently per model (Sarvam's tokenizer is built for Indian languages), so the same Hindi request can cost noticeably different token counts. A customer with heavy Indic traffic should be priced on measured tokens per request, not a blended assumption.
- **Reasoning tokens:** GLM models always reason a little (`low` is the floor). Those hidden tokens are billed as output, so real output volume on GLM-5.3 exceeds the visible text. The measured shares above already include them.
- **Assumptions:** list prices, no volume discounts, no prompt caching (cached input on Sarvam is ₹5/1M for sarvam-105b vs ₹15), same token count across models, router mix from 48 synthetic prompts x 3 runs.
