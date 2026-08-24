"""設定檔載入與管理"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .strategy import StrategyParams, TradeRules

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"

DEFAULT_WATCHLIST = [
    "0700.HK", "9988.HK", "3690.HK", "9618.HK", "9999.HK",
    "1810.HK", "1024.HK", "9888.HK", "9868.HK", "2015.HK",
    "1211.HK", "2318.HK", "1299.HK", "0005.HK", "0941.HK",
    "0883.HK", "0388.HK", "1177.HK", "2020.HK", "6690.HK",
]

DEFAULT_WATCHLIST_US = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AMD", "NFLX", "JPM",
]

STOCK_NAMES = {
    "0700.HK": "騰訊控股", "9988.HK": "阿里巴巴", "3690.HK": "美團",
    "9618.HK": "京東集團", "9999.HK": "網易", "1810.HK": "小米集團",
    "1024.HK": "快手", "9888.HK": "百度", "9868.HK": "小鵬汽車",
    "2015.HK": "理想汽車", "1211.HK": "比亞迪", "2318.HK": "中國平安",
    "1299.HK": "友邦保險", "0005.HK": "匯豐控股", "0941.HK": "中國移動",
    "0883.HK": "中海油", "0388.HK": "港交所", "1177.HK": "中國生物製藥",
    "2020.HK": "安踏體育", "6690.HK": "海爾智家",
    # --- 美股 ---
    "AAPL": "蘋果", "MSFT": "微軟", "NVDA": "輝達", "AMZN": "亞馬遜",
    "GOOGL": "Alphabet", "META": "Meta平台", "TSLA": "特斯拉",
    "AMD": "超微半導體", "NFLX": "奈飛", "JPM": "摩根大通",
}


def stock_name(symbol: str) -> str:
    return STOCK_NAMES.get(symbol.upper(), "")


# ---------------------------------------------------------------- 代號/市場
def normalize_symbol(raw: str) -> str:
    """把用戶輸入統一為內部格式:
    '700'/'0700' → '0700.HK';'9988.hk' → '9988.HK';'aapl'/'US.AAPL' → 'AAPL'
    """
    s = str(raw).strip().upper().replace(" ", "")
    if not s:
        return s
    if s.startswith("HK."):
        return s[3:].zfill(4) + ".HK"
    if s.startswith("US."):
        return s[3:]
    if s.endswith(".HK"):
        return s[:-3].zfill(4) + ".HK"
    if s.isdigit():
        return s.zfill(4) + ".HK"
    return s


def detect_market(symbol: str) -> str:
    """'hk' 或 'us':凡 .HK 結尾視為港股,其餘(AAPL 等)視為美股。"""
    return "hk" if symbol.upper().endswith(".HK") else "us"


def market_of(symbol: str) -> str:
    return detect_market(symbol)


def futu_code(symbol: str) -> str:
    sym = normalize_symbol(symbol)
    if detect_market(sym) == "us":
        return "US." + sym
    return "HK." + sym.split(".")[0].zfill(5)


def yf_code(symbol: str) -> str:
    sym = normalize_symbol(symbol)
    if detect_market(sym) == "us":
        return sym
    return sym.split(".")[0].zfill(4) + ".HK"


class Config:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path or os.environ.get("HK_CONFIG") or ROOT / "config.yaml")
        raw: dict = {}
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        self.apply_raw(raw)

    def apply_raw(self, raw: dict):
        """由設定字典套用全部欄位(初次載入與網頁熱更新共用)。"""
        raw = raw or {}
        self.raw = dict(raw)

        tg = raw.get("telegram") or {}
        self.tg_token = tg.get("bot_token") or ""
        self.tg_chat = str(tg.get("chat_id") or "")
        self.tg_enabled = bool(tg.get("enabled")) and bool(self.tg_token) and bool(self.tg_chat)

        ft = raw.get("futu") or {}
        self.futu_host = ft.get("host", "127.0.0.1")
        self.futu_port = int(ft.get("port", 11111))
        self.futu_enabled = bool(ft.get("enabled", True))

        fd = raw.get("feed") or {}
        self.feed_mode = fd.get("mode", "auto")

        mk = raw.get("market") or {}
        self.timezone = mk.get("timezone", "Asia/Hong_Kong")
        self.sessions = [tuple(x) for x in mk.get(
            "sessions", [["09:30", "12:00"], ["13:00", "16:00"]])]

        sc = raw.get("scanner") or {}
        self.scan_interval = int(sc.get("interval_sec", 30))
        self.bar_size = sc.get("bar_size", "1m")
        self.lookback = int(sc.get("lookback_bars", 300))
        wl = sc.get("watchlist") or DEFAULT_WATCHLIST
        self.watchlist = [normalize_symbol(s) for s in wl]
        wlu = sc.get("watchlist_us")
        if wlu is None:
            wlu = DEFAULT_WATCHLIST_US
        self.watchlist_us = [normalize_symbol(s) for s in wlu]

        self.strategy = StrategyParams.from_dict(raw.get("strategy"))
        self.trade_rules = TradeRules.from_dict(raw.get("trade_rules"))

        bt = raw.get("backtest") or {}
        self.backtest_years = int(bt.get("years", 5))
        self.backtest_cost_pct = float(bt.get("cost_pct", 0.15))

        op = raw.get("optimizer") or {}
        self.opt_metric = op.get("metric", "profit_factor")
        self.opt_min_trades = int(op.get("min_trades", 30))
        self.opt_train_ratio = float(op.get("train_ratio", 0.7))

        sd = raw.get("scheduler") or {}
        self.retune_time = sd.get("retune_time", "17:30")
        self.baseline_on_start = bool(sd.get("baseline_on_start", True))
        # 雲端部署(Render/HF Spaces)可用 HK_BASELINE=0 跳過開機基準回測,加快冷啟動
        if os.environ.get("HK_BASELINE", "").strip().lower() in ("0", "false", "off"):
            self.baseline_on_start = False

        wb = raw.get("web") or {}
        self.web_host = wb.get("host", "0.0.0.0")
        # 雲端平台以 PORT 環境變數指定對外埠(Render=10000、HF Spaces 用 Dockerfile 內預設)
        try:
            self.web_port = int(os.environ.get("PORT") or wb.get("port", 8000))
        except ValueError:
            self.web_port = int(wb.get("port", 8000))
        self.web_access_token = str(wb.get("access_token") or "")

        ai = raw.get("ai") or {}
        self.ai_providers = [dict(p) for p in (ai.get("providers") or [])
                             if isinstance(p, dict)]
        self.ai_default = str(ai.get("default") or "")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = DATA_DIR / "app.db"
        self.best_params_path = DATA_DIR / "best_params.json"

    def ai_provider(self, name: str | None = None) -> dict:
        """取指定(或預設)的 AI 供應商設定;無設定回 {}。"""
        provs = getattr(self, "ai_providers", []) or []
        if not provs:
            return {}
        want = name or self.ai_default or (provs[0].get("name") or "")
        for p in provs:
            if p.get("name") == want:
                return p
        return provs[0]

    def save(self):
        """把目前 self.raw 寫回設定檔。"""
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(self.raw, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---- 每日調叟後的「生效參數」= 基礎參數 + best_params 覆蓋 ----
    def active_strategy(self) -> StrategyParams:
        overlay = {}
        if self.best_params_path.exists():
            try:
                import json
                data = json.loads(self.best_params_path.read_text(encoding="utf-8"))
                overlay = data.get("overrides") or {}
            except Exception:
                overlay = {}
        return self.strategy.overlay(overlay)

    def save_watchlist(self, symbols: list[str], market: str = "hk"):
        symbols = [normalize_symbol(s) for s in symbols]
        key = "watchlist_us" if market == "us" else "watchlist"
        if market == "us":
            self.watchlist_us = symbols
        else:
            self.watchlist = symbols
        self.raw.setdefault("scanner", {})[key] = symbols
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(self.raw, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        tmp.replace(self.path)

    def all_symbols(self) -> list[tuple[str, str]]:
        """全部監察代號 → [(symbol, market)]。"""
        return ([(s, "hk") for s in self.watchlist]
                + [(s, "us") for s in self.watchlist_us])
