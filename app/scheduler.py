"""每日自動回測調叟排程器:每天 retune_time(HKT)重跑網格搜索,
把最佳參數寫入 data/best_params.json,掃描器隨即以新參數運作。"""
from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timedelta

from .config import DATA_DIR
from .optimizer import save_best, tune
from .utils import HKT, now_hkt


class Retuner:
    def __init__(self, cfg, feed, store, notifier, log=print):
        self.cfg = cfg
        self.feed = feed
        self.store = store
        self.notifier = notifier
        self.log = log
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_run: str | None = None
        self.busy = False

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, name="retuner", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()

    def _next_fire(self) -> datetime:
        h, m = map(int, self.cfg.retune_time.split(":"))
        n = now_hkt()
        fire = n.replace(hour=h, minute=m, second=0, microsecond=0)
        if fire <= n:
            fire += timedelta(days=1)
        while fire.weekday() >= 5:      # 週末不跑
            fire += timedelta(days=1)
        return fire

    def _run(self):
        # 啟動時若完全沒有回測紀錄,先跑一次基準,讓儀表板立即有內容
        if self.cfg.baseline_on_start and not self.store.list_backtests(limit=1):
            try:
                self.log("[retune] 首次啟動,先建立基準回測…")
                self.run_tuning(kind="baseline")
            except Exception:
                traceback.print_exc()
        while not self.stop_evt.wait(30):
            nxt = self._next_fire()
            wait_s = max((nxt - now_hkt()).total_seconds(), 5)
            if wait_s > 35:
                continue                 # 每 30 秒醒來檢查一次
            try:
                self.run_tuning(kind="auto-daily")
            except Exception:
                traceback.print_exc()

    def run_tuning(self, kind="manual") -> dict | None:
        if self.busy:
            return None
        self.busy = True
        try:
            frames = {}
            for sym, _mk in self.cfg.all_symbols():
                try:
                    df = self.feed.history_daily(sym, self.cfg.backtest_years)
                    if len(df) > 120:
                        frames[sym] = df
                except Exception as e:  # noqa: BLE001
                    self.log(f"[retune] {sym} 歷史數據失敗: {e}")
            if not frames:
                self.log("[retune] 無可用歷史數據,跳過")
                return None
            base = self.cfg.strategy
            result = tune(frames, base, self.cfg, log=self.log)
            if "error" in result:
                self.log(f"[retune] 失敗: {result['error']}")
                return result
            save_best(self.cfg, result)
            run_id = self.store.insert_backtest(
                kind=kind, universe=list(frames), params=result["params"],
                overrides=result["overrides"], metrics=result["metrics"],
                equity=result["equity"], trades=result["trades"])
            self.last_run = now_hkt().isoformat(timespec="seconds")
            m = result["metrics"]
            summary = (f"📅 每日調叟完成({kind})\n"
                       f"獲利因子 PF={m.get('profit_factor')} | "
                       f"勝率={m.get('win_rate')}% | 交易={m.get('trades')}筆\n"
                       f"驗證PF={result['val_metrics'].get('profit_factor')} | "
                       f"最佳參數={json.dumps(result['overrides'], ensure_ascii=False)}")
            self.log(summary.replace("\n", " / "))
            if self.cfg.tg_enabled:
                self.notifier.send_async(summary)
            return {"run_id": run_id, **{k: result[k] for k in
                                         ("overrides", "metrics", "basis", "ts")}}
        finally:
            self.busy = False

    def status(self) -> dict:
        best = None
        if self.cfg.best_params_path.exists():
            try:
                best = json.loads(self.cfg.best_params_path.read_text(encoding="utf-8"))
            except Exception:
                best = None
        return {"last_run": self.last_run, "next": self._next_fire().isoformat(),
                "busy": self.busy, "best_params": best}
