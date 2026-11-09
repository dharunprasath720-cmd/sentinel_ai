"""Synthetic transaction generator with planted, deliberately non-trivial scenarios.

Scenarios (column `scenario`, evaluation-only, never a model feature):
  normal          - routine per-account activity
  burst           - rapid successive payments; both legitimate (label 0) and takeover-style (label 1)
  ring            - several accounts sharing one device paying one merchant in a short window (label 1)
  legit_unusual   - one large, rare, but legitimate purchase (label 0)
Some legitimate accounts also share a device (families), so a shared device alone is not fraud.
IDs are numeric/hashed and never reveal the scenario.
"""
import hashlib

import numpy as np
import pandas as pd

START = pd.Timestamp("2026-01-01", tz="UTC")
TYPES = ["PAYMENT", "TRANSFER", "CASH_OUT"]
METHODS = ["card", "wallet", "bank"]


def _h(seed: int, kind: str, k: int) -> str:
    return hashlib.sha1(f"{seed}-{kind}-{k}".encode()).hexdigest()[:12]


def generate(seed: int = 42, n_accounts: int = 500, days: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_merch = max(40, n_accounts // 6)
    n_rings = max(3, n_accounts // 100)
    n_fb = max(6, n_accounts // 20)  # takeover-style fraud bursts
    n_pairs = max(2, n_accounts // 25)
    n_b = max(2, n_accounts // 100)  # legitimate bursts
    n_lu = max(5, n_accounts // 25)

    mu = rng.normal(3.5, 0.6, n_accounts)
    sigma = rng.uniform(0.35, 0.7, n_accounts)
    rate = rng.uniform(0.4, 1.6, n_accounts)
    peak = rng.integers(8, 21, n_accounts)
    home = rng.integers(0, 12, n_accounts)
    favs = [rng.choice(n_merch, size=5, replace=False) for _ in range(n_accounts)]
    devices = [_h(seed, "dev", i) for i in range(n_accounts)]
    instruments = [_h(seed, "ins", i) for i in range(n_accounts)]

    perm = rng.permutation(n_accounts)
    for p in range(n_pairs):  # legitimate shared devices (families)
        devices[perm[2 * p + 1]] = devices[perm[2 * p]]
    pool = list(perm[2 * n_pairs:])
    ring_accts = [pool[r * 5:(r + 1) * 5] for r in range(n_rings)]
    burst_fraud = pool[n_rings * 5:n_rings * 5 + n_fb]
    # Fraud arrives continuously: spread fraud events across the horizon (one per stratum,
    # shuffled) so every chronological split contains fraud.
    n_events = n_rings + n_fb
    strata = 3 + (np.arange(n_events) + rng.uniform(0.1, 0.9, n_events)) * (days - 3) / n_events
    event_days = rng.permutation(strata.astype(int))

    rows: list[dict] = []
    normal_amounts: dict[int, list[float]] = {i: [] for i in range(n_accounts)}

    def add(i, ts, amount, merchant, device, typ, status, label, scenario):
        rows.append(dict(
            account_id=f"ACC_{i:05d}", merchant_id=f"M_{merchant:04d}", device_id=device,
            instrument_id=instruments[i], amount=round(max(1.0, float(amount)), 2),
            currency="USD", ts=ts, type=typ, payment_method=METHODS[i % 3],
            status=status, geo=f"R{home[i]:02d}", label=label, source="synthetic",
            business_id="demo_biz", scenario=scenario))

    def stamp(day, hour, minute=0.0):
        return START + pd.Timedelta(days=int(day), hours=int(hour), minutes=float(minute))

    # --- normal activity
    for i in range(n_accounts):
        n = rng.poisson(rate[i] * days)
        d = rng.integers(0, days, n)
        h = np.clip(rng.normal(peak[i], 2.5, n), 0, 23).astype(int)
        m = rng.uniform(0, 59, n)
        amt = np.exp(rng.normal(mu[i], sigma[i], n))
        use_fav = rng.random(n) < 0.9
        for k in range(n):
            merchant = favs[i][rng.integers(0, 5)] if use_fav[k] else rng.integers(0, n_merch)
            r = rng.random()
            status = "failed" if r < 0.03 else ("pending" if r < 0.04 else "completed")
            add(i, stamp(d[k], h[k], m[k]), amt[k], merchant, devices[i],
                TYPES[rng.choice(3, p=[0.7, 0.2, 0.1])], status, 0, "normal")
            normal_amounts[i].append(max(1.0, float(amt[k])))

    # --- bursts: some legitimate (label 0), some takeover-style (label 1)
    legit_burst = rng.choice(pool, size=n_b, replace=False)
    for i in legit_burst:
        day, base = rng.integers(0, days), rng.uniform(0, 50)
        for k in range(rng.integers(5, 9)):
            add(i, stamp(day, peak[i], base + rng.uniform(0, 10)), np.exp(mu[i]),
                favs[i][0], devices[i], "PAYMENT", "completed", 0, "burst")
    for k_ev, i in enumerate(burst_fraud):
        day, base = event_days[n_rings + k_ev], rng.uniform(0, 40)
        new_merch = rng.choice([m for m in range(n_merch) if m not in favs[i]])
        for k in range(7):
            add(i, stamp(day, rng.integers(2, 5), base + rng.uniform(0, 8)),
                np.exp(mu[i]) * rng.uniform(4, 8), new_merch, devices[i],
                "PAYMENT", "completed", 1, "burst")

    # --- coordinated rings
    for r, members in enumerate(ring_accts):
        dev, merchant = _h(seed, "ringdev", r), n_merch + r
        day, hour = event_days[r], rng.integers(0, 24)
        for i in members:
            for k in range(rng.integers(5, 7)):
                add(i, stamp(day, hour, rng.uniform(0, 100)), rng.uniform(150, 400),
                    merchant, dev, "PAYMENT", "completed", 1, "ring")

    # --- legitimate but unusual large purchases
    eligible = [i for i in range(n_accounts) if len(normal_amounts[i]) >= 5]
    for i in rng.choice(eligible, size=n_lu, replace=False):
        add(i, stamp(rng.integers(0, days), peak[i], rng.uniform(0, 59)),
            max(normal_amounts[i]) * rng.uniform(3, 8), rng.integers(0, n_merch),
            devices[i], "PAYMENT", "completed", 0, "legit_unusual")

    df = pd.DataFrame(rows)
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    df.insert(0, "external_id", [f"SYN{i:07d}" for i in range(len(df))])
    return df
