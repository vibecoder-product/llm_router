"""Route one request: decide -> call -> check -> escalate (up only) -> one log row.

CLI:
  python -m router.router --use-case live_chat_reply "Mera order kab aayega?"
  python -m router.router --use-case catalogue_translate --target-lang hi "Cotton kurta, size M"
  python -m router.router --use-case live_chat_reply --force glm-flash "..."   # baseline mode, no routing/fallback
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import checks, clients, config, policy

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "requests.jsonl"
SAFE_REPLY = ("Sorry, we couldn't complete this right now. A support agent will follow up shortly. "
              "/ Maaf kijiye, abhi yeh poora nahi ho paya. Hamari team jaldi aapse sampark karegi.")


def _expected_lang(use_case: str, input_lang: str, target_lang: str | None) -> str | None:
    if use_case == "catalogue_translate":
        return target_lang
    if use_case == "live_chat_reply":
        return input_lang                     # reply in the customer's language
    return None                               # summaries/labels/JSON/SQL: language not checked


def build_user(prompt: str, context: str | None = None, target_lang: str | None = None) -> str:
    """`prompt` is the customer's own text: language and difficulty are judged on it alone.
    `context` (order data, policy snippet) is passed to the model but not to the router's classifier."""
    user = f"{context}\n\nCustomer message:\n{prompt}" if context else prompt
    return f"Target language: {target_lang}\n\n{user}" if target_lang else user


def handle(prompt: str, use_case: str, *, context: str | None = None, target_lang: str | None = None,
           deployment: dict | None = None,
           force_model: str | None = None, config_name: str = "router", log: bool = True,
           extra: dict | None = None, use_cache: bool | None = None,
           log_path: Path | None = None, log_prompt: bool = False) -> dict:
    uc = config.USE_CASES[use_case]
    user = build_user(prompt, context, target_lang)

    if force_model:                            # baselines: fixed model, no router overhead, no fallback
        d = policy.Decision(force_model, [force_model], use_case,
                            policy.features.detect_lang(prompt), "n/a", "baseline",
                            f"{config_name}: always {force_model}", *policy._call_params(force_model, "easy"))
    else:
        d = policy.decide(prompt, use_case, deployment, target_lang)

    expected = _expected_lang(use_case, d.lang, target_lang)
    attempts, model = [], d.model
    diff = d.difficulty if d.difficulty in ("easy", "hard") else "easy"
    while True:
        reasoning, max_tokens = ((d.reasoning, d.max_tokens) if model == d.model
                                 else policy._call_params(model, diff))
        r = clients.call_model(model, uc.system, user, max_tokens=max_tokens, timeout_s=uc.timeout_s,
                               reasoning=reasoning, use_cache=use_cache)
        ok, why = checks.check(r, expects_json=uc.expects_json, expected_lang=expected)
        policy.record_outcome(model, r.ok, r.error)
        m = config.MODELS[model]
        attempts.append({"model": model, "ok": ok, "check": why, "latency_ms": round(r.latency_ms),
                         "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                         "reasoning_tokens": r.reasoning_tokens, "cached": r.cached,
                         "cost_inr": round(m.cost_inr(r.tokens_in, r.tokens_out), 6), "text": r.text})
        if ok or force_model:
            break
        higher = [k for k in d.candidates if config.MODELS[k].tier > m.tier]
        if not higher or len(attempts) > config.MAX_ESCALATIONS:
            break
        model = higher[0]

    final = attempts[-1]
    answered = final["ok"]
    row = {
        "id": uuid.uuid4().hex[:10], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config_name, **(extra or {}),
        # off by default (customer prompts may hold PII); on for the synthetic benchmark
        **({"prompt": prompt} if log_prompt else {}),
        "use_case": use_case, "mode": uc.mode, "lang": d.lang, "difficulty": d.difficulty,
        "decided_by": d.decided_by, "reason": d.reason, "routed_model": d.model, "final_model": final["model"],
        "fallback_fired": len(attempts) > 1,
        "fallback_reason": " -> ".join(a["check"] for a in attempts[:-1]) or None,
        "final_check": final["check"], "answered": answered, "human_handoff": not answered,
        "sla_ms": uc.sla_ms, "sla_traded": d.sla_traded,
        "router_ms": round(d.router_ms, 1), "router_cost_inr": round(d.router_cost_inr, 6),
        "prism": d.prism,
        # totals include every attempt (fallbacks are paid for) plus the router's own overhead
        "tokens_in": sum(a["tokens_in"] for a in attempts),
        "tokens_out": sum(a["tokens_out"] for a in attempts),
        "cost_inr": round(sum(a["cost_inr"] for a in attempts) + d.router_cost_inr, 6),
        "latency_ms": round(sum(a["latency_ms"] for a in attempts) + d.router_ms),
        "attempts": [{k: v for k, v in a.items() if k != "text"} for a in attempts],
        "output": final["text"] if answered else SAFE_REPLY,
        "quality_score": None, "passed": None,     # filled in by the offline scorer
    }
    if log:
        path = log_path or LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Route one prompt.")
    ap.add_argument("prompt")
    ap.add_argument("--use-case", default="live_chat_reply", choices=list(config.USE_CASES))
    ap.add_argument("--target-lang", default=None, help="for catalogue_translate: hi | ta")
    ap.add_argument("--force", default=None, choices=list(config.MODELS), help="baseline: always this model")
    ap.add_argument("--india-only", action="store_true")
    ap.add_argument("--air-gapped", action="store_true")
    a = ap.parse_args()
    row = handle(a.prompt, a.use_case, target_lang=a.target_lang, force_model=a.force,
                 deployment={"india_only": a.india_only, "air_gapped": a.air_gapped}, config_name="cli")
    print(json.dumps({k: row[k] for k in ("reason", "routed_model", "final_model", "fallback_fired",
                                          "fallback_reason", "decided_by", "router_ms", "router_cost_inr",
                                          "tokens_in", "tokens_out", "cost_inr", "latency_ms", "attempts")},
                     ensure_ascii=False, indent=2))
    print("\nOUTPUT:\n" + row["output"])


if __name__ == "__main__":
    main()
