"""Post-answer checks. They run on every answer, cost nothing, and decide whether to escalate.

They catch *visible* failures only: errors, timeouts, refusals, empty/truncated output, broken
JSON, wrong language/script. A fluent but wrong answer passes these checks; the offline quality
score in eval/ is what measures that.
"""
from __future__ import annotations

import json
import re

from . import features
from .clients import CallResult

_REFUSAL = re.compile(
    r"(i can(?:'|no)t (?:help|assist) with|i am unable to (?:help|assist)|i'm unable to (?:help|assist)|"
    r"i cannot provide|as an ai(?: language model)?,? i|i won't be able to help|"
    r"मैं इसमें (?:आपकी )?मदद नहीं कर सकता)", re.I)


def extract_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    return json.loads(m.group(0) if m else t)


def lang_matches(expected: str, output: str) -> bool:
    """Is the output in the expected language/script? Lenient: only flags clear mismatches."""
    if expected == "en":
        return True
    c = features.script_counts(output)
    if expected in ("hi", "ta"):
        return c[expected] >= 0.3 * max(1, c[expected] + c["latin"])
    if expected == "hinglish":
        # Accept romanised Hindi or Devanagari; flag a pure-English reply to a Hinglish customer.
        return features.hinglish_ratio(output) >= 0.12 or c["hi"] > 20
    return True


def check(res: CallResult, *, expects_json: bool = False, expected_lang: str | None = None) -> tuple[bool, str]:
    if res.error:
        return False, res.error                      # timeout | rate_limited | server_error | ...
    if res.refused or _REFUSAL.search(res.text or ""):
        return False, "refusal"
    if not (res.text or "").strip():
        # Seen in testing: reasoning tokens used the whole budget and the visible answer was empty.
        return False, "empty" + ("_reasoning_ate_budget" if res.raw_stop == "length" else "")
    if res.raw_stop == "length":
        return False, "truncated"
    if expects_json:
        try:
            extract_json(res.text)
        except (ValueError, json.JSONDecodeError):
            return False, "bad_json"
    if expected_lang and not lang_matches(expected_lang, res.text):
        return False, f"wrong_language(expected {expected_lang})"
    return True, "ok"
