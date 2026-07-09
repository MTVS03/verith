# snapshot_news.ps1 — 뉴스 데이터 스냅샷 뜨기 (PG + Neo4j)
#
# 지금 내 로컬 DB에 쌓인 뉴스를 팀 공유용 파일로 떠서 backend/dumps/ 에 저장합니다.
# 팀 컨벤션(docs/db_boundaries.md): git이 나르는 건 볼륨이 아니라 "재현 가능한 data artifact".
#   - PG   : news, news_reports          -> backend/dumps/shared_news_pg.sql   (pg_dump)
#   - Neo4j: 뉴스 그래프 전체(MERGE 문)  -> backend/dumps/shared_news_neo4j.cypher
#
# 뜬 뒤에는 두 파일을 git add/commit/push 하면 팀원이 pull 후 복원할 수 있습니다(복원법: backend/dumps/README.md).
#
# 전제: docker compose up 으로 verith-postgres / verith-neo4j 가 떠 있어야 함.
# 실행: PowerShell 에서  ./snapshot_news.ps1

$ErrorActionPreference = "Stop"

# ── 설정 ───────────────────────────────────────────────────────────────────────
# 기본은 embedding 제외(파일 수십 MB -> 수 MB). embedding 은 배치 이벤트 병합에만 쓰이고 조회/리포트는
# 안 읽음. 완전 보존이 필요하면 $true 로.
$IncludeEmbedding = $false
# ───────────────────────────────────────────────────────────────────────────────

$Repo    = $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Dumps   = Join-Path $Backend "dumps"
$Python  = Join-Path $Backend ".venv\Scripts\python.exe"
$PgOut   = Join-Path $Dumps "shared_news_pg.sql"
$Neo4jOut= Join-Path $Dumps "shared_news_neo4j.cypher"

if (-not (Test-Path $Python)) { Write-Error "python 없음: $Python (backend/.venv 확인)"; exit 1 }
if (-not (Test-Path $Dumps))  { New-Item -ItemType Directory -Path $Dumps | Out-Null }

Write-Host "── 뉴스 스냅샷 ──────────────────────────────────────" -ForegroundColor Cyan

# ── 1) PostgreSQL: news + news_reports ─────────────────────────────────────────
# 복원 시 "스냅샷 상태로 리셋"되도록 맨 앞에 TRUNCATE 를 넣는다(COPY + setval 이 데이터·시퀀스 복구).
Write-Host "  [1/2] PostgreSQL (news, news_reports) -> shared_news_pg.sql"
$pgArgs = @("-m", "scripts.export_news_pg", $PgOut)
if ($IncludeEmbedding) { $pgArgs += "--include-embedding" }
Push-Location $Backend
try { & $Python @pgArgs }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Error "PG export 실패 (verith-postgres 떠 있는지 확인)"; exit 1 }

# ── 2) Neo4j: 뉴스 그래프 전체 ─────────────────────────────────────────────────
# APOC 없이 정체성 키(key / news_id) 기준 MERGE 문으로 뜬다(멱등 복원). 접속정보는 backend/.env 에서 자동 로드.
Write-Host "  [2/2] Neo4j (graph) -> shared_news_neo4j.cypher"
Push-Location $Backend
try { & $Python -m scripts.export_news_graph $Neo4jOut }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Error "Neo4j export 실패 (verith-neo4j 떠 있는지 확인)"; exit 1 }

# ── 결과 요약 ──────────────────────────────────────────────────────────────────
$pgRows = ((docker exec verith-postgres psql -U verith -d verith -t -c "SELECT count(*) FROM news;") | Out-String).Trim()
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "완료:" -ForegroundColor Green
Write-Host ("  {0}  (news {1}행)" -f $PgOut, $pgRows)
Write-Host ("  {0}" -f $Neo4jOut)
Write-Host ""
Write-Host "다음: 두 파일을 git add / commit / push -> 팀원이 pull 후 복원(backend/dumps/README.md)" -ForegroundColor DarkGray
