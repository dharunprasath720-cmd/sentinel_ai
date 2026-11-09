"""Detectors for two things an investigation narrative must never state as fact:

  * that fraud is ESTABLISHED (the system only ever has suspicion), and
  * that an ACTION HAS BEEN TAKEN (the system only recommends; humans approve).

Both work sentence by sentence on whitespace-normalised text, so newlines and double spaces do not
hide a claim. Hedged, negated, conditional or recommending sentences ("may be fraud", "not
confirmed fraud", "the account should be blocked") are allowed, as are descriptive uses such as
"fraud probability" or "fraud risk". The filters are deliberately conservative: a false positive
only makes the agent retry or fall back to the deterministic report.
"""
import re

_SENTENCE = re.compile(r"(?<=[.!?;])\s+")
_HEDGE = re.compile(
    r"\b(?:not|no|never|nothing|none|cannot|unconfirmed|unproven|unverified|without|suspect(?:ed)?|"
    r"possible|possibly|potential(?:ly)?|probable|probably|may|might|could|would|should|consider|"
    r"recommend\w*|propos\w*|suggest\w*|pending|awaiting|if|whether|appears?|seems?|indicat\w*|"
    r"consistent|resembl\w*|likely|suspicious)\b|n't", re.I)
_FRAUD = re.compile(r"\bfraud(?:ster|sters|ulent|ulently)?\b", re.I)
_FRAUDSTER = re.compile(r"^fraudsters?$", re.I)
_DESCRIPTIVE_AFTER = re.compile(
    r"\s+(?:probability|probabilities|risk|risks|score|scores|signal|signals|pattern|patterns|ring|rings|"
    r"detection|alert|alerts|investigation|investigations|case|cases|label|labels|model|models|analyst|"
    r"analysts|team|teams|prevention|rate|rates|indicator|indicators|exposure|loss|losses|type|types|"
    r"scenario|scenarios|cluster|clusters)\b", re.I)
_ESTABLISH = re.compile(
    r"\b(?:confirm(?:ed|s)?|prov(?:en|ed|es)|establish(?:ed|es)?|definite(?:ly)?|certain(?:ly)?|"
    r"clear(?:ly)?|undoubted(?:ly)?|verified|determined|unquestionabl\w+|obvious(?:ly)?)\b", re.I)
_COPULA_BEFORE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+\s+){0,2}$", re.I)

_VERB = (r"(?:blocked|frozen|froze|suspended|refunded|reversed|cancell?ed|locked|banned|terminated|"
         r"disabled|charged back)")
_AUX_ACTION = re.compile(rf"\b(?:has|have|had|was|were|is|are)\s+(?:(?:now|already|successfully|been|also)\s+)*{_VERB}\b", re.I)
_I_ACTION = re.compile(rf"\bI\s+(?:(?:have|had|already|just)\s+)*{_VERB}\b", re.I)
_SUBJECT_ACTION = re.compile(rf"\b(?:funds|account|card|payment|transaction)s?\s+(?:(?:is|are|was|were|now)\s+)*{_VERB}\b", re.I)


def _sentences(text: str):
    return [s for s in _SENTENCE.split(re.sub(r"\s+", " ", text or "").strip()) if s]


def asserts_fraud(text: str) -> bool:
    for sentence in _sentences(text):
        if _HEDGE.search(sentence):
            continue
        for m in _FRAUD.finditer(sentence):
            if _DESCRIPTIVE_AFTER.match(sentence[m.end():]):
                continue
            before, after = sentence[max(0, m.start() - 45):m.start()], sentence[m.end():m.end() + 30]
            if (_FRAUDSTER.match(m.group(0)) or _ESTABLISH.search(before) or _ESTABLISH.search(after)
                    or _COPULA_BEFORE.search(before)):
                return True
    return False


def claims_action_taken(text: str) -> bool:
    return any(not _HEDGE.search(s) and (_AUX_ACTION.search(s) or _I_ACTION.search(s) or _SUBJECT_ACTION.search(s))
               for s in _sentences(text))
