"""Neo4j 뉴스 그래프 → 재현 가능한 .cypher 텍스트 스냅샷 export.

팀 컨벤션(`backend/dumps/`)은 "git 이 나르는 건 볼륨이 아니라 재현 가능한 data artifact"다
(docs/db_boundaries.md). PG 는 pg_dump(.sql), Neo4j 는 이 스크립트가 .cypher 로 뜬다.

APOC 없이 동작한다 — 모든 노드에 정체성 유니크 제약(db/graph/bootstrap.py: Event/Company/Keyword/
Person/Country=key, NewsRef=news_id)이 있어, 정체성 키 기준 MERGE 로 멱등·고속 복원된다. 제약은
backend 앱 startup(lifespan)이 만들므로 복원 전에 backend 를 한 번 띄우면 인덱스가 이미 있다.

사용:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
        python -m scripts.export_news_graph [out.cypher]
값이 없으면 backend/.env 를 읽고, 그래도 없으면 로컬 기본값(bolt://localhost:7687)을 쓴다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

# 노드 label → 정체성(유니크 제약) 속성. db/graph/bootstrap.py 와 일치시킨다.
LABEL_KEY: dict[str, str] = {
    "Event": "key",
    "Company": "key",
    "Keyword": "key",
    "Person": "key",
    "Country": "key",
    "NewsRef": "news_id",
}


def _load_env_from_dotenv() -> None:
    """이미 설정된 실제 env 를 우선하고, 없으면 backend/.env 값으로 채운다(의존성 없이 최소 파서)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


def cypher_literal(v: object) -> str:
    """파이썬 값을 Cypher 리터럴 문자열로. (뉴스 그래프 속성은 str/int/float 뿐 — bool/list/None 도 방어적 처리)"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        escaped = (
            v.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f"'{escaped}'"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(cypher_literal(x) for x in v) + "]"
    # 알 수 없는 타입(예: neo4j 시간형)은 문자열로 안전 fallback.
    return cypher_literal(str(v))


def _props_map(props: dict) -> str:
    return "{" + ", ".join(f"`{k}`: {cypher_literal(val)}" for k, val in props.items()) + "}"


def _identity(labels, props: dict):
    """노드의 (정체성 label, 키 속성, 키 값). 알 수 없는 label 이면 None."""
    for label in labels:
        if label in LABEL_KEY:
            keyprop = LABEL_KEY[label]
            return label, keyprop, props.get(keyprop)
    return None


def export(uri: str, user: str, password: str, out_path: Path) -> tuple[int, int, int]:
    """그래프 전체를 MERGE 문 .cypher 로 out_path 에 쓴다. (nodes, rels, skipped) 반환."""
    nodes = rels = skipped = 0
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session, out_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write("// verith 뉴스 그래프 스냅샷 (자동 생성 — 손으로 편집하지 말 것)\n")
            f.write("// 복원: cypher-shell < 이 파일  (먼저 backend 를 한 번 띄워 유니크 제약이 있어야 빠름)\n\n")

            # ── 노드: 정체성 키로 MERGE 후 전체 속성 덮어쓰기(멱등) ─────────────────
            f.write("// ── nodes ──\n")
            for rec in session.run("MATCH (n) RETURN n"):
                node = rec["n"]
                props = dict(node)
                ident = _identity(list(node.labels), props)
                if ident is None:
                    skipped += 1
                    continue
                label, keyprop, keyval = ident
                if keyval is None:
                    skipped += 1
                    continue
                f.write(
                    f"MERGE (n:`{label}` {{`{keyprop}`: {cypher_literal(keyval)}}}) "
                    f"SET n += {_props_map(props)};\n"
                )
                nodes += 1

            # ── 관계: 양끝 정체성으로 MATCH 후 MERGE ─────────────────────────────
            f.write("\n// ── relationships ──\n")
            query = "MATCH (a)-[r]->(b) RETURN a, type(r) AS t, properties(r) AS rp, b"
            for rec in session.run(query):
                a, b = rec["a"], rec["b"]
                a_id = _identity(list(a.labels), dict(a))
                b_id = _identity(list(b.labels), dict(b))
                if a_id is None or b_id is None or a_id[2] is None or b_id[2] is None:
                    skipped += 1
                    continue
                al, ak, av = a_id
                bl, bk, bv = b_id
                rtype = rec["t"]
                rprops = rec["rp"] or {}
                setclause = f" SET r += {_props_map(rprops)}" if rprops else ""
                f.write(
                    f"MATCH (a:`{al}` {{`{ak}`: {cypher_literal(av)}}}), "
                    f"(b:`{bl}` {{`{bk}`: {cypher_literal(bv)}}}) "
                    f"MERGE (a)-[r:`{rtype}`]->(b){setclause};\n"
                )
                rels += 1
    finally:
        driver.close()
    return nodes, rels, skipped


def main() -> None:
    _load_env_from_dotenv()
    uri = os.getenv("NEO4J_URI") or "bolt://localhost:7687"
    user = os.getenv("NEO4J_USER") or "neo4j"
    password = os.getenv("NEO4J_PASSWORD") or "verith1234"

    default_out = Path(__file__).resolve().parent.parent / "dumps" / "shared_news_neo4j.cypher"
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Neo4j export: {uri} -> {out_path}")
    n, r, s = export(uri, user, password, out_path)
    print(f"  nodes={n} rels={r} skipped={s}")
    if s:
        print(f"  ⚠ {s}개 스킵(정체성 키 없는 노드/관계) — 스키마 밖이면 확인 필요")


if __name__ == "__main__":
    main()
