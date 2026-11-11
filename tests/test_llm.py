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


def test_token_usage_is_logged_without_logging_content(caplog):
    import logging
    c = RecordingClient()
    c.beta.messages.create = lambda **kw: NS(content=[NS(type="text", text="SECRET-CONTENT")], stop_reason="end_turn",
                                             usage=NS(input_tokens=1234, output_tokens=56,
                                                      cache_read_input_tokens=7, cache_creation_input_tokens=0))
    caplog.set_level(logging.INFO)
    AnthropicLLM(client=c).create(max_tokens=10, messages=[{"role": "user", "content": "PRIVATE-PROMPT"}])
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "sentinel.llm")
    assert "input=1234" in text and "output=56" in text and "cache_read=7" in text
    assert "SECRET-CONTENT" not in text and "PRIVATE-PROMPT" not in text


def test_from_env_returns_none_without_credentials_even_though_the_sdk_would_construct(monkeypatch):
    # the SDK builds a client with no credentials and only fails on the first request; we must not
    # report such an agent as "configured"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    anthropic.Anthropic()  # constructing really does not raise
    assert AnthropicLLM.from_env() is None


def test_from_env_accepts_an_auth_token_too(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-not-real")
    assert isinstance(AnthropicLLM.from_env(), AnthropicLLM)


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


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_tool_schemas_use_only_validators_the_api_accepts():
    """Found by the first live chat call: strict tools reject minItems other than 0/1 and these
    keywords, with a 400 that turned every chat into a 502. Argument limits are enforced by
    ToolBox.dispatch instead."""
    from sentinel.agent.tools import TOOL_SCHEMAS
    for tool in TOOL_SCHEMAS:
        for node in _walk(tool["input_schema"]):
            for banned in ("minLength", "maxLength", "maxItems", "pattern", "default"):
                assert banned not in node, f"{tool['name']} uses {banned}"
            assert node.get("minItems", 0) in (0, 1), f"{tool['name']} uses minItems={node.get('minItems')}"
