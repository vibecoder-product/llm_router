"""Quality scoring, 0..1 per request. passed = score >= PASS_AT.

Deterministic (free, exact):   ticket_intent (label), policy_dispute (decision + amount), attr_extract (fields),
                               code (execute SQL on the fixture DB and compare result sets).
Two LLM judges (paid):         live_chat_reply, chat_summary, catalogue_translate.
  Judges are GLM-5.3 and Sarvam 105B (different model families). We AVERAGE them and flag disagreements
  (> 3 points apart) for human review. We first took the lower score (to stop a judge favouring its own family),
  but calibration showed a judge hallucinating a script error on correct Tamil; with "min", one judge's mistake
  decided the score. Averaging is more robust, and we saw no sign of self-preference (the Sarvam judge was
  harsher on Sarvam outputs, not softer).
  Deterministic gates run first (language/script, kept numbers/brands) and cap the judge score.
"""
from __future__ import annotations

import json
import re
import unicodedata

from router import checks, clients, config, features
from .fixtures import build_db, results_match

PASS_AT = 0.7
JUDGES = ["glm-5.3", "sarvam-105b"]
_DB = None

LANG_NAME = {"hi": "Hindi (Devanagari script)", "ta": "Tamil (Tamil script)", "hinglish": "Hinglish (romanised Hindi-English)",
             "en": "English"}
TASK_DESC = {
    "live_chat_reply": "Reply to a waiting customer in a support chat, using ONLY the order context provided.",
    "chat_summary": "Summarise a support chat in English in at most 4 bullet points.",
    "catalogue_translate": "Translate an e-commerce product description into the target language.",
}

JUDGE_SYSTEM = ("You are a strict evaluator of AI outputs for an Indian e-commerce support team. You read English, "
                "Hindi, Hinglish and Tamil fluently. Score the RESPONSE from 0 to 10 using the rubric. "
                'Return only JSON: {"score": <integer 0-10>, "reason": "<one short sentence>"}')
RUBRIC = ("Rubric: start at 10. Subtract 2 for each REQUIRED point that is missing or wrong. "
          "Give at most 3 if the response breaks any MUST NOT item or states facts, promises or timelines that are "
          "not supported by the input. Subtract 1-2 for wrong language/script, poor tone or needless length.")


# ------------------------------------------------------------------ deterministic scorers
def _ticket(out: str, ref: dict) -> tuple[float, str]:
    t = out.upper()
    found = [lab for lab in config.TICKET_LABELS if lab in t]
    if not found:
        return 0.0, "no label"
    first = min(found, key=t.index)
    return (1.0, "label ok") if first == ref["label"] else (0.0, f"label {first} != {ref['label']}")


_DEC = re.compile(r"DECISION:\s*\**\s*([A-Z_]+)\**\s*AMOUNT:\s*\**\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)", re.I)


def _policy(out: str, ref: dict) -> tuple[float, str]:
    m = _DEC.findall(out)
    if not m:
        return 0.0, "no DECISION line"
    dec, amt = m[-1]
    amt = float(amt.replace(",", ""))
    ok_dec, ok_amt = dec.upper() == ref["decision"], abs(amt - ref["amount_inr"]) <= 1.0
    if ok_dec and ok_amt:
        return 1.0, "decision+amount ok"
    return 0.0, f"got {dec} ₹{amt:g}, want {ref['decision']} ₹{ref['amount_inr']:g}"


def _n(s) -> str | None:
    if s is None:
        return None
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    if s in ("", "null", "none", "n/a", "na", "not stated", "not specified", "unknown"):
        return None
    s = s.replace("-", " ").replace("aluminum", "aluminium")
    s = re.sub(r"\b(litres?|liters?|ltrs?)\b", "l", s)
    return re.sub(r"\s+", "", s)


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def _attr(out: str, ref: dict) -> tuple[float, str]:
    try:
        got = checks.extract_json(out)
    except (ValueError, json.JSONDecodeError):
        return 0.0, "bad json"
    got = {k.lower(): v for k, v in got.items()} if isinstance(got, dict) else {}
    ok, misses = 0, []
    for k, rv in ref["fields"].items():
        gv = got.get(k)
        if isinstance(rv, (int, float)) or k in ("price_inr", "pack_count"):
            g, r = _num(gv), rv
            hit = (g == r) or (k == "pack_count" and r is None and g in (None, 1.0))
        elif k == "color" and rv is not None:
            g = _n(gv) or ""
            hit = all(c in g for c in _n(rv).split("/"))
        else:
            g, r = _n(gv), _n(rv)
            hit = (g == r) or (g is not None and r is not None and (r in g or g in r))
        ok += hit
        if not hit:
            misses.append(f"{k}={gv!r}")
    return ok / len(ref["fields"]), ("all fields ok" if not misses else "miss " + ", ".join(misses))


def _sql(out: str, ref: dict) -> tuple[float, str]:
    global _DB
    _DB = _DB or build_db()
    m = re.search(r"```(?:sql)?\s*(.*?)```", out, re.S | re.I)
    sql = (m.group(1) if m else out).strip().rstrip(";")
    ok, why = results_match(_DB, sql, ref["sql"])
    return (1.0 if ok else 0.0), why


# ------------------------------------------------------------------ LLM judges
def _judge_one(model: str, prompt_row: dict, output: str) -> tuple[float | None, str]:
    ref = prompt_row["reference"]
    uc = prompt_row["use_case"]
    parts = [f"TASK: {TASK_DESC[uc]}"]
    if prompt_row.get("context"):
        parts.append(f"ORDER CONTEXT: {prompt_row['context']}")
    if uc == "catalogue_translate":
        parts.append(f"TARGET LANGUAGE: {LANG_NAME[prompt_row['target_lang']]}")
        parts.append(f"SOURCE: {prompt_row['prompt']}")
        must = ["faithful and complete translation of the SOURCE (no added or dropped information)",
                "brand names, model numbers, sizes and numbers kept unchanged: " + ", ".join(ref["keep"]),
                "natural, fluent " + LANG_NAME[prompt_row["target_lang"]]]
        must_not = ["adds claims not in the source"]
    else:
        parts.append(("CUSTOMER MESSAGE: " if uc == "live_chat_reply" else "CHAT TRANSCRIPT:\n") + prompt_row["prompt"])
        must, must_not = ref["must"], ref["must_not"]
    parts.append("REQUIRED:\n" + "\n".join(f"- {m}" for m in must))
    parts.append("MUST NOT:\n" + "\n".join(f"- {m}" for m in must_not))
    parts.append(f"RESPONSE:\n{output}")
    parts.append(RUBRIC)
    # sarvam-105b: reasoning off (with it on, the visible answer came back empty). GLM: "low" is its floor.
    r = clients.call_model(model, JUDGE_SYSTEM, "\n\n".join(parts), max_tokens=2500, timeout_s=60,
                           reasoning=None, use_cache=True)
    if not r.ok or not r.text.strip():
        return None, f"judge {model} failed: {r.error or 'empty'}"
    m = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', r.text) or re.search(r"\b(10|\d)\s*/\s*10\b", r.text)
    if not m:
        return None, f"judge {model} unparseable"
    reason = re.search(r'"reason"\s*:\s*"([^"]*)"', r.text)
    return min(10.0, float(m.group(1))) / 10, (reason.group(1) if reason else "")


def _judged(prompt_row: dict, output: str) -> tuple[float | None, dict]:
    scores, reasons = {}, {}
    for j in JUDGES:
        s, why = _judge_one(j, prompt_row, output)
        if s is not None:
            scores[j] = s
        reasons[j] = why
    if not scores:
        return None, {"judges": reasons}
    detail = {"judge_scores": scores, "judges": reasons}
    if len(scores) == 2:
        a, b = scores.values()
        detail["judge_agree"] = abs(a - b) <= 0.2
        detail["needs_human_review"] = abs(a - b) > 0.3
    return sum(scores.values()) / len(scores), detail


# ------------------------------------------------------------------ entry point
def score(prompt_row: dict, output: str, answered: bool = True) -> tuple[float | None, dict]:
    """Returns (score 0..1 or None if unscorable, detail)."""
    if not answered:
        return 0.0, {"why": "no answer (safe reply / human handoff)"}
    uc, ref = prompt_row["use_case"], prompt_row["reference"]
    if uc == "ticket_intent":
        s, why = _ticket(output, ref)
        return s, {"why": why}
    if uc == "policy_dispute":
        s, why = _policy(output, ref)
        return s, {"why": why}
    if uc == "attr_extract":
        s, why = _attr(output, ref)
        return s, {"why": why}
    if uc == "code":
        s, why = _sql(output, ref)
        return s, {"why": why}

    # judged use cases, with deterministic gates
    cap, gates = 1.0, []
    if uc == "live_chat_reply" and not checks.lang_matches(prompt_row["lang"], output):
        cap, gates = 0.5, gates + [f"reply not in customer's language ({prompt_row['lang']})"]
    if uc == "catalogue_translate":
        if not checks.lang_matches(prompt_row["target_lang"], output):
            return 0.0, {"why": "not in target script"}
        missing = [k for k in ref["keep"] if k not in output]
        if missing:
            cap, gates = 0.5, gates + [f"changed/dropped: {missing}"]
    s, detail = _judged(prompt_row, output)
    if s is None:
        return None, detail
    detail["gates"] = gates
    return min(s, cap), detail


def passed(s: float | None) -> bool | None:
    return None if s is None else s >= PASS_AT
