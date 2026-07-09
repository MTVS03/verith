# snapshot_industry.ps1 — 산업 데이터 스냅샷 뜨기 (PG + Neo4j)
#
# 지금 내 로컬 DB에 쌓인 산업 데이터를 팀 공유용 파일로 떠서 backend/dumps/ 에 저장합니다.
# 팀 컨벤션(backend/docs/db_boundaries.md): git이 나르는 건 볼륨이 아니라 "재현 가능한 data artifact".
#   - PG   : industry_reports + agent_reports(agent_type='industry')
#              -> backend/dumps/shared_industry_pg.sql
#   - Neo4j: 산업 그래프(Company/Industry/Product/Policy/Person + 5종 관계) + :Chunk(임베딩 포함)
#              -> backend/dumps/shared_industry_neo4j.cypher
#
# ai/src/agents/industry/data/ (raw·structured·extracted) 는 **이미 git 추적 중**이라 스냅샷 대상이
# 아닙니다. 그냥 git add 하면 됩니다.
#
# 뜬 뒤에는 두 파일을 git add/commit/push 하면 팀원이 pull 후 복원할 수 있습니다
# (복원법: backend/dumps/README.md).
#
# 전제: docker compose up 으로 verith-postgres / verith-neo4j 가 떠 있어야 함.
# 실행: PowerShell 에서  ./snapshot_industry.ps1

$ErrorActionPreference = "Stop"

# ── 설정 ───────────────────────────────────────────────────────────────────────
# 뉴스와 반대로 **기본 포함**. 산업의 :Chunk 임베딩은 배치 전용이 아니라 조회 경로다
# (vector_retrieve.py 의 하이브리드 검색). 빼면 팀원이 GPU로 vectorize.py 를 다시 돌려야 한다.
$IncludeEmbedding = $true
# ───────────────────────────────────────────────────────────────────────────────

$Repo     = $PSScriptRoot
$Backend  = Join-Path $Repo "backend"
$Dumps    = Join-Path $Backend "dumps"
$Python   = Join-Path $Backend ".venv\Scripts\python.exe"
$PgOut    = Join-Path $Dumps "shared_industry_pg.sql"
$Neo4jOut = Join-Path $Dumps "shared_industry_neo4j.cypher"

if (-not (Test-Path $Python)) { Write-Error "python 없음: $Python (backend/.venv 확인)"; exit 1 }
if (-not (Test-Path $Dumps))  { New-Item -ItemType Directory -Path $Dumps | Out-Null }

Write-Host "── 산업 스냅샷 ──────────────────────────────────────" -ForegroundColor Cyan

# ── 1) PostgreSQL ──────────────────────────────────────────────────────────────
# agent_reports 는 공용 테이블이라 스코프 DELETE 만 한다(TRUNCATE 금지).
Write-Host "  [1/2] PostgreSQL (industry_reports, agent_reports) -> shared_industry_pg.sql"
Push-Location $Backend
try { & $Python -m scripts.export_industry_pg $PgOut }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Error "PG export 실패 (verith-postgres 떠 있는지 확인)"; exit 1 }

# ── 2) Neo4j ───────────────────────────────────────────────────────────────────
# 산업 노드는 graph_documents.json allowlist 로 판별한다 — 뉴스와 Company/Person 레이블을
# 공유하고 회사명 28개가 겹치므로 속성 휴리스틱으로는 못 가려낸다.
Write-Host "  [2/2] Neo4j (graph + chunks) -> shared_industry_neo4j.cypher"
$graphArgs = @("-m", "scripts.export_industry_graph", $Neo4jOut)
if (-not $IncludeEmbedding) { $graphArgs += "--no-embedding" }
Push-Location $Backend
try { & $Python @graphArgs }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Error "Neo4j export 실패 (verith-neo4j 떠 있는지 확인)"; exit 1 }

# ── 결과 요약 ──────────────────────────────────────────────────────────────────
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "완료:" -ForegroundColor Green
Write-Host ("  {0}" -f $PgOut)
Write-Host ("  {0}" -f $Neo4jOut)
Write-Host ""
Write-Host "다음: 두 파일을 git add / commit / push -> 팀원이 pull 후 복원(backend/dumps/README.md)" -ForegroundColor DarkGray
