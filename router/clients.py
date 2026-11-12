"""Thin HTTP clients for Sarvam (chat + Prism) and Anthropic.

Every call returns a CallResult with measured wall-clock latency, token counts
from the provider's usage block, and a normalised error / refusal signal.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

from . import config

load_dotenv()

# ---------------------------------------------------------------- credit guards
ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "logs" / "spend.jsonl"
CACHE_DIR = ROOT / "logs" / "cache"
SPEND_CAP_INR = float(os.getenv("SPEND_CAP_INR", "20"))
USE_CACHE = os.getenv("USE_CACHE", "1") == "1"   # benchmark sets this to 0 so latency is real
_spent_this_run = 0.0


class BudgetExceeded(RuntimeError):
    pass


def _charge(provider: str, model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    global _spent_this_run
    _spent_this_run += cost
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "provider": provider, "model": model,
                            "in": tokens_in, "out": tokens_out, "cost_inr": round(cost, 6)}) + "\n")


def _check_budget() -> None:
    if _spent_this_run >= SPEND_CAP_INR:
        raise BudgetExceeded(f"Spend cap ₹{SPEND_CAP_INR} reached this run (₹{_spent_this_run:.2f}). "
                             f"Raise SPEND_CAP_INR in .env if intended.")


def total_spend_inr() -> dict:
    """Cumulative spend across all runs, by provider, from the ledger."""
    out: dict[str, float] = {}
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            row = json.loads(line)
            out[row["provider"]] = out.get(row["provider"], 0.0) + row["cost_inr"]
    return out


def _cache_path(*parts) -> Path:
    h = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return CACHE_DIR / f"{h}.json"

SARVAM_BASE = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_http = httpx.Client(timeout=60)


@dataclass
class CallResult:
    model: str
    text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_estimated: bool = False
    reasoning_tokens: int = 0      # hidden thinking tokens (billed as output, add latency)
    latency_ms: float = 0.0
    error: str | None = None       # "timeout" | "rate_limited" | "server_error" | "http_<code>" | "network"
    refused: bool = False          # provider-signalled refusal (Anthropic stop_reason == "refusal")
    raw_stop: str | None = None
    cached: bool = False           # served from local cache: no spend, latency is the original measurement

    @property
    def ok(self) -> bool:
        return self.error is None


def _key(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
    return val


def _classify_http_error(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status == 402:
        return "out_of_credits"
    if status >= 500:
        return "server_error"
    return f"http_{status}"


def _estimate_tokens(text: str) -> int:
    # Rough fallback only if a provider omits usage; Indic scripts tokenise denser, so this is conservative.
    return max(1, len(text) // 3)


def call_sarvam(model: config.Model, system: str, user: str, max_tokens: int,
                timeout_s: float, reasoning: str | None) -> CallResult:
    res = CallResult(model=model.key)
    body = {
        "model": model.model_id,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        # sarvam-105b: null disables reasoning. glm5.3: cannot disable; omitted/null means MAX, so floor at "low".
        "reasoning_effort": reasoning or model.min_reasoning,
    }
    headers = {"api-subscription-key": _key("SARVAM_API_KEY"), "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        r = _http.post(SARVAM_BASE + model.api_path, json=body, headers=headers, timeout=timeout_s)
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            res.error = _classify_http_error(r.status_code)
            res.text = r.text[:300]
            return res
        data = r.json()
        choice = data["choices"][0]
        res.text = (choice.get("message") or {}).get("content") or ""
        res.raw_stop = choice.get("finish_reason")
        usage = data.get("usage") or {}
        res.tokens_in = usage.get("prompt_tokens", 0)
        res.tokens_out = usage.get("completion_tokens", 0)   # includes reasoning tokens (billed)
        res.reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        if not usage:
            res.tokens_in, res.tokens_out = _estimate_tokens(system + user), _estimate_tokens(res.text)
            res.tokens_estimated = True
    except httpx.TimeoutException:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error = "timeout"
    except httpx.HTTPError as e:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error = "network"
        res.text = str(e)[:300]
    return res


def call_anthropic(model: config.Model, system: str, user: str, max_tokens: int,
                   timeout_s: float, reasoning: str | None = None) -> CallResult:
    res = CallResult(model=model.key)
    body = {
        "model": model.model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
        "temperature": 0.2,
    }
    if system:
        body["system"] = system
    headers = {"x-api-key": _key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    t0 = time.perf_counter()
    try:
        r = _http.post(ANTHROPIC_URL, json=body, headers=headers, timeout=timeout_s)
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            res.error = "server_error" if r.status_code == 529 else _classify_http_error(r.status_code)
            res.text = r.text[:300]
            return res
        data = r.json()
        res.text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        res.raw_stop = data.get("stop_reason")
        res.refused = res.raw_stop == "refusal"
        usage = data.get("usage") or {}
        res.tokens_in = usage.get("input_tokens", 0)
        res.tokens_out = usage.get("output_tokens", 0)
    except httpx.TimeoutException:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error = "timeout"
    except httpx.HTTPError as e:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error = "network"
        res.text = str(e)[:300]
    return res


def has_key(provider: str) -> bool:
    return bool(os.getenv({"sarvam": "SARVAM_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]))


def call_model(model_key: str, system: str, user: str, max_tokens: int = 800,
               timeout_s: float = 20, reasoning: str | None = None,
               use_cache: bool | None = None) -> CallResult:
    m = config.MODELS[model_key]
    use_cache = USE_CACHE if use_cache is None else use_cache
    cp = _cache_path(m.model_id, system, user, max_tokens, reasoning)
    if use_cache and cp.exists():
        res = CallResult(**json.loads(cp.read_text()))
        res.cached = True
        return res
    _check_budget()
    fn = call_sarvam if m.provider == "sarvam" else call_anthropic
    res = fn(m, system, user, max_tokens, timeout_s, reasoning)
    if res.tokens_in or res.tokens_out:          # failed calls with no usage are not billed
        _charge(m.provider, m.key, res.tokens_in, res.tokens_out, m.cost_inr(res.tokens_in, res.tokens_out))
    if res.ok:                                   # never cache failures: we want to see them again
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(asdict(res), ensure_ascii=False))
    return res


@dataclass
class PrismResult:
    answers: dict = field(default_factory=dict)
    tokens_in: int = 0
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def cost_inr(self) -> float:
        return self.tokens_in / 1e6 * config.PRISM_IN_PER_M_INR


def prism(state: str, questions: dict, timeout_s: float = config.PRISM_TIMEOUT_S) -> PrismResult:
    """Ask Sarvam Prism several questions about one piece of text; returns probabilities, not text."""
    out = PrismResult()
    _check_budget()
    body = {"model": "sarvam-prism", "state": state, "questions": questions}
    headers = {"api-subscription-key": _key("SARVAM_API_KEY"), "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        r = _http.post(SARVAM_BASE + "/v2/systemone", json=body, headers=headers, timeout=timeout_s)
        out.latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            out.error = _classify_http_error(r.status_code)
            return out
        data = r.json()
        out.answers = data.get("answers", {})
        out.tokens_in = (data.get("usage") or {}).get("input_tokens", 0)
        _charge("sarvam", "sarvam-prism", out.tokens_in, 0, out.cost_inr)
    except httpx.TimeoutException:
        out.latency_ms = (time.perf_counter() - t0) * 1000
        out.error = "timeout"
    except httpx.HTTPError:
        out.latency_ms = (time.perf_counter() - t0) * 1000
        out.error = "network"
    return out
