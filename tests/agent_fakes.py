"""Stand-ins for Claude (no network). Test code only."""
import json
import re
from types import SimpleNamespace as NS


def text_block(text):
    return NS(type="text", text=text)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def reply(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=10))


class ScriptedLLM:
    """Returns the scripted responses in order (the last one repeats) and records every call."""
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        kwargs["messages"] = list(kwargs["messages"])  # snapshot: the agent keeps appending
        self.calls.append(kwargs)
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def narrative(skeleton, **overrides):
    """A valid model-written narrative built from the evidence skeleton the agent sent."""
    part = {k: skeleton[k] for k in ("model_findings", "behavioural_findings", "graph_findings",
                                     "supporting_evidence", "contradictory_evidence", "missing_information",
                                     "recommended_next_steps", "confidence", "classification")}
    part["summary"] = f"Risk level {skeleton['risk_assessment']['risk_level']}: see cited evidence."
    part.update(overrides)
    return part


def skeleton_in(prompt: str) -> dict:
    return json.loads(re.search(r"<evidence>\n(.*?)\n</evidence>", prompt, re.S).group(1))["skeleton"]


class EchoNarrativeLLM:
    """Reads the evidence out of the prompt and answers with a valid narrative (like a good model)."""
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        sk = skeleton_in(kwargs["messages"][0]["content"])
        return reply(text_block(json.dumps(narrative(sk))))
