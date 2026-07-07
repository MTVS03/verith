"""애플리케이션 설정 (pydantic-settings).

이 브랜치 범위에서는 **DB 접속에 필요한 설정만** 둔다(통합 스키마 생성 전용).
API/AI 서버/JWT 등 나머지 설정은 각 담당자가 후속 브랜치에서 확장한다.

**비밀값/DB URL 은 코드에 하드코딩하지 않는다**(backend_coding_guidelines §2.1/§2.2).
`DATABASE_URL` 은 필수 환경변수이며(예: `postgresql+asyncpg://<user>:<pw>@<host>:5433/<db>`),
없으면 설정 로딩 단계에서 즉시 에러를 낸다. 값은 환경변수 또는 `backend/.env` 로 주입한다.
"""

from __future__ import annotations

import pathlib

from pydantic import model_validator
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
    )

    # SQLAlchemy async DSN. 필수 — 예: postgresql+asyncpg://<user>:<pw>@<host>:5433/<db>
    DATABASE_URL: str

    @model_validator(mode="after")
    def _require_database_url(self) -> "Settings":
        if not self.DATABASE_URL.strip():
            raise ValueError(
                "DATABASE_URL 이 비어 있습니다. 환경변수 또는 backend/.env 에 "
                "postgresql+asyncpg://... DSN 을 설정하세요."
            )
        return self


settings = Settings()
