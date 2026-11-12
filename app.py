"""The router as an HTTP service (same code path as the CLI and the benchmark).

Run:  .venv/bin/uvicorn app:app --port 8000
Try:  curl -s localhost:8000/route -H 'content-type: application/json' \
        -d '{"prompt": "Mera order kab aayega?", "use_case": "live_chat_reply", "context": "Order #1 | expected: today by 8 PM"}'

Inside a customer VPC / air-gapped rack this container sits next to the model servers; set SARVAM_BASE_URL
to the in-cluster endpoint and deployment flags per tenant. No call leaves the network.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from router import config, policy, router

app = FastAPI(title="Sarvam model router", version="0.1")


class RouteRequest(BaseModel):
    prompt: str = Field(..., description="The end user's own text (language/difficulty are judged on this)")
    use_case: str = Field("live_chat_reply", description=f"One of {list(config.USE_CASES)}")
    context: str | None = Field(None, description="Order data / policy snippet passed to the model")
    target_lang: str | None = Field(None, description="For catalogue_translate: hi | ta")
    india_only: bool = False
    air_gapped: bool = False
    dry_run: bool = Field(False, description="Return the routing decision only; no model call, no cost")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "models": config.TIER_ORDER,
            "healthy": {k: policy.healthy(k) for k in config.TIER_ORDER},
            "calibrated": policy.CALIB_PATH.exists()}


@app.post("/route")
def route(req: RouteRequest) -> dict:
    if req.use_case not in config.USE_CASES:
        raise HTTPException(400, f"unknown use_case; expected one of {list(config.USE_CASES)}")
    deployment = {"india_only": req.india_only, "air_gapped": req.air_gapped}
    if req.dry_run:
        d = policy.decide(req.prompt, req.use_case, deployment, req.target_lang)
        return {"model": d.model, "reason": d.reason, "decided_by": d.decided_by,
                "router_ms": round(d.router_ms, 1), "router_cost_inr": d.router_cost_inr}
    row = router.handle(req.prompt, req.use_case, context=req.context, target_lang=req.target_lang,
                        deployment=deployment, config_name="api")
    return {k: row[k] for k in ("id", "output", "final_model", "reason", "fallback_fired", "fallback_reason",
                                "human_handoff", "tokens_in", "tokens_out", "cost_inr", "latency_ms",
                                "router_ms", "router_cost_inr")}
