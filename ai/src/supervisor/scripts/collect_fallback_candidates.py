"""fallback 승격 후보 **오프라인** 집계 스크립트 (collect 단계 — 질문 처리 경로 아님).

capture JSONL(= `JsonlPromotionCaptureSink` 이 남긴 resolved fallback 관측)을 읽어, 후보를 dedup·집계해
candidate JSONL 로 쓴다. **canonical DB 를 읽지도 쓰지도 않는다**(순수 파일 변환, 네트워크 없음).

collect → review → approve → apply 중 **collect 만** 담당한다. 사람이 candidate JSONL 의 promotion_status 를
편집(pending→approved/rejected)하고, approve 된 것만 backend 소유자가 seed/sync 로 반영한다(별도 경로).

사용:
    cd ai
    uv run python -m src.supervisor.scripts.collect_fallback_candidates \
        --input  src/supervisor/planning/data/fallback_capture.jsonl \
        --output src/supervisor/planning/data/fallback_promotion_candidates.jsonl
"""

from __future__ import annotations

import argparse
import json
import pathlib

from src.supervisor.planning.fallback_promotion import (
    PromotionInput,
    aggregate,
    candidate_to_dict,
)


def _load_inputs(path: pathlib.Path) -> list[PromotionInput]:
    recs: list[PromotionInput] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        recs.append(
            PromotionInput(
                normalized_query=d["normalized_query"],
                stock_code=d["stock_code"],
                final_source=d.get("final_source", ""),
                seen_at=d.get("seen_at", ""),
                stock_name=d.get("stock_name"),
                market=d.get("market"),
                match_types=tuple(d.get("match_types") or ()),
                final_status=d.get("final_status", "resolved"),
            )
        )
    return recs


def main() -> None:
    ap = argparse.ArgumentParser(description="fallback 승격 후보 오프라인 집계(canonical write 없음)")
    ap.add_argument("--input", required=True, help="capture JSONL 경로")
    ap.add_argument("--output", required=True, help="candidate JSONL 출력 경로")
    args = ap.parse_args()

    in_path = pathlib.Path(args.input)
    out_path = pathlib.Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"입력 capture 파일이 없습니다: {in_path}")

    inputs = _load_inputs(in_path)
    candidates = aggregate(inputs)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(candidate_to_dict(c), ensure_ascii=False) + "\n")

    alias_n = sum(1 for c in candidates if c.candidate_type == "alias_addition")
    check_n = sum(1 for c in candidates if c.needs_canonical_check)
    print(
        f"[collect] inputs={len(inputs)} candidates={len(candidates)} "
        f"alias_addition={alias_n} needs_canonical_check={check_n} → {out_path}"
    )
    print("[collect] 다음 단계: candidate JSONL 검토 후 promotion_status 편집(approved/rejected). "
          "canonical 반영은 backend 소유자가 seed/sync 로(별도).")


if __name__ == "__main__":
    main()
