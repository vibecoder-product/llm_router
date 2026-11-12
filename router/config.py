"""Every assumption the router makes lives in this file.

Prices are public list prices checked in Nov 2026:
  - Sarvam: https://docs.sarvam.ai/api/getting-started/pricing (INR per 1M tokens)
  - Anthropic: https://platform.claude.com/docs/en/about-claude/pricing (USD per 1M tokens)
FX assumption: 1 USD = 88 INR.
"""
from __future__ import annotations

from dataclasses import dataclass, field

USD_INR = 88.0


@dataclass(frozen=True)
class Model:
    key: str                 # our short name, used in logs
    provider: str            # "sarvam" | "anthropic"
    model_id: str            # provider's model id
    tier: int                # 0 = cheapest; fallbacks only move to a higher tier
    in_per_m_inr: float      # INR per 1M input tokens
    out_per_m_inr: float     # INR per 1M output tokens
    context_tokens: int
    hosted_in_india: bool    # matters for the india_only / air_gapped eligibility rule
    default_p95_ms: int      # prior, overwritten by measured p95 after calibration
    api_path: str = ""       # Sarvam: own models on /v1, hosted open-weight (Token Factory) on /v2
    min_reasoning: str | None = None  # lowest reasoning level the model allows (GLM-5.3 always thinks; "low" is the floor)

    def cost_inr(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in / 1e6 * self.in_per_m_inr + tokens_out / 1e6 * self.out_per_m_inr


# All three routed models are served by the Sarvam platform behind one API key.
# Tier 0 and tier 1 cost about the same but differ on Indian languages, so the router makes a
# language-specialist decision there and a capability/cost decision between tier 1 and tier 2.
_ALL_MODELS: dict[str, Model] = {
    "glm-flash": Model("glm-flash", "sarvam", "glm5.3-flash", 0,
                       13.5, 45.0, 128_000, True, 2_500, "/v2/chat/completions", "low"),  # context assumed
    "sarvam-105b": Model("sarvam-105b", "sarvam", "sarvam-105b", 1,
                         15.0, 60.0, 128_000, True, 3_000, "/v1/chat/completions"),        # reasoning off
    "glm-5.3": Model("glm-5.3", "sarvam", "glm5.3", 2,
                     126.0, 390.0, 1_048_576, True, 6_000, "/v2/chat/completions", "low"),  # cannot disable thinking
    # Optional closed frontier tier: switched on automatically only if ANTHROPIC_API_KEY is set.
    "opus-5.5": Model("opus-5.5", "anthropic", "claude-opus-5-5", 3,
                      4.0 * USD_INR, 20.0 * USD_INR, 1_000_000, False, 8_000),
}


def _enabled(m: Model) -> bool:
    import os
    from dotenv import load_dotenv
    load_dotenv()
    env = {"sarvam": "SARVAM_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[m.provider]
    return bool(os.getenv(env))


MODELS: dict[str, Model] = {k: m for k, m in _ALL_MODELS.items() if _enabled(m)}
TIER_ORDER = sorted(MODELS, key=lambda k: MODELS[k].tier)
CHEAPEST = TIER_ORDER[0]
FRONTIER = TIER_ORDER[-1]

# Reference-only price for Part 2 economics: what the customer pays today if everything goes to a
# closed frontier model. Not called in the benchmark (no key), so its quality is not measured.
REFERENCE_FRONTIER = _ALL_MODELS["opus-5.5"]

# Router helper: Sarvam Prism returns probabilities, billed on input tokens only.
PRISM_IN_PER_M_INR = 4.0
PRISM_TIMEOUT_S = 0.4          # if Prism is slower than this, rules decide instead

# Provider health circuit breaker
BREAKER_FAILS = 3              # consecutive failures before a provider is skipped
BREAKER_COOLDOWN_S = 60

MAX_ESCALATIONS = 2            # fallback moves up at most this many tiers


@dataclass(frozen=True)
class UseCase:
    name: str
    mode: str                  # "interactive" (someone is waiting) | "batch"
    sla_ms: int | None         # p95 latency budget for interactive; None for batch
    quality_bar: float         # minimum calibrated pass rate a model must show
    timeout_s: float           # per-call timeout before falling back
    expects_json: bool = False
    pinned_model: str | None = None   # customer pin, skips the routing decision
    system: str = ""


SYS_SUPPORT = ("You are a customer-support assistant for an Indian e-commerce and quick-commerce app. "
               "Reply in the same language and script the customer used (English, Hinglish, Hindi or Tamil). "
               "Be concise, polite and never promise refunds, timelines or compensation that the policy does not allow.")

TICKET_LABELS = {
    "DELIVERY_STATUS": "where is my order, delivery delayed, stuck in transit / out for delivery",
    "REFUND_STATUS": "refund not received yet, asking when or how much refund will come",
    "RETURN_OR_EXCHANGE": "wants to return or exchange an item they received",
    "CANCEL_ORDER": "wants to cancel an order that has not been delivered",
    "DAMAGED_OR_WRONG_ITEM": "received a damaged, defective, wrong or missing item",
    "PAYMENT_ISSUE": "payment failed, charged twice, money debited but order not placed, UPI/card problems",
    "OTHER": "anything else (account, address change, feedback, invoice)",
}
TICKET_SYSTEM = ("Classify the customer message into exactly one label. If several apply, pick the one for the "
                 "action the customer needs first. Labels:\n"
                 + "\n".join(f"- {k}: {v}" for k, v in TICKET_LABELS.items())
                 + "\nAnswer with the label only.")
POLICY_SYSTEM = ("You are a refunds and returns specialist for an Indian e-commerce app. Apply the policy given "
                 "exactly. Show the key steps briefly. End with exactly one final line in this format:\n"
                 "DECISION: <FULL_REFUND|PARTIAL_REFUND|NO_REFUND|REPLACEMENT> AMOUNT: ₹<number>\n"
                 "(AMOUNT is the rupee amount to refund; use 0 for NO_REFUND or REPLACEMENT.)")

USE_CASES: dict[str, UseCase] = {
    "live_chat_reply": UseCase("live_chat_reply", "interactive", 4_000, 0.85, 10,
                               system=SYS_SUPPORT + " Keep the reply under 80 words."),
    "ticket_intent": UseCase("ticket_intent", "interactive", 2_000, 0.90, 8,
                             system=TICKET_SYSTEM),
    "policy_dispute": UseCase("policy_dispute", "interactive", 8_000, 0.85, 30,
                              system=POLICY_SYSTEM),
    "chat_summary": UseCase("chat_summary", "batch", None, 0.85, 30,
                            system="Summarise the support chat in English in at most 4 bullet points: issue, "
                                   "what the customer wants, what was promised, next action."),
    "attr_extract": UseCase("attr_extract", "batch", None, 0.90, 30, expects_json=True,
                            system="Extract the requested product attributes. Return only a JSON object, no prose. "
                                   "Use null for anything not stated."),
    "catalogue_translate": UseCase("catalogue_translate", "batch", None, 0.85, 30,
                                   system="Translate the product text into the target language given. Keep brand "
                                          "names, sizes and numbers unchanged. Return only the translation."),
    "code": UseCase("code", "batch", None, 0.85, 30,
                    system="Write a single SQLite query for the request. Return only the SQL, no explanation."),
}

# Deployment flags a customer sets once (eligibility layer).
DEFAULT_DEPLOYMENT = {
    "air_gapped": False,    # True => only models we can run on the customer's rack
    "india_only": False,    # True => data must not leave Indian hosting (e.g. DPDP / RBI-driven policy)
}
