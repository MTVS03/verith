# restore_industry.ps1 — 팀 공유 산업 스냅샷을 내 로컬 DB에 복원
#
# git pull 로 받은 backend/dumps/ 의 산업 스냅샷(PG + Neo4j)을 내 로컬 DB에 넣습니다.
#   - PG   : shared_industry_pg.sql       (agent_reports 는 agent_type='industry' 만 스코프 DELETE)
#   - Neo4j: shared_industry_neo4j.cypher (MERGE 문 — 멱등. :Chunk 는 전량 교체)
#
# ⚠ 전제(순서 중요):
#   1) docker compose up -d          (verith-postgres / verith-neo4j)
#   2) backend 스키마 최신화:
#        cd backend; .venv\Scripts\python.exe -m alembic upgrade head
#   3) 주식 마스터 먼저 복원 — agent_reports.stock_code 가 stocks.stock_code 로 FK 를 겁니다:
#        docker exec -i verith-postgres psql -U verith -d verith < backend/dumps/shared_verith_snapshot.sql
#   4) 뉴스 스냅샷도 쓴다면 **restore_news 를 먼저** 돌립니다(아래 주의 참고)
#   5) 그 다음 이 스크립트 실행
#
# ⚠ 복원 순서 주의 (뉴스 → 산업):
#   두 그래프는 Neo4j 의 Company/Person 레이블을 공유하는데 정체성 키가 다릅니다(뉴스=key, 산업=name).
#   회사명 28개가 겹칩니다(LG화학·삼성SDI·SK이노베이션 …). 산업을 먼저 복원하면, 뉴스의
#   MERGE (n:Company {key:...}) SET n += {name:...} 가 같은 이름의 노드를 새로 만들어
#   Company.name 유니크 제약(ingest.py 가 만든 경우)을 28회 위반하거나 중복 노드를 남깁니다.
#
# Neo4j 제약/인덱스는 덤프 헤더가 직접 만들므로 backend 선기동은 필요 없습니다.
#
# 실행: PowerShell 에서  ./restore_industry.ps1

$ErrorActionPreference = "Stop"

$Repo     = $PSScriptRoot
$Dumps    = Join-Path $Repo "backend\dumps"
$PgOut    = Join-Path $Dumps "shared_industry_pg.sql"
$Neo4jOut = Join-Path $Dumps "shared_industry_neo4j.cypher"

if (-not (Test-Path $PgOut))    { Write-Error "없음: $PgOut (git pull 했는지 확인)"; exit 1 }
if (-not (Test-Path $Neo4jOut)) { Write-Error "없음: $Neo4jOut (git pull 했는지 확인)"; exit 1 }

Write-Host "── 산업 스냅샷 복원 ─────────────────────────────────" -ForegroundColor Cyan

# PowerShell 은 `<` 입력 리디렉션을 지원하지 않으므로 cmd 를 거친다(바이트/인코딩도 그대로 전달).
Write-Host "  [1/2] PostgreSQL <- shared_industry_pg.sql"
cmd /c "docker exec -i verith-postgres psql -U verith -d verith -v ON_ERROR_STOP=1 < `"$PgOut`""
if ($LASTEXITCODE -ne 0) {
    Write-Error "PG 복원 실패 (verith-postgres 떠 있는지 / alembic upgrade head 했는지 / stocks 먼저 복원했는지 확인)"
    exit 1
}

Write-Host "  [2/2] Neo4j <- shared_industry_neo4j.cypher"
cmd /c "docker exec -i verith-neo4j cypher-shell -u neo4j -p verith1234 < `"$Neo4jOut`""
if ($LASTEXITCODE -ne 0) { Write-Error "Neo4j 복원 실패 (verith-neo4j 떠 있는지 확인)"; exit 1 }

# ── 결과 요약 ──────────────────────────────────────────────────────────────────
$reports = ((docker exec verith-postgres psql -U verith -d verith -t -c "SELECT count(*) FROM industry_reports;") | Out-String).Trim()
$coreRels = ((docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain `
    "MATCH ()-[r]->() WHERE type(r) IN ['SUPPLIES','COMPETES_WITH','OWNS_STAKE','BELONGS_TO','BENEFITS_FROM'] RETURN count(r);") | Out-String).Trim().Split("`n")[-1].Trim()
$chunks = ((docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain `
    "MATCH (c:Chunk) RETURN count(c);") | Out-String).Trim().Split("`n")[-1].Trim()
$embedded = ((docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain `
    "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c);") | Out-String).Trim().Split("`n")[-1].Trim()

Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "완료:" -ForegroundColor Green
Write-Host ("  industry_reports 행수 : {0}" -f $reports)
Write-Host ("  산업 관계 수(5종)     : {0}" -f $coreRels)
Write-Host ("  :Chunk 노드 수        : {0}" -f $chunks)
Write-Host ("  임베딩 있는 청크      : {0}" -f $embedded)
if ($embedded -ne $chunks) {
    Write-Host "  ⚠ 임베딩 없는 청크가 있습니다 — 벡터 검색(vector_retrieve)이 동작하지 않습니다." -ForegroundColor Yellow
}
Write-Host "backend 가 떠 있었다면 재기동하는 편이 안전합니다." -ForegroundColor DarkGray
