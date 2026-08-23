"""5年回測引擎(日K模擬即日鮮)
訊號在 T 日收盤確認 → T+1 日開盤進場 → 當日內 +5% 目標 / 止損 / 收盤平倉。
含成本、樂觀/悲觀同日雙觸發處理、獲利因子等完整績效指標。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


# ---------------------------------------------------------------- 預計算
def precompute(df: pd.DataFrame, p) -> dict:
    """把與閾值無關的指標一次算好,供參數網格高速重用。"""
    c, o = df["close"], df["open"]
    h, l = df["high"], df["low"]
    v = df["volume"].astype(float)

    vr = (v / ind.sma(v, p.vol_ma_window)).values
    up_bar = ((c > o) & (c > c.shift(1))).values

    ef, es = ind.ema(c, p.ema_fast), ind.ema(c, p.ema_slow)
    trend = ((ef > es) & (c > es) & (ef >= ef.shift(3))).values

    mid, _, _, width = ind.bollinger(c, p.bb_window, p.bb_k)
    wrank = ind.rolling_pctile_rank(width, p.bb_window * 3)
    # 壓縮後開口:squeeze 存在 + 帶寬轉升 + 站上中軌
    w_min = width.rolling(10, min_periods=5).min()
    sq_line = width.rolling(60, min_periods=20).quantile(
        max(0.05, (100 - p.bb_width_pctile) / 100.0))
    had_squeeze = (w_min <= sq_line).values
    bb_width_up = (width > width.shift(1)).values
    above_mid = (c > mid).values

    rsi = ind.wilder_rsi(c, p.rsi_window).values
    rsi_up = np.concatenate([[False], rsi[1:] > rsi[:-1]])

    _, _, hist = ind.macd_parts(c, p.macd_fast, p.macd_slow, p.macd_signal)
    hv = hist.values
    macd_ok = np.zeros(len(c), dtype=bool)
    for i in range(35, len(c)):
        ok, _ = ind.macd_trigger(hv[max(0, i - 40):i + 1],
                                 p.macd_shrink_bars, p.macd_cross_lookback)
        macd_ok[i] = ok

    fib_dist = np.full(len(c), np.nan)
    fib_name = [""] * len(c)
    for i in range(p.fib_lookback + 2, len(c)):
        sl_ = max(0, i - p.fib_lookback) + 1
        sw = ind.swing_fib(h.iloc[sl_:i + 1], l.iloc[sl_:i + 1],
                           c.iloc[i:i + 1], i - sl_ + 1)
        if sw and sw["valid"]:
            cl = float(df["close"].iloc[i])
            best = min((abs(cl - px) / px * 100.0, nm)
                       for nm, px in sw["levels"].items())
            fib_dist[i] = best[0]
            fib_name[i] = best[1]

    warm = ind.warmup_bars(p)
    return {
        "df": df, "warm": warm, "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": o.values, "high": h.values, "low": l.values, "close": c.values,
        "vr": vr, "up_bar": up_bar, "trend": trend,
        "had_squeeze": had_squeeze, "bb_width_up": bb_width_up, "above_mid": above_mid,
        "bb_rank": wrank.values,
        "rsi": rsi, "rsi_up": rsi_up,
        "macd_ok": macd_ok, "fib_dist": fib_dist, "fib_name": fib_name,
    }


def eval_masks(pre: dict, p) -> np.ndarray:
    """依參數組合出六條件買入遮罩(向量化,極快)。"""
    vol = pre["vr"] >= p.vol_expand_ratio
    fib = np.nan_to_num(pre["fib_dist"], nan=1e9) <= p.fib_tolerance_pct
    rsi = (pre["rsi"] >= p.rsi_lo) & (pre["rsi"] <= p.rsi_hi) & pre["rsi_up"]
    bb = pre["had_squeeze"] & pre["bb_width_up"] & pre["above_mid"]
    core = (vol & pre["up_bar"] & pre["trend"] & bb & fib & rsi & pre["macd_ok"])
    if p.require_all:
        mask = core
    else:
        parts = [vol & pre["up_bar"], pre["trend"], bb, fib, rsi, pre["macd_ok"]]
        score = sum(x.astype(np.int8) for x in parts)
        mask = score >= p.min_score
    mask[:pre["warm"] + 1] = False
    return mask


# ---------------------------------------------------------------- 模擬
def simulate(pre: dict, mask: np.ndarray, tp_pct: float, sl_pct: float,
             cost_pct: float = 0.15, pessimistic: bool = True) -> list[dict]:
    """T日訊號 → T+1 開盤進場;當日 TP/SL/收盤出場。"""
    o, h, l, c = pre["open"], pre["high"], pre["low"], pre["close"]
    dates = pre["dates"]
    trades = []
    n = len(mask)
    i = pre["warm"] + 1
    while i < n:
        if mask[i - 1]:                    # 訊號在 i-1 收盤 → i 日開盤進場
            entry = float(o[i])
            if not np.isfinite(entry) or entry <= 0:
                i += 1
                continue
            tp_px = entry * (1 + tp_pct / 100.0)
            sl_px = entry * (1 - sl_pct / 100.0)
            hi_, lo_, op_ = float(h[i]), float(l[i]), float(o[i])
            hit_tp, hit_sl = hi_ >= tp_px, lo_ <= sl_px
            if hit_tp and hit_sl and pessimistic:
                px, why = min(op_, sl_px), "stop-loss"
            elif hit_tp:
                px, why = max(op_, tp_px), "take-profit"      # 跳空高開以開盤價成交
            elif hit_sl:
                px, why = min(op_, sl_px), "stop-loss"
            else:
                px, why = float(c[i]), "eod-close"
            ret = (px - entry) / entry * 100.0 - cost_pct
            trades.append({"date": dates[i], "ret_pct": round(ret, 3),
                           "reason": why, "entry": round(entry, 3),
                           "exit": round(px, 3)})
        i += 1                             # 即日平倉,翌日可依新訊號再進場
    return trades


# ---------------------------------------------------------------- 績效指標
def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "profit_factor": 0.0, "win_rate": 0.0,
                "total_return_pct": 0.0, "max_drawdown_pct": 0.0}
    rets = np.array([t["ret_pct"] for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    pf = (gp / gl) if gl > 1e-9 else (float("inf") if gp > 0 else 0.0)

    # 權益曲線:同日多筆取平均報酬,逐日複利
    by_day: dict[str, list[float]] = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(t["ret_pct"])
    daily = [np.mean(v) for _, v in sorted(by_day.items())]
    eq = np.cumprod(1 + np.asarray(daily) / 100.0)
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / peak).max() * 100.0) if len(eq) else 0.0
    total_ret = float((eq[-1] - 1) * 100.0) if len(eq) else 0.0
    days = max(len(eq), 1)
    cagr = float(((eq[-1]) ** (244.0 / days) - 1) * 100.0) if len(eq) else 0.0

    return {
        "trades": int(len(rets)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(rets) * 100.0, 2),
        "gross_profit_pct": round(gp, 2),
        "gross_loss_pct": round(gl, 2),
        "profit_factor": round(min(pf, 999.0), 3) if np.isfinite(pf) else 999.0,
        "avg_win_pct": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss_pct": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "expectancy_pct": round(float(rets.mean()), 3),
        "total_return_pct": round(total_ret, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trade_days": days,
    }


def equity_curve(trades: list[dict]) -> list[list]:
    by_day: dict[str, list[float]] = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(t["ret_pct"])
    eq, val = [], 1.0
    for d in sorted(by_day):
        val *= 1 + float(np.mean(by_day[d])) / 100.0
        eq.append([d, round(val, 5)])
    return eq


# ---------------------------------------------------------------- 對外介面
def run_portfolio(frames: dict[str, pd.DataFrame], p, tp_pct: float,
                  sl_pct: float, cost_pct: float = 0.15) -> dict:
    """多股票合併回測 → 績效 + 每股明細。"""
    all_trades: list[dict] = []
    per_symbol = {}
    for sym, df in frames.items():
        if df is None or len(df) < ind.warmup_bars(p) + 30:
            continue
        pre = precompute(df, p)
        mask = eval_masks(pre, p)
        trades = simulate(pre, mask, tp_pct, sl_pct, cost_pct)
        for t in trades:
            t["symbol"] = sym
        all_trades.extend(trades)
        per_symbol[sym] = compute_metrics(trades)
    all_trades.sort(key=lambda t: t["date"])
    metrics = compute_metrics(all_trades)
    metrics["per_symbol"] = per_symbol
    return {"metrics": metrics, "trades": all_trades,
            "equity": equity_curve(all_trades)}


def split_frames(frames: dict, ratio: float):
    train, val = {}, {}
    for sym, df in frames.items():
        k = int(len(df) * ratio)
        if k < 80 or len(df) - k < 40:
            continue
        train[sym] = df.iloc[:k]
        val[sym] = df.iloc[k:]
    return train, val
