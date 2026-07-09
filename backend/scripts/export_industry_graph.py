"""Neo4j 산업 그래프 → 재현 가능한 .cypher 텍스트 스냅샷 export.

팀 컨벤션(`backend/dumps/`)은 "git 이 나르는 건 볼륨이 아니라 재현 가능한 data artifact"다
(docs/db_boundaries.md). 뉴스는 `export_news_graph.py`, 산업은 이 스크립트가 담당한다.

⚠ **뉴스 exporter 를 그대로 쓸 수 없는 이유**: 두 그래프가 단일 `verith-neo4j` 인스턴스에
`Company`/`Person` 레이블을 **공유**하는데 정체성 키가 다르다(뉴스=`key`, 산업=`name`).
게다가 뉴스 노드는 **전부 `name` 속성을 함께 가지므로**(`MERGE (n:Company {key:'삼성전자'})
SET n += {name:'삼성전자', ...}`) `n.name IS NOT NULL` 같은 속성 휴리스틱으로는 산업 노드를
가려낼 수 없다. 실제로 회사명 28개가 겹친다(LG화학·삼성SDI·SK이노베이션 …).

그래서 산업 노드 판별은 **`ai/src/agents/industry/data/extracted/graph_documents.json`
allowlist** 를 정본으로 삼는다(그 파일이 산업 그래프의 소스). 관계는 타입 화이트리스트와
양끝 노드 allowlist 를 **둘 다** 만족할 때만 뜬다 — 뉴스도 `BELONGS_TO` 사용을 계획 중이라
(ai/src/agents/news/tasks/07_graph_builder.md) 타입만으로는 스코프가 안 된다.

`:Chunk`(DART 원문 청크 + 임베딩)는 산업 전용 레이블이라 전량 대상이다. 임베딩은 조회 경로
(`vector_retrieve.py`)라 **기본 포함**한다 — 뉴스 embedding 이 배치 전용이라 제외되는 것과 다르다.

사용:
    python -m scripts.export_industry_graph [out.cypher] [--no-embedding]
접속정보는 backend/.env 의 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 를 읽고, 없으면 로컬 기본값.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from neo4j import GraphDatabase

from scripts.export_news_graph import _load_env_from_dotenv, _props_map, cypher_literal

# 산업 그래프의 고정 스키마 — ai/src/agents/industry/schema.py 와 일치시킨다.
NODE_LABELS: tuple[str, ...] = ("Company", "Industry", "Product", "Policy", "Person")
CORE_REL_TYPES: tuple[str, ...] = (
    "SUPPLIES", "COMPETES_WITH", "OWNS_STAKE", "BELONGS_TO", "BENEFITS_FROM",
)
# 관계 정체성은 (start, type, end) 로 유일하다. 여러 근거는 origins/evidences 리스트로 집계된다
# (ai/src/agents/industry/ingest.py: MERGE (s)-[e:TYPE]->(t) SET e.origins = ... ).
CORE_REL_PROPS: tuple[str, ...] = ("origins", "evidences", "qota_rt")

# :Chunk 속성 — ai/src/agents/industry/vectorize.py 의 ingest_chunks() 와 일치. embedding 제외.
CHUNK_PROPS: tuple[str, ...] = (
    "text", "company", "stock_code", "source_url", "report_nm", "bsns_year", "section", "idx",
)
EMBED_DIM = 1024              # vectorize.py: arctic-embed-l-v2.0-ko
VECTOR_INDEX = "chunk_embedding"

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_DOCS = REPO_ROOT / "ai" / "src" / "agents" / "industry" / "data" / "extracted" / "graph_documents.json"


def load_allowlist(path: Path) -> dict[str, set[str]]:
    """graph_documents.json 에서 레이블별 산업 노드 이름 집합을 만든다(산업 노드의 정본)."""
    if not path.exists():
        raise SystemExit(f"없음: {path} — 산업 노드 allowlist 의 정본이다. ai/ 쪽 Step 3 산출물 확인.")
    data = json.loads(path.read_text(encoding="utf-8"))
    by_label: dict[str, set[str]] = {label: set() for label in NODE_LABELS}
    for node in data["nodes"]:
        label = node["type"]
        if label not in by_label:
            raise SystemExit(f"graph_documents.json 에 스키마 밖 label {label!r} — schema.py 확인.")
        by_label[label].add(node["id"])
    return by_label


def embedding_literal(vec) -> str:
    """임베딩 벡터를 Cypher LIST<FLOAT> 리터럴로.

    ``repr(float)`` 로 쓰면 775×1024 벡터가 ~16MB 가 된다. 정규화된 코사인 벡터에는 유효숫자
    6자리면 충분하므로 ``%.6g`` 로 절반 이하로 줄인다. 다만 ``%.6g`` 는 ``0.0`` 을 ``0`` 으로
    내놓는데, 그러면 리스트에 INTEGER 가 섞여 ``db.create.setNodeVectorProperty`` 가 거부한다.
    지수/소수점이 없는 결과에는 ``.0`` 을 붙여 **전부 FLOAT 리터럴**임을 보장한다.
    """
    parts = []
    for v in vec:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            raise ValueError(f"임베딩에 NaN/Inf 포함 — 벡터 손상 의심: {f}")
        s = f"{f:.6g}"
        if "." not in s and "e" not in s and "E" not in s:
            s += ".0"
        parts.append(s)
    return "[" + ", ".join(parts) + "]"


def _pick_label(labels, allowed: tuple[str, ...]) -> str | None:
    """노드의 레이블 중 산업 스키마에 속하는 것 하나를 고른다."""
    for label in labels:
        if label in allowed:
            return label
    return None


def write_header(f, all_names: list[str], include_embedding: bool) -> None:
    """DDL + 스코프 초기화. 복원 전 backend/ingest.py 선기동 없이도 제약이 서게 한다."""
    f.write("// verith 산업 그래프 스냅샷 (자동 생성 — 손으로 편집하지 말 것)\n")
    f.write("// 복원: cypher-shell < 이 파일   (뉴스 스냅샷을 쓴다면 restore_news 를 먼저 돌린다)\n\n")

    f.write("// ── DDL ──\n")
    # Company/Person 은 뉴스와 레이블을 공유한다. name IS UNIQUE 를 걸면 뉴스의
    # MERGE (n:Company {key:...}) SET n += {name:...} 이 제약 위반으로 터진다(회사명 28개 충돌).
    # 그래서 산업 전용 레이블에만 유니크 제약을 두고, 공유 레이블에는 일반 인덱스만 건다.
    for label in ("Industry", "Policy", "Product"):
        f.write(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.`name` IS UNIQUE;\n")
    f.write("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:`Chunk`) REQUIRE c.`id` IS UNIQUE;\n")
    for label in ("Company", "Person"):
        f.write(f"CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON (n.`name`);\n")
    if include_embedding:
        f.write(
            f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (c:`Chunk`) ON (c.`embedding`) "
            "OPTIONS {indexConfig: {"
            f"`vector.dimensions`: {EMBED_DIM}, "
            "`vector.similarity_function`: 'cosine'}};\n"
        )

    f.write("\n// ── 스코프 초기화 (멱등 복원) ──\n")
    f.write("// :Chunk 는 산업 전용 레이블 → 전량 삭제 안전. FROM_FILING 도 함께 정리된다.\n")
    f.write("MATCH (c:`Chunk`) DETACH DELETE c;\n")

    f.write("// 본체 관계 stale 제거. 타입 + 양끝 allowlist 로 스코프해 뉴스 관계를 보호한다.\n")
    names_lit = "[" + ", ".join(cypher_literal(n) for n in all_names) + "]"
    labels_a = " OR ".join(f"a:`{lbl}`" for lbl in NODE_LABELS)
    labels_b = " OR ".join(f"b:`{lbl}`" for lbl in NODE_LABELS)
    types_lit = "[" + ", ".join(f"'{t}'" for t in CORE_REL_TYPES) + "]"
    f.write(
        f"WITH {names_lit} AS names\n"
        f"MATCH (a)-[r]->(b)\n"
        f"WHERE type(r) IN {types_lit}\n"
        f"  AND ({labels_a}) AND ({labels_b})\n"
        f"  AND a.`name` IN names AND b.`name` IN names\n"
        f"DELETE r;\n"
    )
    # 5종 레이블 노드는 삭제하지 않는다 — 뉴스 노드와 물리적으로 같을 수 있어(회사명 28개 충돌)
    # 노드 삭제가 뉴스 그래프를 훼손한다. 관계만 재구성하면 멱등이 성립한다.


def export_nodes(f, allowlist: dict[str, set[str]], session) -> tuple[int, list[str]]:
    """5종 레이블 노드를 allowlist 그대로 MERGE 문으로 emit. (개수, 그래프에 없는 이름) 반환.

    산업은 이 노드들에 ``name`` 외 속성을 쓰지 않으므로(ingest.py) `SET` 절이 필요 없다.
    뉴스와 병합된 노드에 붙어 있을 `key` 등 남의 속성을 덤프로 흘리지 않는 효과도 있다.
    """
    f.write("\n// ── nodes (graph_documents.json allowlist) ──\n")
    total = 0
    missing: list[str] = []
    for label in NODE_LABELS:
        names = sorted(allowlist[label])
        if not names:
            continue
        present = {
            rec["name"]
            for rec in session.run(
                f"MATCH (n:`{label}`) WHERE n.`name` IN $names RETURN n.`name` AS name",
                names=names,
            )
        }
        missing.extend(f"{label}:{n}" for n in names if n not in present)
        for name in names:
            f.write(f"MERGE (n:`{label}` {{`name`: {cypher_literal(name)}}});\n")
        total += len(names)
        print(f"  nodes {label}: {len(names)}")
    return total, missing


def export_chunks(f, session, include_embedding: bool) -> int:
    """:Chunk 노드(+임베딩)를 emit. Chunk 는 산업 전용 레이블이라 allowlist 불필요."""
    f.write("\n// ── :Chunk (DART 원문 청크" + (" + 임베딩" if include_embedding else "") + ") ──\n")
    count = 0
    for rec in session.run("MATCH (c:`Chunk`) RETURN c ORDER BY c.`id`"):
        node = rec["c"]
        props = dict(node)
        chunk_id = props.get("id")
        if chunk_id is None:
            continue
        body = {k: props[k] for k in CHUNK_PROPS if k in props}
        stmt = f"MERGE (c:`Chunk` {{`id`: {cypher_literal(chunk_id)}}}) SET c += {_props_map(body)}"
        emb = props.get("embedding")
        if include_embedding and emb:
            # vectorize.py 와 동일하게 procedure 로 벡터 속성을 심는다(벡터 인덱스가 인식하도록).
            stmt += (
                f" WITH c CALL db.create.setNodeVectorProperty(c, 'embedding', "
                f"{embedding_literal(emb)})"
            )
        f.write(stmt + ";\n")
        count += 1
    print(f"  chunks: {count}" + (" (임베딩 포함)" if include_embedding else " (임베딩 제외)"))
    return count


def export_relationships(f, allowlist: dict[str, set[str]], session) -> tuple[int, int, int]:
    """본체 관계 5종 + FROM_FILING 을 emit. (본체, FROM_FILING, skipped) 반환."""
    all_names = sorted(set().union(*allowlist.values()))

    f.write("\n// ── relationships (5종) ──\n")
    core = skipped = 0
    query = (
        "MATCH (a)-[r]->(b) "
        "WHERE type(r) IN $types "
        f"  AND ({' OR '.join(f'a:`{l}`' for l in NODE_LABELS)}) "
        f"  AND ({' OR '.join(f'b:`{l}`' for l in NODE_LABELS)}) "
        "  AND a.`name` IN $names AND b.`name` IN $names "
        "RETURN a, labels(a) AS al, type(r) AS t, properties(r) AS rp, b, labels(b) AS bl"
    )
    for rec in session.run(query, types=list(CORE_REL_TYPES), names=all_names):
        a_label = _pick_label(rec["al"], NODE_LABELS)
        b_label = _pick_label(rec["bl"], NODE_LABELS)
        a_name, b_name = rec["a"].get("name"), rec["b"].get("name")
        if not (a_label and b_label and a_name and b_name):
            skipped += 1
            continue
        rprops = {k: v for k, v in (rec["rp"] or {}).items() if k in CORE_REL_PROPS}
        setclause = f" SET r += {_props_map(rprops)}" if rprops else ""
        f.write(
            f"MATCH (a:`{a_label}` {{`name`: {cypher_literal(a_name)}}}), "
            f"(b:`{b_label}` {{`name`: {cypher_literal(b_name)}}}) "
            f"MERGE (a)-[r:`{rec['t']}`]->(b){setclause};\n"
        )
        core += 1

    f.write("\n// ── FROM_FILING (:Chunk -> :Company) ──\n")
    from_filing = 0
    for rec in session.run(
        "MATCH (c:`Chunk`)-[:`FROM_FILING`]->(co:`Company`) "
        "WHERE co.`name` IN $names "
        "RETURN c.`id` AS cid, co.`name` AS coname ORDER BY cid",
        names=sorted(allowlist["Company"]),
    ):
        f.write(
            f"MATCH (c:`Chunk` {{`id`: {cypher_literal(rec['cid'])}}}), "
            f"(co:`Company` {{`name`: {cypher_literal(rec['coname'])}}}) "
            f"MERGE (c)-[:`FROM_FILING`]->(co);\n"
        )
        from_filing += 1

    print(f"  rels core: {core}   FROM_FILING: {from_filing}")
    return core, from_filing, skipped


def export(uri: str, user: str, password: str, out_path: Path, include_embedding: bool) -> None:
    allowlist = load_allowlist(GRAPH_DOCS)
    all_names = sorted(set().union(*allowlist.values()))

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session, out_path.open("w", encoding="utf-8", newline="\n") as f:
            write_header(f, all_names, include_embedding)
            nodes, missing = export_nodes(f, allowlist, session)
            chunks = export_chunks(f, session, include_embedding)
            core, from_filing, skipped = export_relationships(f, allowlist, session)
    finally:
        driver.close()

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n  nodes={nodes} chunks={chunks} rels={core}(+{from_filing} FROM_FILING) "
          f"skipped={skipped}  size={size_mb:.1f}MB")
    if missing:
        print(f"  ⚠ allowlist 에 있으나 그래프에 없는 노드 {len(missing)}개 "
              f"(ingest.py 를 안 돌렸을 수 있음): {missing[:10]}")
    if skipped:
        print(f"  ⚠ {skipped}개 관계 스킵 — 양끝 노드의 산업 정체성을 못 잡음")


def main() -> None:
    parser = argparse.ArgumentParser(description="산업 Neo4j 그래프를 .cypher 스냅샷으로 export.")
    parser.add_argument("out", nargs="?", default=None, help="출력 .cypher 경로")
    parser.add_argument("--no-embedding", action="store_true",
                        help=":Chunk.embedding 제외 (파일은 작아지지만 벡터 검색이 죽는다)")
    args = parser.parse_args()

    _load_env_from_dotenv()
    uri = os.getenv("NEO4J_URI") or "bolt://localhost:7687"
    user = os.getenv("NEO4J_USER") or "neo4j"
    password = os.getenv("NEO4J_PASSWORD") or "verith1234"

    default_out = Path(__file__).resolve().parent.parent / "dumps" / "shared_industry_neo4j.cypher"
    out_path = Path(args.out) if args.out else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    include_embedding = not args.no_embedding
    print(f"Neo4j 산업 export: {uri} -> {out_path}")
    export(uri, user, password, out_path, include_embedding)


if __name__ == "__main__":
    main()
