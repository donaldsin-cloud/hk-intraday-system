"""AI 分析引擎:任何 OpenAI 相容 chat/completions 端點皆可。
支援:DeepSeek、OpenAI、Google Gemini(OpenAI相容模式)、OpenRouter、
Moonshot Kimi、阿里通義、Groq、Mistral、Ollama/vLLM 本機模型…
"""
from __future__ import annotations

import json
import time

import requests

DEFAULT_TIMEOUT = 90


# ---------------------------------------------------------------- 提示詞
SYSTEM_PROMPT = (
    "你是一位專業即日買賣(intraday)技術分析助理。用戶會提供一隻股票的最新 "
    "六項技術指標數據(成交量放大/均線多頭排列/布林帶開口/斐波那契回調/"
    "RSI 中軸止穩/MACD 金叉)。留意港美股特性差異(交易時段、流動性、貨幣、稅費)。\n"
    "請用繁體中文輸出,格式如下:\n"
    "【綜合判斷】偏多/偏空/觀望 + 一句理由\n"
    "【指標解讀】逐項一句(成立的說強度,不成立的說欠缺什麼)\n"
    "【關鍵價位】支撐/阻力/止損參考\n"
    "【操作建議】進場策略與倉位建議(保守)\n"
    "【信心度】0-10 分\n"
    "最後加一行免責聲明。總長度控制在 300 字內,不要廢話。"
)


def build_user_prompt(payload: dict) -> str:
    """payload = analyze 端點的結果(res)+ 交易規則。壓成精簡 JSON。"""
    mk = payload.get("market")
    slim = {
        "symbol": payload.get("symbol"),
        "market": mk,
        "market_name": ("香港股市(HKT 09:30-16:00,T+0 即日鮮可来回,計價 HKD)"
                        if mk == "hk" else
                        "美國股市(ET 09:30-16:00 含盤前後流動性差異,計價 USD)"
                        if mk == "us" else str(mk)),
        "bar_size": payload.get("bar_size"),
        "price": payload.get("close"),
        "chg_pct": payload.get("chg_pct"),
        "score_6": payload.get("score"),
        "buy_signal": payload.get("buy"),
        "flags": payload.get("flags"),
        "metrics": payload.get("metrics"),
        "trade_rules": payload.get("trade_rules"),
    }
    return ("請分析以下股票數據:\n```json\n"
            + json.dumps(slim, ensure_ascii=False, default=str)
            + "\n```")


# ---------------------------------------------------------------- 呼叫
def chat_completion(provider: dict, messages: list[dict],
                    temperature: float = 0.4,
                    max_tokens: int = 900,
                    timeout: int = DEFAULT_TIMEOUT) -> tuple[str, float]:
    """呼叫 OpenAI 相容端點,回傳 (回覆文字, 耗時秒)。失敗 raise RuntimeError(中文)。"""
    base = (provider.get("base_url") or "").strip().rstrip("/")
    key = (provider.get("api_key") or "").strip()
    model = (provider.get("model") or "").strip()
    name = provider.get("name") or base
    if not base:
        raise RuntimeError(f"[{name}] 缺少 base_url")
    if not model:
        raise RuntimeError(f"[{name}] 缺少 model 名稱")
    url = base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    t0 = time.time()
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"[{name}] 逾時({timeout}s)— 模型太慢或網絡不通")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"[{name}] 無法連線: {e}")
    dt = time.time() - t0
    if r.status_code == 401:
        raise RuntimeError(f"[{name}] API Key 無效(401)")
    if r.status_code == 429:
        raise RuntimeError(f"[{name}] 額度用盡或太快(429)")
    if r.status_code != 200:
        snippet = r.text[:180]
        raise RuntimeError(f"[{name}] HTTP {r.status_code}: {snippet}")
    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        if not content:
            raise KeyError("empty content")
        return content.strip(), dt
    except Exception:
        raise RuntimeError(f"[{name}] 回應格式異常: {r.text[:180]}")


def analyze_payload(provider: dict, payload: dict) -> tuple[str, float]:
    """對一次 analyze() 的結果做 AI 解讀。"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(payload)}]
    return chat_completion(provider, msgs)


PROVIDER_PRESETS = {
    "DeepSeek": {"base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat"},
    "OpenAI": {"base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini"},
    "Gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.0-flash"},
    "OpenRouter": {"base_url": "https://openrouter.ai/api/v1",
                   "model": "anthropic/claude-3.5-sonnet"},
    "Kimi 月之暗面": {"base_url": "https://api.moonshot.cn/v1",
                    "model": "moonshot-v1-8k"},
    "通義千問": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
              "model": "qwen-plus"},
    "Groq": {"base_url": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile"},
    "Ollama 本機": {"base_url": "http://127.0.0.1:11434/v1",
                 "model": "llama3.1"},
}
