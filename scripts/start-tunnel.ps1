# ======================================================================
#  start-tunnel.ps1 — 一鍵把本機儀表板免費公開到網際網路(Cloudflare Tunnel)
#
#  用法(在 PowerShell 執行):
#    powershell -ExecutionPolicy Bypass -File scripts\start-tunnel.ps1
#
#  首次執行會自動以 winget 安裝 cloudflared。
#  啟動後終端會出現一行 https://xxxx.trycloudflare.com —
#  手機/任何裝置用該網址即可開啟儀表板(關閉視窗即停止對外)。
#
#  ★ 公開前強烈建議先在儀表板「⚙️ 設定」分頁設定「存取金鑰」,
#    否則任何拿到網址的人都能看到訊號與修改參數。
# ======================================================================

$ErrorActionPreference = "Stop"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 cloudflared,正在以 winget 安裝…" -ForegroundColor Cyan
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " 正在建立免費通道 → http://127.0.0.1:8000"
Write-Host " 請保持本視窗開啟;下方輸出的 trycloudflare.com 網址" -ForegroundColor Yellow
Write-Host " 就是你的公開網址(每次重啟會更換)"
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""

cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
