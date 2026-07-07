"""core/stock_master.py — KIS 종목 마스터(이름↔티커 사전) 경계 번역기.

원리: 종목명→티커 확정은 LLM이 아니라 결정론적 사전 lookup 이 한다
(핵심 원칙 "숫자·코드는 코드가 정한다"의 적용 — LLM이 코드를 지어내면
엉뚱한 종목 데이터에 다른 제목이 붙는 사고가 난다). 사전의 출처는 KIS가
공개 배포하는 종목 마스터 파일 — API 권한 불필요(실물 확인 2026-07-07:
KOSPI 2,555 + KOSDAQ 1,827 종목, 삼성전자→005930·우선주 005935 구분 확인).

포맷(실물 확인): 고정폭 한 줄 = 단축코드 9 + 표준코드 12 + 한글명(가변)
+ 꼬리 고정필드(KOSPI 228자 / KOSDAQ 222자), 인코딩 cp949. 주식이 아닌
행(펀드 등)은 단축코드가 6자리 숫자가 아니라서 걸러진다.

캐시: ~/.cache/verith/master/ 에 24시간 (토큰 캐시와 같은 뿌리). 다운로드
실패 시 낡은 캐시가 있으면 그걸 쓴다 — 사전은 하루 이틀 낡아도 대부분
유효하고 신규 상장만 놓친다(설계된 후퇴, 연쇄 시도 아님). 캐시도 없으면
MasterError(실패는 정보).
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path

import httpx

_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/{name}.mst.zip"
# (파일명, 꼬리 고정필드 길이) — KIS 공식 파서 예제와 동일한 상수.
_FILES: tuple[tuple[str, int], ...] = (("kospi_code", 228), ("kosdaq_code", 222))
_CACHE_DIR = Path.home() / ".cache" / "verith" / "master"
_TTL_SECONDS = 24 * 3600
_TICKER_RE = re.compile(r"\d{6}")
_TIMEOUT = 15.0


class MasterError(RuntimeError):
    """마스터 파일을 구할 수 없음 (다운로드 실패 + 캐시 없음)."""


def _parse(text: str, tail: int) -> dict[str, str]:
    """mst 본문 → {종목명: 단축코드}. 6자리 숫자 코드(주식)만 남긴다."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        front = line[: len(line) - tail]
        code, name = front[0:9].strip(), front[21:].strip()
        if _TICKER_RE.fullmatch(code) and name:
            out[name] = code
    return out


def _fetch(name: str) -> str:
    resp = httpx.get(_MASTER_URL.format(name=name), timeout=_TIMEOUT)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    return zf.read(zf.namelist()[0]).decode("cp949")


def _load_text(name: str, now: float, allow_download: bool) -> str:
    """캐시가 신선하면 캐시, 아니면 다운로드. allow_download=False 는 캐시 전용
    (나이 무관) — 티커가 이미 있어 마스터가 '보강'일 뿐일 때 네트워크를 안 탄다."""
    path = _CACHE_DIR / f"{name}.mst"
    if path.exists() and (
        not allow_download or now - path.stat().st_mtime < _TTL_SECONDS
    ):
        return path.read_text(encoding="utf-8")
    if not allow_download:
        raise MasterError(f"종목 마스터 캐시 없음({name}) — 오프라인 모드")
    try:
        text = _fetch(name)
    except Exception as e:
        if path.exists():
            return path.read_text(encoding="utf-8")   # 낡은 캐시 후퇴(신규 상장만 놓침)
        raise MasterError(f"종목 마스터 다운로드 실패({name}): {e}") from e
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def load_master(allow_download: bool = True) -> dict[str, str]:
    """{종목명: 티커} 사전 (KOSPI+KOSDAQ 합본).

    같은 이름이 두 시장에서 다른 코드면 해석 불가로 제거한다 — 애매한 이름을
    임의로 푸는 것이 바로 막으려는 사고다(명백할 때만 확정, 게이트3와 같은 원칙).
    """
    merged: dict[str, str] = {}
    ambiguous: set[str] = set()
    now = time.time()
    for name, tail in _FILES:
        for nm, code in _parse(_load_text(name, now, allow_download), tail).items():
            if nm in merged and merged[nm] != code:
                ambiguous.add(nm)
            merged[nm] = code
    for nm in ambiguous:
        merged.pop(nm, None)
    return merged


def resolve(master: Mapping[str, str], name: str) -> str | None:
    """종목명 → 티커. 정확 일치 → 공백 정리 → 영문 대소문자까지만.

    퍼지 매칭(부분 일치·유사도)은 하지 않는다 — 비슷한 이름을 잘못 확정하는
    것이 미해석보다 훨씬 나쁘다(엉뚱한 종목 리포트). 못 찾으면 None.
    """
    if name in master:
        return master[name]
    norm = " ".join(name.split())
    if norm in master:
        return master[norm]
    upper = norm.upper()
    for nm, code in master.items():
        if nm.upper() == upper:
            return code
    return None


def name_of(master: Mapping[str, str], ticker: str) -> str | None:
    """티커 → 공식 종목명 (역방향 조회). 상장 목록에 없으면 None."""
    for nm, code in master.items():
        if code == ticker:
            return nm
    return None
