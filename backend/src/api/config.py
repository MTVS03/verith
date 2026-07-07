"""애플리케이션 설정 (pydantic-settings).

이 브랜치 범위에서는 **DB 접속에 필요한 설정만** 둔다(통합 스키마 생성 전용).
API/AI 서버/JWT 등 나머지 설정은 각 담당자가 후속 브랜치에서 확장한다.

**비밀값/DB URL 은 코드에 하드코딩하지 않는다**(backend_coding_guidelines §2.1/§2.2).
`DATABASE_URL` 은 필수 환경변수이며(예: `postgresql+asyncpg://<user>:<pw>@<host>:5433/<db>`),
없으면 설정 로딩 단계에서 즉시 에러를 낸다. 값은 환경변수 또는 `backend/.env` 로 주입한다.

**secret-safe:** DATABASE_URL 검증은 pydantic 밖에서 수행한다. pydantic 의 `ValidationError`
는 입력값(파싱된 `.env` dict 전체)을 오류에 실어 다른 비밀값(JWT/토큰 등)을 로그에 노출할 수
있으므로(§2.2), 필수 필드로 두지 않고 **기본값 + 외부 RuntimeError** 로 처리한다.
`hide_input_in_errors=True` 로 향후 다른 필드의 검증 오류에서도 입력 노출을 막는다.
"""

from __future__ import annotations

import pathlib

from pydantic_settings import BaseSettings, SettingsConfigDict

# env_file 은 CWD 가 아니라 backend 루트 기준으로 고정한다
# (repo root 에서 실행해도 backend/.env 를 찾도록).
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """환경변수/.env 기반 설정. 알 수 없는 키는 무시한다(다른 담당 영역 키 공존)."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        # ValidationError 에 입력값(.env dict)을 실어 비밀값을 노출하지 않는다.
        hide_input_in_errors=True,
    )

    # SQLAlchemy async DSN. 검증은 _load_settings() 에서(secret-safe).
    DATABASE_URL: str = ""

    # Neo4j(뉴스 지식그래프) 접속. PostgreSQL 과 마찬가지로 별도 DB 서버이며,
    # bolt 드라이버로 접속한다(예: bolt://localhost:7687). 값·비밀번호는 코드에 박지 않고
    # .env/환경변수에서 읽는다. 검증은 _load_settings() 에서(secret-safe).
    NEO4J_URI: str = ""
    NEO4J_USER: str = ""
    NEO4J_PASSWORD: str = ""

    # AI(technical) 서버 base URL. 코드에 경로를 박지 않고 .env/환경변수에서 읽는다.
    # 없으면 _load_settings() 에서 에러
    AI_SERVICE_URL: str = ""
    # backend → AI 호출 timeout(초). 숫자 튜닝값 — env 로 override 가능.
    AI_REQUEST_TIMEOUT_SECONDS: float = 60.0


def _load_settings() -> Settings:
    """설정 로드 + DATABASE_URL 필수 검증.

    pydantic 필수 필드/validator 로 검증하면 ValidationError 가 파싱된 `.env` 입력 dict 를
    실어 다른 비밀값을 노출할 수 있다. 따라서 검증을 pydantic 밖에서 수행하고, 입력값을 담지
    않는 깔끔한 RuntimeError 만 던진다.
    """
    s = Settings()
    if not s.DATABASE_URL.strip():
        raise RuntimeError(
            "DATABASE_URL 이 설정되지 않았습니다. 환경변수 또는 backend/.env 에 "
            "postgresql+asyncpg://... DSN 을 설정하세요."
        )
    if not s.NEO4J_URI.strip():
        raise RuntimeError(
            "NEO4J_URI 가 설정되지 않았습니다. 환경변수 또는 backend/.env 에 "
            "bolt://<host>:7687 형태의 URI 를 설정하세요."
        )
    if not s.NEO4J_USER.strip() or not s.NEO4J_PASSWORD.strip():
        raise RuntimeError(
            "NEO4J_USER / NEO4J_PASSWORD 가 설정되지 않았습니다. 환경변수 또는 "
            "backend/.env 에 Neo4j 계정 정보를 설정하세요."
        )
    if not s.AI_SERVICE_URL.strip():
        raise RuntimeError(
            "AI_SERVICE_URL 이 설정되지 않았습니다. 환경변수 또는 backend/.env 에 "
            "AI 서버 base URL 을 설정하세요."
        )
    return s


settings = _load_settings()
