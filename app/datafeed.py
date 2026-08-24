"""數據源抽象層:Futu OpenAPI / yfinance / 合成數據(示範)
統一輸出:DataFrame(index=DatetimeIndex, columns=open/high/low/close/volume)
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .config import futu_code, yf_code
from .utils import HKT, now_hkt


class FeedError(Exception):
    pass


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """欄位標準化為小寫 ohlcv,索引轉為 naive HKT 時間。"""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [str(c).lower().split()[0] for c in df.columns]
    ren = {}
    for cand in ("open", "high", "low", "close"):
        for alt in (cand, f"{cand}s"):
            if alt in df.columns:
                ren[alt] = cand
                break
    volcol = next((x for x in ("volume", "vol", "volumes") if x in df.columns), None)
    ren["adj close"] = "close"
    df = df.rename(columns=ren)
    cols = ["open", "high", "low", "close"] + ([volcol] if volcol else [])
    missing = [c for c in ["open", "high", "low", "close"] if c not in df.columns]
    if missing:
        raise FeedError(f"K線數據缺少欄位: {missing}")
    if volcol is None:
        df["volume"] = 0
        cols.append("volume")
    df = df[cols].astype(float)
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(HKT).tz_localize(None)
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def drop_partial_last(df: pd.DataFrame) -> pd.DataFrame:
    """即時K線:丟棄最後一根可能未完成的K線,避免訊號重繪。"""
    if len(df) > 1:
        return df.iloc[:-1]
    return df


# ---------------------------------------------------------------- Futu
class FutuFeed:
    name = "futu"

    def __init__(self, cfg):
        from futu import OpenQuoteContext  # noqa: 需求未裝時拋錯由工廠捕捉
        self._mod = __import__("futu")
        self.qc = None
        self.cfg = cfg
        self._connect()

    def _connect(self):
        self.qc = self._mod.OpenQuoteContext(host=self.cfg.futu_host,
                                             port=self.cfg.futu_port)

    def warmup_check(self):
        ret, _ = self.qc.get_global_state()
        if ret != self._mod.RET_OK:
            raise FeedError("FutuOpenD 未就緒")

    def get_bars(self, symbol: str, size: str = "1m", count: int = 300) -> pd.DataFrame:
        kl = {"1m": self._mod.KLType.K_1M,
              "5m": self._mod.KLType.K_5M,
              "15m": self._mod.KLType.K_15M}.get(size, self._mod.KLType.K_1M)
        code = futu_code(symbol)
        sub = {"1m": self._mod.SubType.K_1M,
               "5m": self._mod.SubType.K_5M,
               "15m": self._mod.SubType.K_15M}.get(size, self._mod.SubType.K_1M)
        self.qc.subscribe([code], [sub], register_push=False)
        ret, data, _ = self.qc.request_history_kline(
            code, start=(now_hkt() - timedelta(days=10)).strftime("%Y-%m-%d"),
            end=None, ktype=kl, max_count=count + 5, page_req_key=None)
        if ret != self._mod.RET_OK:
            raise FeedError(f"futu 取K線失敗: {data}")
        df = data.rename(columns={"time_key": "datetime", "turnover": "turnover"})
        df.index = pd.to_datetime(df.pop("datetime"))
        out = _normalize(df)
        return drop_partial_last(out.tail(count))

    def history_daily(self, symbol: str, years: int = 5) -> pd.DataFrame:
        code = futu_code(symbol)
        frames = []
        end = now_hkt()
        start = end - timedelta(days=int(years * 365) + 14)
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(days=365 * 3), end)  # 單頁最多1000根,3年日K足夠
            ret, data, _ = self.qc.request_history_kline(
                code, start=cur.strftime("%Y-%m-%d"), end=nxt.strftime("%Y-%m-%d"),
                ktype=self._mod.KLType.K_DAY, max_count=1000, page_req_key=None)
            if ret != self._mod.RET_OK:
                raise FeedError(f"futu 歷史日K失敗: {data}")
            data.index = pd.to_datetime(data.pop("time_key"))
            frames.append(_normalize(data))
            cur = nxt + timedelta(days=1)
        out = pd.concat(frames)
        return out[~out.index.duplicated(keep="last")].sort_index()

    def close(self):
        try:
            if self.qc:
                self.qc.close()
        except Exception:
            pass


# ---------------------------------------------------------------- yfinance
class YFinanceFeed:
    name = "yfinance"

    def __init__(self, cfg):
        import yfinance  # noqa
        self.yf = yfinance
        self.cfg = cfg
        # 把 yfinance 的 sqlite 快取導到專案 data/ 下,
        # 避免受限環境(或無寫入權限的系統快取目錄)造成寫入失敗。
        try:
            from .config import DATA_DIR
            cache_dir = DATA_DIR / "yf-cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            from yfinance import cache as _yfcache
            _yfcache.set_cache_location(str(cache_dir))
        except Exception:
            pass

    @staticmethod
    def _retry(fn, what: str, tries: int = 3):
        """帶退避重試:Yahoo 對資料中心 IP 偶發 429/斷線。"""
        import time as _t
        last = None
        for i in range(tries):
            try:
                out = fn()
                if out is None or (hasattr(out, "__len__") and len(out) == 0):
                    raise RuntimeError("返回空數據")
                return out
            except Exception as e:  # noqa: BLE001
                last = e
                if i < tries - 1:
                    _t.sleep(min(1.5 * (i + 1), 4))
        raise FeedError(f"{what} 失敗(重試 {tries} 次): {last}")

    def warmup_check(self):
        self._retry(lambda: self.yf.Ticker(yf_code("0700.HK")).history(
            period="5d", interval="1d"), "yfinance 連線測試")

    def get_bars(self, symbol: str, size: str = "1m", count: int = 300) -> pd.DataFrame:
        period = {"1m": "7d", "5m": "60d", "15m": "60d"}.get(size, "7d")
        code = yf_code(symbol)

        def _fetch():
            raw = self.yf.Ticker(code).history(period=period, interval=size,
                                               auto_adjust=False)
            out = _normalize(raw)
            if len(out) == 0:
                raise RuntimeError(f"{code} 無 {size} K線(Yahoo 可能封鎖此 IP 或休市)")
            return out

        out = self._retry(_fetch, f"取得 {symbol} {size}K")
        return drop_partial_last(out.tail(count))

    def history_daily(self, symbol: str, years: int = 5) -> pd.DataFrame:
        code = yf_code(symbol)

        def _fetch():
            raw = self.yf.download(code, period=f"{max(1, min(years, 20))}y",
                                   interval="1d", progress=False, auto_adjust=False)
            out = _normalize(raw)
            if len(out) == 0:
                raise RuntimeError("空數據")
            return out

        try:
            return self._retry(_fetch, f"取得 {symbol} 日K")
        except FeedError:
            # 雲端備援:Stooq 免金鑰 CSV(對資料中心 IP 友善)
            fb = _stooq_daily(symbol, years)
            if fb is not None and len(fb) > 60:
                return fb
            raise

    def close(self):
        pass


# ---------------------------------------------------------------- Stooq 備援
def _stooq_daily(symbol: str, years: int = 5) -> pd.DataFrame | None:
    """Stooq 免金鑰日K CSV:雲端 IP 友善。港股=0700.hk、美股=aapl.us。"""
    import io
    import requests
    from .config import detect_market, normalize_symbol
    sym = normalize_symbol(symbol)
    s = (sym.split(".")[0].zfill(4) + ".hk") if detect_market(sym) == "hk" \
        else (sym.lower() + ".us")
    url = f"https://stooq.com/q/d/l/?s={s}&i=d"
    try:
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if "No data" in r.text[:200] or len(r.text) < 100:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=max(1, min(years, 20)))
        df = df[df.index >= cutoff]
        return _normalize(df[["open", "high", "low", "close", "volume"]])
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 合成數據
def _symbol_seed(symbol: str) -> int:
    return abs(hash(symbol)) % (2 ** 31)


def synth_daily_frame(symbol: str, years: int = 5) -> pd.DataFrame:
    """帶趨勢輪換的幾何布朗運動,量價相關;固定種子可重現。"""
    rng = np.random.default_rng(_symbol_seed(symbol))
    n = int(years * 244)
    drift = rng.normal(0.0004, 0.0009)          # 年化漂移
    vol = rng.uniform(0.018, 0.032)
    rets, regimes = [], []
    r_drift = drift
    for i in range(n):
        if i % 40 == 0:                          # 每 ~2個月換一次短趨勢
            r_drift = drift + rng.normal(0, 0.0022)
        e = rng.normal(r_drift, vol)
        rets.append(e)
        regimes.append(r_drift)
    close = 80.0 * np.exp(np.cumsum(rets))
    opn = close * np.exp(rng.normal(-0.0005, 0.006, n))
    hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    base_vol = 2e6 * (1 + 30 * np.abs(np.array(rets)))           # 大波動=大成交
    volume = base_vol * np.exp(rng.normal(11.5, 0.55, n))
    idx = pd.bdate_range(end=now_hkt().date() - timedelta(days=1), periods=n)
    return _normalize(pd.DataFrame({"Open": opn, "High": hi, "Low": lo,
                                    "Close": close, "Volume": volume}, index=idx))


class SyntheticFeed:
    name = "synthetic"

    def __init__(self, cfg):
        self.cfg = cfg
        self._cache: dict[str, pd.DataFrame] = {}
        self._minute_cache: dict[str, pd.DataFrame] = {}

    def warmup_check(self):
        pass  # 永遠可用

    def _synth_minutes(self, symbol: str) -> pd.DataFrame:
        """以最近 60 個交易日生成 1 分鐘合成K線(示範用)。"""
        daily = self.history_daily(symbol, years=2)
        if len(daily) < 61:
            raise FeedError("synthetic daily 不足")
        rng = np.random.default_rng(_symbol_seed(symbol) ^ 0xBADC0DE)
        rows = []
        last_days = daily.iloc[-60:]
        for day, row in last_days.iterrows():
            o, c = float(row["open"]), float(row["close"])
            h, l = float(row["high"]), float(row["low"])
            v = float(row.get("volume", 1e6)) or 1e6
            path = np.linspace(o, c, 330) + rng.normal(0, (h - l) / 12, 330)
            path = np.clip(path, l * 0.999, h * 1.001)
            ts = day.replace(hour=9, minute=30)
            for i, px in enumerate(path):
                t = ts + timedelta(minutes=int(i * (330 / 329)))
                rows.append((t, px, px * 1.0004, px * 0.9996, px,
                             max(v / 330 * (1 + rng.normal(0, 0.35)), 1.0)))
        df = pd.DataFrame(rows, columns=["dt", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("dt"))
        return df.sort_index()

    def get_bars(self, symbol: str, size: str = "1m", count: int = 300) -> pd.DataFrame:
        key = (symbol, size)
        if key not in self._minute_cache:
            df = self._synth_minutes(symbol)
            self._minute_cache[key] = df
        df = self._minute_cache[key]
        return df.tail(count)

    def history_daily(self, symbol: str, years: int = 5) -> pd.DataFrame:
        ck = (symbol, years)
        if ck not in self._cache:
            self._cache[ck] = synth_daily_frame(symbol, years)
        return self._cache[ck]

    def close(self):
        pass


# ---------------------------------------------------------------- 騰訊行情
def _tx_headers():
    return {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}


def _tx_symbol(symbol: str) -> str:
    from .config import detect_market, normalize_symbol
    s = normalize_symbol(symbol)
    if detect_market(s) == "hk":
        return "hk" + s.split(".")[0].zfill(5)
    return "us" + s.upper()


def _tx_parse(bars: list) -> pd.DataFrame:
    """騰訊K線列 [時間,開,收,高,低,量,…] → 標準 OHLCV DataFrame。"""
    rows = []
    for b in bars:
        t = str(b[0])
        ts = pd.to_datetime(t, format="%Y%m%d%H%M") if len(t) >= 12 \
            else pd.to_datetime(t)
        # 騰訊順序:[時間, 開, 收, 高, 低, 量]
        rows.append((ts, float(b[1]), float(b[3]), float(b[4]),
                     float(b[2]), float(b[5])))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low",
                                     "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


class TencentFeed:
    """騰訊行情(web.ifzq.gtimg.cn)— 免金鑰,港/美 分K與日K。"""
    name = "tencent"

    def __init__(self, cfg):
        self.cfg = cfg

    def _get(self, url: str):
        import requests
        r = requests.get(url, headers=_tx_headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def warmup_check(self):
        df = self._daily("hk00700", 120)
        if df is None or len(df) == 0:
            raise FeedError("騰訊行情無法取得測試數據")

    def _mkline(self, code: str, m: str, n: int):
        """分K端點有兩個主機,依序嘗試。"""
        last = None
        for host in ("https://ifzq.gtimg.cn", "https://web.ifzq.gtimg.cn"):
            try:
                return self._get(f"{host}/appstock/app/kline/mkline"
                                 f"?param={code},{m},,{n}")
            except Exception as e:  # noqa: BLE001
                last = e
        raise FeedError(f"騰訊分K連線失敗: {last}")

    def _daily(self, symbol: str, count: int) -> pd.DataFrame:
        code = _tx_symbol(symbol)
        d = self._get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                      f"?param={code},day,,,{count},qfq")
        node = (d.get("data") or {}).get(code) or {}
        bars = next((node[k] for k in node if "day" in k and
                     isinstance(node[k], list)), None)
        if not bars:
            raise FeedError(f"騰訊無 {symbol} 日K數據")
        out = _normalize(_tx_parse(bars))
        if len(out) < min(count, 60):     # 太少=代號不對(如美股缺後綴)
            raise FeedError(f"騰訊 {symbol} 日K僅{len(out)}根")
        return out

    def get_bars(self, symbol: str, size: str = "1m", count: int = 300) -> pd.DataFrame:
        m = {"1m": "m1", "5m": "m5", "15m": "m15"}.get(size, "m1")
        code = _tx_symbol(symbol)
        d = self._mkline(code, m, max(count + 20, 60))
        node = (d.get("data") or {}).get(code) or {}
        bars = node.get(m)
        if not bars:
            raise FeedError(f"騰訊無 {symbol} {size} K(Yahoo式休市或代號不支援)")
        out = _normalize(_tx_parse(bars))
        return drop_partial_last(out.tail(count))

    def history_daily(self, symbol: str, years: int = 5) -> pd.DataFrame:
        want = min(int(years * 260) + 30, 4000)
        try:
            return self._daily(symbol, want)
        except FeedError:
            if _tx_symbol(symbol).startswith("us"):     # 美股補交易所後綴再試
                for suf in (".OQ", ".N", ".A"):
                    code = _tx_symbol(symbol) + suf
                    d = self._get("https://web.ifzq.gtimg.cn/appstock/app/fqkline"
                                  f"/get?param={code},day,,,{want},qfq")
                    node = (d.get("data") or {}).get(code) or {}
                    bars = next((node[k] for k in node if "day" in k
                                 and isinstance(node[k], list)), None)
                    if bars and len(bars) > 100:
                        return _normalize(_tx_parse(bars))
            raise

    def close(self):
        pass


# ---------------------------------------------------------------- 東方財富
_EM_KLT = {"1m": "1", "5m": "5", "15m": "15"}
_EM_US_MARKETS = ("105", "106", "107")      # NYSE / NASDAQ / AMEX


def _em_secid(symbol: str, resolved: dict | None = None) -> tuple[str, str]:
    from .config import detect_market, normalize_symbol
    s = normalize_symbol(symbol)
    if detect_market(s) == "hk":
        return "116." + s.split(".")[0].zfill(5), ""
    code = s.upper()
    hit = (resolved or {}).get(code)
    if hit:
        return f"{hit}.{code}", hit
    return f"105.{code}", ""                  # 先試 NYSE,失敗時上層輪詢


def _em_parse(klines: list) -> pd.DataFrame:
    """東方財富 klines 字串 'date,open,close,high,low,volume[,amount…]' → DF"""
    rows = []
    for line in klines:
        p = str(line).split(",")
        # 順序:f51日期 f52開 f53收 f54高 f55低 f56量
        rows.append((pd.to_datetime(p[0]), float(p[1]), float(p[3]),
                     float(p[4]), float(p[2]), float(p[5])))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low",
                                     "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


class EastMoneyFeed:
    """東方財富(push2his.eastmoney.com)— 免金鑰歷史K線,HK=116/US=105-107。"""
    name = "eastmoney"

    def __init__(self, cfg):
        self.cfg = cfg
        self._mk_cache: dict[str, str] = {}

    def _get(self, secid: str, klt: str, lmt: int):
        import requests
        u = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
             f"?secid={secid}&klt={klt}&fqt=1&lmt={lmt}&end=20500101"
             "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57")
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        kl = data.get("klines") or []
        return kl

    def warmup_check(self):
        kl = self._get("116.00700", "101", 30)
        if not kl:
            raise FeedError("東方財富無法取得測試數據")

    def _resolve_us(self, symbol: str, klt: str, lmt: int) -> list:
        """美股要選對市場代號:105 NYSE → 106 NASDAQ → 107 AMEX。"""
        from .config import normalize_symbol
        code = normalize_symbol(symbol).upper()
        cached = self._mk_cache.get(code)
        order = ([cached] if cached else []) + \
                [m for m in _EM_US_MARKETS if m != cached]
        last_err = None
        for m in order:
            try:
                kl = self._get(f"{m}.{code}", klt, lmt)
                if kl:
                    self._mk_cache[code] = m
                    return kl
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise FeedError(f"東方財富無 {code} 數據({last_err})")

    def get_bars(self, symbol: str, size: str = "1m", count: int = 300) -> pd.DataFrame:
        klt = _EM_KLT.get(size, "1")
        secid, mk = _em_secid(symbol, self._mk_cache)
        if mk:                                    # 已知美股歸屬市場
            kl = self._get(secid, klt, max(count + 20, 60))
        else:
            kl = self._resolve_us(symbol, klt, max(count + 20, 60)) \
                if market_us(symbol) else self._get(secid, klt, max(count + 20, 60))
            if not kl and not market_us(symbol):
                raise FeedError(f"東方財富無 {symbol} {size} K")
        if not kl:
            raise FeedError(f"東方財富無 {symbol} {size} K")
        out = _normalize(_em_parse(kl))
        return drop_partial_last(out.tail(count))

    def history_daily(self, symbol: str, years: int = 5) -> pd.DataFrame:
        want = min(int(years * 260) + 30, 8000)
        secid, mk = _em_secid(symbol, self._mk_cache)
        kl = self._resolve_us(symbol, "101", want) if market_us(symbol) \
            else self._get(secid, "101", want)
        if not kl:
            raise FeedError(f"東方財富無 {symbol} 日K")
        out = _normalize(_em_parse(kl))
        cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(
            years=max(1, min(years, 20)))
        out = out[out.index >= cutoff]
        if len(out) < 60:
            raise FeedError(f"東方財富 {symbol} 日K不足({len(out)}根)")
        return out

    def close(self):
        pass


def market_us(symbol: str) -> bool:
    from .config import detect_market, normalize_symbol
    return detect_market(normalize_symbol(symbol)) == "us"


# ---------------------------------------------------------------- 工廠
_FEED_CLASSES = {"futu": FutuFeed, "yfinance": YFinanceFeed,
                 "tencent": TencentFeed, "eastmoney": EastMoneyFeed,
                 "synthetic": SyntheticFeed}


def create_feed(cfg, prefer: str | None = None):
    """mode=auto 時依 futu → yfinance → tencent → eastmoney → synthetic 探測降級。
    騰訊/東方財富免金鑰且對雲端 IP 友善,作 Yahoo 被封時的備援。"""
    mode = prefer or os.environ.get("HK_FEED") or cfg.feed_mode or "auto"
    order = [mode] if mode != "auto" else \
        ["futu", "yfinance", "tencent", "eastmoney", "synthetic"]
    errors = []
    for name in order:
        cls = _FEED_CLASSES.get(name)
        if cls is None:
            continue
        try:
            feed = cls(cfg)
            feed.warmup_check()
            return feed
        except Exception as e:  # noqa: BLE001 — 任何來源失敗都降級
            msg = f"數據源 {name} 不可用: {type(e).__name__}: {e}"
            errors.append(msg)
            print(f"[feed] {msg}")
    raise FeedError("; ".join(errors))
