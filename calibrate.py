"""Measure each model on the CALIBRATION split, so the router decides from data instead of priors.

For every calibration prompt: classify it the way the router does (lang + easy/hard), call EVERY model with
the parameters the router would use, run the post-checks, score quality, and record latency.
Writes:
  results/calibration_table.json   pass counts per cell + p95 latency per model (read by router/policy.py)
  results/calibration_runs.jsonl   one row per (prompt, model) for audit
Run: python calibrate.py        (held-out test prompts are never touched)
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from eval import score as S
from router import checks, clients, config, features, policy
from router.router import _expected_lang, build_user

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "eval" / "prompts.jsonl"
OUT_TABLE = ROOT / "results" / "calibration_table.json"
OUT_RUNS = ROOT / "results" / "calibration_runs.jsonl"


def main() -> None:
    rows = [json.loads(l) for l in PROMPTS.open()]
    calib = [r for r in rows if r["split"] == "calib"]
    assert calib and all(r["split"] == "calib" for r in calib)
    OUT_RUNS.parent.mkdir(exist_ok=True)
    runs = []
    for i, p in enumerate(calib, 1):
        lang = p.get("target_lang") or features.detect_lang(p["prompt"])
        lg = features.lang_group(lang)
        diff, by, _, _, pinfo = policy._difficulty(p["prompt"], config.USE_CASES[p["use_case"]], lang)
        uc = config.USE_CASES[p["use_case"]]
        user = build_user(p["prompt"], p.get("context"), p.get("target_lang"))
        for m in config.TIER_ORDER:
            reasoning, max_tokens = policy._call_params(m, diff)
            r = clients.call_model(m, uc.system, user, max_tokens=max_tokens, timeout_s=uc.timeout_s,
                                   reasoning=reasoning, use_cache=True)
            ok, why = checks.check(r, expects_json=uc.expects_json,
                                   expected_lang=_expected_lang(p["use_case"], lang, p.get("target_lang")))
            s, detail = S.score(p, r.text or "", answered=ok)
            runs.append({"prompt_id": p["id"], "use_case": p["use_case"], "lang": lang, "lang_group": lg,
                         "difficulty": diff, "decided_by": by, "prism": pinfo, "hard_label": p["hard"],
                         "model": m, "check": why, "latency_ms": round(r.latency_ms), "cached": r.cached,
                         "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "reasoning_tokens": r.reasoning_tokens,
                         "cost_inr": round(config.MODELS[m].cost_inr(r.tokens_in, r.tokens_out), 6),
                         "score": s, "passed": S.passed(s), "detail": detail, "output": r.text})
            print(f"[{i:2}/{len(calib)}] {p['id']:5} {lang:8} {diff:4} ({by:5}) {m:11} check={why:24} "
                  f"score={'-' if s is None else f'{s:.2f}'} {r.latency_ms:6.0f}ms{' (cached)' if r.cached else ''}")
            time.sleep(0.3)   # stay well under Sarvam's per-minute limits

    OUT_RUNS.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in runs) + "\n")

    # ---- calibration table: pass counts per (use_case, lang_group, difficulty, model) and coarser (*, lg, diff, model)
    cells: dict[str, dict] = defaultdict(lambda: {"passes": 0, "n": 0})
    for x in runs:
        if x["passed"] is None:
            continue
        for key in (f"{x['use_case']}|{x['lang_group']}|{x['difficulty']}|{x['model']}",
                    f"*|{x['lang_group']}|{x['difficulty']}|{x['model']}"):
            cells[key]["n"] += 1
            cells[key]["passes"] += int(x["passed"])
    df = pd.DataFrame(runs)
    # p95 per model AND difficulty: reasoning is switched on for hard work, which changes latency a lot
    ok = df[df["check"] != "timeout"]
    p95 = {f"{m}|{d}": v for (m, d), v in ok.groupby(["model", "difficulty"])["latency_ms"].quantile(0.95).round().items()}
    p95.update(ok.groupby("model")["latency_ms"].quantile(0.95).round().to_dict())
    OUT_TABLE.write_text(json.dumps({"source": "calibrate.py on calibration split", "n_prompts": len(calib),
                                     "pass": dict(cells), "p95_ms": p95}, indent=1))

    # ---- readable summary
    print("\nPass rate by model x (lang_group, difficulty):")
    print(df.assign(p=df["passed"].astype(float)).pivot_table(index=["lang_group", "difficulty"], columns="model",
                                                              values="p", aggfunc="mean").round(2).to_string())
    print("\nPass rate by model x use_case:")
    print(df.assign(p=df["passed"].astype(float)).pivot_table(index="use_case", columns="model",
                                                              values="p", aggfunc="mean").round(2).to_string())
    print("\nLatency p50 / p95 (ms) by model x difficulty:")
    print(df.groupby(["model", "difficulty"])["latency_ms"].describe(percentiles=[.5, .95])[["count", "50%", "95%"]].round().to_string())
    print("\nDoes the router's easy/hard label separate outcomes? (cheapest model pass rate)")
    print(df[df.model == config.CHEAPEST].groupby("difficulty")["passed"].mean().round(2).to_string())
    print("\nModel cost on calibration (₹):", df.groupby("model")["cost_inr"].sum().round(4).to_dict())
    print("Wrote", OUT_TABLE, "and", OUT_RUNS)
    print("Spend ledger:", {k: round(v, 3) for k, v in clients.total_spend_inr().items()})


if __name__ == "__main__":
    main()
