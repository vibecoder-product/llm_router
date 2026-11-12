"""One call per model + one Prism call. Run: .venv/bin/python smoke_test.py"""
from router import clients, config

PROMPT = "Mera order 3 din se 'out for delivery' dikha raha hai. Kab aayega?"

for key in config.TIER_ORDER:
    if not clients.has_key(config.MODELS[key].provider):
        print(f"\n=== {key}: skipped, no {config.MODELS[key].provider} key in .env ===")
        continue
    for reasoning in ([None, "low"] if config.MODELS[key].provider == "sarvam" else [None]):
        r = clients.call_model(key, config.SYS_SUPPORT, PROMPT, max_tokens=300, timeout_s=30, reasoning=reasoning)
        cost = config.MODELS[key].cost_inr(r.tokens_in, r.tokens_out)
        print(f"\n=== {key} reasoning={reasoning} ===")
        print(f"ok={r.ok} error={r.error} stop={r.raw_stop} refused={r.refused}")
        print(f"tokens in/out={r.tokens_in}/{r.tokens_out} est={r.tokens_estimated} "
              f"latency={r.latency_ms:.0f}ms cost=₹{cost:.5f}")
        print("text:", (r.text or "")[:300].replace("\n", " "))

print("\n=== sarvam-prism ===")
for timeout in (5.0, config.PRISM_TIMEOUT_S):
    p = clients.prism(PROMPT, {
        "needs_reasoning": {"type": "noul",
                            "instructions": "Does answering this need multi-step reasoning or policy calculation?"},
        "complexity": {"type": "score", "instructions": "How hard is this request for a support assistant?",
                       "criteria": ["trivial", "easy", "moderate", "hard", "very hard"]},
    }, timeout_s=timeout)
    print(f"timeout={timeout}s error={p.error} latency={p.latency_ms:.0f}ms tokens_in={p.tokens_in} "
          f"cost=₹{p.cost_inr:.6f}")
    print("answers:", p.answers)

print("\nCumulative spend (all runs, from logs/spend.jsonl):", clients.total_spend_inr())
