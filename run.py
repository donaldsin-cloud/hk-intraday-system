#!/usr/bin/env python3
"""港股即日買賣訊號系統 — 命令列入口

  python run.py web                # 啟動 Web 儀表板 + 掃描器 + 每日調叟(預設)
  python run.py scan-once          # 手動掃描一輪,結果印在終端
  python run.py backtest           # 以目前參數回測最近5年
  python run.py tune               # 立即執行獲利因子網格調叟
  python run.py selftest           # 自我測試(指標/策略/回測/儲存/訊息)
  python run.py telegram-test      # 發送 Telegram 測試訊息
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Windows 主控台強制 UTF-8,避免中文/emoji 輸出失敗
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 專案內依賴目錄(scripts/bootstrap_deps.py 的 stdlib 安裝位置)
_deps = ROOT / ".deps"
if _deps.exists():
    sys.path.append(str(_deps))


def get_cfg(config_path):
    from app.config import Config
    return Config(config_path)


def _norm(s):
    from app.config import normalize_symbol
    return normalize_symbol(s)


def cmd_web(args):
    import uvicorn
    cfg = get_cfg(args.config)
    from app.webapp import create_app
    app = create_app(cfg)
    # 明確指定 h11 + asyncio:避免環境中殘缺的 httptools/uvloop 命名空間干擾
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port,
                http="h11", ws="auto", loop="asyncio", log_level="info")


def cmd_scan_once(args):
    cfg = get_cfg(args.config)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from app.datafeed import create_feed
    from app.indicators import FLAG_KEYS, evaluate
    from app.utils import open_markets
    feed = create_feed(cfg)
    opened = open_markets(cfg)
    print(f"數據源: {feed.name} | 開市市場: {sorted(opened) or '無(休市)'}"
          f" | 生效參數覆蓋見 data/best_params.json")
    params = cfg.active_strategy()
    header = f"{'市場':^4} {'代號':<9}{'現價':>8} {'評分':>4} " + " ".join(
        f"{k[:4]:^5}" for k in FLAG_KEYS) + "  買入?"
    print(header)
    print("-" * len(header))
    for sym, mk in cfg.all_symbols():
        tag = "HK" if mk == "hk" else "US"
        try:
            df = feed.get_bars(sym, cfg.bar_size, cfg.lookback)
            res = evaluate(df, params)
            marks = " ".join("✓".center(4) if res["flags"][k] else "·".center(4)
                             for k in FLAG_KEYS)
            mark = "★ BUY" if res["buy"] else ("-" if not res["ready"] else "")
            print(f"{tag:^4} {sym:<9}{res['close'] or 0:>8.2f} {res['score']:>4}"
                  f" {marks}  {mark}")
        except Exception as e:  # noqa: BLE001
            print(f"{tag:^4} {sym:<9}  失敗: {e}")


def _load_frames(cfg, feed, symbols):
    frames = {}
    for sym in symbols:
        try:
            df = feed.history_daily(sym, cfg.backtest_years)
            if len(df) > 150:
                frames[sym] = df
                print(f"  {sym}: {len(df)} 根日K")
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: 取數失敗 {e}")
    return frames


def cmd_backtest(args):
    cfg = get_cfg(args.config)
    from app.backtest import run_portfolio
    from app.datafeed import create_feed
    feed = create_feed(cfg)
    symbols = ([normalize_symbol(s) for s in args.symbols.split(",")]
               if args.symbols else [s for s, _m in cfg.all_symbols()])
    print(f"回測 {cfg.backtest_years} 年 | 成本 {cfg.backtest_cost_pct}%/"
          f"筆 | 目標 +{cfg.trade_rules.take_profit_pct}%")
    frames = _load_frames(cfg, feed, symbols)
    p = cfg.active_strategy()
    out = run_portfolio(frames, p, cfg.trade_rules.take_profit_pct,
                        cfg.trade_rules.stop_loss_pct, cfg.backtest_cost_pct)
    m = out["metrics"]
    for k, v in m.items():
        if k != "per_symbol":
            print(f"  {k}: {v}")
    from app.store import Store
    run_id = Store(cfg.db_path).insert_backtest(
        "manual", list(frames), p.to_dict(), {}, m, out["equity"], out["trades"])
    print(f"已存入資料庫 → 回測 #{run_id}(儀表板「回測與調叟」頁可看詳情)")


def cmd_tune(args):
    cfg = get_cfg(args.config)
    from app.datafeed import create_feed
    from app.optimizer import save_best, tune
    from app.store import Store
    feed = create_feed(cfg)
    print(f"調叟開始:網格搜索 × 訓練70%/驗證30%,目標=最高獲利因子…")
    frames = _load_frames(cfg, feed,
                          [s for s, _m in cfg.all_symbols()])
    result = tune(frames, cfg.strategy, cfg, log=print)
    if "error" in result:
        print(f"失敗: {result['error']}")
        return 1
    save_best(cfg, result)
    Store(cfg.db_path).insert_backtest(
        "manual-tune", list(frames), result["params"], result["overrides"],
        result["metrics"], result["equity"], result["trades"])
    m = result["metrics"]
    print("最佳參數覆蓋:", result["overrides"])
    print(f"全期驗證: PF={m['profit_factor']} 勝率={m['win_rate']}% "
          f"交易={m['trades']} 總報酬={m['total_return_pct']}% "
          f"最大回撤={m['max_drawdown_pct']}%")
    print(f"已寫入 {cfg.best_params_path}")
    return 0


def cmd_selftest(args):
    from app.selftest import run_all
    return run_all()


def cmd_telegram_test(args):
    cfg = get_cfg(args.config)
    from app.notifier import Notifier
    ok, err = Notifier(cfg).test()
    print("✅ 已發送" if ok else f"❌ 失敗: {err}"
          "(請檢查 config.yaml 的 bot_token / chat_id / enabled)")
    return 0 if ok else 1


def main():
    pa = argparse.ArgumentParser(description="港股即日買賣訊號系統")
    pa.add_argument("--config", "-c", default=None, help="設定檔路徑")
    sub = pa.add_subparsers(dest="cmd", required=True)
    sub.add_parser("web").set_defaults(fn=cmd_web)
    sub.add_parser("scan-once").set_defaults(fn=cmd_scan_once)
    b = sub.add_parser("backtest"); b.add_argument("--symbols", default=None); b.set_defaults(fn=cmd_backtest)
    sub.add_parser("tune").set_defaults(fn=cmd_tune)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    sub.add_parser("telegram-test").set_defaults(fn=cmd_telegram_test)
    args = pa.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
