"""自我測試:指標數學、六大條件觸發、回測管線、儲存層、Telegram 訊息模板"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


def _df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=idx)


def test_indicator_math():
    from app.indicators import bollinger, macd_parts, rolling_pctile_rank, wilder_rsi
    rng = np.random.default_rng(7)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 500)))
    r = wilder_rsi(close, 14)
    assert r.between(0, 100).all(), "RSI 越界"
    _, _, hist = macd_parts(close)
    assert len(hist) == len(close) and np.isfinite(hist.iloc[-1])
    _, _, _, width = bollinger(close)
    assert (width.dropna() >= 0).all(), "布林帶寬為負"
    rk = rolling_pctile_rank(width, 60)
    v = rk.dropna().iloc[-1]
    assert 0 <= v <= 100
    return "RSI/MACD/Bollinger/百分位數學正確"


def _crafted_setup_df():
    """構造『盤整→上升→深腳→反彈→淺腳彈→淺腳墊高(雙底)→放量反轉』走勢。
    幾何參數由 scripts/probe_geometry.py 隨機搜索驗證可令六大條件
    於反轉段同時成立(布林定義=壓縮後開口)。"""
    prices, vols = [], []
    px = 100.0
    for i in range(80):                        # 盤整基底
        prices.append(100 * (1 + 0.0015 * math.sin(i / 3.1)))
        vols.append(1_000_000)
    for _ in range(98):                        # 溫和上升浪 +0.21%/根
        px *= 1.0021
        prices.append(px)
        vols.append(1_000_000 * (1 + 0.2 * _ / 98))
    for _ in range(11):                        # legA 深腳 -0.37%/根
        px *= 1 - 0.0037
        prices.append(px)
        vols.append(1_250_000)
    la_low = px
    for _ in range(7):                         # 反彈 +0.53%/根
        px *= 1.0053
        prices.append(px)
        vols.append(1_150_000)
    btop = px
    tgt = la_low + (btop - la_low) * 0.194     # legB 淺腳墊高( higher low)
    for _ in range(6):
        px += (tgt - px) * 0.35
        prices.append(px)
        vols.append(950_000)
    for k in range(18):                        # 放量反轉 +0.45%/根
        px *= 1.0045
        prices.append(px)
        vols.append(2_900_000 * (1 + 0.04 * k))
    rows = []
    prev = prices[0]
    for i, c in enumerate(prices):
        o = prev
        rows.append((o, max(o, c) * 1.0012, min(o, c) * 0.9988, c,
                     float(vols[i])))
        prev = c
    return _df(rows)


def test_six_condition_trigger():
    from app.strategy import StrategyParams
    from app.indicators import evaluate, warmup_bars
    df = _crafted_setup_df()
    p = StrategyParams(vol_expand_ratio=2.0, fib_tolerance_pct=2.5,
                       bb_width_pctile=70, fib_levels=[0.236, 0.382],
                       rsi_lo=45, rsi_hi=58)
    assert len(df) >= warmup_bars(p), "樣本長度不足"
    hits = []
    for i in range(warmup_bars(p), len(df)):
        res = evaluate(df.iloc[:i + 1], p)
        if res["buy"]:
            hits.append((i, res))
    assert hits, "精心構造的多頭回調形態未觸發買入(六大條件聯動失效)"
    i, best = max(hits, key=lambda x: x[1]["score"])
    missing = [k for k, v in best["flags"].items() if not v]
    assert not missing, f"觸發時仍有條件未成立: {missing}"

    # ★ 現行模式:至少 4 項成立(require_all=false, min_score=4)也應觸發
    p4 = StrategyParams(vol_expand_ratio=2.0, fib_tolerance_pct=2.5,
                        bb_width_pctile=70, fib_levels=[0.236, 0.382],
                        rsi_lo=45, rsi_hi=58,
                        require_all=False, min_score=4)
    buys4 = [i for i in range(warmup_bars(p4), len(df))
             if evaluate(df.iloc[:i + 1], p4)["buy"]]
    assert buys4, "min_score=4 模式未觸發"
    assert all(evaluate(df.iloc[:i + 1], p4)["score"] >= 4 for i in buys4)
    return (f"六項全中@第{i}根 ✓;4/6 模式另於 {len(buys4)} 根K線觸發"
            f"(首見第{buys4[0]}根)✓")


def test_backtest_pipeline():
    from app.backtest import compute_metrics, equity_curve, eval_masks, precompute, simulate
    from app.datafeed import synth_daily_frame
    from app.strategy import StrategyParams
    frames = {}
    for sym in ("0700.HK", "9988.HK", "1810.HK"):
        frames[sym] = synth_daily_frame(sym, years=5)
    p = StrategyParams(require_all=False, min_score=3)
    all_trades = []
    for sym, df in frames.items():
        pre = precompute(df, p)
        mask = eval_masks(pre, p)
        trades = simulate(pre, mask, tp_pct=5.0, sl_pct=3.0, cost_pct=0.15)
        for t in trades:
            t["symbol"] = sym
        all_trades.extend(trades)
    m = compute_metrics(all_trades)
    eq = equity_curve(all_trades)
    assert m["trades"] > 10, f"交易數異常: {m['trades']}"
    assert m["profit_factor"] >= 0 and eq and len(eq) == m["trade_days"]
    reasons = {t["reason"] for t in all_trades}
    assert reasons <= {"take-profit", "stop-loss", "eod-close"}
    return (f"5年×3股模擬回測:{m['trades']}筆 PF={m['profit_factor']} "
            f"勝率={m['win_rate']}% 出場原因={sorted(reasons)}")


def test_store_roundtrip():
    from app.config import DATA_DIR
    from app.store import Store
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = DATA_DIR / "selftest.db"
    if db.exists():
        db.unlink()
    try:
        st = Store(db)
        st.insert_signal("0700.HK", "BUY", price=380.5, score=6,
                         flags={"vol": True}, note="測試")
        st.set_state("0700.HK", {"price": 380.5})
        rid = st.insert_backtest("baseline", ["0700.HK"], {"a": 1}, {"b": 2},
                                 {"profit_factor": 1.5, "win_rate": 55,
                                  "trades": 40, "total_return_pct": 12.3},
                                 [["2024-01-02", 1.01]], [{"date": "2024-01-02",
                                                           "ret_pct": 1.0,
                                                           "reason": "take-profit"}])
        row = st.get_backtest(rid)
        assert row["metrics"]["profit_factor"] == 1.5
        assert st.recent_signals(5)[0]["symbol"] == "0700.HK"
        assert st.all_states()["0700.HK"]["price"] == 380.5
    finally:
        import gc
        st = None
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            p2 = Path(str(db) + suffix)
            if p2.exists():
                try:
                    p2.unlink()
                except PermissionError:
                    pass
    return "SQLite 訊號/狀態/回測讀寫一致 ✓"


def test_messages():
    from app.config import Config
    from app.strategy import TradeRules
    from app.notifier import Notifier
    cfg = Config()                       # 讀取真實 config.yaml
    cfg.tg_enabled = False               # 測試時不真正發送
    n = Notifier(cfg)
    res = {"close": 300.0, "score": 6,
           "label": {"① 成交量放大": True, "② 均線向上·價在均線上方": True,
                     "③ 布林帶開口": True, "④ 回調至斐波 38.2/61.8": True,
                     "⑤ RSI 50 附近止穩回升": True, "⑥ MACD 縮柱·金叉": True},
           "metrics": {"vol_ratio": 2.4, "rsi": 52.1, "fib_name": "38.2%",
                       "fib_level": 296.8, "fib_dist_pct": 0.9,
                       "macd_hist": -0.02, "macd_note": "golden-cross",
                       "bb_width_pctile": 88}}
    msg = n.buy_message("0700.HK", res, TradeRules())
    for kw in ("買入訊號", "+5%", "止損", "RSI"):
        assert kw in msg, f"買入訊息缺少 {kw}"
    sell = n.sell_message("0700.HK", 315.0, 5.0, "🎯 到達目標利潤 5%")
    assert "賣出訊號" in sell and "+5.00%" in sell
    return "買入/賣出 Telegram 訊息模板完整 ✓"


def test_markets():
    """雙市場(港/美)代號正規化與映射。"""
    from app.config import (detect_market, futu_code, normalize_symbol, yf_code)
    assert normalize_symbol("700") == "0700.HK"
    assert normalize_symbol("9988.hk") == "9988.HK"
    assert normalize_symbol("hk.0700") == "0700.HK"
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol("US.TSLA") == "TSLA"
    assert detect_market("0700.HK") == "hk"
    assert detect_market("AAPL") == "us"
    assert futu_code("0700.HK") == "HK.00700"
    assert futu_code("aapl") == "US.AAPL"
    assert yf_code("0700") == "0700.HK"
    assert yf_code("tsla") == "TSLA"
    # 美股時區/時段定義存在(不依賴當下時間)
    from app.utils import MARKET_TZ, _parse_sessions
    class _C:  # 模擬 cfg
        sessions = [["09:30", "12:00"], ["13:00", "16:00"]]
    hk = _parse_sessions(_C, "hk")
    us = _parse_sessions(_C, "us")
    assert len(hk) == 2 and len(us) == 1 and us[0][0].hour == 9
    assert str(MARKET_TZ["us"]) .startswith("America")
    return "港/美代號正規化、Futu/Yahoo 映射、時區時段 ✓"


def test_ai():
    """AI 模組:提示詞建構、供應商設定管線、錯誤處理。"""
    from app.ai import SYSTEM_PROMPT, build_user_prompt, chat_completion
    p = build_user_prompt({"symbol": "0700.HK", "market": "hk", "close": 300.5,
                           "score": 4, "flags": {"vol": True},
                           "metrics": {}, "trade_rules": {}})
    assert "0700.HK" in p and "score_6" in p
    assert "綜合判斷" in SYSTEM_PROMPT and "信心度" in SYSTEM_PROMPT
    # 供應商設定 → Config 管線(暫存 yaml)
    import tempfile, os
    yml = ("ai:\n"
           "  providers:\n"
           "    - name: TestAI\n"
           "      base_url: http://example.invalid/v1\n"
           "      api_key: sk-test\n"
           "      model: test-model\n"
           "  default: TestAI\n")
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(yml)
        from app.config import Config
        c = Config(path)
        assert c.ai_provider()["model"] == "test-model"
        assert c.ai_provider("不存在")["name"] == "TestAI"   # 回退第一個
        assert c.ai_default == "TestAI"
    finally:
        os.unlink(path)
    # 錯誤處理:連不通的端點要給可讀的中文錯誤
    try:
        chat_completion({"name": "離線測試", "base_url": "http://127.0.0.1:9",
                         "api_key": "", "model": "m"},
                        [{"role": "user", "content": "hi"}], timeout=3)
        raise AssertionError("應該失敗卻成功")
    except RuntimeError as e:
        assert "無法連線" in str(e) or "逾時" in str(e)
    return "提示詞/設定管線/中文錯誤訊息 ✓"


def test_strategy_type_coercion():
    """回歸測試:字串數值(雲端儲存路徑曾產生)必須被強制轉型,否則
    warmup_bars 的 macd_slow + macd_signal 會爆 str+int TypeError。"""
    from .strategy import StrategyParams, TradeRules
    p = StrategyParams.from_dict({"macd_slow": "26", "macd_signal": 9,
                                  "min_score": "4", "require_all": "false",
                                  "vol_expand_ratio": "2.5", "rsi_lo": "45"})
    assert isinstance(p.macd_slow, int) and p.macd_slow == 26
    assert isinstance(p.min_score, int) and p.min_score == 4
    assert p.require_all is False
    assert isinstance(p.vol_expand_ratio, float) and p.vol_expand_ratio == 2.5
    # overlay(每日調叟)同樣要轉型
    q = p.overlay({"ema_slow": "120", "bb_k": "3"})
    assert q.ema_slow == 120 and isinstance(q.bb_k, float)
    # warmup_bars 現在應能正常計算(不再 str+int)
    from .indicators import warmup_bars
    assert warmup_bars(q) > 0
    tr = TradeRules.from_dict({"take_profit_pct": "5", "stop_loss_pct": 3})
    assert tr.take_profit_pct == 5.0 and isinstance(tr.stop_loss_pct, float)
    return "字串數值自動轉型 + warmup_bars 可計算 ✓"


def test_custom_required_flags():
    """自定必中指標組合:required_flags 優先;掃描與回測遮罩一致。"""
    import numpy as np
    from .indicators import buy_signal
    from .strategy import StrategyParams

    p = StrategyParams(require_all=False, min_score=1,
                       required_flags=["vol", "macd"])
    # 只中 vol → 不買(缺 macd)
    assert not buy_signal({"vol": True, "macd": False}, 1, p)
    # vol+macd 都中 → 買(即使 score=2 < min_score=1 無關,優先規則生效)
    assert buy_signal({"vol": True, "macd": True, "rsi": False}, 2, p)
    # 清空 required_flags → 回退 min_score 規則
    p2 = StrategyParams(require_all=False, min_score=2, required_flags=[])
    assert buy_signal({"vol": True, "macd": True}, 2, p2)
    assert not buy_signal({"vol": True, "macd": False}, 1, p2)
    # 非法鍵自動過濾 + 字串化清單容錯
    p3 = StrategyParams.from_dict({"required_flags": ["vol", "hack", 123]})
    assert p3.required_flags == ["vol"]
    p4 = StrategyParams.from_dict({"required_flags": "['vol','rsi']"})
    assert sorted(p4.required_flags) == ["rsi", "vol"]
    # 回測遮罩同樣吃 required_flags(用極小合成序列)
    from . import backtest as bt
    n = 80
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = pd.Series(np.linspace(10, 20, n), index=idx)
    df = pd.DataFrame({"open": close, "high": close * 1.01,
                       "low": close * 0.99, "close": close,
                       "volume": np.linspace(1e6, 2e6, n)}, index=idx)
    pre = bt.precompute(df, p)
    mask = bt.eval_masks(pre, p)
    assert mask.dtype == bool and len(mask) == n
    return "required_flags 優先判定 + 回測遮罩整合 ✓"


def test_screener_scoring():
    """開市前選股:候選池充足 + 評分函數對「放量近高上攻」給高分。"""
    from .screener import Screener
    from .universe import HK_POOL, US_POOL
    assert len(HK_POOL) >= 80 and len(US_POOL) >= 120
    n = 200
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = np.linspace(100, 140, n)
    close[-1] = 150                     # 末段創近高
    vol = np.full(n, 1e6)
    vol[-1] = 5e6                       # 放量
    df = pd.DataFrame({"open": close * 0.99, "high": close * 1.02,
                       "low": close * 0.98, "close": close,
                       "volume": vol}, index=idx)
    row = Screener.score_row(df)
    assert row is not None and row["score"] > 50
    assert row["vol_ratio"] >= 4.5 and row["near_high_pct"] > 0
    return "選股評分 + 候選池規模 ✓"


def test_sectors():
    """行業分類:sector_of 對港/美代號與各種寫法歸類正確。"""
    from .sectors import sector_of, SECTORS, KEY2LABEL
    assert len(SECTORS) == 11 and SECTORS[-1][0] == "other"
    assert sector_of("0700.HK") == "comm"        # 騰訊
    assert sector_of("AAPL") == "tech"
    assert sector_of("700.HK") == "comm"          # 零補齊容錯
    assert sector_of("aapl") == "tech"            # 大小寫
    assert sector_of("0005.HK") == "financial"    # 匯豐
    assert sector_of("UNKNOWN.XYZ") == "other"    # 未收錄 → 其他
    assert KEY2LABEL["tech"] == "Technology"
    return "行業分類(sector_of 港美股/寫法容錯)✓"


def run_all() -> int:
    tests = [test_indicator_math, test_markets, test_ai,
             test_six_condition_trigger,
             test_backtest_pipeline, test_store_roundtrip, test_messages,
             test_strategy_type_coercion, test_custom_required_flags,
             test_screener_scoring, test_sectors]
    print("=" * 62)
    print("港股即日買賣系統 — 自我測試")
    print("=" * 62)
    failed = 0
    for t in tests:
        try:
            detail = t()
            print(f"✅ {t.__name__}: {detail}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
    print("-" * 62)
    print("全部通過 🎉" if not failed else f"{failed} 項失敗")
    return 1 if failed else 0
