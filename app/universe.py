"""開市前自動選股候選池:流動性佳、具代表性與波幅的港股/美股代號。
免金鑰數據源無法可靠列舉全市場,故用精選池(可自行編輯)。"""

# 港股:恒指/國指主要成份 + 高流動性活躍股(內部代號 .HK)
HK_POOL = [
    "0005.HK", "0011.HK", "0016.HK", "0001.HK", "0002.HK", "0003.HK",
    "0006.HK", "0012.HK", "0017.HK", "0027.HK", "0066.HK", "0083.HK",
    "0101.HK", "0144.HK", "0151.HK", "0175.HK", "0267.HK", "0288.HK",
    "0291.HK", "0316.HK", "0322.HK", "0386.HK", "0388.HK", "0669.HK",
    "0688.HK", "0700.HK", "0728.HK", "0762.HK", "0788.HK", "0823.HK",
    "0836.HK", "0857.HK", "0868.HK", "0881.HK", "0883.HK", "0914.HK",
    "0939.HK", "0941.HK", "0960.HK", "0966.HK", "0968.HK", "0992.HK",
    "1024.HK", "1044.HK", "1088.HK", "1093.HK", "1099.HK", "1109.HK",
    "1113.HK", "1128.HK", "1177.HK", "1193.HK", "1211.HK", "1288.HK",
    "1299.HK", "1336.HK", "1339.HK", "1359.HK", "1378.HK", "1398.HK",
    "1772.HK", "1801.HK", "1810.HK", "1833.HK", "1876.HK", "1918.HK",
    "1928.HK", "1997.HK", "2015.HK", "2018.HK", "2020.HK", "2202.HK",
    "2238.HK", "2269.HK", "2313.HK", "2318.HK", "2319.HK", "2331.HK",
    "2382.HK", "2388.HK", "2600.HK", "2601.HK", "2628.HK", "2688.HK",
    "2899.HK", "3328.HK", "3690.HK", "3692.HK", "3699.HK", "3868.HK",
    "3968.HK", "3988.HK", "6030.HK", "6098.HK", "6160.HK", "6618.HK",
    "6690.HK", "6699.HK", "6862.HK", "9618.HK", "9626.HK", "9633.HK",
    "9681.HK", "9688.HK", "9866.HK", "9868.HK", "9878.HK", "9888.HK",
    "9961.HK", "9988.HK", "9999.HK",
]

# 美股:大型科技 + 半導體 + 金融/消費龍頭 + 高波幅熱門股(市值流動性篩選)
US_POOL = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "LLY", "JPM", "V", "UNH", "XOM", "MA", "JNJ", "PG", "COST", "HD",
    "ABBV", "WMT", "NFLX", "AMD", "MRK", "PEP", "KO", "ADBE", "CRM",
    "BAC", "TMO", "MCD", "CSCO", "ACN", "ABT", "WFC", "DIS", "ORCL",
    "INTC", "QCOM", "TXN", "DHR", "NKE", "PM", "CAT", "AMGN", "IBM",
    "GE", "HON", "LOW", "GS", "UNP", "RTX", "SPGI", "BKNG", "BLK",
    "PLD", "UPS", "MS", "SBUX", "LMT", "MDT", "ADI", "GILD", "ISRG",
    "VRTX", "REGN", "ADP", "SYK", "TJX", "MMC", "AON", "CB", "PGR",
    "MO", "BMY", "SOFI", "PLTR", "COIN", "MSTR", "HOOD", "SQ", "PYPL",
    "SHOP", "SNOW", "NET", "CRWD", "ZS", "PANW", "DDOG", "MDB", "OKTA",
    "ROKU", "SNAP", "PINS", "UBER", "LYFT", "ABNB", "DASH", "RBLX",
    "UAL", "DAL", "LUV", "CCL", "RCL", "NCLH", "DKNG", "CZR", "WYNN",
    "LVS", "MGM", "MAR", "HLT", "BABA", "JD", "PDD", "BIDU", "NTES",
    "TCOM", "LI", "NIO", "XPEV", "MU", "ON", "AMAT", "LRCX", "KLAC",
    "ASML", "ARM", "SMCI", "TSM", "CVX", "SLB", "COP", "EOG", "PSX",
    "OXY", "MARA", "RIOT", "GM", "F", "BA", "BAX", "TGT", "KR", "CVS",
]

UNIVERSE = {"hk": HK_POOL, "us": US_POOL}
