"""FastAPI Web 服務:儀表板 + REST API(手機/瀏覽器皆可用)
注意:此檔不可加 `from __future__ import annotations` —
閉包內定義的 Pydantic body 模型需要真實型別註解才能被 FastAPI 綁定。
"""
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import ROOT, Config, market_of, normalize_symbol, stock_name
from .datafeed import create_feed
from . import indicators
from .notifier import Notifier
from .scanner import Scanner
from .scheduler import Retuner
from .store import Store
from .utils import any_market_open, is_market_open, setup_logging

STATIC_DIR = Path(__file__).parent / "static"
SYM_RE = re.compile(r"^\d{1,5}\.HK$")


class AppCtx:
    cfg: Config = None
    store: Store = None
    feed = None
    notifier: Notifier = None
    scanner: Scanner = None
    retuner: Retuner = None


def create_app(cfg: Config | None = None, autostart: bool | None = None) -> FastAPI:
    log = setup_logging()
    ctx = AppCtx()
    ctx.cfg = cfg or Config()
    ctx.store = Store(ctx.cfg.db_path)
    ctx.notifier = Notifier(ctx.cfg, ctx.store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        do_start = (autostart if autostart is not None
                    else os.environ.get("HK_NO_AUTOSTART") != "1")
        try:
            ctx.feed = create_feed(ctx.cfg)
        except Exception as e:  # noqa: BLE001
            log.error(f"數據源全部不可用: {e}")
            ctx.feed = None
        if do_start and ctx.feed:
            ctx.scanner = Scanner(ctx.cfg, ctx.feed, ctx.store, ctx.notifier)
            ctx.scanner.start()
            ctx.retuner = Retuner(ctx.cfg, ctx.feed, ctx.store, ctx.notifier, log=log.info)
            ctx.retuner.start()
            log.info(f"掃描器+排程器已啟動 feed={getattr(ctx.feed,'name','?')}")
        yield
        if ctx.scanner:
            ctx.scanner.stop()
        if ctx.retuner:
            ctx.retuner.stop()

    app = FastAPI(title="港股即日買賣訊號系統", lifespan=lifespan)

    # ---------------- 頁面 ----------------
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    # ---------------- 狀態 ----------------
    @app.get("/api/meta")
    def meta():
        return {
            "market_open": any_market_open(ctx.cfg),
            "hk_open": is_market_open(ctx.cfg, "hk"),
            "us_open": is_market_open(ctx.cfg, "us"),
            "feed": getattr(ctx.feed, "name", "unavailable"),
            "watchlist": ctx.cfg.watchlist,
            "watchlist_us": ctx.cfg.watchlist_us,
            "strategy": ctx.cfg.active_strategy().to_dict(),
            "trade_rules": ctx.cfg.trade_rules.__dict__,
            "telegram_enabled": ctx.cfg.tg_enabled,
            "scanner": ctx.scanner.status() if ctx.scanner else {"running": False},
            "retuner": ctx.retuner.status() if ctx.retuner else {"running": False},
        }

    @app.get("/api/state")
    def state():
        return {
            "market_open": any_market_open(ctx.cfg),
            "hk_open": is_market_open(ctx.cfg, "hk"),
            "us_open": is_market_open(ctx.cfg, "us"),
            "feed": getattr(ctx.feed, "name", "unavailable"),
            "symbols": ctx.scanner.snapshot() if ctx.scanner else [],
            "ts": ctx.scanner.last_cycle if ctx.scanner else None,
        }

    # ---------------- 自選獨立分析 ----------------
    @app.get("/api/analyze")
    def analyze(symbol: str, size: str = "1m", bars: int = 300):
        """獨立分析任意自選股票(美股/港股皆可),不影響監察名單。"""
        if not ctx.feed:
            raise HTTPException(503, "數據源不可用")
        sym = normalize_symbol(symbol)
        if not sym or not (1 <= len(sym) <= 12):
            raise HTTPException(400, "代號格式無效(例:AAPL、TSLA、0700.HK)")
        mk = market_of(sym)
        size = size if size in ("1m", "5m", "15m") else "1m"
        bars = max(120, min(int(bars), 600))
        try:
            df = ctx.feed.get_bars(sym, size, bars)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"取得 {sym} K線失敗: {e}")
        res = indicators.evaluate(df, ctx.cfg.active_strategy())
        chg = None
        try:
            if len(df) >= 2 and df["close"].iloc[-2]:
                chg = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-2]) - 1) * 100
        except Exception:
            chg = None
        return {"symbol": sym, "name": stock_name(sym), "market": mk,
                "bar_size": size, "chg_pct": round(chg, 2) if chg is not None else None,
                **res}

    class SingleBTBody(BaseModel):
        symbol: str
        years: int = 5

    @app.post("/api/backtest-single")
    def backtest_single(body: SingleBTBody):
        """對單一自選股票跑 N 年回測(結果存入回測清單)。"""
        from . import backtest as btmod
        if not ctx.feed:
            raise HTTPException(503, "數據源不可用")
        sym = normalize_symbol(body.symbol)
        years = max(1, min(int(body.years), 20))
        try:
            df = ctx.feed.history_daily(sym, years)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"取得 {sym} 歷史日K失敗: {e}")
        if len(df) < 220:
            raise HTTPException(400, f"{sym} 日K不足({len(df)}根),無法回測")
        p = ctx.cfg.active_strategy()
        rules = ctx.cfg.trade_rules
        out = btmod.run_portfolio({sym: df}, p, rules.take_profit_pct,
                                  rules.stop_loss_pct, ctx.cfg.backtest_cost_pct)
        run_id = ctx.store.insert_backtest(
            kind=f"single:{sym}", universe=[sym], params=p.to_dict(),
            overrides={}, metrics=out["metrics"], equity=out["equity"],
            trades=out["trades"])
        m = out["metrics"]
        return {"run_id": run_id, "symbol": sym, "years": years,
                "profit_factor": m.get("profit_factor"),
                "win_rate": m.get("win_rate"), "trades": m.get("trades"),
                "total_return_pct": m.get("total_return_pct"),
                "max_drawdown_pct": m.get("max_drawdown_pct")}

    @app.post("/api/scan-now")
    def scan_now():
        if not ctx.scanner:
            raise HTTPException(503, "掃描器未啟動(數據源不可用?)")
        threading.Thread(target=ctx.scanner.scan_once, daemon=True).start()
        return {"ok": True}

    # ---------------- 訊號 ----------------
    @app.get("/api/signals")
    def signals(limit: int = 60):
        return ctx.store.recent_signals(min(max(limit, 1), 300))

    # ---------------- 回測 ----------------
    @app.get("/api/backtests")
    def backtests():
        return ctx.store.list_backtests()

    @app.get("/api/backtests/{run_id}")
    def backtest_detail(run_id: int):
        row = ctx.store.get_backtest(run_id)
        if not row:
            raise HTTPException(404, "找不到回測紀錄")
        return row

    # ---------------- 設定 ----------------
    class WatchlistBody(BaseModel):
        symbols: list[str]
        market: str = "hk"          # "hk" | "us"

    @app.post("/api/config/watchlist")
    def set_watchlist(body: WatchlistBody):
        market = body.market if body.market in ("hk", "us") else "hk"
        syms = [normalize_symbol(s) for s in body.symbols if s.strip()]
        if market == "hk":
            valid = [s for s in syms if SYM_RE.match(s)]
            if not (1 <= len(valid) <= 100):
                raise HTTPException(400, "需要 1~100 個有效港股代號(如 0700.HK)")
        else:
            import re as _re
            us_re = _re.compile(r"^[A-Z.]{1,10}$")
            valid = [s for s in syms if us_re.match(s) and "." not in s]
            if not (1 <= len(valid) <= 100):
                raise HTTPException(400, "需要 1~100 個有效美股代號(如 AAPL)")
        ctx.cfg.save_watchlist(valid, market)
        return {"ok": True, "market": market,
                "watchlist": valid}

    class TelegramTestBody(BaseModel):
        bot_token: str | None = None
        chat_id: str | None = None

    @app.post("/api/telegram-test")
    def telegram_test(body: TelegramTestBody):
        ok, err = ctx.notifier.test()
        return {"ok": ok, "error": err}

    # ---------------- 網頁設定(所有參數) ----------------
    @app.get("/api/config/full")
    def get_full_config():
        c = ctx.cfg
        return {
            "strategy": c.strategy.to_dict(),
            "trade_rules": c.trade_rules.__dict__,
            "scanner": {"interval_sec": c.scan_interval, "bar_size": c.bar_size,
                        "lookback_bars": c.lookback,
                        "watchlist": c.watchlist, "watchlist_us": c.watchlist_us},
            "backtest": {"years": c.backtest_years, "cost_pct": c.backtest_cost_pct},
            "optimizer": {"min_trades": c.opt_min_trades,
                          "train_ratio": c.opt_train_ratio},
            "scheduler": {"retune_time": c.retune_time,
                          "baseline_on_start": c.baseline_on_start},
            "feed": {"mode": c.feed_mode},
            "telegram": {"enabled": bool(c.tg_token and c.tg_chat and
                                         (c.raw.get("telegram") or {}).get("enabled")),
                         "bot_token": c.tg_token, "chat_id": c.tg_chat},
            "web": {"access_token": c.web_access_token},
            "ai": {"providers": getattr(c, "ai_providers", []),
                   "default": getattr(c, "ai_default", "")},
            "overlay_active": c.best_params_path.exists(),
        }

    class FullConfigBody(BaseModel):
        strategy: dict | None = None
        trade_rules: dict | None = None
        scanner: dict | None = None
        backtest: dict | None = None
        optimizer: dict | None = None
        scheduler: dict | None = None
        feed: dict | None = None
        telegram: dict | None = None
        web: dict | None = None

    def _coerce_like(old, new):
        """按舊值型別轉換新值(bool/int/float/str)。"""
        if isinstance(old, bool) or isinstance(old, int) and not isinstance(old, bool) \
                or isinstance(old, float):
            try:
                if isinstance(old, bool):
                    v = new if isinstance(new, bool) else str(new).strip().lower() in (
                        "1", "true", "yes", "on", "是")
                    return bool(v)
                t = type(old)
                return t(float(new)) if t is float else t(int(float(new)))
            except Exception:
                return old
        return str(new)

    @app.post("/api/config/full")
    def set_full_config(body: FullConfigBody):
        raw = ctx.cfg.raw
        updates = body.model_dump(exclude_none=True)
        for group, payload in updates.items():
            g = raw.setdefault(group, {})
            for k, v in payload.items():
                if k in ("watchlist", "watchlist_us"):
                    mk = "us" if k == "watchlist_us" else "hk"
                    syms = [normalize_symbol(x) for x in v if str(x).strip()]
                    if mk == "hk":
                        syms = [s for s in syms if SYM_RE.match(s)]
                    if syms:
                        g[k] = syms
                    continue
                g[k] = _coerce_like(g.get(k), v)
        ctx.cfg.apply_raw(raw)
        ctx.cfg.save()
        return {"ok": True, **get_full_config()}

    @app.post("/api/config/clear-overlay")
    def clear_overlay():
        """刪除每日調叟的覆蓋,讓「設定」頁的基礎參數直接生效。"""
        removed = False
        if ctx.cfg.best_params_path.exists():
            ctx.cfg.best_params_path.unlink()
            removed = True
        return {"ok": True, "removed": removed}

    # ---------------- 🤖 AI 分析 ----------------
    class AIProviderBody(BaseModel):
        name: str
        base_url: str
        api_key: str = ""
        model: str

    class AISettingsBody(BaseModel):
        providers: list[AIProviderBody]
        default: str = ""

    @app.get("/api/ai/providers")
    def ai_providers_list():
        provs = [{"name": p.get("name"), "base_url": p.get("base_url"),
                  "model": p.get("model"), "has_key": bool(p.get("api_key"))}
                 for p in getattr(ctx.cfg, "ai_providers", [])]
        return {"providers": provs,
                "default": getattr(ctx.cfg, "ai_default", ""),
                "configured": bool(provs)}

    @app.post("/api/ai/settings")
    def ai_save(body: AISettingsBody):
        provs = [p.model_dump() for p in body.providers if p.name.strip()]
        names = [p["name"] for p in provs]
        if len(names) != len(set(names)):
            raise HTTPException(400, "供應商名稱重複")
        dflt = body.default if body.default in names else (names[0] if names else "")
        raw = ctx.cfg.raw
        raw["ai"] = {"providers": provs, "default": dflt}
        ctx.cfg.apply_raw(raw)
        ctx.cfg.save()
        return {"ok": True, "default": dflt, "count": len(provs)}

    class AITestBody(BaseModel):
        name: str

    @app.post("/api/ai/test")
    def ai_test(body: AITestBody):
        from .ai import chat_completion
        p = ctx.cfg.ai_provider(body.name)
        if not p:
            raise HTTPException(404, f"找不到 AI 供應商 {body.name}")
        try:
            text, dt = chat_completion(
                p, [{"role": "user", "content": "只回覆兩個字:正常"}],
                max_tokens=10, temperature=0)
            return {"ok": True, "provider": p.get("name"),
                    "model": p.get("model"), "latency_s": round(dt, 1),
                    "reply": text[:50]}
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/ai/settings-test")
    def ai_test_direct(body: AIProviderBody):
        """測試一組(尚未儲存的)供應商設定。"""
        from .ai import chat_completion
        try:
            text, dt = chat_completion(
                body.model_dump(),
                [{"role": "user", "content": "只回覆兩個字:正常"}],
                max_tokens=10, temperature=0)
            return {"ok": True, "model": body.model,
                    "latency_s": round(dt, 1), "reply": text[:50]}
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

    class AIAnalyzeBody(BaseModel):
        symbol: str
        size: str = "1m"
        provider: str | None = None

    @app.post("/api/ai/analyze")
    def ai_analyze(body: AIAnalyzeBody):
        """取數 → 六指標評估 → 交給指定(或預設)AI 模型解讀。"""
        from .ai import analyze_payload
        p = ctx.cfg.ai_provider(body.provider)
        if not p:
            raise HTTPException(400, "尚未設定任何 AI 供應商(請到「⚙️ 設定」新增)")
        sym = normalize_symbol(body.symbol)
        size = body.size if body.size in ("1m", "5m", "15m") else "1m"
        try:
            df = ctx.feed.get_bars(sym, size, 300) if ctx.feed else None
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"取得 {sym} K線失敗: {e}")
        res = indicators.evaluate(df, ctx.cfg.active_strategy())
        payload = {"symbol": sym, "market": market_of(sym), "bar_size": size,
                   **res, "trade_rules": ctx.cfg.trade_rules.__dict__}
        try:
            content, dt = analyze_payload(p, payload)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        return {"ok": True, "provider": p.get("name"), "model": p.get("model"),
                "symbol": sym, "score": res.get("score"),
                "latency_s": round(dt, 1), "content": content}

    @app.middleware("http")
    async def access_guard(request, call_next):  # noqa: ANN001
        """設定存取金鑰後,/api/* 一律需 X-Access-Key 或 ?key= 才可呼叫。"""
        tok = getattr(ctx.cfg, "web_access_token", "")
        if tok and request.url.path.startswith("/api"):
            key = (request.headers.get("x-access-key")
                   or request.query_params.get("key") or "")
            if key != tok:
                return JSONResponse(status_code=401,
                                    content={"detail": "需要存取金鑰"})
        return await call_next(request)

    @app.exception_handler(Exception)
    async def on_error(request, exc):  # noqa: ANN001
        return JSONResponse(status_code=500, content={"detail": str(exc)[:300]})

    return app


app = None  # 由 run.py 建立帶設定檔的實例
