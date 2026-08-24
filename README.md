# 📈 港美即日買賣訊號系統(HK Intraday Scanner)

瀏覽器 / 手機皆可使用的**港股 + 美股**即日買賣決策支援系統。
接入**富途牛牛 OpenAPI**,開市時段自動掃描港股(09:30-16:00 HKT)與美股(21:30-05:00 HKT)監察名單,
以**六大入市指標**判斷買入時機(現行:≥4 項成立即觸發),經 **Telegram** 推送買賣訊號,
以**最近 5 年數據回測**、**最高獲利因子**為目標自動調叟,每日收市後自動重跑。
另支援**自選獨立分析**(任意股票即時六指標分析+單股回測)與**網頁上修改所有參數**。

> ⚠️ **風險聲明**:本系統輸出僅為程化技術分析訊號,不構成任何投資建議。
> 港股即日買賣風險極高,請先以紙上模擬驗證,自負盈虧。

---

## 一、系統架構

```
┌──────────────┐   行情/K線   ┌─────────────────────────────────┐
│  FutuOpenD   │◄────────────►│        Python 後端 (app/)       │
│ (富途牛牛網關) │              │                                 │
└──────────────┘              │  scanner.py   即時掃描狀態機     │
┌──────────────┐              │  indicators.py 六大指標引擎      │
│  yfinance    │◄──備援──────►│  backtest.py  5年回測引擎        │
│ (歷史數據備援) │              │  optimizer.py 獲利因子調叟       │
└──────────────┘              │  scheduler.py 每日自動調叟       │
┌──────────────┐              │  notifier.py  Telegram 推送      │
│ Telegram Bot │◄──推送───────│  webapp.py    FastAPI 儀表板     │
└──────────────┘              └───────────────┬─────────────────┘
                                              │ HTTP :8000
                                   ┌──────────▼──────────┐
                                   │ 手機/瀏覽器 儀表板    │
                                   │ 即時監察|訊號|回測詳情│
                                   └─────────────────────┘
```

數據源自動降級:`futu → yfinance → synthetic(示範用合成數據)`。
未接富途也能完整跑通全流程(示範模式)。

---

## 二、六大入市指標(≥4 項成立即發買入訊號)

| # | 條件 | 量化定義 | 主要參數 |
|---|------|----------|----------|
| ① | 成交量放大 | 量 ≥ N 倍 20 根均量,且為上升K線 | `vol_expand_ratio`(預設2.0) |
| ② | 均線向上·價在均線上方 | EMA20 > EMA50、收盤 > EMA50、EMA20 三根向上 | `ema_fast/ema_slow` |
| ③ | 布林帶開口 | 近端存在壓縮(squeeze)後帶寬轉向擴張,價站中軌上 | `bb_width_pctile` |
| ④ | 回調至斐波那契 | 擺動低→高推動浪後,價貼近 38.2% 或 61.8% 回調位 ±容差 | `fib_levels`, `fib_tolerance_pct` |
| ⑤ | RSI 止穩回升 | RSI14 落於 50 附近區間且較上一根上升 | `rsi_lo=45`, `rsi_hi=58` |
| ⑥ | MACD 點火 | 能量柱連續縮短,或近 5 根內金叉,柱體翻升 | `macd_shrink_bars`, `macd_cross_lookback` |

**★ 買入觸發(現行設定)**:`require_all: false` + `min_score: 4` → **六項中至少 4 項成立即發買入訊號**(6/6 全中會在訊息中特別標注「全中!」)。想改回嚴格模式:把 `config.yaml` 的 `strategy.require_all` 設回 `true`;或調整 `min_score`(3~6)控制鬆緊。

**賣出規則(即日鮮)**:
- 🎯 持倉利潤 ≥ **+5%** → Telegram 賣出訊號(`take_profit_pct`)
- 🛑 跌破止損 −3%(`stop_loss_pct`)
- ⏰ 收市前 10 分鐘強制平倉提示(`force_eod_exit`)
- 同一股票當日只交易一次(防重複進出)

---

## 三、快速開始

### 0. 環境需求
- Windows / macOS / Linux + **Python 3.10+(本機驗證於 3.14)**
- 無需科學上網;Telegram 推送需能連 api.telegram.org

### 1. 安裝依賴
```powershell
cd hk-intraday-system
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 富途行情(可選,建議安裝):
pip install futu-api
```
> 若所處環境 pip 受限,可用專案附帶的純 stdlib 引導器:
> `python scripts\bootstrap_deps.py`(裝到 `.deps\`,程式會自動加入路徑)

### 2. 自我測試(30 秒驗證一切)
```powershell
python run.py selftest
```
應看到 5 項 ✅(指標數學/六條件聯動觸發/回測管線/儲存層/訊息模板)。

### 3. 接入富途牛牛
1. 下載並安裝 [FutuOpenD](https://www.futunn.com/download/OpenAPI)(富途開放網關)
2. 用富途牛牛帳號登入 FutuOpenD(行情權限依你的帳號等級)
3. 確認監聽位址 = `127.0.0.1:11111`(與 `config.yaml` 的 `futu` 區塊一致)
4. `config.yaml` 保持 `futu.enabled: true`,`feed.mode: auto`

### 4. 設定 Telegram
1. Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` 建立 Bot,取得 `bot_token`
2. 找 [@userinfobot](https://t.me/userinfobot) 取得自己的數字 `chat_id`
   (群組推送:把 Bot 加入群組,chat_id 用群組的 `-100...` ID)
3. 填入 `config.yaml`:
```yaml
telegram:
  enabled: true
  bot_token: "123456:ABC-xxx"
  chat_id: "你的數字ID"
```
4. 測試:`python run.py telegram-test`

### 5. 啟動系統
```powershell
python run.py web          # 啟動儀表板 + 即時掃描 + 每日調叟
```
- 本機瀏覽器打開 `http://127.0.0.1:8000`
- **手機**:同一 Wi-Fi 下打開 `http://電腦IP:8000`(config 已設 `host: 0.0.0.0`)

---

## 四、每日流程(自動化)

| 時間(HKT) | 系統行為 |
|------------|---------|
| 09:30–12:00 / 13:00–16:00 | 每 30 秒掃描監察名單 → 六指標評估 → 買入訊號推播 |
| 持倉期間 | 監控 +5% 目標 / 止損 / 收市平倉 → 賣出訊號推播 |
| 16:00 收市 | 當日交易結束,狀態機重置 |
| **17:30** | **自動以最近5年數據重跑 432 格網格搜索**(前70%訓練/後30%驗證),選出「驗證集獲利因子最高且交易數達標」的標」的參數,寫入 `data/best_params.json` |
| 翌日開市 | 掃描器自動採用新參數 → 參數每天與市場同步演化 |

調叟結果可在儀表板「回測與調叟」分頁查看:**獲利因子、勝率、期望值、年化、最大回撤、權益曲線、每股表現、逐筆交易**。

---

## 五、常用指令

```powershell
python run.py web                 # 全系統啟動(Web+掃描+排程)
python run.py scan-once           # 手動掃一輪,終端印出六指標狀態表
python run.py backtest            # 以目前生效參數回測近5年(存入資料庫)
python run.py tune                # 立即手動跑一次獲利因子調叟
python run.py selftest            # 自我測試
python run.py telegram-test       # Telegram 測試訊息
```

改監察名單:直接改 `config.yaml` 的 `scanner.watchlist`,或之後透過 API:
```
POST /api/config/watchlist   {"symbols": ["0700.HK", "9988.HK", ...]}
POST /api/scan-now           # 立即掃描一輪
```

---

## 六、REST API 一覽

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/meta` | 系統設定/生效參數/feed/港美開市狀態 |
| GET | `/api/state` | 港美監察名單即時六指標狀態 |
| POST | `/api/scan-now` | 觸發立即掃描 |
| GET | `/api/analyze?symbol=AAPL` | 🔍 自選股票獨立六指標分析 |
| POST | `/api/backtest-single` | 單一自選股回測 `{"symbol":"NVDA","years":5}` |
| GET | `/api/signals?limit=60` | 買賣訊號歷史 |
| GET | `/api/backtests` | 回測清單 |
| GET | `/api/backtests/{id}` | 回測詳情(指標/權益曲線/交易明細) |
| GET/POST | `/api/config/full` | ⚙️ 讀取/儲存所有參數(即時生效) |
| POST | `/api/config/watchlist` | 更新監察名單(body 加 `"market":"hk"\|"us"`) |
| POST | `/api/config/clear-overlay` | 清除每日調叟覆蓋(best_params.json) |

> 設定 `web.access_token` 後,以上 API 需帶 `X-Access-Key` 標頭或 `?key=` 參數。

---

## 七、回測方法論(重要)

- 以**日K**模擬即日鮮:T 日收盤確認訊號 → T+1 開盤進場 → 當日內觸及 +5%/止損以該價出場,否則收市平倉。同日雙觸發按**悲觀假設**計(先止損)。
- 成本:每筆來回 `cost_pct=0.15%`(佣金+滑價近似,可自行調整;實際港股另有印花稅等,請自行校準)。
- **獲利因子 PF = 總盈利 ÷ 總虧損**;調叟評分對 PF 封頂 20 並按交易數懲罰,避免小樣本過擬合;選優優先「驗證集交易數 ≥ 30」的層級。
- 合成示範數據上訊號稀少屬正常(隨機遊走極少出現六項共振);接上真實港股行情後訊號頻率才具參考性。
- 富途日K歷史受帳號權限限制;分頁抓取已處理,若某股取數失敗會自動略過不影響整體。

## 八、🇺🇸 美股支援 與 🔍 自選獨立分析

**美股**:在 `config.yaml` 的 `scanner.watchlist_us`(或「⚙️ 設定」頁)填美股代號
(預設 AAPL/MSFT/NVDA/AMZN/GOOGL/META/TSLA/AMD/NFLX/JPM)。
美股時段(美東 09:30-16:00,自動處理冬夏令)掃描器自動切換掃描美股;
買賣規則、Telegram 推送、每日調叟與港股完全一致。富途代號映射自動處理(`HK.00700` / `US.AAPL`)。

**自選獨立分析**(儀表板「🔍 自選分析」分頁):
1. 輸入任意代號 — `AAPL`、`TSLA`、`0700.HK`、`700` 皆可(自動辨識市場)
2. 按「🔍 分析」→ 即時六指標狀態、評分、止損/目標參考價
3. 按「回測此股 5 年」→ 該股 5 年日K回測(PF/勝率/交易數/回撤),結果存入回測清單
4. 完全不影響監察名單與掃描排程

對應 API:`GET /api/analyze?symbol=AAPL&size=1m`、`POST /api/backtest-single`(body: `{"symbol":"NVDA","years":5}`)

## 九、⚙️ 網頁上修改所有參數

儀表板「⚙️ 設定」分頁可線上調整**全部參數**,儲存後即時生效並寫回 config.yaml:
- 六大指標所有閾值;買入觸發方式(六項全中 / 最低項數 min_score)
- 即日買賣規則(+5% 目標、止損、收市平倉提示)
- 掃描間隔/K線週期/回看根數;港美監察名單(每行一個代號)
- 回測年數/成本、調叟門檻、每日調叟時間、數據源模式
- Telegram token/chat_id;公開存取金鑰
- 「清除每日調叟覆蓋」:刪除 best_params.json,讓本頁基礎參數直接生效

對應 API:`GET/POST /api/config/full`、`POST /api/config/clear-overlay`

## 十、🌐 免費公開到網際網路

兩種方式,按需求選:

**A. 不想開著自己的電腦 → 雲端獨立運行(Render / ClawCloud,免費)**
整個系統跑在雲端容器,自動改用 yfinance 數據源,24 小時掃描+Telegram 推送。
👉 詳細步驟見 [DEPLOY.md](DEPLOY.md)(Render 免信用卡;ClawCloud 不休眠)。
> 舊建議的 Hugging Face Spaces 已改為付費,不再推薦。

**B. 電腦可以開著 → Cloudflare Tunnel(保留富途即時行情)**
後端仍在你電腦上跑,Cloudflare 只負責轉發流量,免費、免開埠、自動 HTTPS。

1. **先設存取金鑰**(重要!):儀表板「⚙️ 設定」→「公開存取保護」→ 填自訂密碼 → 儲存。
   之後所有 `/api/*` 都需要此金鑰(首次開啟網頁會跳出輸入框,瀏覽器會記住)。
2. 一鍵建立臨時通道(首次自動安裝 cloudflared):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start-tunnel.ps1
   ```
3. 終端輸出 `https://xxxx.trycloudflare.com` → 手機/任何裝置直接開啟。
4. 想要**固定網址**:免費註冊 Cloudflare 帳號並加入一個域名後:
   ```powershell
   cloudflared tunnel login
   cloudflared tunnel create hk-scanner
   cloudflared tunnel route dns hk-scanner stock.你的域名.com
   cloudflared tunnel run hk-scanner
   ```

| 方案 | 費用 | 富途即時 | 不用開電腦 | 固定網址 |
|------|------|---------|-----------|---------|
| Render / ClawCloud 雲端 | 免費 | ❌ yfinance | ✅ | ✅ |
| Oracle Cloud 永久免費VM | 免費 | ❌ yfinance | ✅ | ✅ |
| Cloudflare Tunnel | 免費 | ✅ | ❌ | 臨時會換 / 自綁固定 |
| ngrok 免費版 | 免費 | ✅ | ❌ | 免費版會換 |

> 🔒 公開前**務必**設定存取金鑰(「⚙️ 設定」分頁 → 公開存取保護)。

## 十一、目錄結構

```
hk-intraday-system/
├─ run.py                 # CLI 入口
├─ config.yaml            # 主設定(Telegram/富途/參數/名單)
├─ requirements.txt
├─ app/
│  ├─ indicators.py       # 六大指標引擎
│  ├─ strategy.py         # 參數定義
│  ├─ datafeed.py         # futu/yfinance/synthetic 數據源
│  ├─ scanner.py          # 即時掃描狀態機(WATCH→LONG→DONE)
│  ├─ backtest.py         # 5年回測引擎(預計算+向量化遮罩)
│  ├─ optimizer.py        # 432格網格搜索×訓練/驗證切分
│  ├─ scheduler.py        # 每日17:30自動調叟
│  ├─ notifier.py         # Telegram 訊息模板
│  ├─ store.py            # SQLite(訊號/狀態/回測)
│  ├─ webapp.py           # FastAPI
│  ├─ selftest.py         # 自我測試
│  └─ static/index.html   # 手機可用儀表板
├─ scripts/
│  ├─ bootstrap_deps.py   # 沙盒友善依賴引導器
│  └─ probe_geometry.py   # 形態幾何驗證探針
└─ data/                  # 執行期產生(app.db、best_params.json、logs)
```

## 十二、🤖 AI 分析(自行加不同 model / API)

「⚙️ 設定」分頁底部可加入**任意數量的 AI 模型**,只要該服務支援 OpenAI 相容的
`chat/completions` 端點即可。內建模板一鍵帶入:

| 模板 | Base URL | 預設 Model |
|------|----------|-----------|
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| OpenAI | `https://api.openai.com/v1` | gpt-4o-mini |
| Google Gemini | `…generativelanguage.googleapis.com/v1beta/openai` | gemini-2.0-flash |
| OpenRouter(Claude等) | `https://openrouter.ai/api/v1` | anthropic/claude-3.5-sonnet |
| Kimi 月之暗面 | `https://api.moonshot.cn/v1` | moonshot-v1-8k |
| 通義千問 | `dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus |
| Groq | `https://api.groq.com/openai/v1` | llama-3.3-70b-versatile |
| Ollama 本機 | `http://127.0.0.1:11434/v1` | llama3.1 |

用法:
1. 「⚙️ 設定」→ 選供應商模板 →「＋ 新增模型」→ 貼上你的 **API Key** → 可勾選其中一個為**預設** →「💾 儲存 AI 設定」
2. 按「測試連線」即時驗證 Key 與端點(不用先存檔)
3. 到「🔍 自選分析」輸入代號 → 選模型 → 按 **🤖 AI 解讀**
   → AI 會收到完整六指標數據(JSON),回覆【綜合判斷】【指標解讀】【關鍵價位】【操作建議】【信心度】

API 對應:`GET /api/ai/providers`、`POST /api/ai/settings`、
`POST /api/ai/settings-test`(未存檔直接測)、`POST /api/ai/analyze`(body: symbol/size/provider)

> 🔐 API Key 只寫入伺服器上的 config.yaml(已被 .gitignore 排除,不會上 GitHub);
> 公開部署時記得設定存取金鑰,否則任何人都能用你的 Key。

- **介面語言**:右上角 **EN / 中文** 一鍵切換(選擇存在瀏覽器);切到英文時「🤖 AI 解讀」也會改用英文提示詞輸出。
- **數據源備援鏈**:`auto` = futu → yfinance → **tencent(騰訊行情)** → **eastmoney(東方財富)** → synthetic。後兩者免金鑰、對雲端 IP 友善,Yahoo 在 Render 被限流時自動頂上;也可在「⚙️ 設定」直接指定單一來源。

## 十三、常見問題

- **一定要 FutuOpenD 嗎?** 不必。沒有它系統以 yfinance(延遲/歷史)或合成數據運作;但要「即時開市掃描」就需要 FutuOpenD 登入在背景執行。
- **會自動下單嗎?** 不會。本系統只產生訊號與通知,下單請在富途牛牛 App 自行操作(刻意設計,降低誤觸風險)。
- **公眾假期?** 目前只排除週末;港股假期表請留意系統在休市日不會有成交級訊號(FutuOpenD 亦無新K線),之後可加假期表。
- **如何改賣出目標不是 5%?** 改 `config.yaml` → `trade_rules.take_profit_pct`。
