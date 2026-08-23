# ======================================================================
#  雲端部署用 Dockerfile — 支援 Hugging Face Spaces(免費)與 Render(免費層)
#
#  Hugging Face Spaces:建立 Space → SDK 選「Docker」→ 上傳本專案即可。
#    容器預設聽 7860(Spaces 標準埠)。
#  Render:New Web Service → 連 GitHub repo → Runtime「Docker」→ Free。
#    平台會注入 PORT 環境變數,自動生效。
#
#  兩者都會因雲端連不到你電腦的 FutuOpenD 而自動使用 yfinance 數據源
#  (亦可在平台環境變數明確設 HK_FEED=yfinance)。
# ======================================================================
FROM python:3.12-slim

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py ./

# config.yaml 不入 repo(含 Telegram token 等機密)。
# 容器內沒有設定檔時系統使用內建預設值;Telegram token / 存取金鑰
# 部署後在網頁「⚙️ 設定」填寫即可(會寫入容器內的 config.yaml)。

# HF Spaces 建議非 root;Render 亦相容
RUN useradd -m -u 1000 user && mkdir -p /app/data && chown -R user:user /app
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PORT=7860 \
    HK_FEED=yfinance \
    HK_BASELINE=0

EXPOSE 7860
CMD ["python", "run.py", "web"]
