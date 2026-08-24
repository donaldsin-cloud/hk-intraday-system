"""Telegram 買賣訊號通知"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests

from .config import stock_name


def _friendly_tg_error(status: int, body: str) -> str:
    """把 Telegram API 錯誤轉成可操作的中文提示。"""
    low = (body or "").lower()
    if status == 401:
        return "Bot Token 錯誤(401)— 請向 @BotFather 重新確認"
    if "chat not found" in low:
        return ("Chat ID 錯誤或尚未對話(400)— 請先在 Telegram 找你的 bot "
                "按 Start 再試;群組 ID 需為 -100 開頭")
    if "bot was blocked" in low:
        return "Bot 已被用戶封鎖"
    if status == 429:
        return "發送過於頻繁(429),稍後自動重試"
    return f"HTTP {status}: {(body or '')[:160]}"


class Notifier:
    def __init__(self, cfg, store=None):
        self.cfg = cfg
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tg")
        self.last_error: str | None = None

    # ---------------- 低階發送 ----------------
    def _post(self, text: str) -> bool:
        # 每次即時讀取 cfg — 網頁儲存 token/chat_id 後立即生效(無需重啟)
        if not self.cfg.tg_token or not self.cfg.tg_chat:
            self.last_error = "缺 bot_token 或 chat_id"
            return False
        if not self.cfg.tg_enabled:
            self.last_error = "未勾選「啟用推送」"
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.cfg.tg_token}/sendMessage",
                json={"chat_id": self.cfg.tg_chat, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=10)
            ok = r.ok
            if not ok:
                self.last_error = _friendly_tg_error(r.status_code, r.text)
            return ok
        except Exception as e:  # noqa: BLE001
            self.last_error = f"無法連線 Telegram: {e}"
            return False

    def send_async(self, text: str):
        self.pool.submit(self._post, text)

    def send_sync(self, text: str) -> bool:
        return self._post(text)

    def test(self) -> tuple[bool, str]:
        ok = self.send_sync("✅ <b>港股即日買賣系統</b> Telegram 連線測試成功")
        return ok, (self.last_error or "OK")

    # ---------------- 訊息模板 ----------------
    def buy_message(self, symbol: str, res: dict, trade_rules,
                    bar_size="1m") -> str:
        name = stock_name(symbol)
        m = res["metrics"]
        price = res.get("close") or 0.0
        tp = trade_rules.take_profit_pct
        sl = trade_rules.stop_loss_pct
        tp_px = price * (1 + tp / 100)
        sl_px = price * (1 - sl / 100)
        lines = [
            f"🟢 <b>【買入訊號】{res['score']}/6 項指標成立</b>"
            + ("(全中!)" if res["score"] == 6 else ""),
            f"📈 <b>{symbol} {name}</b>({bar_size}K線收盤)",
            f"💵 現價:<b>{price:.2f}</b>",
            "",
            "✅ " + "\n✅ ".join(k for k, v in res["label"].items() if v),
            "",
            f"📊 量比 <b>{m.get('vol_ratio', '-')}×</b>"
            f" | RSI <b>{m.get('rsi', '-')}</b>"
            f" | 布林帶寬百分位 <b>{m.get('bb_width_pctile', '-')}</b>",
            f"📐 斐波 <b>{m.get('fib_name', '-')}</b> 位 ≈ {m.get('fib_level', '-')}"
            f"(距離 {m.get('fib_dist_pct', '-')}%)",
            f"⚡ MACD 柱 <b>{m.get('macd_hist', '-')}</b>({m.get('macd_note', '')})",
            "",
            f"🎯 即日計劃:止損 {sl_px:.2f}(-{sl:g}%) / 目標 <b>{tp_px:.2f}(+{tp:g}%)</b>",
            "⚠️ 即日買賣,不留倉過夜。程式訊號僅供參考,不構成投資建議。",
        ]
        return "\n".join(lines)

    def sell_message(self, symbol: str, price: float, pnl_pct: float,
                     reason: str, hold_min: float | None = None) -> str:
        name = stock_name(symbol)
        emoji = "🎯" if pnl_pct >= 0 else "🛑"
        hold = f"　持倉 {hold_min:.0f} 分鐘" if hold_min is not None else ""
        return ("\n".join([
            f"{emoji} <b>【賣出訊號】</b>{reason}",
            f"📉 <b>{symbol} {name}</b>",
            f"💰 賣出參考價:<b>{price:.2f}</b>"
            f"　損益:<b>{pnl_pct:+.2f}%</b>{hold}",
            "⚠️ 即日平倉,資金回籠待下一次訊號。",
        ]))

    # ---------------- 事件快捷 ----------------
    def notify_buy(self, symbol, res, trade_rules, flags, bar_size="1m"):
        msg = self.buy_message(symbol, res, trade_rules, bar_size)
        if self.cfg.tg_enabled:
            self.send_async(msg)
        if self.store:
            self.store.insert_signal(symbol, "BUY", price=res.get("close"),
                                     score=res.get("score"), flags=flags,
                                     note=msg.splitlines()[3] if len(msg.splitlines()) > 3 else "")

    def notify_sell(self, symbol, price, pnl_pct, reason, flags=None,
                    hold_min=None):
        msg = self.sell_message(symbol, price, pnl_pct, reason, hold_min)
        if self.cfg.tg_enabled:
            self.send_async(msg)
        if self.store:
            self.store.insert_signal(symbol, "SELL", price=price, pnl=pnl_pct,
                                     flags=flags or {}, note=reason)


def send_test(bot_token: str, chat_id: str) -> tuple[bool, str]:
    """用給定(或已儲存)token/chat 直接發送測試訊息。
    不受「啟用推送」開關限制 — 方便先測通再儲存。"""
    bot_token = (bot_token or "").strip()
    chat_id = str(chat_id or "").strip()
    if not bot_token or not chat_id:
        return False, "請先填 Bot Token 與 Chat ID"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id,
                  "text": "✅ <b>港股即日買賣系統</b> Telegram 測試成功",
                  "parse_mode": "HTML"}, timeout=12)
        if r.ok:
            return True, "測試訊息已送出 — 請到 Telegram 查看"
        return False, _friendly_tg_error(r.status_code, r.text)
    except Exception as e:  # noqa: BLE001
        return False, f"無法連線 Telegram: {e}"
