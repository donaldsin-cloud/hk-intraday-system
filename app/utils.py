"""共用工具:時區/交易時段/日誌(支援港股與美股雙市場)"""
from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from .config import LOG_DIR, market_of

HKT = ZoneInfo("Asia/Hong_Kong")
MARKET_TZ = {
    "hk": ZoneInfo("Asia/Hong_Kong"),
    "us": ZoneInfo("America/New_York"),   # 自動處理冬/夏令時間
}
DEFAULT_SESSIONS = {
    "hk": [("09:30", "12:00"), ("13:00", "16:00")],
    "us": [("09:30", "16:00")],
}


def now_hkt() -> datetime:
    return datetime.now(HKT)


def now_in(market: str) -> datetime:
    return datetime.now(MARKET_TZ.get(market, HKT))


def today_str() -> str:
    return now_hkt().strftime("%Y-%m-%d")


def _parse_sessions(cfg, market: str) -> list[tuple[dtime, dtime]]:
    if market == "hk":
        raw = getattr(cfg, "sessions", None) or DEFAULT_SESSIONS["hk"]
    else:
        raw = DEFAULT_SESSIONS["us"]
    out = []
    for a, b in raw:
        ah, am = map(int, str(a).split(":"))
        bh, bm = map(int, str(b).split(":"))
        out.append((dtime(ah, am), dtime(bh, bm)))
    return out


def is_market_open(cfg, market: str = "hk") -> bool:
    """該市場是否開市(只排除週末;公眾假期請自行留意)。"""
    n = now_in(market)
    if n.weekday() >= 5:
        return False
    t = n.time()
    return any(s <= t <= e for s, e in _parse_sessions(cfg, market))


def any_market_open(cfg) -> bool:
    return is_market_open(cfg, "hk") or is_market_open(cfg, "us")


def open_markets(cfg) -> set[str]:
    return {m for m in ("hk", "us") if is_market_open(cfg, m)}


def minutes_to_close(cfg, market: str = "hk") -> float | None:
    """距離該市場最近收市時點的分鐘數;非交易時段回傳 None。"""
    n = now_in(market)
    if n.weekday() >= 5:
        return None
    t = n.time()
    for s, e in _parse_sessions(cfg, market):
        if s <= t <= e:
            delta = datetime.combine(n.date(), e, tzinfo=MARKET_TZ[market]) - n
            return max(delta.total_seconds() / 60.0, 0.0)
    return None


def session_ends_within(cfg, minutes: float, market: str = "hk") -> bool:
    m = minutes_to_close(cfg, market)
    return m is not None and m <= minutes


def symbol_market(symbol: str) -> str:
    return market_of(symbol)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:  # 已初始化
        return logging.getLogger("hk")
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    return logging.getLogger("hk")
