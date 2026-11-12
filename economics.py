"""Part 2: monthly cost to serve 50M input + 10M output tokens under each configuration.

Method (all assumptions printed):
  - List prices from router/config.py (Sarvam INR price list; Anthropic USD list at ₹88/$).
  - Same token counts on every model (the brief's numbers). Tokenizer differences are a sensitivity below.
  - Router mix = MEASURED share of tokens each model served in the benchmark router run, INCLUDING tokens
    burned on failed attempts that then fell back (so shares can sum to > 100%), plus Prism overhead
    measured as Prism input tokens per routed input token.
Run: python economics.py   (needs results/benchmark_scored.jsonl or benchmark_requests.jsonl)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from router import config

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "results" / "benchmark_requests.jsonl"
OUT = ROOT / "results" / "economics.md"
IN_M, OUT_M = 50.0, 10.0            # millions of tokens per month (from the brief)


def monthly(m: config.Model, in_m: float = IN_M, out_m: float = OUT_M) -> float:
    return in_m * m.in_per_m_inr + out_m * m.out_per_m_inr


def main() -> None:
    rows = [json.loads(l) for l in SRC.open()]
    r = [x for x in rows if x["config"] == "router"]
    # tokens of the attempt that produced the answer = the "useful" workload; everything else is overhead
    final_in = sum(x["attempts"][-1]["tokens_in"] for x in r)
    final_out = sum(x["attempts"][-1]["tokens_out"] for x in r)
    share = {}
    for k in config.TIER_ORDER:
        tin = sum(a["tokens_in"] for x in r for a in x["attempts"] if a["model"] == k)
        tout = sum(a["tokens_out"] for x in r for a in x["attempts"] if a["model"] == k)
        share[k] = (tin / final_in, tout / final_out)
    prism_cost_per_m_in = sum(x["router_cost_inr"] for x in r) / (final_in / 1e6)   # ₹ per 1M routed input tokens

    cheapest, frontier = config.MODELS[config.CHEAPEST], config.MODELS[config.FRONTIER]
    c_cheap, c_front = monthly(cheapest), monthly(frontier)
    parts = {k: IN_M * s_in * config.MODELS[k].in_per_m_inr + OUT_M * s_out * config.MODELS[k].out_per_m_inr
             for k, (s_in, s_out) in share.items()}
    c_prism = IN_M * prism_cost_per_m_in
    c_router = sum(parts.values()) + c_prism
    c_opus = monthly(config.REFERENCE_FRONTIER)

    L = ["# Part 2: monthly cost to serve 50M input + 10M output tokens\n",
         "| Configuration | Monthly cost | vs always-frontier |", "|---|---|---|",
         f"| Always-cheapest ({cheapest.model_id}) | ₹{c_cheap:,.0f} | {c_cheap / c_front:.0%} |",
         f"| Always-frontier ({frontier.model_id}) | ₹{c_front:,.0f} | 100% |",
         f"| **Router (measured mix)** | **₹{c_router:,.0f}** | **{c_router / c_front:.0%}** |",
         f"\n**Router saves {1 - c_router / c_front:.1%} vs always-frontier** "
         f"(₹{c_front - c_router:,.0f}/month).\n",
         "Router cost breakdown (shares include tokens spent on attempts that later fell back):\n",
         "| Model | share of input tokens | share of output tokens | ₹/month |", "|---|---|---|---|"]
    for k, (s_in, s_out) in share.items():
        L.append(f"| {k} | {s_in:.1%} | {s_out:.1%} | ₹{parts[k]:,.0f} |")
    L.append(f"| Prism (router overhead) | - | - | ₹{c_prism:,.0f} |")
    L += ["", "## Status-quo reference (not measured)\n",
          f"If the same customer sends everything to a closed frontier model (Claude Opus 5.5 at list price, "
          f"$4/$20 per 1M at ₹{config.USD_INR:.0f}/$): **₹{c_opus:,.0f}/month**. The router configuration would be "
          f"{1 - c_router / c_opus:.1%} cheaper than that, but we did not measure Opus quality on our test set, so "
          f"this is a price comparison only.\n",
          "## Sensitivity\n",
          "| Scenario | Router ₹/month | Saving vs frontier |", "|---|---|---|"]

    def scen(label: str, frontier_share: float):
        # keep the measured cheap-tier split, move a fixed share of tokens onto the frontier model
        cheap_keys = [k for k in share if k != config.FRONTIER]
        base = sum(share[k][0] for k in cheap_keys) or 1
        c = frontier_share * c_front + sum((1 - frontier_share) * share[k][0] / base * monthly(config.MODELS[k])
                                           for k in cheap_keys) + c_prism
        L.append(f"| {label} | ₹{c:,.0f} | {1 - c / c_front:.0%} |")

    for fs in (0.1, 0.3, 0.5):
        scen(f"{fs:.0%} of tokens need the frontier tier", fs)
    n_prompts = len({x["prompt_id"] for x in r})
    L += ["", "- **Tokenizer effect (not measured):** the brief's token counts are assumed identical on every model. "
              "In practice Indic text tokenises differently per model (Sarvam's tokenizer is built for Indian "
              "languages), so the same Hindi request can cost noticeably different token counts. A customer with "
              "heavy Indic traffic should be priced on measured tokens per request, not a blended assumption.",
          "- **Reasoning tokens:** GLM models always reason a little (`low` is the floor). Those hidden tokens "
          "are billed as output, so real output volume on GLM-5.3 exceeds the visible text. The measured shares "
          "above already include them.",
          "- **Assumptions:** list prices, no volume discounts, no prompt caching (cached input on Sarvam is "
          "₹5/1M for sarvam-105b vs ₹15), same token count across models, router mix from "
          f"{n_prompts} synthetic prompts x 3 runs."]
    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
