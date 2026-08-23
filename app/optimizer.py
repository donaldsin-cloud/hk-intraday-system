"""獲利因子最佳化器:網格搜索 + 70/30 訓練/驗證切分,每日自動重跑"""
from __future__ import annotations

import itertools
import json
from datetime import datetime

import numpy as np

from . import backtest as bt


def param_grid() -> list[dict]:
    """針對六大條件關鍵閾值 + 止損的組合網格(432組)。"""
    grid = {
        "vol_expand_ratio": [1.5, 2.0, 2.5, 3.0],
        "fib_tolerance_pct": [1.0, 1.5, 2.0, 2.5],
        "bb_width_pctile": [70, 80, 90],
        "rsi_band": [(40, 60), (45, 58), (48, 55)],
        "stop_loss_pct": [2.0, 3.0, 4.0],
    }
    keys = list(grid)
    combos = []
    for values in itertools.product(*grid.values()):
        d = dict(zip(keys, values))
        lo, hi = d.pop("rsi_band")
        d["rsi_lo"], d["rsi_hi"] = float(lo), float(hi)
        d["stop_loss_pct"] = float(d["stop_loss_pct"])
        combos.append(d)
    return combos


def _pf(metrics: dict) -> float:
    """評分用獲利因子:封頂 20(避免小樣本零虧損的 ∞),
    並按交易數線性懲罰(n<20 時),避免兩三筆幸運交易勝出。"""
    pf = float(metrics.get("profit_factor", 0.0))
    pf = min(pf, 20.0)
    n = metrics.get("trades", 0)
    return pf * min(1.0, n / 20.0) if n else 0.0


def _select(results: list[dict], min_trades: int):
    """分層選優:驗證集交易數達標者按驗證PF排序;
    不足時逐級放寬,永遠偏好樣本更多的層。"""
    tiers = [
        ("val≥min", [r for r in results if r["val"]["trades"] >= min_trades],
         "score_val"),
        ("val≥12", [r for r in results if r["val"]["trades"] >= 12],
         "score_val"),
        ("val≥6", [r for r in results if r["val"]["trades"] >= 6],
         "score_val"),
        ("train≥12", [r for r in results if r["train"]["trades"] >= 12],
         "score_train"),
        ("all", results, "score_train"),
    ]
    for name, pool, key in tiers:
        if pool:
            best = max(pool, key=lambda r: (r[key],
                                            r["train" if key == "score_val" else "val"]["trades"]))
            return best, name, len(pool)
    return results[0], "fallback", 1


def tune(frames: dict, base_params, cfg, log=print) -> dict:
    """訓練/驗證切分 → 網格搜索 → 以驗證集獲利因子選優 → 全期複核。

    效率關鍵:調叟只改閾值類參數,其中僅 bb_width_pctile 影響預計算,
    故每個 (symbol, pctile) 只做一次 precompute。"""
    train_f, val_f = bt.split_frames(frames, cfg.opt_train_ratio)
    if not train_f or not val_f:
        return {"error": "數據不足以切分訓練/驗證集"}

    tp = cfg.trade_rules.take_profit_pct
    cost = cfg.backtest_cost_pct
    min_trades = cfg.opt_min_trades

    pre_cache: dict = {}

    def pres(frame_dict, pctile):
        out = {}
        for sym, df in frame_dict.items():
            key = (sym, pctile)
            if key not in pre_cache:
                pre_cache[key] = bt.precompute(
                    df, base_params.overlay({"bb_width_pctile": pctile}))
            out[sym] = pre_cache[key]
        return out

    def run_set(frame_dict, ov):
        p = base_params.overlay(ov)
        sl = float(ov["stop_loss_pct"])
        trades = []
        for sym, pre in pres(frame_dict, p.bb_width_pctile).items():
            mask = bt.eval_masks(pre, p)
            for t in bt.simulate(pre, mask, tp, sl, cost):
                t["symbol"] = sym
                trades.append(t)
        trades.sort(key=lambda t: t["date"])
        return {"metrics": bt.compute_metrics(trades), "trades": trades}

    grid = param_grid()
    results = []
    for i, ov in enumerate(grid):
        tr = run_set(train_f, ov)
        va = run_set(val_f, ov)
        results.append({
            "overrides": ov,
            "train": tr["metrics"], "val": va["metrics"],
            "score_train": _pf(tr["metrics"]), "score_val": _pf(va["metrics"]),
        })
        if (i + 1) % 100 == 0:
            log(f"[tune] {i + 1}/{len(grid)} 組合完成")

    best, tier, pool_n = _select(results, min_trades)
    basis = tier

    # 全期用最佳參數複核
    p_best = base_params.overlay(best["overrides"])
    full = bt.run_portfolio(frames, p_best, tp,
                            float(best["overrides"]["stop_loss_pct"]), cost)

    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "basis": basis,
        "overrides": best["overrides"],
        "params": p_best.to_dict(),
        "train_metrics": best["train"],
        "val_metrics": best["val"],
        "metrics": full["metrics"],
        "equity": full["equity"],
        "trades": full["trades"],
        "grid_size": len(results),
        "valid_candidates": pool_n,
        "tier": tier,
    }


def save_best(cfg, tune_result: dict):
    payload = {
        "ts": tune_result["ts"], "basis": tune_result["basis"],
        "overrides": tune_result["overrides"],
        "profit_factor": tune_result["metrics"].get("profit_factor"),
        "win_rate": tune_result["metrics"].get("win_rate"),
        "trades": tune_result["metrics"].get("trades"),
    }
    cfg.best_params_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
