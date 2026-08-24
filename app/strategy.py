"""策略參數(六大入市指標 + 即日買賣規則的數值化定義)"""
from __future__ import annotations

import typing
from dataclasses import dataclass, field, fields, asdict


def _cast(v, ann):
    """依欄位註解強制轉型 — 防 config.yaml/best_params.json 混入字串數值。"""
    if ann is bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on", "是")
    try:
        if ann is int and not isinstance(v, bool):
            return int(float(str(v).strip()))
        if ann is float and not isinstance(v, bool):
            return float(str(v).strip())
    except (TypeError, ValueError):
        return 0 if ann is int else 0.0
    return v


@dataclass
class StrategyParams:
    # ① 成交量放大
    vol_ma_window: int = 20
    vol_expand_ratio: float = 2.0
    # ② 均線向上、價格在均線上方
    ema_fast: int = 20
    ema_slow: int = 50
    # ③ 布林帶開口
    bb_window: int = 20
    bb_k: float = 2.0
    bb_width_pctile: float = 80.0
    # ④ 斐波那契回調
    fib_lookback: int = 60
    fib_levels: list = field(default_factory=lambda: [0.382, 0.618])
    fib_tolerance_pct: float = 1.5
    # ⑤ RSI 50 附近止穩回升
    rsi_window: int = 14
    rsi_lo: float = 45.0
    rsi_hi: float = 58.0
    # ⑥ MACD 能量柱縮短 + 金叉
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_shrink_bars: int = 3
    macd_cross_lookback: int = 5
    # 觸發方式
    require_all: bool = True
    min_score: int = 5

    @classmethod
    def from_dict(cls, d: dict | None) -> "StrategyParams":
        names = {f.name for f in fields(cls)}
        hints = typing.get_type_hints(cls)
        d = d or {}
        return cls(**{k: _cast(v, hints.get(k)) for k, v in d.items()
                      if k in names})

    def to_dict(self) -> dict:
        return asdict(self)

    def overlay(self, overrides: dict) -> "StrategyParams":
        """以調叟產生的覆蓋值產生新參數(不修改自身);值會強制轉型。"""
        merged = self.to_dict()
        names = {f.name for f in fields(self)}
        merged.update({k: v for k, v in (overrides or {}).items() if k in names})
        return StrategyParams.from_dict(merged)


@dataclass
class TradeRules:
    take_profit_pct: float = 5.0   # ★用戶指定:+5% 以上利潤即提示賣出
    stop_loss_pct: float = 3.0
    force_eod_exit: bool = True
    eod_warn_minutes: float = 10.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "TradeRules":
        names = {f.name for f in fields(cls)}
        hints = typing.get_type_hints(cls)
        return cls(**{k: _cast(v, hints.get(k)) for k, v in (d or {}).items()
                      if k in names})
