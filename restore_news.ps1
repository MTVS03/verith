# restore_news.ps1 — 팀 공유 뉴스 스냅샷을 내 로컬 DB에 복원
#
# git pull 로 받은 backend/dumps/ 의 뉴스 스냅샷(PG + Neo4j)을 내 로컬 DB에 넣습니다.
#   - PG   : shared_news_pg.sql       (맨 앞 TRUNCATE 로 news/news_reports 를 스냅샷 상태로 리셋)
#   - Neo4j: shared_news_neo4j.cypher (MERGE 문 — 기존 그래프에 덮어써 반영)
#
# ⚠ 전제(순서 중요):
#   1) docker compose up -d          (verith-postgres / verith-neo4j)
#   2) backend 스키마 최신화 + 제약 생성 — 아래 중 하나:
#        cd backend; .venv\Scripts\python.exe -m alembic upgrade head   (PG 스키마)
#        그리고 backend 를 한 번 기동  (Neo4j 유니크 제약 생성 → 복원 속도/정합)
#   3) 그 다음 이 스크립트 실행
#
# 실행: PowerShell 에서  ./restore_news.ps1

$ErrorActionPreference = "Stop"

$Repo     = $PSScriptRoot
$Dumps    = Join-Path $Repo "backend\dumps"
$PgOut    = Join-Path $Dumps "shared_news_pg.sql"
$Neo4jOut = Join-Path $Dumps "shared_news_neo4j.cypher"

if (-not (Test-Path $PgOut))    { Write-Error "없음: $PgOut (git pull 했는지 확인)"; exit 1 }
if (-not (Test-Path $Neo4jOut)) { Write-Error "없음: $Neo4jOut (git pull 했는지 확인)"; exit 1 }

Write-Host "── 뉴스 스냅샷 복원 ─────────────────────────────────" -ForegroundColor Cyan

# PowerShell 은 `<` 입력 리디렉션을 지원하지 않으므로 cmd 를 거친다(바이트/인코딩도 그대로 전달).
Write-Host "  [1/2] PostgreSQL <- shared_news_pg.sql"
cmd /c "docker exec -i verith-postgres psql -U verith -d verith < `"$PgOut`""
if ($LASTEXITCODE -ne 0) { Write-Error "PG 복원 실패 (verith-postgres 떠 있는지 / alembic upgrade head 했는지 확인)"; exit 1 }

Write-Host "  [2/2] Neo4j <- shared_news_neo4j.cypher"
cmd /c "docker exec -i verith-neo4j cypher-shell -u neo4j -p verith1234 < `"$Neo4jOut`""
if ($LASTEXITCODE -ne 0) { Write-Error "Neo4j 복원 실패 (verith-neo4j 떠 있는지 확인)"; exit 1 }

$pgRows = ((docker exec verith-postgres psql -U verith -d verith -t -c "SELECT count(*) FROM news;") | Out-String).Trim()
$n4Nodes = ((docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain "MATCH (n) RETURN count(n);") | Out-String).Trim()
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "완료:" -ForegroundColor Green
Write-Host ("  news 행수     : {0}" -f $pgRows)
Write-Host ("  neo4j 노드수  : {0}" -f $n4Nodes)
Write-Host "backend 가 떠 있었다면 재기동하는 편이 안전합니다." -ForegroundColor DarkGray
