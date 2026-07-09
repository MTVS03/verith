#!/usr/bin/env bash
# restore_industry.sh — 팀 공유 산업 스냅샷을 내 로컬 DB에 복원 (WSL / macOS / Linux)
#
# git pull 로 받은 backend/dumps/ 의 산업 스냅샷(PG + Neo4j)을 내 로컬 DB에 넣습니다.
#   - PG   : shared_industry_pg.sql       (agent_reports 는 agent_type='industry' 만 스코프 DELETE)
#   - Neo4j: shared_industry_neo4j.cypher (MERGE 문 — 멱등. :Chunk 는 전량 교체)
#
# ⚠ 전제(순서 중요):
#   1) docker compose up -d          (verith-postgres / verith-neo4j)
#   2) cd backend && uv run alembic upgrade head
#   3) 주식 마스터 먼저 복원 — agent_reports.stock_code 가 stocks.stock_code 로 FK 를 겁니다:
#        docker exec -i verith-postgres psql -U verith -d verith < backend/dumps/shared_verith_snapshot.sql
#   4) 뉴스 스냅샷도 쓴다면 **./restore_news.sh 를 먼저** 돌립니다(아래 주의 참고)
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
# 실행:  ./restore_industry.sh     (권한 없으면  bash restore_industry.sh)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMPS="$REPO/backend/dumps"
PG_OUT="$DUMPS/shared_industry_pg.sql"
NEO4J_OUT="$DUMPS/shared_industry_neo4j.cypher"

[ -f "$PG_OUT" ]    || { echo "없음: $PG_OUT (git pull 했는지 확인)" >&2; exit 1; }
[ -f "$NEO4J_OUT" ] || { echo "없음: $NEO4J_OUT (git pull 했는지 확인)" >&2; exit 1; }

echo "── 산업 스냅샷 복원 ─────────────────────────────────"

echo "  [1/2] PostgreSQL <- shared_industry_pg.sql"
docker exec -i verith-postgres psql -U verith -d verith -v ON_ERROR_STOP=1 < "$PG_OUT" \
  || { echo "PG 복원 실패 (verith-postgres 떠 있는지 / alembic upgrade head 했는지 / stocks 먼저 복원했는지 확인)" >&2; exit 1; }

echo "  [2/2] Neo4j <- shared_industry_neo4j.cypher"
docker exec -i verith-neo4j cypher-shell -u neo4j -p verith1234 < "$NEO4J_OUT" \
  || { echo "Neo4j 복원 실패 (verith-neo4j 떠 있는지 확인)" >&2; exit 1; }

cypher() { docker exec verith-neo4j cypher-shell -u neo4j -p verith1234 --format plain "$1" | tail -n 1 | tr -d '[:space:]'; }

REPORTS=$(docker exec verith-postgres psql -U verith -d verith -t -c "SELECT count(*) FROM industry_reports;" | tr -d '[:space:]')
CORE_RELS=$(cypher "MATCH ()-[r]->() WHERE type(r) IN ['SUPPLIES','COMPETES_WITH','OWNS_STAKE','BELONGS_TO','BENEFITS_FROM'] RETURN count(r);")
CHUNKS=$(cypher "MATCH (c:Chunk) RETURN count(c);")
EMBEDDED=$(cypher "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c);")

echo "────────────────────────────────────────────────────"
echo "완료:"
echo "  industry_reports 행수 : $REPORTS"
echo "  산업 관계 수(5종)     : $CORE_RELS"
echo "  :Chunk 노드 수        : $CHUNKS"
echo "  임베딩 있는 청크      : $EMBEDDED"
[ "$EMBEDDED" = "$CHUNKS" ] || echo "  ⚠ 임베딩 없는 청크가 있습니다 — 벡터 검색(vector_retrieve)이 동작하지 않습니다."
echo "backend 가 떠 있었다면 재기동하는 편이 안전합니다."
