"""開市前自動選股器:於各市場開市前,對候選池逐隻以日K評分,
挑出最值得留意的 N 隻(預設 100),可自動寫入即時監察名單。

評分(0-100,透明可解釋):
  vol_ratio = 最新量 ÷ 前20日均量 → 佔 35 分(上限 3×)
  mom5      = 近5日報酬(取絕對值,捕捉單邊動能/急跌反彈)→ 佔 25 分(上限 6%)
  near_high = 距離近250日高點(越近越高分)→ 佔 25 分(10% 內線性)
  bb_expand = 布林帶寬 100 日百分位(開口異動)→ 佔 15 分
"""
from __future__ import annotations

import json
import threading
import traceback
import time
from datetime import datetime, timedelta

from .config import DATA_DIR, normalize_symbol
from .universe import UNIVERSE
from .utils import HKT, now_hkt


class Screener:
    def __init__(self, cfg, feed, log=print, notifier=None):
        self.cfg = cfg
        self.feed = feed
        self.log = log
        self.notifier = notifier
        self.path = DATA_DIR / "auto_watchlist.json"
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.busy = False
        self._done: dict[str, str] = {}      # market -> "YYYY-MM-DD" 當日已跑

    # ---------------- 排程 ----------------
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, name="screener", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()

    def _fire_today(self, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        n = now_hkt()
        f = n.replace(hour=h, minute=m, second=0, microsecond=0)
        return f

    def _run(self):
        while not self.stop_evt.wait(30):
            if not getattr(self.cfg, "screener_enabled", False):
                continue
            today = now_hkt().strftime("%Y-%m-%d")
            if now_hkt().weekday() >= 5:
                continue
            for mk, hhmm in (("hk", self.cfg.screener_hk_time),
                             ("us", self.cfg.screener_us_time)):
                fire = self._fire_today(hhmm)
                if fire <= now_hkt() and self._done.get(mk) != today:
                    self._done[mk] = today
                    threading.Thread(target=self._safe, args=(mk,), daemon=True).start()

    def _safe(self, mk):
        try:
            self.run_screen(mk)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.log(f"[screener] {mk} 失敗,詳見日誌")

    # ---------------- 評分 ----------------
    @staticmethod
    def score_row(df) -> dict | None:
        import numpy as np
        if df is None or len(df) < 60:
            return None
        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        if float(c.iloc[-1]) <= 0:
            return None
        avg_v = float(v.iloc[-21:-1].mean())
        vr = float(v.iloc[-1]) / avg_v if avg_v > 0 else 1.0
        mom = float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) >= 6 else 0.0
        hi = float(df["high"].tail(252).max())
        near = (hi - float(c.iloc[-1])) / hi if hi > 0 else 1.0
        # 布林帶寬百分位(開口異動)
        from .indicators import bollinger, rolling_pctile_rank
        mid, up, lo, width = bollinger(c)
        bbp = float(rolling_pctile_rank(width, min(100, len(width))).iloc[-1])
        bbp = 0.0 if bbp != bbp else bbp            # NaN → 0
        score = (min(vr / 3.0, 1.0) * 35
                 + min(abs(mom) / 0.06, 1.0) * 25
                 + max(0.0, 1.0 - near / 0.10) * 25
                 + (bbp / 100.0) * 15)
        return {"vol_ratio": round(vr, 2), "mom_pct": round(mom * 100, 2),
                "near_high_pct": round((1 - near) * 100, 2),
                "bb_width_pctile": round(bbp, 1),
                "close": round(float(c.iloc[-1]), 3), "score": round(score, 1)}

    def run_screen(self, market: str = "hk") -> dict:
        if self.busy:
            return {"error": "已有選股進行中"}
        market = "us" if market == "us" else "hk"
        self.busy = True
        top_n = max(5, min(int(getattr(self.cfg, "screener_top_n", 100)), 300))
        items, failed = [], 0
        try:
            pool = UNIVERSE.get(market, [])
            for raw in pool:
                sym = normalize_symbol(raw)
                try:
                    df = self.feed.history_daily(sym, 1)
                    row = self.score_row(df)
                    if row:
                        row["symbol"] = sym
                        items.append(row)
                except Exception:  # noqa: BLE001
                    failed += 1
                time.sleep(0.10)               # 限流保護(免費源)
            items.sort(key=lambda x: x["score"], reverse=True)
            items = items[:top_n]
            data = self._load()
            data[market] = {"ts": now_hkt().isoformat(timespec="seconds"),
                            "top_n": top_n, "failed": failed, "items": items}
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
            if getattr(self.cfg, "screener_auto_apply", True):
                syms = [i["symbol"] for i in items]
                try:
                    self.cfg.save_watchlist(syms, market)
                except Exception as e:  # noqa: BLE001
                    self.log(f"[screener] 寫入監察名單失敗: {e}")
            self.log(f"[screener] {market} 選股完成: "
                     f"{len(items)} 隻(失敗 {failed}),前3="
                     f"{[i['symbol'] for i in items[:3]]}")
            if self.notifier and self.cfg.tg_enabled:
                top = items[:5]
                self.notifier.send_async(
                    "🔍 <b>開市前自動選股</b> "
                    f"{'🇺🇸 美股' if market == 'us' else '🇭🇰 港股'} 前5:\n" +
                    "\n".join(f"{i+1}. {t['symbol']} — {t['score']}分"
                              f"(量比{t['vol_ratio']}× 動能{t['mom_pct']}%)"
                              for i, t in enumerate(top)))
            return data.get(market, {})
        finally:
            self.busy = False

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def latest(self) -> dict:
        d = self._load()
        return {"hk": d.get("hk", {"items": []}), "us": d.get("us", {"items": []})}

    def status(self) -> dict:
        d = self._load()
        return {"busy": self.busy, "enabled": getattr(self.cfg, "screener_enabled", False),
                "hk": d.get("hk", {}).get("ts"), "us": d.get("us", {}).get("ts")}
