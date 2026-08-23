# 🚀 雲端獨立運行部署指南(不用開著自己的電腦)

把整套系統(後端+掃描器+儀表板)放到免費雲端上 24 小時運行。
雲端連不到你電腦的 FutuOpenD,系統會**自動改用 yfinance 數據源**(真實市場數據),
掃描、Telegram 推送、回測、每日調叟、網頁設定全部照常運作。

> ❌ Hugging Face Spaces 的 Docker SDK 已改為付費,不再列為方案。

| 方案 | 費用 | 休眠? | 門檻 | 推薦度 |
|------|------|-------|------|--------|
| **A. Render 免費層** | $0 | 15分鐘無人訪問會睡(可防) | 最低,免信用卡 | ★★★ 起步首選 |
| **B. ClawCloud Run** | $0(每月送$5額度) | **不會休眠** | GitHub帳號需滿180天 | ★★★ 最穩定 |
| **C. Oracle Cloud 永久免費VM** | $0 永遠 | 不會休眠 | 要信用卡驗證+較多指令 | ★★ 進階/長期 |
| Cloudflare Tunnel(對照) | $0 | 無此問題 | 要開著自己電腦 | 富途即時行情才需要 |

---

## 方案 A:Render 免費層(最快上手,約10分鐘)

1. 把專案推上 GitHub 公開 repo(完整步驟見下方「推上 GitHub」)
   ✅ 安全:`.gitignore` 已排除 `config.yaml`(你的 Telegram token 不會被上傳);
   部署後在網頁「⚙️ 設定」填 Telegram token 即可
2. 到 https://render.com 用 GitHub 帳號登入(免信用卡)
3. **New → Web Service** → 選你的 repo:
   - Runtime:**Docker**(會自動讀 Dockerfile 建置)
   - Instance Type:**Free**
4. 等 3-5 分鐘 Build 完成 → 取得網址 `https://xxx.onrender.com`
5. 開啟網址 → 「⚙️ 設定」→ 填 Telegram token/chat_id → **設存取金鑰**

### 防休眠
Free 層 15 分鐘沒流量會休眠(下次開啟等 ~40 秒)。解法:
https://uptimerobot.com 免費註冊 → Add Monitor → HTTP(s) → 貼上網址 → 每 15 分鐘 ping。
> 注意:Render 官方不鼓勵純防睡 ping;若被限制就改方案 B。

---

## 方案 B:ClawCloud Run(不會休眠,$0 長期跑)

ClawCloud 對 **GitHub 帳號滿 180 天**的用戶永久贈送 **$5/月額度**
(最小規格容器約 $2-3/月,足夠本系統 24 小時在線,**沒有休眠**)。

### 步驟
1. 前置:把專案推上 GitHub;並建一個容器映像倉(GHCR):
   在 repo 加 `.github/workflows/docker.yml`:
   ```yaml
   name: docker
   on:
     workflow_dispatch:
     push: { branches: [main] }
   permissions: { contents: read, packages: write }
   jobs:
     build:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: docker/login-action@v3
           with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
         - uses: docker/build-push-action@v6
           with:
             context: .
             push: true
             tags: ghcr.io/${{ github.repository_owner }}/hk-scanner:latest
   ```
   push 後到 repo「Actions」跑一次,即產生映像 `ghcr.io/你的帳號/hk-scanner:latest`
   (repo Settings→Actions→General→Workflow permissions 要選 Read and write;映像要設 Public 或在 ClawCloud 填 GHCR token)
2. 到 https://run.claw.cloud 用 **Sign in with GitHub** 註冊(確認你的 GitHub 帳齡 ≥180 天)
3. 控制台選區域(建議 Singapore/Japan)→ **App Launchpad → Create App**:
   - Image:`ghcr.io/你的帳號/hk-scanner:latest`(private 就填 GHCR 使用者+PAT)
   - CPU/Memory:0.5C / 1GB(夠用且在 $5 內)
   - Port:`7860` → 開啟 **Public Access**(自動送 HTTPS 網址)
   - Environment Variables 可加:`HK_FEED=yfinance`、`HK_BASELINE=0`
4. Deploy → 開啟公網網址 → 「⚙️ 設定」填 Telegram → **設存取金鑰**

---

## 方案 C:Oracle Cloud「永久免費」VM(進階,真·永遠免費伺服器)

Oracle Always Free 給一台 ARM VM(最多 4 OCPU/24GB RAM)+ 每月 10TB 流量,
**不休眠、不限期**,比任何容器平台都強;缺點:註冊要信用卡驗證(不扣費)、全指令操作。

1. https://www.oracle.com/cloud/free/ 註冊(選 Home Region 離你近的,如 Singapore)
2. 建立 Compute → Shape 選 **Ampere A1**(2 OCPU / 12GB 即綽綽有餘)→ Ubuntu 22.04 映像
3. SSH 進去後三行裝好:
   ```bash
   curl -fsSL https://get.docker.com | sh        # 或直接 apt install python3-pip
   git clone <你的repo> && cd hk-intraday-system
   pip3 install -r requirements.txt
   HK_FEED=yfinance HK_BASELINE=0 python3 run.py web --host 0.0.0.0
   ```
   (或直接 `docker build -t hk . && docker run -d -p 8000:8000 -e PORT=8000 hk`)
4. 主控台 Security List 開 TCP 8000 → 瀏覽器開 `http://VM公網IP:8000` → 一樣先設存取金鑰
5. 開機自啟動:寫個 systemd service(指南略,可再問我)

---

## 推上 GitHub 公開 repo(兩種方法)

### 方法 1:純網頁拖曳(零指令,5分鐘)
1. 到 https://github.com 註冊/登入 → 右上 **+** → **New repository**
   - Repository name:`hk-intraday-system`
   - 選 **Public** → 勾選 Add a README(方便之後同步)→ **Create repository**
2. 在你的電腦把專案資料夾整理成要上傳的內容(`app/`、`run.py`、`Dockerfile`、
   `requirements.txt`、`config.example.yaml`;**不要** config.yaml / data / .deps)
3. GitHub repo 頁面按 **uploading an existing file** → 把上述檔案與 `app` 資料夾
   直接拖進瀏覽器 → **Commit changes**

> 缺點:日後更新程式要重新手動拖曳。想一勞永逸用方法 2。

### 方法 2:Git 指令(推薦,日後更新只需一行 push)
```powershell
# 第一次設定(全機只需一次)
git config --global user.name "你的名字"
git config --global user.email "你的Email"

cd C:\Users\donal\Documents\hk-intraday-system
git init
git add .
git commit -m "HK/US intraday scanner v1"
git branch -M main
# 先到 GitHub 網頁建好空 repo(不要勾 README),然後:
git remote add origin https://github.com/<你的帳號>/hk-intraday-system.git
git push -u origin main          # 會彈出瀏覽器登入 GitHub,授權一次即可

# ── 以後有改動,只要三行 ──
git add .
git commit -m "更新說明"
git push
```

### ✅ 推送後安全自檢(必做一次)
打開 GitHub repo 頁面確認:
- 看得到 `config.example.yaml`,**看不到** `config.yaml`
- 沒有 `data/`、`.deps/`、`.venv-deps/`(被 .gitignore 擋掉)
- 點開任何檔案搜尋 `bot_token` 應無實際 token

---

## 共通說明

| 項目 | 行為 |
|------|------|
| 數據源 | 自動 yfinance(Dockerfile 已內建 `HK_FEED=yfinance`) |
| 港股掃描 | HKT 09:30-16:00 自動跑 |
| 美股掃描 | ET 09:30-16:00 自動跑 |
| Telegram | 正常推送 |
| 每日調叟 | HKT 17:30 自動跑(`HK_BASELINE=0` 讓重啟秒級啟動) |
| 存取保護 | 「⚙️ 設定」→ access_token,**公開前必設** |

> 💡 富途 Level-2 即時深度行情仍只有本機 + Cloudflare Tunnel 能做到;
> 雲端方案的 yfinance 已涵蓋本系統全部六大指標所需的量價 K 線。
