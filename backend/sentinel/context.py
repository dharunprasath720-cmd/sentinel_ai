"""Shared runtime objects handed to the API. Every field except `business_id` is optional so
the app (and its tests) can run with only the pieces they need."""
from dataclasses import dataclass
from typing import Any


@dataclass
class AppContext:
    business_id: str = "demo_biz"      # business that PayPal webhooks and the simulator belong to
    bundle: Any = None                 # models.train.TrainedBundle
    risk_engine: Any = None            # risk.engine.RiskEngine
    normalisers: Any = None            # dict[str, Normaliser]
    live_scorer: Any = None            # live.scorer.LiveScorer
    paypal: Any = None                 # paypal.client.PayPalClient
    webhook_id: str | None = None      # PayPal webhook id (from the Developer Portal)
    llm: Any = None                    # agent.llm.LLM
    demo_frame: Any = None             # DataFrame replayed by the simulator
    model_version: str = "unversioned"
