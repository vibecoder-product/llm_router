# Model Router for the Sarvam Inference Platform

A router that sends each support request to the cheapest model that measurably handles it, and proves it with
real, logged API calls. Every model in this build runs on the Sarvam platform behind one API key, and every
model, including the router's own classifier, has open weights. So the whole stack can run inside a customer's VPC or
an air-gapped rack.

**Segment:** Indian e-commerce and quick-commerce customer support (text). **Test traffic:** 48 held-out
synthetic prompts, 46% Hinglish/Hindi/Tamil.

> **Result (48 held-out prompts × 3 runs, real calls):** the router cost **₹19.50 per 1,000 requests vs ₹73.56 for
> always-frontier (−73%)**, with the **same pass rate (91% vs 89%; within noise)** and a **lower p95 latency
> (2.1 s vs 3.4 s)**. The honest catch is that always-cheapest also scored 91% at ₹7.55. On this workload a ₹13.5/1M model
> matched a ₹126/1M one, and the extra the router spent on the expensive tier (SQL, hard summaries) bought no
> measurable quality on our test set. Monthly cost for 50M in / 10M out: **₹1,125 / ₹10,200 / ₹2,854, so the router
> saves 72.0%** against always-frontier (Part 2).

---

## Quick start

```bash
git clone https://github.com/vibecoder-product/llm_router.git && cd llm_router
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env            # add SARVAM_API_KEY (₹100 free credit covers everything here)

.venv/bin/python -m router.router --use-case live_chat_reply "Bhai mera order kab aayega?"   # route one prompt
.venv/bin/uvicorn app:app --port 8000                                                         # HTTP service: POST /route
.venv/bin/python -m eval.build_prompts      # regenerate the test set (deterministic)
.venv/bin/python calibrate.py               # measure every model on the 30 calibration prompts
.venv/bin/python run_benchmark.py run       # 48 held-out prompts x 3 configs x 3 runs (cache off)
.venv/bin/python run_benchmark.py score && .venv/bin/python run_benchmark.py summary
.venv/bin/python economics.py               # Part 2 numbers from the measured mix
```

Credit guards: every paid call is written to `logs/spend.jsonl`, each run stops at `SPEND_CAP_INR` (₹20
by default), and identical development calls are served from a local cache. The benchmark turns the cache
off so latencies are real. The whole project cost **about ₹32** of Sarvam credit.

## Stack

| Piece | What it is |
|---|---|
| Language | Python 3.11, `httpx`, `pandas`, FastAPI. No LLM framework |
| Models (routed) | `glm5.3-flash` (tier 0), `sarvam-105b` (tier 1), `glm5.3` (tier 2), all on the Sarvam API |
| Router classifier | `sarvam-prism`: Sarvam's calibrated decision model. It returns probabilities, not text, at ₹4/1M input tokens |
| Judges (offline only) | GLM-5.3 and Sarvam 105B, averaged |
| Optional tier 3 | Claude Opus 5.5 turns on automatically if `ANTHROPIC_API_KEY` is set. It wasn't used here |

| Model | ₹ / 1M in | ₹ / 1M out | Measured p50 / p95 latency | Profile |
|---|---|---|---|---|
| `glm5.3-flash` (tier 0) | 13.5 | 45 | easy 0.8 / 1.6 s · hard 1.0 / 1.7 s | Cheapest, and the best all-rounder on calibration: 100% easy, 89% hard. Failed the window-function SQL |
| `sarvam-105b` (tier 1) | 15 | 60 | easy **0.4 / 0.8 s** · hard 1.3 / 2.2 s | **Fastest**, and 100% on SQL including the query glm-flash failed. Weaker at following chat instructions (invented details, transliterated brand names). Reasoning must be off; see trade-offs |
| `glm5.3` (tier 2) | 126 | 390 | easy 1.3 / 2.5 s · hard 1.9 / 3.3 s | 30/30 on calibration, at 9× the price. Always reasons (`low` is the minimum), and it's the slowest |

Prices are Sarvam's public list prices (Nov 2026). They are all in [router/config.py](router/config.py), alongside every
other assumption.

**Why these three.** Two of them, glm-flash and Sarvam 105B, cost almost the same, so they don't give the
router a real cost choice. They are there because they differ in *behaviour*: which languages they handle well,
how fast they are, and how they fail. The cost choice is between those two and GLM-5.3, which is about 9× the price. I'd rather say
that up front than pretend there are three price points. Closed frontier models (Claude, GPT) aren't available on
Sarvam's platform. Kimi K3.1 Pro and DeepSeek V4 Pro need provisioned throughput, which this account doesn't have. So the
"always-frontier" baseline is the strongest open-weight model available. Against a closed frontier model at list price
the savings would be larger (see Part 2).

**What the data then decided.** Calibration routed ~82% of traffic to glm-flash and ~17% to GLM-5.3 (SQL and hard
summaries). Sarvam 105B ended up with about 1%, mostly as a fallback when glm-flash answered a Hinglish customer in
English. That's awkward for Sarvam, since its own model earns the highest margin. But it is also the best evidence that the router
picks by measured quality rather than by who owns the model (see Q5).

## Routing policy, in one paragraph

Each request carries a `use_case` tag (the calling app knows whether it is a live chat or a catalogue job). The
router then goes through five steps:

1. **Eligibility.** It drops models the request can't use: a model the customer's deployment can't reach (`air_gapped`,
   `india_only`), a context window that's too small, or a provider that has failed three times in a row (skipped for 60 seconds).
2. **Pins.** It applies any customer pin, for example "always use the strongest model for X".
3. **Easy or hard.** It decides from free rules: length, how many numbers are present, keywords in English and
   romanised Hindi, and code markers. Only when the rules are unsure does it ask **Sarvam Prism** one question:
   how likely the request is to need multi-step reasoning, and how complex it is. That call takes about 150 ms, costs about ₹0.0005, and works in
   any language.
4. **Pick.** It takes the cheapest eligible model whose *measured* pass rate on the calibration set, for that use
   case, language group and difficulty, clears the use case's quality bar. For interactive use cases the model's
   measured p95 latency plus the router's own overhead must also fit the use case's latency SLA.
5. **Check and fall back.** After the answer comes back, free checks look for errors, timeouts, refusals, empty or
   truncated output, broken JSON and the wrong language or script. Any failure escalates one tier, up to twice and
   never down, and every attempt is paid for in the totals.

Every log row carries the reason in words, for example
(real rows from the benchmark):

```
live_chat_reply | hinglish | easy via rules (short, no hard signals) | glm-flash pass 1.00 (calib:lang×difficulty) vs bar 0.85, p95 1606ms vs SLA 4000ms | cheapest clearing bar + SLA
code | en | hard via prism (p_reason=0.895 cx=2.14) | glm-5.3 pass 1.00 (calib:cell) vs bar 0.85 | cheapest clearing bar
```

| Use case | Mode | Latency SLA (p95) | Quality bar | How quality is scored |
|---|---|---|---|---|
| `live_chat_reply` | interactive | 4 s | 0.85 | 2 judges against facts from the order context + language gate |
| `ticket_intent` | interactive | 2 s | 0.90 | exact label |
| `policy_dispute` | interactive | 8 s | 0.85 | decision label + rupee amount, computed by code from the policy |
| `chat_summary` | batch | none | 0.85 | 2 judges against required facts / forbidden claims |
| `attr_extract` | batch | none | 0.90 | JSON field match |
| `catalogue_translate` | batch | none | 0.85 | 2 judges + script check + numbers/brands preserved |
| `code` (SQL) | batch | none | 0.85 | **executed** on a synthetic orders DB, result sets compared |

**What happens on a timeout or a refusal.** A timeout is set per use case (8–30 s), and when it fires the router
retries on the next tier up. A refusal (the provider's own refusal signal, or refusal phrasing in English or Hindi) also escalates. Rate
limits and 5xx errors escalate and count towards the circuit breaker. If every eligible tier fails, the customer gets a
safe bilingual holding reply ("an agent will follow up"), and the row is marked `human_handoff: true`. We tested a forced
timeout: it escalated through all three tiers, then handed off at ₹0, because failed calls aren't billed.

## Per-request logging

One JSON line per request (`logs/requests.jsonl`; the benchmark writes `results/benchmark_requests.jsonl`):

| Asked for | Field |
|---|---|
| Route chosen and why | `routed_model`, `reason`, `decided_by` (rules / prism / pin / baseline), `difficulty`, `lang`, `prism` probabilities |
| Model | `routed_model` vs `final_model` (after any fallback) |
| Tokens | `tokens_in`, `tokens_out`; per attempt also `reasoning_tokens` (hidden thinking, billed as output) |
| Cost | `cost_inr` = all attempts + router; `router_cost_inr` separately |
| Latency | `latency_ms` = all attempts + router; `router_ms` separately |
| Quality score | `quality_score`, `passed` (written by the offline scorer) |
| Fallback | `fallback_fired`, `fallback_reason` (e.g. `wrong_language(expected hinglish)`), `attempts[]` with each try |
| Outcome | `final_check`, `answered`, `human_handoff`, `sla_ms`, `sla_traded` |

The router's own cost and latency (rules plus Prism) are reported separately *and* included in every total.

## Results: baselines vs router

Run with `python run_benchmark.py run|score|summary`. Full tables are in [results/summary.md](results/summary.md), and every
request is in [results/benchmark_scored.jsonl](results/benchmark_scored.jsonl). There are 48 held-out prompts × 3 runs per config, with the
cache off. Quality is weighted per prompt. Router totals include Prism, rule time and every fallback attempt.

| Config | ₹ / 1k requests | vs frontier | p50 | **p95** | Quality (0–1) | **Pass rate [95% CI]** | English | Indic | Hard slice |
|---|---|---|---|---|---|---|---|---|---|
| Always-cheapest (glm-flash) | ₹7.55 | 10% | 0.88 s | 1.81 s | 0.92 | 91% [83, 98] | 93% | 86% | 91% |
| Always-frontier (GLM-5.3) | ₹73.56 | 100% | 1.39 s | 3.36 s | 0.91 | 89% [81, 97] | 87% | 93% | 79% |
| **Router** | **₹19.50** | **27%** | 1.01 s | 2.13 s | 0.91 | **91% [83, 98]** | 92% | 89% | 87% |

- **Router internals.** Traffic went 82% to glm-flash, 17% to GLM-5.3 and 1% to Sarvam 105B. Rules decided 65% of requests and Prism 34%.
  Prism timed out twice (400 ms budget) and the rules took over. Router overhead averaged **58 ms (p95 164 ms) and 1.6%
  of cost**. Fallback fired on 0.7% of requests: glm-flash answered a Hinglish customer in English, the language check
  caught it, and Sarvam 105B answered instead (+0.7 s). No request was handed to a human, and every interactive request met its SLA.
- **Where the router paid more and why.** SQL went to GLM-5.3 because, on 9 calibration SQL prompts, glm-flash
  passed 6/9 and Sarvam 105B 7/9, both under the 0.85 bar. On held-out data glm-flash passed every SQL run. That ₹8 →
  ₹76 per 1k on SQL is the router's insurance premium, and our test set can't show that it paid off.
- **Noise is large.** Router and always-cheapest used the *same* model for refunds and live chat, yet differ by
  about 10 points on those use cases. The 95% CIs are about ±8 points, and the router-minus-baseline differences all include 0.
- **The judge choice doesn't change the conclusion.** With GLM-5.3 as the only judge, all three configs score 93%. The two judges agreed
  within 2 points on 81% of the 59 judged outputs. Nine were more than 3 points apart and are flagged for human review.
- **Frontier isn't automatically better.** GLM-5.3 lost points by transliterating brand names ("Philips",
  "Aashirvaad") into Devanagari and Tamil script, against the instruction to keep them unchanged.

### What this means commercially
For this kind of traffic (support chat, tagging, extraction, translation, policy arithmetic), the frontier tier is
mostly unnecessary. **The 73% saving comes from not over-buying.** A well-chosen cheap model gets most of it on its own.
The router earns its place by making that choice **per request and per use case from measured data**, catching visible
failures (wrong language), keeping a costlier tier for the slices where calibration says the cheap model isn't safe,
and giving the customer the knobs (bars, SLAs, pins) to decide how much insurance to buy.


## What our quality measure does not capture

- **Tone, empathy and brand voice**, beyond what a judge's 0–10 score absorbs.
- **Whether the customer's problem actually got resolved**, CSAT, repeat contacts or refunds paid wrongly. These are the business
  outcomes; we only measure outputs.
- **Invented facts the judges miss.** The judges compare answers with the order context, but a plausible invention can still slip through.
  We saw both judges disagree with each other, and one confidently misread Tamil script.
- **Indic quality beyond the judges.** The person running this reads English only, so Hindi and Tamil quality
  rests on script checks plus two model judges. There was no native-speaker review.
- **Real traffic.** The prompts are synthetic, so they have no ASR noise, typos, abusive messages, very long histories or real
  order systems. With 48 prompts, one prompt moves a pass rate by about 2 points.
- **Time to first token.** We don't stream, so latency is the full response time, while chat users feel time to
  first token.
- **Drift.** It is a single snapshot. Model updates, prompt changes and seasonal traffic aren't covered.
- **Judged use cases are scored on run 1 only**, to save credit. The other use cases are scored on every run.
- **Synthetic data limits.** In the synthetic orders DB every pincode has ≥50 orders, so one SQL condition can't change the
  answer. Keyword rules misfire too: "Supervisor (join**ing**)" matched the SQL keyword "join".
- **Silent failures.** The fallback layer caught one failure out of 144. Every other failure (wrong SQL, invented promises such as
  "the rider will have change") was fluent and passed the post-answer checks. That's the case for an answer verifier
  (see the roadmap).

## Trade-offs considered and dropped

| Option | Why dropped |
|---|---|
| Always cascade (cheap first, escalate if unhappy) | It doubles latency and cost on exactly the hard requests, and interactive chat can't absorb that. We escalate only on *visible* failures |
| Learned router (RouteLLM-style, embeddings plus kNN) | It needs thousands of labelled preferences we don't have, and it's harder to explain per request. It's the v3 path once production logs exist |
| An LLM generating the route | It's slow (hundreds of ms), it costs output tokens, and its confidence isn't calibrated. Prism is built for exactly this decision |
| Prism on every request | Rules are free and decide most requests confidently. Prism runs only when they're unsure, which saves about 150 ms on interactive traffic |
| An expected-cost objective (token cost + P(fail) × cost of a wrong answer) | It's better in theory, and it gives the customer a contract knob ("a wrong refund decision costs ₹500"). But it's harder to explain in one paragraph. This is the v2 we'd build with a customer |
| A Prism answer verifier and shadow sampling to the frontier tier | They would catch silent wrong answers and measure drift. They're on the roadmap, not built, because they add latency and the benchmark couldn't prove their value |
| Taking the lower score of the two judges | It was meant to stop a judge favouring its own family. Calibration showed one judge hallucinating a script error on correct Tamil, so with min one judge's mistake decided the score. We switched to the mean and flag disagreements for review |
| Reasoning on for Sarvam 105B on hard work | With `reasoning_effort=low` and a 2,500-token budget, it spent the whole budget thinking and returned **empty answers** on 8 of 9 hard calibration prompts (10–13 s each). With reasoning off it passed **6/9 in 0.6–2.4 s**. The reasoning setting changed this model's quality on hard work more than any routing decision did. GLM models can't switch reasoning off, and leaving the parameter out means *maximum* reasoning, so we force `low` |
| A hosted observability platform (Braintrust etc.) for the logs | Reviewers can read JSONL without a login, and it doesn't assume data can leave the customer's network. A Braintrust exporter is a planned add-on |
| Voice | It's out of scope. The brief lists voice as a workload, but Part 1 doesn't require audio. Voice would plug in as STT → router → TTS, with the LLM step pinned to the fastest Indic model under a turn budget of about 1.5 s |
| Session stickiness for multi-turn chat | The test set is single-turn. In production you'd keep a conversation on one model (consistent voice, prompt cache) unless it escalates |

## How we learned from Cursor and Ramp

- **Cursor Router** runs a per-request classifier on task type and complexity, and lets admins pick Cost / Balance /
  Intelligence modes and allow or deny models. We took two things from it: a cheap classifier on the hot path, and
  *customer-owned knobs*. Ours are the per-use-case quality bars, latency SLAs, pins and deployment flags in config.
- **Ramp Router** sends each request to the cheapest *approved* model that clears a quality bar, with failure-aware
  fallback and latency monitoring. That is our core rule. Its reported savings (around 26–40%) also set our
  expectations: a router that claims 90% should show the traffic mix behind the number.
- **Where we differ:** both are SaaS gateways in front of closed frontier models. Here, the cheap tier, the Indic tier and
  the router's brain are all Sarvam's own open-weight models, so the router can run where the data has to stay.

## Running this inside a customer VPC or an air-gapped deployment

- **Same code, different endpoints.** `SARVAM_BASE_URL` points at in-cluster model servers. Sarvam 105B, GLM-5.3,
  GLM-5.3 Flash and Prism all have open weights. Prism is a LoRA on Sarvam 105B and fits on one ≥120 GB GPU in FP8,
  so it can share the 105B deployment.
- **The router is stateless and cheap.** It's a FastAPI container ([app.py](app.py)) that scales horizontally behind the
  customer's load balancer. The circuit-breaker state is per pod; at scale it moves to Redis.
- **The eligibility layer is the compliance story.** `air_gapped` and `india_only` flags (per tenant or per request)
  remove any model that would send data outside, before routing happens. A closed frontier tier simply doesn't exist
  in an air-gapped config, and the router degrades gracefully to the best local tier.
- **Logs stay in their network.** The JSONL rows map onto OpenTelemetry GenAI spans, which can go into the customer's own stack or a
  self-hosted Langfuse. Prompts aren't logged by default (`log_prompt=False`) because of personal data.
- **Calibration runs on their data.** `calibrate.py` runs on a golden set the customer signs off. That golden set is
  how we get "numbers their team trusts", and re-running it after any model update is the drift guard.
- **Capacity.** Routing shifts load towards the small models, so the GPU plan changes too. Most of the QPS lands on
  the cheap tier, while the expensive tier is sized for the hard slice plus fallback headroom.

## Assumptions and notes on the brief

- **Q6 is missing from the brief**, which lists questions 1–5, 7 and 8 but says "eight". I answered all seven listed and added a Q6 of
  my own (what to measure in the first 30 days).
- The brief says both "1 week" and "24-hour window". It changed nothing here.
- "50M input tokens" doesn't say on whose tokenizer, so I assumed the same count on every model. See the Part 2 sensitivity.
- All prompts are synthetic, written for this assignment (drafted with Claude). Indic prompts carry English glosses in
  `eval/prompts.jsonl`.
- **The test set changed once, before any held-out result existed.** The first calibration showed the cheapest model
  passing 24 of 25 prompts, because our "hard" items weren't hard for it. We added 5 harder calibration and 8 harder
  held-out prompts (multi-rule refunds with timing traps, window-function SQL, chats where the agent corrects
  themselves, messy listings) *before* running the held-out benchmark.
- **The router was changed once after a held-out run, and this is disclosed so the numbers can be judged fairly.** The first
  run sent SQL to Sarvam 105B on the strength of a 3/3 calibration cell, and it failed 10 of 18 held-out SQL runs. We
  raised the minimum calibration-cell size from 3 to 5 and added 6 SQL prompts to the *calibration* split (none to
  held-out), then re-ran only the router config. Because the change was prompted by held-out results, treat the
  router's held-out numbers as slightly optimistic. The baselines were not re-run.

## Part 2: The economics (50M input + 10M output tokens a month)

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

### Status-quo reference (not measured)

If the same customer sends everything to a closed frontier model (Claude Opus 5.5 at list price, $4/$20 per 1M at ₹88/$): **₹35,200/month**. The router configuration would be 91.9% cheaper than that, but we did not measure Opus quality on our test set, so this is a price comparison only.

### Sensitivity

| Scenario | Router ₹/month | Saving vs frontier |
|---|---|---|
| 10% of tokens need the frontier tier | ₹2,103 | 79% |
| 30% of tokens need the frontier tier | ₹3,918 | 62% |
| 50% of tokens need the frontier tier | ₹5,733 | 44% |

- **Tokenizer effect (not measured):** the brief's token counts are assumed identical on every model. In practice Indic text tokenises differently per model (Sarvam's tokenizer is built for Indian languages), so the same Hindi request can cost noticeably different token counts. A customer with heavy Indic traffic should be priced on measured tokens per request, not a blended assumption.
- **Reasoning tokens:** GLM models always reason a little (`low` is the floor). Those hidden tokens are billed as output, so real output volume on GLM-5.3 exceeds the visible text. The measured shares above already include them.
- **Assumptions:** list prices, no volume discounts, no prompt caching (cached input on Sarvam is ₹5/1M for sarvam-105b vs ₹15), same token count across models, router mix from 48 synthetic prompts x 3 runs.

**The four numbers:** always-cheapest **₹1,125**, always-frontier **₹10,200**, router **₹2,854** per month, a
**72.0% saving** against always-frontier.

**Scale check.** At list prices this customer is small: ₹2,854–₹35,200 a month. A ₹2 crore-a-year account is about ₹16.7
lakh a month, roughly 475× the Opus figure. Accounts that size come from volume plus deployment (VPC or on-prem capacity), not
from per-token margin on 60M tokens.


## Part 3: Business questions

**1. Pricing a ₹2 crore/year BFSI account. My pick: a platform subscription, an annual commit with included capacity.**
A bank budgets annually, its procurement and RBI outsourcing reviews prefer a predictable fixed fee, and a sovereign or VPC deployment
is mostly fixed cost to us (GPUs, support), so a commitment matches our cost structure. Within the commitment, routing
savings become *headroom*: the bank runs more workloads (100% call QA instead of 2% sampling) for the same fee,
instead of seeing its bill and our revenue shrink. Usage above the included capacity is billed at published per-model rates. I'd reject
a blended per-token rate (it hides the mix, and our margin breaks if the mix moves to frontier), pure pass-through (it puts our revenue in a race
against our own router) and outcome pricing (bank outcomes are hard to attribute, and legal teams resist it).

**2. Routing shrinks the tokens we bill. Build it anyway.** Be honest about the maths first. In our numbers this customer goes
from ₹10,200 to ₹2,854 a month. If the status quo was Opus pass-through at a ~10% margin (₹3,520 gross profit), routed
open-weight at an assumed ~60% margin gives about ₹1,700. So at flat volume, routing *cuts* gross profit. We build it anyway because
(a) routing is being given away (Ramp's router is free), so customers will route; the only question is whether it happens on our
platform. (b) Cheaper inference creates volume: we need about 2× usage to break even, and 100% QA, catalogue translation and
backfills easily get there. (c) It moves workloads off foreign pass-through models onto models we host. (d) Paired with
commit pricing (Q1), the savings become usage, not churn.

**3. 55% saving, +120 ms at p95, −3% quality on the hardest tenth. Who is it wrong for?** It's wrong for real-time voice agents,
where 120 ms is a big slice of a ~1 s turn budget. It's wrong for real-time fraud or UPI risk scoring with hard SLAs. And it's wrong for anyone whose hardest 10% *is* their value:
credit decisions, regulatory notices, high-value disputes, wealth advice. The same routing is right for summaries, tagging and
translation. **What goes in the contract:**
- quality floors per use case, measured on the *customer's own* golden set (hard slice ≥ frontier − 1 pt)
- named critical intents pinned to frontier
- p95 latency SLOs per workload
- 2–4 weeks in shadow mode before cutover
- automatic rollback when a floor is breached, plus service credits
- a monthly audit sample, and a share of the savings

In our own run the trade-off went the other way: p95 fell from 3.4 s to 2.1 s, and the hard slice scored 87% vs 79%.
But that's 48 prompts, and I'd still contract as above.

**4. "We'll just send everything to the frontier model and eat the cost."**
*Three sentences:* "On our support benchmark, always-frontier cost about 4× more than routing (₹73.56 vs ₹19.50 per 1,000 requests),
was 1.2 s slower at p95, and scored no better (89% vs 91%), so for most of your traffic you're paying for latency, not
quality. You don't have to trust our numbers: we'll shadow a week of your real traffic, score both paths on your
own golden set, and you choose workload by workload. Anything you're not comfortable with stays pinned to the frontier
model, so the downside is zero." *First discovery question:* "Which single workload is the biggest line on your inference bill, and how
do you measure its quality today?"

**5. OpenRouter, Not Diamond, Martian, the hyperscalers. Where Sarvam wins and loses, structurally.**
*Wins:*
- We own the cheap tier and the Indic tier, so routing pushes volume onto models we host and tune. Router failures become
  training data for those models.
- Sovereign, VPC and air-gapped deployment. The whole stack in this repo, including the router's classifier (Prism), runs offline on open
  weights. SaaS routers can't follow the data into a bank's rack.
- DPDP and RBI data residency, INR billing, Indic evaluation sets and local support.

*Loses:*
- Model breadth: closed frontier models aren't on our platform.
- **Perceived neutrality.** We have a motive to route to our own models. Our own benchmark sent about 1% to Sarvam 105B, and
  publishing that kind of audit log is the answer.
- Developer reach and ecosystem.
- Hyperscaler credits and marketplace procurement.
- Learned routers trained on far more traffic than ours (Not Diamond, Martian).
- English-only workloads, where we have no edge.

**6. (Missing from the brief; my own.) What would you measure in the first 30 days after go-live?**
- **Weekly, per use case:** golden-set pass rate, split by language and on the "VIP" slice.
- **Per request:** fallback rate, human-handoff rate, router overhead, judge-disagreement rate.
- **Spend:** traffic share by tier and ₹ per 1,000 requests against the frontier counterfactual. A 2% shadow sample goes to frontier so
  there is a live comparison.
- **The customer's own KPIs:** CSAT, repeat contacts within 48 hours, average handle time and wrong-refund rate.

Model and prompt changes ship only after a golden-set regression. The success criterion is agreed up front: equal KPIs at a
lower cost per contact.

**7. Segment: Indian e-commerce / quick-commerce support.**
*First workload:* ticket intent tagging plus post-chat summaries. It's offline, very high volume, Hinglish-heavy and low risk:
a wrong tag costs an agent a few seconds, not a refund.

*Proof by the end of week two*, from a shadow run on one week of real tickets inside their cloud:
- agreement with agents' dispositions of at least 90%
- QA acceptance of at least 90% on 200 sampled summaries
- Indic quality on par with English
- cost per 1,000 tickets against their current bill
- zero data leaving their network

*From pilot to ₹10 crore run-rate (₹83 lakh a month):*
1. **Live chat assist.** Text alone is roughly 150M routed calls a month at about ₹0.02 each, or around ₹30 lakh a month.
2. **Voice.** NDR and COD-confirmation calls: 10M minutes at an assumed ₹1–1.5/min all-in (STT is ₹0.49/min list).
3. **Vernacular catalogue translation.**
4. **A dedicated VPC deployment fee.**

The volumes are hypothetical, but the shape holds: text proves quality, and voice plus deployment builds the run-rate.

**8. Six months in, quality quietly drops on the customer's most valuable 5% of queries, and their users notice first.**
- **Today:** pin that slice to the top tier. It's a config change that takes effect in minutes. Tell the customer before they escalate, with the logs
  showing what changed, and credit them.
- **This week:** find the root cause (a model or provider update, a prompt change, a shift in the traffic mix, judge drift) and add the
  failing cases to their golden set. Recalibrate, and only un-pin once the slice clears its floor again.
- **Make it structural, so they don't churn:**
  - tag the top 5% with the customer (high-value orders, VIP customers, escalation-prone intents)
  - give that slice its own quality monitor, with a higher judge-sampling rate and a 2–5% shadow sample to frontier
  - alert on drift in fallback rate, handoff rate and CSAT
  - no model update without a regression run on that slice
  - an in-product "bad answer" button that feeds the eval set
  - a contracted quality floor on the slice, with service credits

  Users noticing first means our monitoring was looking at averages, so the fix is to monitor the slice they value.

## Roadmap (not built)
- **Expected-cost routing:** choose by token cost + P(fail) × the customer's stated cost of a wrong answer, which is the contract knob from Q3.
- **A Prism answer verifier** on the uncertain band, aimed at the silent failures this benchmark found.
- **Shadow sampling to the frontier tier, plus weekly recalibration.** That is the drift guard from Q8.
- **Calibration that doesn't trust thin cells.** Use shrinkage towards the coarser cell rather than a hard minimum *n*, and grow the
  golden set from production logs.
- **A Braintrust or Langfuse exporter** for the logs, and **session stickiness** for multi-turn chat.

