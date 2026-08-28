"""股票行業分類(GICS 風格,依使用者指定 10 大類 + 其他)。
內建精選池與常見代號對照;未收錄者歸入「其他 Other」。
key 為內部代號:美股 "AAPL"、港股 "0700.HK"。"""

import re

# 依使用者指定順序;(key, 英文, 中文)
SECTORS = [
    ("tech", "Technology", "科技"),
    ("energy", "Energy", "能源"),
    ("financial", "Financial", "金融"),
    ("real_estate", "Real Estate", "房地產"),
    ("health", "Health Care", "醫療保健"),
    ("materials", "Materials", "原材料"),
    ("comm", "Communication Services", "通訊服務"),
    ("cons_disc", "Consumer Discretionary", "非必需消費"),
    ("cons_stap", "Consumer Staples", "必需消費"),
    ("utilities", "Utilities", "公用事業"),
    ("other", "Other", "其他"),
]
KEY2LABEL = {k: en for k, en, _ in SECTORS}
LABEL2KEY = {en: k for k, en, _ in SECTORS}

# 美股 → 行業(缺省歸「其他」)
US = {
    # Technology
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "AMD": "tech",
    "AVGO": "tech", "INTC": "tech", "QCOM": "tech", "TXN": "tech",
    "ADBE": "tech", "CRM": "tech", "ORCL": "tech", "CSCO": "tech",
    "ACN": "tech", "IBM": "tech", "ADI": "tech", "MU": "tech",
    "ON": "tech", "AMAT": "tech", "LRCX": "tech", "KLAC": "tech",
    "ASML": "tech", "ARM": "tech", "SMCI": "tech", "TSM": "tech",
    "PLTR": "tech", "MSTR": "tech", "SNOW": "tech", "NET": "tech",
    "CRWD": "tech", "ZS": "tech", "PANW": "tech", "DDOG": "tech",
    "MDB": "tech", "OKTA": "tech", "SHOP": "tech", "MARA": "tech",
    "RIOT": "tech", "ADP": "tech",
    # Communication Services
    "GOOGL": "comm", "META": "comm", "NFLX": "comm", "DIS": "comm",
    "ROKU": "comm", "SNAP": "comm", "PINS": "comm", "RBLX": "comm",
    "BIDU": "comm", "NTES": "comm", "DASH": "comm",
    # Consumer Discretionary
    "AMZN": "cons_disc", "TSLA": "cons_disc", "HD": "cons_disc",
    "MCD": "cons_disc", "NKE": "cons_disc", "LOW": "cons_disc",
    "BKNG": "cons_disc", "SBUX": "cons_disc", "TJX": "cons_disc",
    "ABNB": "cons_disc", "UBER": "cons_disc", "LYFT": "cons_disc",
    "CCL": "cons_disc", "RCL": "cons_disc", "NCLH": "cons_disc",
    "DKNG": "cons_disc", "CZR": "cons_disc", "WYNN": "cons_disc",
    "LVS": "cons_disc", "MGM": "cons_disc", "MAR": "cons_disc",
    "HLT": "cons_disc", "BABA": "cons_disc", "JD": "cons_disc",
    "PDD": "cons_disc", "TCOM": "cons_disc", "LI": "cons_disc",
    "NIO": "cons_disc", "XPEV": "cons_disc", "GM": "cons_disc",
    "F": "cons_disc",
    # Consumer Staples
    "PG": "cons_stap", "COST": "cons_stap", "WMT": "cons_stap",
    "PEP": "cons_stap", "KO": "cons_stap", "PM": "cons_stap",
    "MO": "cons_stap", "TGT": "cons_stap", "KR": "cons_stap",
    "CVS": "cons_stap",
    # Energy
    "XOM": "energy", "CVX": "energy", "SLB": "energy", "COP": "energy",
    "EOG": "energy", "PSX": "energy", "OXY": "energy",
    # Financial
    "JPM": "financial", "V": "financial", "MA": "financial",
    "BAC": "financial", "WFC": "financial", "GS": "financial",
    "MS": "financial", "SPGI": "financial", "BLK": "financial",
    "MMC": "financial", "AON": "financial", "CB": "financial",
    "PGR": "financial", "SOFI": "financial", "COIN": "financial",
    "HOOD": "financial", "SQ": "financial", "PYPL": "financial",
    # Health Care
    "LLY": "health", "UNH": "health", "JNJ": "health", "ABBV": "health",
    "MRK": "health", "TMO": "health", "ABT": "health", "AMGN": "health",
    "MDT": "health", "GILD": "health", "ISRG": "health", "VRTX": "health",
    "REGN": "health", "SYK": "health", "BMY": "health", "DHR": "health",
    "BAX": "health",
    # Materials
    "LIN": "materials", "SHW": "materials", "APD": "materials",
    "NEM": "materials", "FCX": "materials",
    # Real Estate
    "PLD": "real_estate", "AMT": "real_estate", "EQIX": "real_estate",
    "SPG": "real_estate", "O": "real_estate",
    # Utilities
    "NEE": "utilities", "DUK": "utilities", "SO": "utilities",
    "D": "utilities", "AEP": "utilities",
}

# 港股 → 行業
HK = {
    # Technology
    "0992.HK": "tech", "1810.HK": "tech", "2018.HK": "tech",
    "2382.HK": "tech",
    # Communication Services
    "0700.HK": "comm", "0728.HK": "comm", "0762.HK": "comm",
    "0788.HK": "comm", "0941.HK": "comm", "1024.HK": "comm",
    "9626.HK": "comm", "9888.HK": "comm", "9999.HK": "comm",
    # Consumer Discretionary
    "0027.HK": "cons_disc", "0175.HK": "cons_disc", "0881.HK": "cons_disc",
    "1128.HK": "cons_disc", "1211.HK": "cons_disc", "1928.HK": "cons_disc",
    "2015.HK": "cons_disc", "2020.HK": "cons_disc", "2238.HK": "cons_disc",
    "2313.HK": "cons_disc", "2331.HK": "cons_disc", "3690.HK": "cons_disc",
    "6690.HK": "cons_disc", "6862.HK": "cons_disc", "9618.HK": "cons_disc",
    "9866.HK": "cons_disc", "9868.HK": "cons_disc", "9961.HK": "cons_disc",
    "9988.HK": "cons_disc",
    # Consumer Staples
    "0151.HK": "cons_stap", "0288.HK": "cons_stap", "0291.HK": "cons_stap",
    "0322.HK": "cons_stap", "1044.HK": "cons_stap", "1876.HK": "cons_stap",
    "2319.HK": "cons_stap", "9633.HK": "cons_stap",
    # Energy
    "0386.HK": "energy", "0857.HK": "energy", "0883.HK": "energy",
    "1088.HK": "energy",
    # Financial
    "0005.HK": "financial", "0011.HK": "financial", "0388.HK": "financial",
    "0939.HK": "financial", "0966.HK": "financial", "1288.HK": "financial",
    "1299.HK": "financial", "1336.HK": "financial", "1339.HK": "financial",
    "1359.HK": "financial", "1398.HK": "financial", "2318.HK": "financial",
    "2388.HK": "financial", "2601.HK": "financial", "2628.HK": "financial",
    "3328.HK": "financial", "3968.HK": "financial", "3988.HK": "financial",
    "6030.HK": "financial",
    # Health Care
    "1093.HK": "health", "1099.HK": "health", "1177.HK": "health",
    "1801.HK": "health", "1833.HK": "health", "2269.HK": "health",
    "3692.HK": "health", "6160.HK": "health", "6618.HK": "health",
    "6699.HK": "health", "9688.HK": "health",
    # Materials
    "0868.HK": "materials", "0914.HK": "materials", "0968.HK": "materials",
    "1378.HK": "materials", "1772.HK": "materials", "2600.HK": "materials",
    "2899.HK": "materials",
    # Real Estate
    "0016.HK": "real_estate", "0012.HK": "real_estate", "0017.HK": "real_estate",
    "0083.HK": "real_estate", "0101.HK": "real_estate", "0688.HK": "real_estate",
    "0823.HK": "real_estate", "0960.HK": "real_estate", "1109.HK": "real_estate",
    "1113.HK": "real_estate", "1918.HK": "real_estate", "1997.HK": "real_estate",
    "2202.HK": "real_estate", "6098.HK": "real_estate",
    # Utilities
    "0002.HK": "utilities", "0003.HK": "utilities", "0006.HK": "utilities",
    "0836.HK": "utilities", "1193.HK": "utilities", "2688.HK": "utilities",
    "3868.HK": "utilities",
}

MAP = {**US, **HK}
OTHER = "other"


def sector_of(symbol: str) -> str:
    """回傳分類 key(tech/energy/.../other)。"""
    s = str(symbol or "").strip().upper()
    if not s:
        return OTHER
    if s in MAP:
        return MAP[s]
    # 港股:容忍 700.HK / HK.00700 / 00700.HK 等寫法 → 0700.HK
    if s.endswith(".HK") or (s.isdigit() and len(s) <= 5):
        m = re.search(r"(\d{1,5})", s)
        if m:
            key = m.group(1).zfill(4) + ".HK"
            if key in MAP:
                return MAP[key]
    # 美股:容忍 US.AAPL / AAPL.US
    core = s.replace("US.", "").replace(".US", "")
    if core in MAP:
        return MAP[core]
    return OTHER


def sector_label(symbol: str) -> str:
    return KEY2LABEL.get(sector_of(symbol), "Other")
