import requests

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}

# --- 騰訊 分K ---
for code in ["hk00700", "usAAPL"]:
    u = f"https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},m1,,320"
    try:
        d = requests.get(u, headers=H, timeout=15).json()
        node = d.get("data", {}).get(code)
        key = [k for k in (node or {}) if k.startswith("m")]
        arr = (node or {}).get(key[0]) if key else None
        print("TX m1", code, "->", len(arr) if arr else 0,
              "| first:", arr[0][:3] if arr else "-")
    except Exception as e:
        print("TX m1", code, "EXC:", str(e)[:80])

# --- 騰訊 日K ---
for code in ["hk00700", "usAAPL"]:
    u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,1300,qfq"
    try:
        d = requests.get(u, headers=H, timeout=15).json()
        node = d.get("data", {}).get(code)
        key = [k for k in (node or {}) if "day" in k]
        arr = (node or {}).get(key[0]) if key else None
        print("TX day", code, "->", len(arr) if arr else 0,
              "| last:", arr[-1][:3] if arr else "-")
    except Exception as e:
        print("TX day", code, "EXC:", str(e)[:80])

# --- 東方財富 ---
def em(secid, klt, lmt):
    u = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
         f"?secid={secid}&klt={klt}&fqt=1&lmt={lmt}&end=20500101"
         "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56")
    return requests.get(u, headers=H, timeout=15).json()

for secid, tag in [("116.00700", "HK 0700"), ("105.AAPL", "US AAPL"),
                   ("106.AAPL", "US AAPL nas")]:
    try:
        d = em(secid, 101, 5)
        kl = (d.get("data") or {}).get("klines") or []
        print("EM", tag, "->", len(kl), "| last:", kl[-1] if kl else "-")
    except Exception as e:
        print("EM", tag, "EXC:", str(e)[:80])
