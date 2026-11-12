"""Thin wrapper over the Anthropic SDK (claude-api guidance, 2026).

  * model: claude-opus-5-5. Thinking is always on for this model, so `thinking` is never sent;
    depth is set with output_config.effort (the default is `medium`, the agent asks for `high`).
  * never sent: temperature / top_p / top_k / budget_tokens (rejected with a 400), forced tool_choice.
  * refusal fallback is enabled by default via the server-side beta; the scalar form
    (`fallbacks: "default"`) is sent through extra_body because the SDK's typed parameter is
    documented for the array form only. UNVERIFIED against the live API until the first real
    call (Task 8); set use_fallbacks=False if the API rejects it.
  * credentials only from the environment / `ant auth login` profile, never from code.
"""
import datetime
import logging
import os
from typing import Protocol

log = logging.getLogger("sentinel.llm")
MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    def create(self, **kwargs): ...


class AnthropicLLM:
    def __init__(self, client=None, model: str = MODEL, use_fallbacks: bool = True):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.use_fallbacks = client, model, use_fallbacks
        # optional spending guard for a public deploy: at most N model calls per UTC day (0 or unset = no limit)
        self.daily_limit = int(os.environ.get("SENTINEL_AI_DAILY_LIMIT", "0") or 0)
        self._day, self._calls = datetime.date.today(), 0

    def create(self, **kwargs):
        if self.daily_limit:
            today = datetime.datetime.now(datetime.timezone.utc).date()
            if today != self._day:
                self._day, self._calls = today, 0
            if self._calls >= self.daily_limit:
                raise RuntimeError("daily AI call limit reached")  # the agent degrades to the deterministic report
            self._calls += 1
        params = dict(kwargs)
        if self.use_fallbacks:
            params["betas"] = [*params.get("betas", []), FALLBACK_BETA]
            params["extra_body"] = {**params.get("extra_body", {}), "fallbacks": "default"}
        resp = self.client.beta.messages.create(model=self.model, **params)
        usage = getattr(resp, "usage", None)
        if usage is not None:  # token counts only: never prompts or completions
            log.info("claude usage: model=%s input=%s output=%s cache_read=%s cache_write=%s stop=%s", self.model,
                     getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
                     getattr(usage, "cache_read_input_tokens", None),
                     getattr(usage, "cache_creation_input_tokens", None), getattr(resp, "stop_reason", None))
        return resp

    @classmethod
    def from_env(cls) -> "AnthropicLLM | None":
        """An LLM only if ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is set; otherwise None and the
        agent runs deterministically. (The SDK happily constructs a client with no credentials and
        only fails on the first request, so construction is not a usable check. For an
        `ant auth login` profile, build AnthropicLLM() explicitly.)"""
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return None
        return cls()
