from types import SimpleNamespace as NS

import anthropic

from sentinel.agent import llm as llm_mod
from sentinel.agent.llm import FALLBACK_BETA, MODEL, AnthropicLLM
from sentinel.agent.report import narrative_json_schema


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return NS(content=[], stop_reason="end_turn")


def test_model_is_opus_5_5_and_fallbacks_are_on_by_default():
    c = RecordingClient()
    AnthropicLLM(client=c).create(max_tokens=100, messages=[{"role": "user", "content": "hi"}])
    kw = c.calls[0]
    assert MODEL == "claude-opus-5-5" and kw["model"] == MODEL
    assert FALLBACK_BETA in kw["betas"] and kw["extra_body"] == {"fallbacks": "default"}
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(kw)


def test_fallbacks_can_be_switched_off_and_existing_betas_are_kept():
    c = RecordingClient()
    AnthropicLLM(client=c, use_fallbacks=False).create(max_tokens=1, messages=[], betas=["x"])
    assert "extra_body" not in c.calls[0] and c.calls[0]["betas"] == ["x"]


def test_from_env_returns_none_when_credentials_are_missing(monkeypatch):
    def boom(*a, **k):
        raise anthropic.AnthropicError("no credentials")
    monkeypatch.setattr(anthropic, "Anthropic", boom)
    assert AnthropicLLM.from_env() is None


def test_from_env_builds_a_client_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    out = AnthropicLLM.from_env()
    assert isinstance(out, AnthropicLLM) and out.model == MODEL


def test_structured_output_schema_has_no_unsupported_validators():
    schema = narrative_json_schema()
    blob = str(schema)
    for banned in ("minLength", "maxLength", "minItems", "maxItems", "'pattern'", "'default'"):
        assert banned not in blob
    assert schema["additionalProperties"] is False and "classification" in schema["properties"]
    assert set(schema["$defs"]["Finding"]["required"]) == {"claim", "evidence_ids"}
