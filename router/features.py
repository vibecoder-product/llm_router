"""Cheap, deterministic request features (no API calls, < 1 ms).

lang:        en | hinglish | hi | ta | indic_other
difficulty:  rule-based guess, with a flag saying whether the rules are confident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Unicode blocks for the scripts we care about.
_SCRIPTS = {
    "hi": (0x0900, 0x097F),   # Devanagari (Hindi, Marathi)
    "ta": (0x0B80, 0x0BFF),   # Tamil
    "bn": (0x0980, 0x09FF),   # Bengali
    "te": (0x0C00, 0x0C7F),   # Telugu
    "kn": (0x0C80, 0x0CFF),   # Kannada
}

# Common romanised-Hindi words. Hinglish is written in Latin script, so script detection alone misses it.
# Words that are also common English (to, me, ya, please, par) are deliberately left out.
HINGLISH_WORDS = set("""
hai hain ho hoga hogi tha thi kya kyu kyun kab kaise kahan kaha kitna kitne nahi nahin na mat
mera meri mere mujhe mujhko humko hum aap aapka aapki apna tum tera bhai yaar ji haan
ka ki ke ko se mein pe tak aur lekin toh bhi abhi jaldi
kar karo karna karein kiya kiye raha rahi rahe gaya gayi gaye diya dijiye chahiye milega milegi
paisa paise wapas wapis dikha dikh bata batao samjha theek thik accha acha sahi galat
""".split())

HARD_KEYWORDS = [
    # English
    "policy", "eligible", "eligibility", "calculate", "prorat", "partial refund", "dispute", "compare",
    "explain why", "step by step", "escalat", "legal", "chargeback", "compensation", "terms",
    "deduct", "penalty", "within days", "sql", "query", "join",
    # Romanised Hindi
    "kitna wapas", "hisaab", "hisab", "kyun kata", "kaise calculate", "niyam",
]
_NUM = re.compile(r"(₹|rs\.?|inr)?\s?\d[\d,]*(\.\d+)?", re.I)
_CODE = re.compile(r"(select |insert |update |create table|```|def |;\s*$)", re.I | re.M)


def script_counts(text: str) -> dict[str, int]:
    counts = {k: 0 for k in _SCRIPTS}
    counts["latin"] = 0
    for ch in text:
        o = ord(ch)
        if ch.isascii() and ch.isalpha():
            counts["latin"] += 1
            continue
        for k, (lo, hi) in _SCRIPTS.items():
            if lo <= o <= hi:
                counts[k] += 1
                break
    return counts


def hinglish_ratio(text: str) -> float:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return 0.0
    return sum(w in HINGLISH_WORDS for w in words) / len(words)


def detect_lang(text: str) -> str:
    c = script_counts(text)
    indic = {k: v for k, v in c.items() if k != "latin"}
    top, top_n = max(indic.items(), key=lambda kv: kv[1])
    if top_n > 0 and top_n >= 0.3 * (top_n + c["latin"]):
        return top if top in ("hi", "ta") else "indic_other"
    return "hinglish" if hinglish_ratio(text) >= 0.15 else "en"


def lang_group(lang: str) -> str:
    """Coarse bucket used for calibration cells: English vs any Indian-language traffic."""
    return "en" if lang == "en" else "indic"


@dataclass
class RuleDifficulty:
    hard: bool
    confident: bool
    signals: list[str]


def rule_difficulty(text: str) -> RuleDifficulty:
    t = text.lower()
    signals = []
    if len(text) > 1500:
        signals.append("long")
    nums = len(_NUM.findall(text))
    if nums >= 3:
        signals.append(f"{nums} numbers")
    kws = [k for k in HARD_KEYWORDS if k in t]
    if kws:
        signals.append("kw:" + ",".join(kws[:3]))
    if _CODE.search(text):
        signals.append("code")

    n = len(signals)
    if n >= 2:
        return RuleDifficulty(True, True, signals)          # clearly hard
    if n == 0 and len(text) < 400:
        return RuleDifficulty(False, True, ["short, no hard signals"])  # clearly easy
    return RuleDifficulty(n == 1, False, signals or ["medium length"])  # unsure -> ask Prism
