# start_news_scheduler.ps1 — 뉴스 자동 수집 스케줄러 기동
#
# 이 스크립트만 실행하면 뉴스가 자동으로 수집됩니다.
#   - 뜨자마자 1회 즉시 수집(BATCH_RUN_ON_START)
#   - 이후 매시간 자동 수집(BATCH_INTERVAL_MINUTES, config 기본 60분)
#   - 7일 지난 기사 자동 삭제(cleanup 스케줄러 동봉)
# 이 창을 닫으면 자동 수집도 멈춥니다. (backend/ai/frontend와 별개 프로세스)
#
# 전제: postgres/neo4j(docker compose up)와 backend가 떠 있어야 함.
# 실행: PowerShell에서  ./start_news_scheduler.ps1   (또는 파일 우클릭 > PowerShell로 실행)

$ErrorActionPreference = "Stop"

# ── 설정(필요하면 여기만 바꾸세요) ─────────────────────────────────────────────
$BackendUrl   = "http://127.0.0.1:8000"   # backend 주소(최신 코드를 8000에 fresh 기동 — 8001 워크어라운드 폐기).
$MaxArticles  = 40                          # 배치당 최대 처리 기사 수(무제한이면 Qwen 폭주). 비우면 무제한.
$RunOnStart   = "true"                       # true=기동 직후 1회 즉시 수집
# ──────────────────────────────────────────────────────────────────────────────

$AiRoot = Join-Path $PSScriptRoot "ai"
$Python = Join-Path $AiRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "python 실행파일을 못 찾음: $Python  (ai/.venv 가 있는지 확인)"
    exit 1
}

# 환경변수 (실제 env가 ai/.env보다 우선. Qwen 주소 등은 ai/.env에서 자동 로드됨)
$env:PYTHONUTF8         = "1"
$env:BACKEND_BASE_URL   = $BackendUrl
$env:BATCH_RUN_ON_START = $RunOnStart
if ("$MaxArticles" -ne "") { $env:CRAWL_MAX_ARTICLES = "$MaxArticles" }

Write-Host "── 뉴스 스케줄러 기동 ──────────────────────────────" -ForegroundColor Cyan
Write-Host "  backend      : $BackendUrl"
Write-Host "  max articles : $MaxArticles"
Write-Host "  run on start : $RunOnStart"
Write-Host "  종료하려면 이 창에서 Ctrl+C" -ForegroundColor DarkGray
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan

# import가 패키지 경로(src.agents.news.*)라 ai/ 루트에서 -m 으로 실행해야 함
Set-Location $AiRoot
& $Python -m src.agents.news.scheduler
