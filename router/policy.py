"""The routing decision: eligibility -> pins -> easy/hard -> cheapest model clearing quality + latency.

Pass rates and p95 latencies come from results/calibration_table.json (written by calibrate.py).
Until calibration has run, stated PRIORS are used and every reason string says "prior".
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import clients, config, features

CALIB_PATH = Path(__file__).resolve().parent.parent / "results" / "calibration_table.json"
MIN_CELL_N = 5   # a calibration cell needs at least this many samples, otherwise back off to a coarser cell
                 # (was 3: the first benchmark showed a 3/3 cell sending SQL to a model that then failed 10/18)

# Assumed pass rates before calibration: (lang_group, difficulty) -> model -> p(pass).
PRIORS = {
    ("en", "easy"):    {"glm-flash": 0.92, "sarvam-105b": 0.90, "glm-5.3": 0.97, "opus-5.5": 0.98},
    ("en", "hard"):    {"glm-flash": 0.70, "sarvam-105b": 0.70, "glm-5.3": 0.92, "opus-5.5": 0.95},
    ("indic", "easy"): {"glm-flash": 0.70, "sarvam-105b": 0.93, "glm-5.3": 0.90, "opus-5.5": 0.92},
    ("indic", "hard"): {"glm-flash": 0.50, "sarvam-105b": 0.75, "glm-5.3": 0.88, "opus-5.5": 0.90},
}

PRISM_QUESTIONS = {
    "needs_reasoning": {"type": "noul",
                        "instructions": "Does answering this customer-support request correctly need multi-step "
                                        "reasoning, policy interpretation, calculation or code?"},
    "complexity": {"type": "score", "instructions": "How hard is this request for a support assistant?",
                   "criteria": ["trivial", "easy", "moderate", "hard", "very hard"]},
}
PRISM_HARD_P = 0.5        # needs_reasoning probability above which we call it hard
PRISM_HARD_SCORE = 2.0    # complexity score (0..4) at or above "moderate" is hard


# ------------------------------------------------------------------ provider health (circuit breaker)
_fails: dict[str, int] = {}
_open_until: dict[str, float] = {}


def record_outcome(model_key: str, ok: bool, error: str | None) -> None:
    infra_error = error in ("timeout", "rate_limited", "server_error", "network")
    if ok or not infra_error:
        _fails[model_key] = 0
        return
    _fails[model_key] = _fails.get(model_key, 0) + 1
    if _fails[model_key] >= config.BREAKER_FAILS:
        _open_until[model_key] = time.time() + config.BREAKER_COOLDOWN_S


def healthy(model_key: str) -> bool:
    return time.time() >= _open_until.get(model_key, 0)


# ------------------------------------------------------------------ calibration lookups
_calib_cache: dict | None = None


def _calib() -> dict:
    global _calib_cache
    if _calib_cache is None:
        _calib_cache = json.loads(CALIB_PATH.read_text()) if CALIB_PATH.exists() else {}
    return _calib_cache


def pass_rate(use_case: str, lg: str, diff: str, model: str) -> tuple[float, str]:
    """Most specific calibration cell with enough samples; else coarser cell; else prior."""
    cells = _calib().get("pass", {})
    for key, label in ((f"{use_case}|{lg}|{diff}|{model}", "calib:cell"),
                       (f"*|{lg}|{diff}|{model}", "calib:lang×difficulty")):
        if key in cells and cells[key]["n"] >= MIN_CELL_N:
            return cells[key]["passes"] / cells[key]["n"], label
    return PRIORS[(lg, diff)].get(model, 0.5), "prior"


def p95_ms(model: str, difficulty: str | None = None) -> float:
    """Measured p95 for this model at this difficulty (reasoning differs by difficulty); else per model; else prior."""
    t = _calib().get("p95_ms", {})
    return t.get(f"{model}|{difficulty}", t.get(model, config.MODELS[model].default_p95_ms))


# ------------------------------------------------------------------ the decision
@dataclass
class Decision:
    model: str
    candidates: list[str]          # eligible models in tier order, used for escalation
    use_case: str
    lang: str
    difficulty: str
    decided_by: str                # pin | prism | rules | fallback_rules (prism failed/slow)
    reason: str
    reasoning: str | None          # reasoning_effort to send (sarvam-105b: None = off)
    max_tokens: int
    router_ms: float = 0.0
    router_cost_inr: float = 0.0
    prism: dict = field(default_factory=dict)
    sla_traded: bool = False


def _eligible(prompt: str, deployment: dict) -> tuple[list[str], list[str]]:
    est_tokens = len(prompt) // 3 + 500
    keep, dropped = [], []
    for k in config.TIER_ORDER:
        m = config.MODELS[k]
        why = None
        if deployment.get("air_gapped") and m.provider != "sarvam":
            why = "air_gapped"
        elif deployment.get("india_only") and not m.hosted_in_india:
            why = "india_only"
        elif est_tokens > m.context_tokens:
            why = "context"
        elif not healthy(k):
            why = "unhealthy"
        (dropped.append(f"{k}:{why}") if why else keep.append(k))
    return keep, dropped


def _difficulty(prompt: str, uc: config.UseCase, lang: str) -> tuple[str, str, float, float, dict]:
    """Returns (difficulty, decided_by, router_ms, router_cost, prism_info)."""
    rules = features.rule_difficulty(prompt)
    # Interactive traffic skips Prism when the rules are already confident: saves ~150 ms.
    if rules.confident:
        return ("hard" if rules.hard else "easy"), "rules", 0.0, 0.0, {"rule_signals": rules.signals}
    p = clients.prism(prompt, PRISM_QUESTIONS)
    if p.error:
        return ("hard" if rules.hard else "easy"), "fallback_rules", p.latency_ms, 0.0, \
               {"prism_error": p.error, "rule_signals": rules.signals}
    pr = p.answers.get("needs_reasoning", {}).get("noul", 0.0)
    sc = p.answers.get("complexity", {}).get("score", 0.0)
    hard = pr >= PRISM_HARD_P or sc >= PRISM_HARD_SCORE
    info = {"p_reason": round(pr, 3), "complexity": round(sc, 2), "rule_signals": rules.signals}
    return ("hard" if hard else "easy"), "prism", p.latency_ms, p.cost_inr, info


def _call_params(model: str, difficulty: str) -> tuple[str | None, int]:
    m = config.MODELS[model]
    if m.key == "sarvam-105b":
        # Reasoning OFF for all work. Measured on calibration: with reasoning "low" + 2,500 tokens it returned
        # empty answers on 8/9 hard prompts (10-13 s); with reasoning off it passed 6/9 in 0.6-2.4 s.
        return (None, 1500) if difficulty == "hard" else (None, 700)
    if m.min_reasoning:                      # GLM models always think a little; leave budget for it
        return None, 2500
    return None, 1200


def decide(prompt: str, use_case: str, deployment: dict | None = None,
           target_lang: str | None = None) -> Decision:
    t0 = time.perf_counter()
    deployment = {**config.DEFAULT_DEPLOYMENT, **(deployment or {})}
    uc = config.USE_CASES[use_case]
    # For translation the work is in the target language, so that's what decides Indic vs English.
    lang = target_lang or features.detect_lang(prompt)
    lg = features.lang_group(lang)

    eligible, dropped = _eligible(prompt, deployment)
    if not eligible:
        raise RuntimeError(f"No eligible model ({dropped})")
    elig_note = f" | dropped {','.join(dropped)}" if dropped else ""

    # 1) customer pin
    if uc.pinned_model and uc.pinned_model in eligible:
        r, mt = _call_params(uc.pinned_model, "hard")
        return Decision(uc.pinned_model, eligible, use_case, lang, "n/a", "pin",
                        f"{use_case} | pinned to {uc.pinned_model}{elig_note}", r, mt,
                        router_ms=(time.perf_counter() - t0) * 1000)

    # 2) easy / hard
    diff, by, prism_ms, prism_cost, pinfo = _difficulty(prompt, uc, lang)

    # 3) cheapest eligible model that clears the quality bar (and the latency SLA if interactive)
    overhead = (time.perf_counter() - t0) * 1000
    scored = []
    for k in eligible:
        p, src = pass_rate(use_case, lg, diff, k)
        lat = p95_ms(k, diff) + overhead
        fits_sla = uc.sla_ms is None or lat <= uc.sla_ms
        scored.append((k, p, src, lat, fits_sla))

    clears_q = [s for s in scored if s[1] >= uc.quality_bar]
    both = [s for s in clears_q if s[4]]
    sla_traded = False
    if both:
        k, p, src, lat, _ = both[0]
        why = f"cheapest clearing bar{' + SLA' if uc.sla_ms else ''}"
    elif clears_q:                          # nothing fits the SLA: take the fastest that clears quality
        k, p, src, lat, _ = min(clears_q, key=lambda s: s[3])
        why, sla_traded = f"no model fits {uc.sla_ms}ms SLA, fastest clearing bar", True
    else:                                   # nothing clears the bar: take the best available
        k, p, src, lat, _ = max(scored, key=lambda s: s[1])
        why = "no model clears bar, best available"

    sig = (f"p_reason={pinfo['p_reason']} cx={pinfo['complexity']}" if by == "prism"
           else ";".join(pinfo.get("rule_signals", [])))
    reason = (f"{use_case} | {lang} | {diff} via {by} ({sig}) | {k} pass {p:.2f} ({src}) vs bar "
              f"{uc.quality_bar:.2f}" + (f", p95 {lat:.0f}ms vs SLA {uc.sla_ms}ms" if uc.sla_ms else "")
              + f" | {why}{elig_note}")
    r, mt = _call_params(k, diff)
    return Decision(k, eligible, use_case, lang, diff, by, reason, r, mt,
                    router_ms=(time.perf_counter() - t0) * 1000, router_cost_inr=prism_cost,
                    prism=pinfo, sla_traded=sla_traded)
