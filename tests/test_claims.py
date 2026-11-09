import pytest

from sentinel.agent.claims import asserts_fraud, claims_action_taken

ASSERTS_FRAUD = [
    "This transaction is fraud.", "Fraud confirmed.", "The merchant is a fraudster.", "It is definitely a fraud.",
    "definitely a fraud", "It was confirmed as fraud by the model.", "This is proven fraud.", "confirmed\nfraud",
    "confirmed  fraud", "The account is fraudulent.", "We have established that this is fraud.",
    "This payment is clearly fraudulent.", "Confirmed fraud.", "These are fraudsters.",
]
NOT_AN_ASSERTION = [
    "This is not confirmed fraud.", "It isn't confirmed fraud, only suspicious.", "No fraud has been established.",
    "The pattern is consistent with fraud but unconfirmed.", "Possible fraud; needs review.",
    "The model's fraud probability for this transaction is 0.91 (risk level HIGH, composite score 0.73).",
    "Fraud risk is high.", "The fraud score is 0.8 and the transaction is suspicious.", "This may be fraud.",
    "Suspected fraud ring.", "We cannot say whether this is fraud.", "Unconfirmed fraud signals were found.",
    "Scores are model-based suspicion, not a confirmed outcome.",
    "No confirmed outcome (chargeback or customer confirmation) is available: this is a suspicion, not a verdict.",
    "Cannot rule out that this is not confirmed fraud.", "", "A routine grocery payment.",
]
ACTION_CLAIMS = [
    "The account has been blocked.", "I have blocked the account and frozen the funds.", "The payment was refunded.",
    "Funds frozen.", "The card is now suspended.", "I blocked the card.", "The transaction has already been reversed.",
    "Your account was locked.",
]
NOT_AN_ACTION_CLAIM = [
    "A temporary hold is recommended for analyst approval; nothing is executed automatically.",
    "The account should be blocked if the analyst agrees.", "Consider suspending the card.",
    "Nothing was blocked; this is a recommendation.", "No action has been taken.",
    "If confirmed, the account could be frozen.", "Request additional verification from the account holder before further activity.",
    "Hold the decision until approval.", "",
]


@pytest.mark.parametrize("text", ASSERTS_FRAUD)
def test_fraud_assertions_are_caught_however_they_are_phrased(text):
    assert asserts_fraud(text), text


@pytest.mark.parametrize("text", NOT_AN_ASSERTION)
def test_hedged_negated_or_descriptive_mentions_are_allowed(text):
    assert not asserts_fraud(text), text


@pytest.mark.parametrize("text", ACTION_CLAIMS)
def test_claims_that_an_action_was_executed_are_caught(text):
    assert claims_action_taken(text), text


@pytest.mark.parametrize("text", NOT_AN_ACTION_CLAIM)
def test_recommendations_and_negations_are_not_action_claims(text):
    assert not claims_action_taken(text), text
