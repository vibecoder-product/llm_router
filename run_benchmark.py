"""Benchmark on the 40 HELD-OUT prompts: always-cheapest vs always-frontier vs router.

Stages (each can be re-run alone; only `run` spends on model calls):
  python run_benchmark.py run       # 40 prompts x 3 configs x RUNS, cache OFF (real latency) -> results/benchmark_requests.jsonl
  python run_benchmark.py score     # quality scores -> results/benchmark_scored.jsonl
  python run_benchmark.py summary   # tables -> results/summary.md
Scoring: deterministic use cases are scored on every run; judged use cases (paid) on run 1 only.
Aggregates weight every prompt equally (mean over its scored runs first).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from eval import score as S
from router import clients, config, router

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "eval" / "prompts.jsonl"
RAW = ROOT / "results" / "benchmark_requests.jsonl"
SCORED = ROOT / "results" / "benchmark_scored.jsonl"
SUMMARY = ROOT / "results" / "summary.md"
RUNS = 3
CONFIGS = {"always_cheapest": config.CHEAPEST, "always_frontier": config.FRONTIER, "router": None}
JUDGED = {"live_chat_reply", "chat_summary", "catalogue_translate"}


def held_out() -> list[dict]:
    rows = [json.loads(l) for l in PROMPTS.open()]
    test = [r for r in rows if r["split"] == "test"]
    assert all(not r["id"].split("-")[1].startswith("c") for r in test), "calibration id leaked into test split"
    return test


def stage_run(only: str | None = None) -> None:
    """`only`: re-run a single config, replacing its rows and keeping the others (e.g. after a router change)."""
    test = held_out()
    names = list(CONFIGS)
    if only:
        assert only in CONFIGS, f"unknown config {only}"
        kept = [l for l in RAW.read_text().splitlines() if json.loads(l)["config"] != only] if RAW.exists() else []
        RAW.write_text("\n".join(kept) + ("\n" if kept else ""))
    elif RAW.exists():
        sys.exit(f"{RAW} exists; delete it to re-run (prevents double-spending), or use: run --only router")
    t0 = time.time()
    for run in range(1, RUNS + 1):
        for i, p in enumerate(test):
            order = names[(i + run) % 3:] + names[:(i + run) % 3]   # rotate config order per prompt
            for name in order:
                if only and name != only:
                    continue
                row = router.handle(p["prompt"], p["use_case"], context=p.get("context"),
                                    target_lang=p.get("target_lang"), force_model=CONFIGS[name],
                                    config_name=name, use_cache=False, log_path=RAW, log_prompt=True,
                                    extra={"prompt_id": p["id"], "run": run, "hard_label": p["hard"]})
                print(f"run{run} {p['id']:5} {name:16} -> {row['final_model']:11} {row['latency_ms']:6}ms "
                      f"₹{row['cost_inr']:.4f} {row['final_check']}{' FALLBACK' if row['fallback_fired'] else ''}")
                time.sleep(0.3)
    print(f"done in {time.time() - t0:.0f}s; spend ledger {clients.total_spend_inr()}")


def stage_score() -> None:
    prompts = {p["id"]: p for p in held_out()}
    rows = [json.loads(l) for l in RAW.open()]
    out = []
    for i, r in enumerate(rows, 1):
        p = prompts[r["prompt_id"]]
        if p["use_case"] in JUDGED and r["run"] != 1:
            r["quality_score"], r["passed"], r["score_detail"] = None, None, {"why": "judged use case: scored on run 1 only"}
        else:
            s, detail = S.score(p, r["output"], answered=r["answered"])
            r["quality_score"], r["passed"], r["score_detail"] = s, S.passed(s), detail
        out.append(r)
        if i % 30 == 0:
            print(f"scored {i}/{len(rows)}")
    SCORED.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n")
    print("wrote", SCORED, "| spend", clients.total_spend_inr())


def _per_prompt(df: pd.DataFrame) -> pd.DataFrame:
    """Mean quality / pass per (config, prompt) over scored runs, so each prompt weighs the same."""
    s = df.dropna(subset=["quality_score"])
    return s.groupby(["config", "prompt_id"]).agg(q=("quality_score", "mean"),
                                                  p=("passed", lambda x: np.mean(x.astype(float))),
                                                  lang=("lang", "first"), hard=("hard_label", "first"),
                                                  uc=("use_case", "first")).reset_index()


def stage_summary() -> None:
    df = pd.read_json(SCORED, lines=True)
    df["lang_group"] = np.where(df["lang"] == "en", "English", "Indic")
    pp = _per_prompt(df)
    n_prompts = df["prompt_id"].nunique()
    lines = [f"# Benchmark results\n",
             f"{n_prompts} held-out prompts x {RUNS} runs per config ({len(df)} requests). Cost/latency over all runs; "
             f"quality weighted per prompt. Router totals include Prism + rule overhead and every fallback attempt.\n"]

    rows = []
    for name in CONFIGS:
        d, q = df[df.config == name], pp[pp.config == name]
        inter = d[d["mode"] == "interactive"]
        rows.append({
            "config": name,
            "cost ₹ / 1k req": d["cost_inr"].mean() * 1000,
            "p50 ms": d["latency_ms"].quantile(.5), "p95 ms": d["latency_ms"].quantile(.95),
            "quality (0-1)": q["q"].mean(), "pass rate": q["p"].mean(),
            "pass: English": q[q.lang == "en"]["p"].mean(), "pass: Indic": q[q.lang != "en"]["p"].mean(),
            "pass: hard slice": q[q.hard]["p"].mean(),
            "interactive within SLA": (inter["latency_ms"] <= inter["sla_ms"]).mean(),
            "human handoffs": int((~d["answered"]).sum()),
        })
    t = pd.DataFrame(rows).set_index("config")
    frontier_cost = t.loc["always_frontier", "cost ₹ / 1k req"]
    t.insert(1, "cost vs frontier", t["cost ₹ / 1k req"] / frontier_cost)
    fmt = t.copy()
    for c in fmt.columns:
        if c in ("cost ₹ / 1k req",):
            fmt[c] = fmt[c].map(lambda v: f"₹{v:,.2f}")
        elif c in ("p50 ms", "p95 ms", "human handoffs"):
            fmt[c] = fmt[c].map(lambda v: f"{v:,.0f}")
        elif c == "quality (0-1)":
            fmt[c] = fmt[c].map(lambda v: f"{v:.2f}")
        else:
            fmt[c] = fmt[c].map(lambda v: f"{v:.0%}")
    lines += ["## Headline\n", fmt.to_markdown(), ""]

    r = df[df.config == "router"]
    lines += ["## Router internals\n",
              f"- Traffic split by answering model: {r['final_model'].value_counts(normalize=True).round(2).to_dict()}",
              f"- Decided by: {r['decided_by'].value_counts().to_dict()}",
              f"- Fallback fired: {r['fallback_fired'].mean():.1%} of requests "
              f"({r[r.fallback_fired]['fallback_reason'].value_counts().to_dict()})",
              f"- Router overhead: mean {r['router_ms'].mean():.0f} ms, p95 {r['router_ms'].quantile(.95):.0f} ms; "
              f"cost ₹{r['router_cost_inr'].sum():.4f} of ₹{r['cost_inr'].sum():.4f} total "
              f"({r['router_cost_inr'].sum() / r['cost_inr'].sum():.2%})",
              f"- SLA traded (no model fit the latency budget): {int(r['sla_traded'].sum())}", ""]

    by_uc = pp.pivot_table(index="uc", columns="config", values="p", aggfunc="mean").round(2)
    lines += ["## Pass rate by use case\n", by_uc.to_markdown(), ""]
    cost_uc = df.pivot_table(index="use_case", columns="config", values="cost_inr", aggfunc="mean") * 1000
    lines += ["## Cost per 1k requests by use case (₹)\n", cost_uc.round(2).to_markdown(), ""]
    # ---- uncertainty: bootstrap over prompts (each prompt's per-config pass rate is the unit)
    rng = np.random.default_rng(0)
    wide = pp.pivot_table(index="prompt_id", columns="config", values="p")
    boots = {c: [] for c in CONFIGS}
    diffs = {"router - cheapest": [], "router - frontier": []}
    ids = wide.index.to_numpy()
    for _ in range(2000):
        sample = wide.loc[rng.choice(ids, len(ids))]
        for c in CONFIGS:
            boots[c].append(sample[c].mean())
        diffs["router - cheapest"].append((sample["router"] - sample["always_cheapest"]).mean())
        diffs["router - frontier"].append((sample["router"] - sample["always_frontier"]).mean())
    ci = lambda xs: f"{np.mean(xs):.0%} [{np.percentile(xs, 2.5):.0%}, {np.percentile(xs, 97.5):.0%}]"
    lines += ["## Uncertainty (95% bootstrap CI over the 48 prompts)\n",
              "| | pass rate [95% CI] |", "|---|---|"]
    lines += [f"| {c} | {ci(boots[c])} |" for c in CONFIGS]
    lines += [f"| {k} | {ci(v)} |" for k, v in diffs.items()]
    lines += ["", "A difference whose interval includes 0% is not distinguishable from noise at this sample size.", ""]

    # ---- judge sensitivity: GLM-only judge vs the two-judge average used above
    def glm_only(row):
        d = row["score_detail"] if isinstance(row["score_detail"], dict) else {}
        js = d.get("judge_scores")
        if not js or "glm-5.3" not in js:
            return row["quality_score"]
        return min(js["glm-5.3"], 0.5 if d.get("gates") else 1.0)
    alt = df.dropna(subset=["quality_score"]).copy()
    alt["quality_score"] = alt.apply(glm_only, axis=1)
    alt["passed"] = alt["quality_score"] >= S.PASS_AT
    pa = _per_prompt(alt)
    lines += ["## Judge sensitivity\n", "| config | pass rate (2-judge average, headline) | pass rate (GLM-5.3 judge only) |",
              "|---|---|---|"]
    lines += [f"| {c} | {pp[pp.config == c]['p'].mean():.0%} | {pa[pa.config == c]['p'].mean():.0%} |" for c in CONFIGS]
    jd = df.dropna(subset=["quality_score"])
    det = [x for x in jd["score_detail"] if isinstance(x, dict) and "judge_agree" in x]
    if det:
        lines += ["", f"Judged outputs: {len(det)}. Judges within 2 points: {np.mean([x['judge_agree'] for x in det]):.0%}. "
                  f"Flagged for human review (>3 points apart): {sum(x.get('needs_human_review', False) for x in det)}.", ""]
    SUMMARY.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "run"
    if stage == "run" and "--only" in sys.argv:
        stage_run(sys.argv[sys.argv.index("--only") + 1])
    else:
        {"run": stage_run, "score": stage_score, "summary": stage_summary}[stage]()
