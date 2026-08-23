"""六大入市指標引擎
① 成交量放大   ② 均線多頭排列+價在均線上   ③ 布林帶開口
④ 斐波那契 38.2%/61.8% 回調到位              ⑤ RSI 50 附近止穩回升
⑥ MACD 能量柱縮短 + 金叉
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLAG_LABELS = {
    "vol": "① 成交量放大",
    "trend": "② 均線向上·價在均線上方",
    "bb": "③ 布林帶開口",
    "fib": "④ 回調至斐波 38.2/61.8",
    "rsi": "⑤ RSI 50 附近止穩回升",
    "macd": "⑥ MACD 縮柱·金叉",
}
FLAG_KEYS = list(FLAG_LABELS.keys())


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


# ---------------------------------------------------------------- 基礎指標
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(2, n // 2)).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def macd_parts(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = close.rolling(n, min_periods=n // 2).mean()
    sd = close.rolling(n, min_periods=n // 2).std(ddof=0)
    up = mid + k * sd
    lo = mid - k * sd
    width = (up - lo) / mid * 100.0
    return mid, up, lo, width


def rolling_pctile_rank(s: pd.Series, w: int) -> pd.Series:
    """滾動百分位:當前值在過去 w 根中的排名(0-100)。"""
    def _rk(a: np.ndarray) -> float:
        cur = a[-1]
        if not np.isfinite(cur):
            return np.nan
        return float(np.mean(a <= cur) * 100.0)
    return s.rolling(w, min_periods=max(10, w // 3)).apply(_rk, raw=True)


# ---------------------------------------------------------------- 斐波那契擺動
def swing_fib(high: pd.Series, low: pd.Series, close: pd.Series,
              lookback: int, levels=(0.382, 0.618)) -> dict | None:
    """由回看窗內最低點起,取其後最高點作為上升推動浪,
    計算 38.2% / 61.8% 回調支撐位。價格須處於 lo~hi 之間才算有效回調。"""
    h = high.iloc[-lookback:]
    l = low.iloc[-lookback:]
    if len(l) < 5:
        return None
    li = int(np.argmin(l.values))
    lo = float(l.iloc[li])
    seg_h = h.iloc[li:]
    if len(seg_h) < 2:
        return None
    hi_i = int(np.argmax(seg_h.values))
    hi = float(seg_h.iloc[hi_i])
    if hi <= lo or hi_i == 0:
        return None
    cl = float(close.iloc[-1])
    rng = hi - lo
    lvls = {f"{r * 100:.1f}%": hi - rng * r for r in levels}
    retrace = (hi - cl) / rng * 100.0 if cl < hi else 0.0
    return {"lo": lo, "hi": hi, "levels": lvls,
            "retrace_pct": retrace, "valid": bool(lo <= cl <= hi)}


# ---------------------------------------------------------------- MACD 觸發
def macd_trigger(hv: np.ndarray, shrink_n: int, cross_lookback: int):
    """金叉出現(近 lookback 根內 由負轉正),或能量柱連續縮短且仍在收斂。"""
    hv = np.asarray(hv, dtype=float)
    hv = hv[np.isfinite(hv)]
    need = max(shrink_n + 2, cross_lookback + 2)
    if len(hv) < need:
        return False, "insufficient-data"
    tail = hv[-(cross_lookback + 1):]
    crossed = any(tail[i - 1] < 0 <= tail[i] for i in range(1, len(tail)))
    seg = hv[-(shrink_n + 1):]
    shrink = all(abs(seg[i]) <= abs(seg[i - 1]) + 1e-12 for i in range(1, len(seg)))
    rising = hv[-1] > hv[-2]
    ok = bool(rising and (crossed or (shrink and hv[-1] < 0)))
    note = "golden-cross" if crossed else ("shrinking-hist" if shrink else "none")
    return ok, note


# ---------------------------------------------------------------- 綜合評估
WARMUP_EXTRA = 10

def warmup_bars(p) -> int:
    return max(p.ema_slow, p.fib_lookback, p.bb_window, p.vol_ma_window,
               p.macd_slow + p.macd_signal) + WARMUP_EXTRA


def evaluate(df: pd.DataFrame, p) -> dict:
    """對最新一根K線評估六大條件。df 需含 open/high/low/close/volume。"""
    res = {"ready": False, "flags": {k: False for k in FLAG_KEYS},
           "score": 0, "buy": False, "label": {}, "metrics": {}, "close": None}
    if df is None or len(df) == 0:
        return res
    if len(df) < warmup_bars(p):
        return res
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < warmup_bars(p):
        return res
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    v = df["volume"].astype(float)

    # ① 成交量放大:量 > N倍均量,且為上升K線
    vr = v / sma(v, p.vol_ma_window)
    vr_last = _f(vr.iloc[-1])
    up_bar = bool(c.iloc[-1] > o.iloc[-1] and c.iloc[-1] > c.iloc[-2])
    res["flags"]["vol"] = bool(vr_last is not None and vr_last >= p.vol_expand_ratio and up_bar)
    res["metrics"]["vol_ratio"] = round(vr_last, 2) if vr_last else None

    # ② 均線向上、價格在均線上方
    ef, es = ema(c, p.ema_fast), ema(c, p.ema_slow)
    ef_l, es_l = _f(ef.iloc[-1]), _f(es.iloc[-1])
    rising = ef.iloc[-1] >= ef.iloc[-4]
    res["flags"]["trend"] = bool(ef_l and es_l and ef_l > es_l and c.iloc[-1] > es_l and rising)
    res["metrics"]["ema_fast"] = round(ef_l, 2) if ef_l else None
    res["metrics"]["ema_slow"] = round(es_l, 2) if es_l else None

    # ③ 布林帶開口:近端出現過壓縮(squeeze)後帶寬轉向擴張,且價在中軌上方
    mid, _, _, width = bollinger(c, p.bb_window, p.bb_k)
    w_min = width.rolling(10, min_periods=5).min()
    sq_line = width.rolling(60, min_periods=20).quantile(
        max(0.05, (100 - p.bb_width_pctile) / 100.0))
    had_squeeze = bool((w_min.iloc[-1] <= sq_line.iloc[-1]))
    w_now, w_prev = _f(width.iloc[-1]), _f(width.iloc[-2])
    res["flags"]["bb"] = bool(had_squeeze and w_now and w_prev and w_now > w_prev
                              and _f(mid.iloc[-1]) and c.iloc[-1] > mid.iloc[-1])
    rank = rolling_pctile_rank(width, p.bb_window * 3)
    rk = _f(rank.iloc[-1])
    res["metrics"]["bb_width_pctile"] = round(rk) if rk is not None else None
    res["metrics"]["bb_squeeze"] = had_squeeze

    # ④ 回調至斐波那契 38.2% 或 61.8%
    sw = swing_fib(h, l, c, p.fib_lookback, tuple(p.fib_levels))
    best = None
    if sw:
        cl = float(c.iloc[-1])
        if sw["valid"]:
            for nm, px in sw["levels"].items():
                d = abs(cl - px) / px * 100.0
                if best is None or d < best[1]:
                    best = (nm, d, px)
    res["flags"]["fib"] = bool(best and best[1] <= p.fib_tolerance_pct)
    if best:
        res["metrics"].update({"fib_name": best[0], "fib_level": round(best[2], 2),
                               "fib_dist_pct": round(best[1], 2)})
    if sw:
        res["metrics"]["swing_low"] = round(sw["lo"], 2)
        res["metrics"]["swing_high"] = round(sw["hi"], 2)

    # ⑤ RSI 在 50 附近止穩並重新向上
    r = wilder_rsi(c, p.rsi_window)
    rv, rv2 = _f(r.iloc[-1]), _f(r.iloc[-2])
    res["flags"]["rsi"] = bool(rv is not None and rv2 is not None
                               and p.rsi_lo <= rv <= p.rsi_hi and rv > rv2)
    res["metrics"]["rsi"] = round(rv, 1) if rv is not None else None

    # ⑥ MACD 能量柱縮短 + 金叉
    _, _, hist = macd_parts(c, p.macd_fast, p.macd_slow, p.macd_signal)
    ok, note = macd_trigger(hist.values, p.macd_shrink_bars, p.macd_cross_lookback)
    res["flags"]["macd"] = ok
    res["metrics"]["macd_hist"] = _f(hist.iloc[-1])
    res["metrics"]["macd_note"] = note

    score = sum(1 for k in FLAG_KEYS if res["flags"][k])
    res["score"] = score
    res["buy"] = (score == len(FLAG_KEYS)) if p.require_all else (score >= p.min_score)
    res["label"] = {FLAG_LABELS[k]: res["flags"][k] for k in FLAG_KEYS}
    res["ready"] = True
    res["close"] = _f(c.iloc[-1])
    return res
