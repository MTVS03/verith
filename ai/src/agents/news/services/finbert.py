# services/finbert.py
"""KR-FinBert-SC 감성 서비스 — 기사 본문 1건/배치 → SentimentResult(라벨 + confidence).

TASK 04. 감성은 오직 이 전용 모델(KR-FinBert-SC)이 낸다. LLM(services/llm.py)에게 감성을
시키지 않는다(CLAUDE.md §2-4). 무거운 로직(모델 로드·추론·라벨 매핑)은 여기, 노드는 얇게(§2-2).

⚠️ 입력은 기사 '본문'(Article.content)이다. summary(LLM 통일 요약)가 아니다. 요약은 감성 신호를
   깎을 수 있어 감성 판정에는 원문 본문을 넣는다(TASK 04 §2, event_merge=summary와 혼동 금지).
⚠️ 반환 SentimentResult는 schemas 소유. 여기서 재정의하지 않고 schemas/article.py 에서 import 한다.

테스트 시임: transformers·모델은 무겁고 선택 의존성이라, 저수준 추론을 `_infer_raw` 한 함수로 격리한다.
테스트는 이 함수를 monkeypatch 해 실제 모델·네트워크 없이 고정 라벨·확률을 돌려준다(llm._chat_completion 규약과 동일).
"""
from __future__ import annotations

import logging

from config import (
    FINBERT_BATCH_SIZE,
    FINBERT_DEVICE,
    FINBERT_LABEL_MAP,
    FINBERT_MAX_INPUT_CHARS,
    FINBERT_MODEL,
)
from schemas.article import Sentiment, SentimentResult

logger = logging.getLogger(__name__)

# 프로세스 내 1회 로드(모듈 캐시). 모델은 무겁고 재사용되므로 기사마다 다시 로드하지 않는다(속도, §3.2-1).
# (tokenizer, model) 튜플. transformers/torch 는 무거워 지연 import 한다(테스트는 _infer_raw 를 mock).
_model_bundle = None

# BERT 계열 최대 토큰 길이(아키텍처 상한). 문자 상한(FINBERT_MAX_INPUT_CHARS)과 별개의 2차 방어.
_MAX_TOKENS = 512

# 라벨명 대소문자·공백 차이에 견디도록 정규화한 매핑(config 원본은 건드리지 않음).
_NORMALIZED_LABEL_MAP: dict[str, str] = {
    str(label).strip().lower(): value for label, value in FINBERT_LABEL_MAP.items()
}


def _get_model():
    """KR-FinBert-SC 를 지연 로드(싱글턴). transformers 로 from_pretrained 로드한다.

    - 최초 호출 시 Hugging Face 에서 모델을 자동 다운로드해 로컬 캐시에 저장한다(이후 재사용).
    - transformers/torch 는 무거워 모듈 import 시점이 아니라 실제 추론 때 import 한다.
    - 테스트는 _infer_raw 를 monkeypatch 하므로 이 함수(=실제 모델 로드)에 도달하지 않는다.
    """
    global _model_bundle
    if _model_bundle is None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
        model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)
        use_cuda = str(FINBERT_DEVICE).lower().startswith("cuda") and torch.cuda.is_available()
        model.to("cuda" if use_cuda else "cpu")
        model.eval()  # 추론 전용(드롭아웃 등 비활성)
        _model_bundle = (tokenizer, model)
    return _model_bundle


def _infer_raw(texts: list[str]) -> list[dict]:
    """저수준 배치 추론: 본문 리스트 → [{"label": str, "score": float}, ...] (예측 라벨 + confidence).

    KR-FinBert-SC(BertForSequenceClassification) 로짓을 softmax 해 예측 라벨과 그 확률(0~1)을 낸다.
    라벨명은 모델 config.id2label(negative/neutral/positive) 을 그대로 쓰고, Sentiment 매핑은 상위(classify)가 한다.
    이 함수가 테스트 시임이다(monkeypatch 대상). 순서·길이는 입력과 일치한다.
    """
    import torch

    tokenizer, model = _get_model()
    id2label = model.config.id2label
    out: list[dict] = []
    # FINBERT_BATCH_SIZE 단위로 나눠 추론(처리량·메모리 안전 — 큰 배치 한 번에 패딩하지 않음).
    for start in range(0, len(texts), FINBERT_BATCH_SIZE):
        chunk = texts[start:start + FINBERT_BATCH_SIZE]
        enc = tokenizer(
            chunk,
            return_tensors="pt",
            truncation=True,
            max_length=_MAX_TOKENS,   # 512 토큰 한계(문자 상한과 별개의 2차 방어)
            padding=True,
        )
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.no_grad():
            logits = model(**enc).logits
        probs = torch.softmax(logits, dim=-1)
        scores, indices = probs.max(dim=-1)
        out.extend(
            {"label": id2label[int(idx)], "score": float(score)}
            for idx, score in zip(indices.tolist(), scores.tolist())
        )
    return out


def _map_label(label: str) -> Sentiment | None:
    """모델 출력 라벨 → Sentiment Enum. 매핑에 없으면 None(임의 중립 강제 금지 — 오분류 은폐 방지, §3.2-2)."""
    value = _NORMALIZED_LABEL_MAP.get(str(label).strip().lower())
    if value is None:
        return None
    return Sentiment(value)


def _truncate(text: str) -> str:
    """입력을 FINBERT_MAX_INPUT_CHARS 로 자른다(512 토큰 한계·속도). 초과분은 버린다."""
    return text[:FINBERT_MAX_INPUT_CHARS]


def classify(text: str) -> SentimentResult | None:
    """기사 본문(Article.content, summary 아님) 1건 → SentimentResult(sentiment, score) 또는 None.

    - 입력은 FINBERT_MAX_INPUT_CHARS 로 잘라 넣는다(512 토큰 한계).
    - 모델 라벨을 FINBERT_LABEL_MAP 으로 Sentiment(긍정/중립/부정)에 매핑한다.
      매핑 밖 라벨은 로깅 후 실패 신호(None). 임의로 '중립'으로 눕히지 않는다.
    - score = 예측 라벨의 confidence(softmax 최댓값, 0~1) = Article.sentiment_score.
    - 빈 문자열/None 은 모델을 호출하지 않고 '감성 없음'(None)을 반환한다(환각 금지, §2-5).
    - 반환 None 은 '감성을 붙일 수 없음' 신호다(호출측이 sentiment=None 유지). 저장·부수효과 없음(§2-1).
    """
    if not text or not text.strip():
        return None  # 본문 없는 입력은 모델을 부르지 않는다(방어적 거름, §3.2-4)

    try:
        raw = _infer_raw([_truncate(text)])
    except Exception as exc:  # 추론 자체 실패는 삼키지 말고 로깅, 해당 기사만 감성 실패로 신호(§7)
        logger.warning("감성 추론 실패, skip: %s", exc)
        return None

    return _to_result(raw[0] if raw else None)


def classify_batch(texts: list[str]) -> list[SentimentResult | None]:
    """여러 기사 본문을 배치 추론(처리량, model_choice §1). 반환 길이·순서는 입력과 항상 일치.

    - 각 원소는 SentimentResult 또는 None(빈 입력·매핑 밖 라벨·추론 실패 = 감성 없음).
    - 배치 추론이 실패하면(예: OOM·특정 입력 예외) 배치 전체를 버리지 않고 각 텍스트를 classify() 로
      1건씩 재시도한다. 개별 실패한 기사만 None 으로 격리하고 나머지는 정상 결과를 채운다(실패 격리, §7).
    - 빈 입력은 모델을 부르지 않고 그 자리를 None 으로 둔다(호출측이 짝을 맞출 수 있게 자리 유지).
    """
    if not texts:
        return []

    # 빈 입력은 배치에서 제외하되(모델 호출 낭비·오류 방지) 자리는 None 으로 남겨 순서/길이를 보존한다.
    results: list[SentimentResult | None] = [None] * len(texts)
    idx_to_infer = [i for i, t in enumerate(texts) if t and t.strip()]
    if not idx_to_infer:
        return results

    payload = [_truncate(texts[i]) for i in idx_to_infer]
    try:
        raw = _infer_raw(payload)
        if len(raw) != len(payload):  # 파이프라인이 길이를 어기면 계약 위반 → 개별 fallback 으로
            raise ValueError(f"배치 출력 길이 불일치: {len(raw)} != {len(payload)}")
        for i, item in zip(idx_to_infer, raw):
            results[i] = _to_result(item)
    except Exception as exc:  # 배치 실패 → 건 단위 fallback(한 건의 이상 입력이 배치 전체를 날리지 않게)
        logger.warning("배치 감성 추론 실패, 개별 fallback: %s", exc)
        for i in idx_to_infer:
            results[i] = classify(texts[i])

    return results


def _to_result(raw: dict | None) -> SentimentResult | None:
    """저수준 추론 결과({label, score}) → SentimentResult. 매핑 밖 라벨·형식 오류는 로깅 후 None."""
    if not raw:
        return None
    label = raw.get("label")
    sentiment = _map_label(label) if label is not None else None
    if sentiment is None:
        logger.warning("매핑 밖 감성 라벨(무시, 중립 강제 안 함): %r", label)
        return None
    try:
        score = float(raw.get("score"))
    except (TypeError, ValueError):
        logger.warning("감성 score 형식 오류(무시): %r", raw.get("score"))
        return None
    return SentimentResult(sentiment=sentiment, score=score)
