"""即時掃描器:開市時段輪詢K線 → 六大指標評估 → 狀態機 → Telegram 通知
狀態機:WATCH(觀察)→ LONG(已發買入訊號並模擬持倉)→ DONE(當日已完成交易)
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime

from . import indicators
from .config import market_of, stock_name
from .utils import HKT, any_market_open, is_market_open, now_hkt, now_in, \
    open_markets, session_ends_within


class Scanner:
    def __init__(self, cfg, feed, store, notifier):
        self.cfg = cfg
        self.feed = feed
        self.store = store
        self.notifier = notifier
        self.stop_evt = threading.Event()
        self.lock = threading.RLock()
        self.state: dict[str, dict] = {}
        self.last_cycle: str | None = None
        self.cycle_errors = 0
        self._thread: threading.Thread | None = None

    # ---------------- 週期控制 ----------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="scanner", daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_evt.set()

    def _run(self):
        while not self.stop_evt.wait(3):
            try:
                if open_markets(self.cfg):
                    self.scan_once()
                else:
                    self.last_cycle = None
            except Exception:
                self.cycle_errors += 1
                traceback.print_exc()
            self.stop_evt.wait(max(2, self.cfg.scan_interval))

    def scan_once(self):
        """執行一輪掃描(API 的「立即掃描」也走這裡)。
        只評估當前開市中的市場;休市市場的狀態保持不變。"""
        with self.lock:
            params = self.cfg.active_strategy()
            opened = open_markets(self.cfg)
            for sym, _mk in list(self.cfg.all_symbols()):
                if market_of(sym) not in opened:
                    continue
                try:
                    df = self.feed.get_bars(sym, self.cfg.bar_size, self.cfg.lookback)
                    res = indicators.evaluate(df, params)
                except Exception as e:  # noqa: BLE001
                    self.store.set_state(sym, {"symbol": sym, "error": str(e)[:200],
                                               "ts": now_hkt().isoformat(timespec="seconds")})
                    continue
                st = self.state.setdefault(sym, {"phase": "WATCH"})
                self._transition(sym, st, res, params)
                snapshot = self._snapshot_one(sym, st, res)
                self.store.set_state(sym, snapshot)
            self.last_cycle = now_hkt().isoformat(timespec="seconds")

    # ---------------- 狀態機 ----------------
    def _transition(self, sym: str, st: dict, res: dict, params):
        mk = market_of(sym)
        today = now_in(mk).strftime("%Y-%m-%d")   # 以該市場本地日期重置
        if st.get("day") != today:
            st.update(day=today, phase="WATCH", entry=None,
                      entry_ts=None, last_pnl=None)

        rules = self.cfg.trade_rules
        price = res.get("close")
        if price is None:
            return

        if st["phase"] == "WATCH":
            if res["buy"]:
                self.notifier.notify_buy(sym, res, rules, res["flags"],
                                         bar_size=self.cfg.bar_size)
                st.update(phase="LONG", entry=float(price),
                          entry_ts=now_in(mk).isoformat(timespec="seconds"))

        elif st["phase"] == "LONG":
            pnl = (float(price) / st["entry"] - 1.0) * 100.0
            st["last_pnl"] = round(pnl, 2)
            reason = None
            if pnl >= rules.take_profit_pct:
                reason = f"🎯 到達目標利潤 {rules.take_profit_pct}%"
            elif pnl <= -rules.stop_loss_pct:
                reason = f"🛑 觸發止損 {rules.stop_loss_pct}%"
            elif rules.force_eod_exit and session_ends_within(
                    self.cfg, rules.eod_warn_minutes, market=mk):
                reason = "⏰ 臨近收市,即日平倉"
            if reason:
                hold_min = None
                if st.get("entry_ts"):
                    try:
                        t0 = datetime.fromisoformat(st["entry_ts"])
                        hold_min = (now_hkt() - t0).total_seconds() / 60.0
                    except Exception:
                        pass
                self.notifier.notify_sell(sym, float(price), pnl, reason,
                                          flags=res["flags"], hold_min=hold_min)
                st.update(phase="DONE")

    # ---------------- API 快照 ----------------
    def _snapshot_one(self, sym: str, st: dict, res: dict) -> dict:
        m = res.get("metrics") or {}
        return {
            "symbol": sym, "name": stock_name(sym),
            "market": market_of(sym),
            "price": res.get("close"), "score": res.get("score"),
            "buy": res.get("buy"), "ready": res.get("ready"),
            "flags": res.get("flags"), "metrics": m,
            "phase": st.get("phase"), "entry": st.get("entry"),
            "pnl": st.get("last_pnl"), "error": None,
            "bar_size": self.cfg.bar_size,
            "ts": now_hkt().isoformat(timespec="seconds"),
        }

    def snapshot(self) -> list[dict]:
        data = self.store.all_states()
        out = []
        for sym, mk in self.cfg.all_symbols():
            row = data.get(sym) or {"symbol": sym, "name": stock_name(sym),
                                    "market": mk, "phase": "-", "ready": False}
            row.setdefault("market", mk)
            out.append(row)
        return out

    def status(self) -> dict:
        return {"last_cycle": self.last_cycle, "errors": self.cycle_errors,
                "market_open": any_market_open(self.cfg),
                "hk_open": is_market_open(self.cfg, "hk"),
                "us_open": is_market_open(self.cfg, "us"),
                "tz": str(HKT)}
