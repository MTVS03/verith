#!/usr/bin/env bash
# restore_news.sh — 팀 공유 뉴스 스냅샷을 내 로컬 DB에 복원 (WSL / macOS / Linux)
#
# git pull 로 받은 backend/dumps/ 의 뉴스 스냅샷(PG + Neo4j)을 내 로컬 DB에 넣습니다.
#   - PG   : shared_news_pg.sql       (맨 앞 TRUNCATE 로 news/news_reports 를 스냅샷 상태로 리셋)
#   - Neo4j: shared_news_neo4j.cypher (MERGE 문 — 기존 그래프에 덮어써 반영)
#
# ⚠ 전제(순서 중요):
#   1) docker compose up -d          (verith-postgres / verith-neo4j 가 떠 있어야 함)
#   2) backend 스키마 최신화 + 제약 생성:
#        cd backend && uv run alembic upgrade head   (PG 스키마)
#        그리고 backend 를 한 번 기동  (Neo4j 유니크 제약 생성 → 복원 속도/정합)
#   3) 그 다음 이 스크립트 실행
#
# 실행:  ./restore_news.sh     (권한 없으면  bash restore_news.sh)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMPS="$REPO/backend/dumps"
PG_OUT="$DUMPS/shared_news_pg.sql"
NEO4J_OUT="$DUMPS/shared_news_neo4j.cypher"

[ -f "$PG_OUT" ]    || { echo "없음: $PG_OUT (git pull 했는지 확인)" >&2; exit 1; }
[ -f "$NEO4J_OUT" ] || { echo "없음: $NEO4J_OUT (git pull 했는지 확인)" >&2; exit 1; }

echo "── 뉴스 스냅샷 복원 ─────────────────────────────────"

echo "  [1/2] PostgreSQL <- shared_news_pg.sql"
docker exec -i verith-postgres psql -U verith -d verith < "$PG_OUT" \
  || { echo "PG 복원 실패 (verith-postgres 떠 있는지 / alembic upgrade head 했는지 확인)" >&2; exit 1; }

echo "  [2/2] Neo4j <- shared_news_neo4j.cypher"
docker exec -i verith-neo4j cypher-shell -u neo4j -p verith1234 < "$NEO4J_OUT" \
  || { echo "Neo4j 복원 실패 (verith-neo4j 떠 있는지 확인)" >&2; exit 1; }

PG_ROWS=$(docker exec verith-postgres psql -U verith -d verith -t -c "SELECT count(*) FROM news;" | tr -d '[:space:]')
N4_NODES=$(docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain "MATCH (n) RETURN count(n);" | tail -n 1 | tr -d '[:space:]')
echo "────────────────────────────────────────────────────"
echo "완료:"
echo "  news 행수     : $PG_ROWS"
echo "  neo4j 노드수  : $N4_NODES"
echo "backend 가 떠 있었다면 재기동하는 편이 안전합니다."
