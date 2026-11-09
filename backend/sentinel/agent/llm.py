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
from typing import Protocol

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

    def create(self, **kwargs):
        params = dict(kwargs)
        if self.use_fallbacks:
            params["betas"] = [*params.get("betas", []), FALLBACK_BETA]
            params["extra_body"] = {**params.get("extra_body", {}), "fallbacks": "default"}
        return self.client.beta.messages.create(model=self.model, **params)

    @classmethod
    def from_env(cls) -> "AnthropicLLM | None":
        """An LLM if credentials are available, else None (the agent then runs deterministically)."""
        try:
            return cls()
        except Exception:  # noqa: BLE001  (missing credentials raise at construction)
            return None
