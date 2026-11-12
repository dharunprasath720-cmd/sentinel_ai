## Inspiration

Fraud tools often fail in one of two ways. Some are a black box that blocks a customer and gives no reason. Others are a long pile of alerts that nobody can finish.

We wanted to build a small system that must show its reasoning at every step. We also wanted an AI helper that may only say what it can prove. So the idea was simple: **a fraud tool you can audit.**

## What it does

SENTINEL AI scores each payment as it arrives and helps an analyst decide what to do.

- It gives every payment a risk score from seven signals.
- It finds rings of accounts that share a device and pay the same merchant within minutes.
- It explains each score with named risk factors and SHAP values.
- It takes **real PayPal Sandbox payments** by webhook and scores them live.
- It uses **Claude** to write case reports and answer questions. Every claim must cite an evidence id that a tool returned.
- It never blocks anything by itself. A person decides, and every action goes into an audit log.

The risk score is plain arithmetic, so the same input always gives the same answer:

    risk = w1*s1 + w2*s2 + ... + w7*s7
    (the 7 weights add up to 1, and each signal s is between 0 and 1)

Here each s is one signal (for example the model probability or the graph risk), and each w is its weight from a versioned policy file. A score of 0.20 or more is MODERATE, 0.40 or more is HIGH, and 0.65 or more is CRITICAL.

## How we built it

- **Backend:** Python 3.11, FastAPI, SQLAlchemy and SQLite.
- **Models:** logistic regression, LightGBM and Isolation Forest. We calibrated the probabilities and used SHAP for explanations.
- **Graph:** NetworkX with Louvain community detection to find account clusters.
- **PayPal:** OAuth, Orders v2, and `PAYMENT.CAPTURE.COMPLETED` webhooks. Each webhook is checked with PayPal's signature verification API before we trust it.
- **AI:** Claude calls ten read-only tools. Its answer is checked, and replies that state fraud as a fact are withheld.
- **Frontend:** React, TypeScript, Vite, Recharts and React Flow.
- **AG Grid:** the live feed and the alert triage list are AG Grid tables. Rows update by transaction id, so sorting and filters stay in place while new events stream in. We used only the free Community edition.

One feature extractor serves training, batch scoring and live scoring. Each feature uses only history from *before* the event, so the model never sees the future.

We built it test-first: 412 backend tests and 124 frontend tests. We also wrote a script that records the demo video from the real app.

## Challenges we ran into

- **Making the data hard enough.** Our first fake data was too easy, and the model scored a perfect PR-AUC of 1.000. That was a warning sign, not a win. We made fraud look like normal behaviour and added honest cases such as shared family devices and flash sales. The scores then dropped to realistic values: the LightGBM model reached a PR-AUC of 0.739, with recall 0.479 and precision 0.767.
- **Bugs that only real services showed.**
  - The first live Claude call failed because a tool schema used a rule the API rejects.
  - The first real webhook showed that a PayPal capture has no payer identity. We score it as its own account instead of mixing it into someone else's history.
  - Filming the demo showed that live-flagged clusters could not be opened in the graph view.
- **Keeping the AI honest.** Simple keyword filters for the word "fraud" were easy to get around. So we check claims sentence by sentence, in both reports and chat.
- **A steady live table.** Filters had to survive streaming rows. Keying each row by transaction id fixed it.

## Accomplishments that we're proud of

- A real PayPal Sandbox payment goes from a signed webhook to a live score on the dashboard.
- Claude's reports cite their evidence, and the system rejects answers that overclaim.
- All five planted fraud rings were flagged. On our synthetic data, 79% of fraud reached HIGH or above, with 89% precision at that level.
- Live scoring takes about 81 ms at the median and 162 ms at the 95th percentile.
- We tested everything and wrote down what we did *not* verify, so the README is honest about its limits.

## What we learned

- **Honest tests matter.** A perfect score usually means the test is too easy.
- **Real integrations find real bugs.** Mocks passed, but the live services showed problems we had not seen.
- **Explainable beats clever.** A plain weighted sum is easier to trust, test and explain than a hidden rule.
- **AI needs rails.** Claude is useful when it can only read, must cite its evidence, and cannot take action.
- **Look at both numbers.** Precision and recall tell different stories:

    precision = true alerts / all alerts raised
    recall    = fraud caught / all fraud that exists

A tool that misses fraud can still look good on one number alone.

We want to be clear about the limits. About a fifth of planted fraud is missed. The data is synthetic. PayPal is Sandbox only, and we never ran refunds. This is a hackathon prototype, not a production system.

## What's next for Sentinel AI

- An approved-case refund flow through PayPal.
- Testing on a public fraud dataset.
- Rate limiting, and Postgres instead of SQLite.
