"""SQLite 持久化:訊號 / 狀態 / 回測結果"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        with self._tx() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS signals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, price REAL, pnl REAL,
                score INTEGER, flags_json TEXT, note TEXT);
            CREATE TABLE IF NOT EXISTS state_kv(
                symbol TEXT PRIMARY KEY, updated TEXT, json TEXT);
            CREATE TABLE IF NOT EXISTS backtests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, kind TEXT, universe TEXT,
                params_json TEXT, overrides_json TEXT,
                metrics_json TEXT, equity_json TEXT, trades_json TEXT);
            """)

    @contextmanager
    def _tx(self):
        """開啟連線 → 自動 commit/rollback → 保證關閉。"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    # ---------------- signals ----------------
    def insert_signal(self, symbol, side, price=None, pnl=None, score=None,
                      flags=None, note=""):
        with self.lock, self._tx() as c:
            c.execute(
                "INSERT INTO signals(ts,symbol,side,price,pnl,score,flags_json,note)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (_now(), symbol, side, price, pnl, score,
                 json.dumps(flags or {}, ensure_ascii=False), note))

    def recent_signals(self, limit=50) -> list[dict]:
        with self.lock, self._tx() as c:
            rows = c.execute(
                "SELECT ts,symbol,side,price,pnl,score,flags_json,note FROM signals"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            out.append({"ts": r[0], "symbol": r[1], "side": r[2], "price": r[3],
                        "pnl": r[4], "score": r[5],
                        "flags": json.loads(r[6] or "{}"), "note": r[7]})
        return out

    # ---------------- live state ----------------
    def set_state(self, symbol, data: dict):
        with self.lock, self._tx() as c:
            c.execute("INSERT OR REPLACE INTO state_kv(symbol,updated,json)"
                      " VALUES(?,?,?)",
                      (symbol, _now(), json.dumps(data, ensure_ascii=False)))

    def all_states(self) -> dict[str, dict]:
        with self.lock, self._tx() as c:
            rows = c.execute("SELECT symbol,json FROM state_kv").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    # ---------------- backtests ----------------
    def insert_backtest(self, kind, universe, params, overrides,
                        metrics, equity, trades) -> int:
        with self.lock, self._tx() as c:
            cur = c.execute(
                "INSERT INTO backtests(ts,kind,universe,params_json,overrides_json,"
                "metrics_json,equity_json,trades_json) VALUES(?,?,?,?,?,?,?,?)",
                (_now(), kind, ",".join(universe),
                 json.dumps(params, ensure_ascii=False),
                 json.dumps(overrides or {}, ensure_ascii=False),
                 json.dumps(metrics, ensure_ascii=False),
                 json.dumps(equity[-1500:], ensure_ascii=False),
                 json.dumps(trades[-500:], ensure_ascii=False)))
            return int(cur.lastrowid)

    def list_backtests(self, limit=30) -> list[dict]:
        with self.lock, self._tx() as c:
            rows = c.execute(
                "SELECT id,ts,kind,universe,metrics_json,overrides_json"
                " FROM backtests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "kind": r[2], "universe": r[3],
                 "summary": {
                     "profit_factor": (json.loads(r[4]) or {}).get("profit_factor"),
                     "win_rate": (json.loads(r[4]) or {}).get("win_rate"),
                     "trades": (json.loads(r[4]) or {}).get("trades"),
                     "total_return_pct": (json.loads(r[4]) or {}).get("total_return_pct"),
                 },
                 "overrides": json.loads(r[5] or "{}")} for r in rows]

    def get_backtest(self, run_id: int) -> dict | None:
        with self.lock, self._tx() as c:
            row = c.execute(
                "SELECT id,ts,kind,universe,params_json,overrides_json,"
                "metrics_json,equity_json,trades_json FROM backtests WHERE id=?",
                (run_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "ts": row[1], "kind": row[2], "universe": row[3],
                "params": json.loads(row[4]), "overrides": json.loads(row[5] or "{}"),
                "metrics": json.loads(row[6]), "equity": json.loads(row[7]),
                "trades": json.loads(row[8])}
