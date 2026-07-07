# services/embedder.py
"""arctic-embed-l-v2.0-ko 임베딩 서비스 — 기사 summary 1건/배치 → 임베딩 벡터(TASK 05).

summary 유사도는 오직 이 전용 임베딩 모델이 낸다(CLAUDE.md §4). 무거운 로직(모델 로드·인코딩)은
여기, 노드는 얇게(§2-2). 유사도 '계산'(코사인)은 utils/similarity.py, 병합 '판정'은
services/event_merge.py 가 한다 — embedder는 벡터만 만든다(단일 책임, TASK 05 §3.2-5).

⚠️ 기사끼리 대칭 비교라 검색용 query/document 프리픽스를 붙이지 않는다(model_choice §3). 프리픽스를
   섞으면 대칭성이 깨져 병합이 흔들린다.
⚠️ 입력은 Article.summary(LLM 통일 요약)다. 감성(finbert)이 content를 쓰는 것과 다르다(입력이 다름).

테스트 시임: sentence-transformers·모델은 무겁고 선택 의존성이라, 저수준 인코딩을 `_embed_raw` 한 함수로
격리한다. 테스트는 이 함수를 monkeypatch 해 실제 모델·네트워크 없이 고정 벡터를 돌려준다
(finbert._infer_raw 규약과 동일).
"""
from __future__ import annotations

import logging

from config import (
    EMBED_BATCH_SIZE,
    EMBED_DEVICE,
    EMBED_MAX_INPUT_CHARS,
    EMBED_MODEL,
)

logger = logging.getLogger(__name__)

# 프로세스 내 1회 로드(모듈 캐시). 모델은 무겁고 재사용되므로 기사마다 다시 로드하지 않는다(속도, §3.2-1).
# sentence-transformers/torch 는 무거워 지연 import 한다(테스트는 _embed_raw 를 mock).
_model = None


def _get_model():
    """arctic-embed-l-v2.0-ko 를 지연 로드(싱글턴). sentence-transformers 로 로드한다.

    - 최초 호출 시 모델을 자동 다운로드해 로컬 캐시에 저장한다(이후 재사용).
    - sentence-transformers/torch 는 무거워 모듈 import 시점이 아니라 실제 인코딩 때 import 한다.
    - 테스트는 _embed_raw 를 monkeypatch 하므로 이 함수(=실제 모델 로드)에 도달하지 않는다.
    """
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        use_cuda = str(EMBED_DEVICE).lower().startswith("cuda") and torch.cuda.is_available()
        _model = SentenceTransformer(EMBED_MODEL, device="cuda" if use_cuda else "cpu")
    return _model


def _embed_raw(texts: list[str]) -> list[list[float]]:
    """저수준 배치 인코딩: 텍스트 리스트 → 벡터 리스트. 순서·길이는 입력과 일치.

    프리픽스를 붙이지 않고 모든 텍스트를 같은 방식으로 임베딩한다(대칭 비교). 이 함수가 테스트 시임이다
    (monkeypatch 대상). EMBED_BATCH_SIZE 단위 배치는 sentence-transformers 가 내부에서 처리한다.
    """
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=False,   # 코사인 정규화는 utils/similarity 가 계산 시 수행
    )
    return [[float(x) for x in vec] for vec in vectors]


def _truncate(text: str) -> str:
    """입력을 EMBED_MAX_INPUT_CHARS 로 자른다(8K 컨텍스트·속도). 초과분은 버린다."""
    return text[:EMBED_MAX_INPUT_CHARS]


def embed(text: str | None) -> list[float] | None:
    """summary 1건 → 임베딩 벡터 또는 None.

    - 입력은 EMBED_MAX_INPUT_CHARS 로 잘라 넣는다. 프리픽스 없음(대칭 비교).
    - 빈/None 입력은 모델을 부르지 않고 None('임베딩 없음')을 돌려준다(무의미 벡터 방지, §2-5).
    - 인코딩 자체 실패는 삼키지 말고 로깅, 해당 건만 None 으로 신호(§7). 저장·부수효과 없음(§2-1).
    """
    if not text or not text.strip():
        return None  # 요약 없는 입력은 모델을 부르지 않는다(방어적 거름)

    try:
        raw = _embed_raw([_truncate(text)])
    except Exception as exc:  # 인코딩 실패는 로깅 후 '임베딩 없음' 신호(호출측이 embedding=None 유지)
        logger.warning("임베딩 실패, skip: %s", exc)
        return None

    return raw[0] if raw else None


def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """여러 summary 를 배치 임베딩(처리량). 반환 길이·순서는 입력과 항상 일치.

    - 각 원소는 벡터 또는 None(빈 입력·인코딩 실패 = 임베딩 없음).
    - 배치 인코딩이 실패하면(예: OOM·특정 입력 예외) 배치 전체를 버리지 않고 각 텍스트를 embed() 로
      1건씩 재시도한다. 개별 실패한 건만 None 으로 격리하고 나머지는 정상 벡터를 채운다(실패 격리, §7).
    - 빈 입력은 모델을 부르지 않고 그 자리를 None 으로 둔다(호출측이 짝을 맞출 수 있게 자리 유지).
    """
    if not texts:
        return []

    # 빈 입력은 배치에서 제외하되(모델 호출 낭비·오류 방지) 자리는 None 으로 남겨 순서/길이를 보존한다.
    results: list[list[float] | None] = [None] * len(texts)
    idx_to_embed = [i for i, t in enumerate(texts) if t and t.strip()]
    if not idx_to_embed:
        return results

    payload = [_truncate(texts[i]) for i in idx_to_embed]
    try:
        raw = _embed_raw(payload)
        if len(raw) != len(payload):  # 파이프라인이 길이를 어기면 계약 위반 → 개별 fallback 으로
            raise ValueError(f"배치 출력 길이 불일치: {len(raw)} != {len(payload)}")
        for i, vec in zip(idx_to_embed, raw):
            results[i] = vec
    except Exception as exc:  # 배치 실패 → 건 단위 fallback(한 건의 이상 입력이 배치 전체를 날리지 않게)
        logger.warning("배치 임베딩 실패, 개별 fallback: %s", exc)
        for i in idx_to_embed:
            results[i] = embed(texts[i])

    return results
