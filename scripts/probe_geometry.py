"""臨時探針v3:隨機搜索形態參數空間,找出六項同時成立的組合"""
import math
import random
import sys

sys.path.insert(0, ".")
import pandas as pd

from app.indicators import evaluate, warmup_bars
from app.strategy import StrategyParams

P = StrategyParams(vol_expand_ratio=2.0, fib_tolerance_pct=2.5,
                   bb_width_pctile=70, fib_levels=[0.236, 0.382],
                   rsi_lo=45, rsi_hi=58)
WARM = warmup_bars(P)


def build(r):
    px = 100.0
    prices, vols = [], []
    for i in range(80):
        prices.append(100 * (1 + 0.0015 * math.sin(i / 3.1)))
        vols.append(1_000_000)
    n_rally = r["rally_n"]
    for _ in range(n_rally):
        px *= 1 + r["rally_rate"]
        prices.append(px)
        vols.append(1_000_000 * (1 + 0.2 * _ / n_rally))
    hi = max(prices[-8:])
    # legA 深腳
    for _ in range(r["legA_n"]):
        px *= 1 - r["legA_drop"]
        prices.append(px)
        vols.append(1_250_000)
    la_low = px
    # bounce
    for _ in range(r["bounce_n"]):
        px *= 1 + r["bounce_rate"]
        prices.append(px)
        vols.append(1_150_000)
    btop = px
    # legB 淺腳(墊高)
    tgt = la_low + (btop - la_low) * r["legB_frac"]
    for _ in range(r["legB_n"]):
        px += (tgt - px) * 0.35
        prices.append(px)
        vols.append(950_000)
    # resume
    for _ in range(r.get("rs_n", 18)):
        px *= 1 + r["rs_rate"]
        prices.append(px)
        vols.append(2_900_000 * (1 + 0.04 * _))
    rows = []
    prev = prices[0]
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="min")
    for i, c in enumerate(prices):
        o = prev
        rows.append((o, max(o, c) * 1.0012, min(o, c) * 0.9988, c, float(vols[i])))
        prev = c
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=idx)


random.seed(11)
found = []
for trial in range(220):
    r = {
        "rally_rate": random.uniform(0.0018, 0.004),
        "rally_n": random.randint(70, 120),
        "legA_drop": random.uniform(0.0025, 0.007),
        "legA_n": random.randint(6, 14),
        "bounce_rate": random.uniform(0.002, 0.006),
        "bounce_n": random.randint(4, 10),
        "legB_frac": random.uniform(0.15, 0.75),
        "legB_n": random.randint(5, 12),
        "rs_rate": random.uniform(0.003, 0.010),
        "rs_n": 18,
    }
    df = build(r)
    hits = 0
    first = None
    for i in range(WARM, len(df)):
        res = evaluate(df.iloc[:i + 1], P)
        if res["buy"]:
            hits += 1
            if first is None:
                first = i
    if hits:
        found.append((hits, first, {k: round(v, 4) if isinstance(v, float) else v
                                    for k, v in r.items()}))
        if len(found) >= 5:
            break

print(f"found {len(found)} viable geometries")
for h, f, r in found:
    print(f"hits={h} first@{f} {r}")
if not found:
    print("none — need engine-param relaxation")
