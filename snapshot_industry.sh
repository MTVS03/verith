#!/usr/bin/env bash
# snapshot_industry.sh — 산업 데이터 스냅샷 뜨기 (WSL / macOS / Linux)
#
# snapshot_industry.ps1 의 bash 대응. 지금 내 로컬 DB에 쌓인 산업 데이터를 backend/dumps/ 에 뜬다.
#   - PG   : industry_reports + agent_reports(agent_type='industry')
#   - Neo4j: 산업 그래프 + :Chunk(임베딩 포함)
#
# ai/src/agents/industry/data/ 는 이미 git 추적 중이라 스냅샷 대상이 아니다(그냥 git add).
#
# 전제: docker compose up 으로 verith-postgres / verith-neo4j 가 떠 있어야 함.
# 실행:  ./snapshot_industry.sh            (권한 없으면  bash snapshot_industry.sh)
#        ./snapshot_industry.sh --no-embedding

set -euo pipefail

# 뉴스와 반대로 임베딩 기본 포함 — 산업 :Chunk 임베딩은 vector_retrieve.py 의 조회 경로다.
GRAPH_ARGS=()
[ "${1:-}" = "--no-embedding" ] && GRAPH_ARGS+=("--no-embedding")

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$REPO/backend"
DUMPS="$BACKEND/dumps"
PG_OUT="$DUMPS/shared_industry_pg.sql"
NEO4J_OUT="$DUMPS/shared_industry_neo4j.cypher"

mkdir -p "$DUMPS"

echo "── 산업 스냅샷 ──────────────────────────────────────"

echo "  [1/2] PostgreSQL (industry_reports, agent_reports) -> shared_industry_pg.sql"
(cd "$BACKEND" && uv run python -m scripts.export_industry_pg "$PG_OUT") \
  || { echo "PG export 실패 (verith-postgres 떠 있는지 확인)" >&2; exit 1; }

echo "  [2/2] Neo4j (graph + chunks) -> shared_industry_neo4j.cypher"
(cd "$BACKEND" && uv run python -m scripts.export_industry_graph "$NEO4J_OUT" "${GRAPH_ARGS[@]+"${GRAPH_ARGS[@]}"}") \
  || { echo "Neo4j export 실패 (verith-neo4j 떠 있는지 확인)" >&2; exit 1; }

echo "────────────────────────────────────────────────────"
echo "완료:"
echo "  $PG_OUT"
echo "  $NEO4J_OUT"
echo
echo "다음: 두 파일을 git add / commit / push -> 팀원이 pull 후 복원(backend/dumps/README.md)"
